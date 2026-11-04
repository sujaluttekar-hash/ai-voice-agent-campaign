# Voice_Bot_Progressive — Ozonetel CDR to Google Sheets

This repository is dedicated exclusively to the Ozonetel campaign `Voice_Bot_Progressive`.

## Automation
- Runs once daily at 10:00 AM India time (04:30 UTC); can also be started manually from Actions.
- Each scheduled run pulls only T-1 (yesterday in India time), exactly one date.
- `campaigns.txt` allow-lists only `Voice_Bot_Progressive`.
- Appends only previously unseen calls using Ozonetel Call ID; legacy rows without IDs use a normalized composite fallback. Existing data rows are preserved.
- Uses the 19-column CDR layout and records successful runs in a `logs` worksheet.

## Required Actions secrets
Set these in **Settings → Secrets and variables → Actions → Secrets**:
- `OZONETEL_API_KEY`
- `OZONETEL_USER_NAME`
- `GOOGLE_SERVICE_ACCOUNT_JSON`
- `GOOGLE_SHEET_ID` — the dedicated destination spreadsheet ID for this campaign.

Optional repository variable:
- `OZONETEL_HOST` (defaults to `in1-ccaas-api.ozonetel.com`).

Share the destination spreadsheet with the Google service-account email as an Editor. Do not reuse the other campaign's destination sheet unless you intentionally want the data combined.

## Important
The puller includes Ozonetel Call ID as column A and uses it as the primary deduplication key. The uploader supports upgrading the previous 18-column layout and the previous 19-column layout (Call ID last), reordering existing values to the requested layout while retaining data rows. Historical rows without IDs use a normalized composite fallback. Each scheduled run uploads only yesterday’s calls.

Do not commit credentials, service-account JSON, or exported call data.
