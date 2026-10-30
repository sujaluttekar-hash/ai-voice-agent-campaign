# Voice_Bot_Progressive — Ozonetel CDR to Google Sheets

This repository is dedicated exclusively to the Ozonetel campaign `Voice_Bot_Progressive`.

## Automation
- Runs every 6 hours and can also be started manually from Actions.
- Each run pulls T-2 through today (India time).
- `campaigns.txt` allow-lists only `Voice_Bot_Progressive`.
- Appends only previously unseen calls; never clears, rewrites, sorts, or replaces existing data.
- Uses the 18-column CDR layout and records successful runs in a `logs` worksheet.

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
The export has no Ozonetel Call ID column. Duplicate protection therefore uses a composite identity (date, start time, campaign, caller number, agent, call type, and agent ID). Existing rows are retained and mutable fields are not updated.

Do not commit credentials, service-account JSON, or exported call data.
