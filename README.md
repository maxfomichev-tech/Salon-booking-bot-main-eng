# Aaron Beauty Salon — Telegram Bot

Telegram bot for Aaron beauty salon (Jerusalem, Israel).

Features:
- AI-powered client consultation (via Groq free models)
- Service catalog with prices
- Appointment booking to Google Calendar
- Optional client database in Google Sheets (or local `clients.csv`)

## 1) Requirements

- Windows + **Python 3.12 or 3.13** (note: Python 3.14 may require building some packages from source)
- Telegram Bot Token (from @BotFather)
- Groq API key (from Groq Console)
- Google Calendar for booking events
- (optional) Google Sheets for client storage

## 2) Quick Start

1. Install dependencies:

```bash
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

If you have Python 3.14 and installation "hangs" on building packages (e.g. `pydantic-core`), install Python 3.13 and create the environment:

```bash
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

2. Create `.env` from the example:

```bash
copy .env.example .env
```

3. Set up Google (service account method)

- In Google Cloud Console, create a **Service Account** and download the JSON key.
- Add credentials to `.env` (see `.env.example`).
- In Google Calendar (web), open calendar settings → **Access** → **Share** and add the service account email (format: `xxx@yyy.iam.gserviceaccount.com`) with **Make changes** permission.
- In `.env`, set `GOOGLE_CALENDAR_ID`:
  - typically the calendar email, or an ID like `...@group.calendar.google.com`.

4. (Optional) Google Sheets for clients

- In `.env`, set `GOOGLE_SHEETS_ID`.
  - Prepare a Google Sheet (can be empty) and get its ID from the URL like `.../spreadsheets/d/<ID>/...`
  - Grant the service account (email like `...iam.gserviceaccount.com`) access to the sheet (at least "Editor")

5. Run:

```bash
python -m src.bot
```

## Deploy to Render

Recommended: run in **webhook mode**.

1. Push the project to GitHub.
2. In Render, create **New → Web Service** from the repository.
3. Set environment variables (secrets):
  - `TELEGRAM_BOT_TOKEN`
  - `GROQ_API_KEY`
  - `GOOGLE_CALENDAR_ID`
  - `GOOGLE_SERVICE_ACCOUNT_JSON` **or** `GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT`
  - (optional) `GOOGLE_SHEETS_ID`
4. Render automatically populates `RENDER_EXTERNAL_URL`, and the bot builds `WEBHOOK_URL = <your_render_url>/webhook`.

Health check: `GET /health` (returns `ok`).

## 3) Service Price List

- The `services_pricelist.csv` file can be opened in Excel and edited.
- To generate an `.xlsx` version:

```bash
python scripts/make_xlsx.py
```

## 4) How Booking Works

The bot collects:
- name
- phone
- service
- date and time

After confirmation, it creates an event in Google Calendar.

## 5) Environment Variables

See `.env.example`.
