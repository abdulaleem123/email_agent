# Chatversio AI — Email CRM

Enterprise email-agent CRM: 4 persona agents (Osaja · Saif · Aleem · Dawood),
OTP-secured single-admin login, per-agent knowledge bases + inboxes, batched
campaigns (20–50) with green completion tracking, Tavily advanced research with
pain-point extraction, country-aware email psychology, MX verification →
garbage routing, same-day cross-agent dedupe, HTML template mode with the
Chatversio logo at the bottom (first touch only — replies/follow-ups always plain).

## Run (dev)

```bash
# 1) Redis
redis-server            # or: docker run -p 6379:6379 redis:7

# 2) Backend
cd backend
python -m venv venv && venv\Scripts\activate     # Windows
pip install -r requirements.txt
copy .env.example .env                            # fill it in
uvicorn app.main:app --reload --port 8000

# 3) Celery (separate terminals)
celery -A app.celery_app.celery worker --loglevel=info --pool=solo   # --pool=solo on Windows
celery -A app.celery_app.celery beat --loglevel=info

# 4) Frontend
cd frontend
npm install
npm run dev            # http://192.168.0.104:5173
```

Login with `ADMIN_EMAIL` / `ADMIN_PASSWORD` from `.env`. With `OTP_ENABLED=true`
a 6-digit code is emailed via your SMTP account.

## Per-agent mailboxes
Each agent can send & receive from its OWN email — configure it in the UI:
Agents -> Configure -> Mailbox (SMTP + IMAP host/port/user/password).
- Saif (Hostinger): smtp.hostinger.com:587 / imap.hostinger.com:993 with the
  mailbox password (e.g. sai@chatversio-ai.com)
- Osaja/Aleem/Dawood (Gmail): smtp.gmail.com:587 / imap.gmail.com:993 with an
  **App Password** (2-Step Verification on -> Security -> App Passwords)
The global `.env` SMTP is used for system emails (login OTP) and as a fallback
for agents without their own mailbox. Passwords are write-only in the API.

## Production (Hostinger VPS)
- Postgres `DATABASE_URL`, gunicorn (`gunicorn -k uvicorn.workers.UvicornWorker app.main:app`),
  Nginx in front, `npm run build` + `SERVE_FRONTEND=true` (or serve `dist/` from Nginx).
- Deliverability (Primary inbox, not Promotions) is won at DNS: SPF + DKIM +
  DMARC records on the sending domain, plus gradual volume warm-up. The app can
  additionally DKIM-sign if `DKIM_*` is configured.

## Pitch Decker
Pick a lead → Osaja researches the company (cached Tavily) and role-plays a
region-aware sales call (US/UK/UAE/KSA/EU psychology) that ends in a soft close.
The transcript shows in a right-hand panel with the lead details + phone, and is
saved as a pitch record. Needs an OpenAI key (Super Admin → API Keys).
