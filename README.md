# Seller Fee Invoice Downloader

Local Streamlit app to download Amazon Seller Central (India) **Seller Fee Invoices** as PDFs for a selected month/year.

## Features

- One-time Seller Central login (headed browser); session saved locally
- Reuses [atstrack](https://github.com/) `data/sessions/auth_state.json` when this app has no local session yet
- Month + year picker; matches invoices whose **End Date** (UTC) falls in that month
- Auto **Load More** until older rows are loaded or the target month is reachable
- ZIP download in the browser (temporary; not archived on disk)

## Streamlit Cloud

This app can run on [Streamlit Community Cloud](https://streamlit.io/cloud), with limits:

1. **`packages.txt`** — installs Debian **`chromium`** plus libraries (no Playwright browser download on the server).
2. **After deploy** — use **Reboot app** in Cloud so `packages.txt` is applied.
3. **Login** — interactive browser login **does not work** on Cloud. On your Mac, run the app locally (or atstrack), click **Login to Seller Central**, then upload `data/sessions/auth_state.json` in the Cloud app sidebar.

Redeploy after pushing changes that touch `packages.txt` or Playwright setup.

## Prerequisites

- Python 3.11+
- Amazon Seller Central India account

## Setup

```bash
cd sellerfeeinvoice
bash scripts/setup.sh
```

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
unset PLAYWRIGHT_BROWSERS_PATH
playwright install chromium
```

## Usage

```bash
streamlit run app.py
```

1. Sidebar: **Login to Seller Central** (or use an existing atstrack session).
2. Choose month and year.
3. Click **Download invoices** and save the ZIP when prompted.

Invoices page: [Seller Fee Invoices](https://sellercentral.amazon.in/tax/seller-fee-invoices)

## Session files

| Path | Purpose |
|------|---------|
| `data/sessions/auth_state.json` | Written when you log in from this app |
| `../atstrack/data/sessions/auth_state.json` | Read-only fallback if local file is missing |

Override atstrack path: `ATSTRACK_SESSION_PATH` environment variable.

## Debug

Set `HEADED_DOWNLOAD=1` to run the scraper with a visible browser.

## Tests

```bash
source .venv/bin/activate
pytest tests/
```
