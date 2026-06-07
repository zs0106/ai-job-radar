# GitHub Actions Workflows

## weekly_data_fetch.yml

Runs every Sunday at 4:00 UTC (Saturday 11pm EST) to collect job market data and update the dashboard.

### What it does
1. Fetches DS/MLE/AI Engineer job listings from Adzuna API (Canada + US)
2. Extracts skill frequencies and company hiring data
3. Appends new data row to Google Sheets warehouse
4. Overwrites `data/data.json` with latest data + 12-week history
5. Commits and pushes `data/data.json` back to this repo

### How to trigger manually
1. Go to the **Actions** tab in this repo
2. Click **Weekly Data Fetch** in the left sidebar
3. Click **Run workflow** → **Run workflow**
4. Watch logs in real time — each step shows green ✓ on success

### How to check if last run succeeded
- Actions tab → click the most recent run → all steps should be green
- Check `data/data.json` was updated (commit by "Hiring Signal Bot")
- Check Google Sheets has a new row in `weekly_job_counts` tab

### Required secrets
Add these at: `Settings → Secrets and variables → Actions → New repository secret`

| Secret name | Where to get it |
|---|---|
| `ADZUNA_APP_ID` | developer.adzuna.com → your app |
| `ADZUNA_APP_KEY` | developer.adzuna.com → your app |
| `GOOGLE_SHEET_ID` | Spreadsheet URL (the long ID between /d/ and /edit) |
| `GOOGLE_CREDENTIALS_JSON` | Google Cloud Console → Service Account → JSON key (paste full JSON) |

### How to debug a failed run
1. Click the failed run in the Actions tab
2. Click the failed step to expand its logs
3. Common issues:
   - `ADZUNA` errors → check API key secrets are set correctly
   - `gspread auth error` → re-share the spreadsheet with the service account email
   - `git push` fails → Settings → Actions → General → Workflow permissions → Read and write
