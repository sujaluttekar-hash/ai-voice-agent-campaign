"""Append only T-1 CDR rows using Call ID-based deduplication."""
import csv
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

CSV_PATH = Path(__file__).with_name("ozonetel_cdr.csv")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
LOG_WORKSHEET_NAME = "logs"
EXPECTED_HEADERS = [
    "Call ID", "Call Type", "Campaign", "Caller No", "Caller_E164", "Skill",
    "Call Date", "Start Time", "Time to Answer", "End Time", "Talk Time",
    "Duration", "Agent", "Disposition", "Status", "Comments", "Agent ID",
    "DID", "Dial Count",
]
LOG_HEADERS = [
    "Run Time (IST)", "Status", "Refresh Start Date", "Refresh End Date",
    "Rows Added (New Dates)", "Rows Refreshed/Replaced", "Historical Rows Retained",
    "Total Data Rows After Refresh", "Columns Written", "Data Tab", "Trigger",
    "GitHub Run Number", "GitHub Run ID",
]


def get_or_create_worksheet(spreadsheet, title, rows=1000, cols=20):
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)


def parse_date(value):
    value = (value or "").strip().lstrip("'")
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(value[:10], fmt).date()
        except ValueError:
            pass
    return None


def main():
    if not CSV_PATH.exists():
        raise SystemExit("Upload stopped: ozonetel_cdr.csv was not created by the API pull.")

    with CSV_PATH.open("r", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows or rows[0] != EXPECTED_HEADERS:
        raise SystemExit(
            f"Upload stopped: CSV headers do not match the required {len(EXPECTED_HEADERS)} columns."
        )

    from_text = os.environ.get("CDR_FROM_DATE", "").strip()
    to_text = os.environ.get("CDR_TO_DATE", "").strip()
    start_date, end_date = parse_date(from_text), parse_date(to_text)
    if not start_date or not end_date or start_date > end_date:
        raise SystemExit("Upload stopped: CDR_FROM_DATE/CDR_TO_DATE are missing or invalid.")
    if start_date != end_date:
        raise SystemExit("Upload stopped: this campaign uploads exactly one date (T-1) per run.")

    incoming = [row + [""] * (len(EXPECTED_HEADERS) - len(row)) for row in rows[1:] if any(c.strip() for c in row)]
    if not incoming:
        raise SystemExit("Upload stopped: CSV contains no data rows; existing sheet was left unchanged.")
    date_idx = EXPECTED_HEADERS.index("Call Date")
    invalid_dates = [r[date_idx] for r in incoming if not parse_date(r[date_idx])]
    if invalid_dates:
        raise SystemExit(f"Upload stopped: found an unparseable Call Date: {invalid_dates[0]!r}")

    # Reject any API records outside the requested date window (workflow sets this to T-1 only).
    incoming_dates = [parse_date(r[date_idx]) for r in incoming]
    if any(d != start_date for d in incoming_dates):
        raise SystemExit("Upload stopped: CSV must contain only the requested T-1 date.")

    credentials_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    worksheet_name = os.environ.get("GOOGLE_WORKSHEET_NAME", "ozontel dump").strip()
    if not credentials_json or not sheet_id:
        raise SystemExit("Upload stopped: required Google Sheets secrets/configuration are missing.")
    try:
        service_account_info = json.loads(credentials_json)
    except json.JSONDecodeError:
        raise SystemExit("Upload stopped: GOOGLE_SERVICE_ACCOUNT_JSON must contain valid service-account JSON.")

    credentials = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
    spreadsheet = gspread.authorize(credentials).open_by_key(sheet_id)
    worksheet = get_or_create_worksheet(
        spreadsheet, worksheet_name, rows=max(len(incoming) + 1000, 1000), cols=len(EXPECTED_HEADERS)
    )

    old_values = worksheet.get_all_values()
    old_headers_no_id = EXPECTED_HEADERS[1:]
    old_headers_id_last = EXPECTED_HEADERS[1:] + ["Call ID"]
    if old_values:
        current_headers = old_values[0]
        if current_headers == old_headers_no_id:
            # Upgrade old 18-column layout: preserve values and add blank Call ID in column A.
            old_rows = [[""] + (r + [""] * 18)[:18] for r in old_values[1:]]
            migrated = [EXPECTED_HEADERS] + old_rows
            worksheet.clear()
            worksheet.update(range_name="A1", values=migrated, value_input_option="RAW")
            old_values = migrated
        elif current_headers == old_headers_id_last:
            # Reorder prior 19-column layout, where Call ID was the final column.
            reordered = [EXPECTED_HEADERS] + [[r[18] if len(r) > 18 else ""] + (r + [""] * 18)[:18] for r in old_values[1:]]
            worksheet.clear()
            worksheet.update(range_name="A1", values=reordered, value_input_option="RAW")
            old_values = reordered
        elif current_headers != EXPECTED_HEADERS:
            raise SystemExit("Upload stopped: existing worksheet headers do not match the requested layout or a supported older layout; sheet was left unchanged.")
        old_rows = [
            (r + [""] * len(EXPECTED_HEADERS))[:len(EXPECTED_HEADERS)]
            for r in old_values[1:] if any(c.strip() for c in r)
        ]
    else:
        old_rows = []
        worksheet.update(range_name="A1", values=[EXPECTED_HEADERS], value_input_option="RAW")

    # Existing values are preserved during one-time schema migration; new calls are append-only.
    # Deduplicate by Call ID; legacy rows without IDs use a normalized composite fallback.
    def clean_cell(value):
        value = str(value or "").strip()
        # Sheets strips the leading apostrophe used to force phone/ID values to text.
        return value[1:] if value.startswith("'") else value

    def phone_key(value):
        return "".join(ch for ch in clean_cell(value) if ch.isdigit())

    def call_key(row):
        row = [clean_cell(c) for c in (row + [""] * len(EXPECTED_HEADERS))[:len(EXPECTED_HEADERS)]]
        call_id = row[EXPECTED_HEADERS.index("Call ID")].strip()
        if call_id:
            # Ozonetel CallID is the primary identity and is stable across mutable call details.
            return ("call_id", call_id)
        # Legacy rows have no Call ID. Use a normalized composite fallback for those rows only.
        call_date = parse_date(row[date_idx])
        call_date_key = call_date.isoformat() if call_date else row[date_idx]
        phone = phone_key(row[4]) or phone_key(row[3])  # Caller_E164, fallback Caller No
        return (
            "legacy",
            call_date_key,
            row[7].strip(),       # Start Time
            row[2].strip(),       # Campaign
            phone,
            row[12].strip(),      # Agent
            row[1].strip().casefold(),
            row[16].strip(),      # Agent ID
        )

    existing_call_keys = {call_key(r) for r in old_rows}
    new_rows = []
    seen_call_keys = set()
    for row in incoming:
        padded_row = (row + [""] * len(EXPECTED_HEADERS))[:len(EXPECTED_HEADERS)]
        key = call_key(padded_row)
        if key not in existing_call_keys and key not in seen_call_keys:
            new_rows.append(list(padded_row))
            seen_call_keys.add(key)

    if new_rows:
        worksheet.append_rows(new_rows, value_input_option="USER_ENTERED", table_range="A1")

    rows_added = len(new_rows)
    rows_refreshed = 0
    historical_rows_count = len(old_rows)
    total_rows = len(old_rows) + rows_added

    log_ws = get_or_create_worksheet(spreadsheet, LOG_WORKSHEET_NAME, rows=1000, cols=len(LOG_HEADERS))
    current_headers = log_ws.row_values(1)
    if current_headers != LOG_HEADERS:
        log_ws.update(range_name="A1", values=[LOG_HEADERS], value_input_option="RAW")

    timestamp = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d-%b-%Y %I:%M:%S %p")
    log_row = [
        timestamp, "SUCCESS", start_date.strftime("%d-%m-%Y"), end_date.strftime("%d-%m-%Y"),
        rows_added, rows_refreshed, historical_rows_count, total_rows, len(EXPECTED_HEADERS),
        worksheet_name, os.environ.get("GITHUB_EVENT_NAME", "manual/local"),
        os.environ.get("GITHUB_RUN_NUMBER", ""), os.environ.get("GITHUB_RUN_ID", ""),
    ]
    log_ws.append_row(log_row, value_input_option="USER_ENTERED")
    print(
        f"Append successful: {rows_added} new rows appended; no existing rows changed; "
        f"{total_rows} total data rows; {len(EXPECTED_HEADERS)} columns. "
        f"Date range {start_date:%d-%m-%Y} to {end_date:%d-%m-%Y}. Logged in '{LOG_WORKSHEET_NAME}'."
    )


if __name__ == "__main__":
    main()
