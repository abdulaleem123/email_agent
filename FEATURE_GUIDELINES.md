# ChatVersio Email CRM — Feature Guidelines

Har feature ka: **kya karta hai** + **manually kaise test karo**.

---

## 0. Run / Stop / Login

**Abhi chal raha hai** (ye session already started):

| Service | URL / Port |
|---|---|
| Frontend (Vite) | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| Redis | localhost:6379 |
| Celery worker + beat | background processes |

**Login:** `saif@chatversio-ai.com` / `emailagent@123` (OTP off hai)

**Aage se manually chalane ke liye** (ya phir sirf `.\run.ps1`):

```powershell
# backend
cd backend
.\venv\Scripts\uvicorn app.main:app --port 8000
# celery worker (naya window)
cd backend
.\venv\Scripts\celery -A app.celery_app.celery worker --loglevel=info --pool=solo
# celery beat (naya window)
cd backend
.\venv\Scripts\celery -A app.celery_app.celery beat --loglevel=info
# frontend (naya window)
cd frontend
npm run dev
```

**Stop karne ke liye:** `taskkill /IM python.exe /F` (uvicorn+celery band), browser band.
Dobara start se pehle: port check `Get-NetTCPConnection -LocalPort 8000,5173 -State Listen`

**Note:** `redis-portable\` folder nahi hai — system Redis hi chal raha hai :6379 par.

---

## 1. Navigation (left sidebar)

`Dashboard · Messages · Escalation · Mail Records · Agents · Campaigns ·
Pitch Decker · Leads · Knowledge · Trash · Settings` (+ SuperAdmin alag se)

---

## 2. Agents (`Agents` page)

- **Banate waqt:** naam, role, persona (who you are), `why_you`, `target_titles`,
  `target_location`, country/sentiment/judgment prompts, pitch style.
- **SMTP/IMAP config:** har agent ka apna mailbox hota hai (send + poll dono).
  SMTP password sirf write hai — API kabhi return nahi karti (masked).
- **Play/Pause toggle (⏸):** `POST /api/agents/{id}/toggle`. Paused agent:
  - koi nayi email send **nahi** karta (even mid-delay abort)
  - uske leads **turant release** ho jate hain (ownership, neeche dekho)
  - follow-ups bhi nahi jate
- **Daily limit:** Settings → Sending volume se per-agent cap.

**Test:** ek agent pause → Leads page par uske contacted leads doosre agent ko
enrollable (reason: "Osaja — paused (released)"). Wapas play → blocked.

---

## 3. Leads (`Leads` page) — core

### Upload
1. **Upload** → file (`.xlsx/.csv`) + **agent** + **campaign** choose → auto-enroll ON.
2. Progress live dikhta hai (ImportProgress). Fresh leads = `new` → enroll → `enrolled`
   → first email queue ho jati hai (delay 180–720s, Settings → Delays).
3. Upload par row ko **agent stamp** milta hai → wo lead sirf us agent ke filter mein.

### Status flow
```
new ──enroll──> enrolled ──send──> contacted ──reply──> replied
                                   │                      │
                                   ├─ bad/bounce ─> garbage
                                   └─ not interested ─> closed   (garbage/expired bhi)
```

### Filters
- **Agent** dropdown + **Campaign** dropdown → scoped view (default: mera view).
- **Unassigned only** → jinhein kisi ko assign nahi kiya (fresh claim ke liye).
- Row mein agent dropdown `new/enrolled/contacted` par dikhta hai → direct reassign.

### Block modal (takeover rok diya toh)
Modal mein reason:
- `Osaja — active` → owner zinda hai, hold karega
- `Osaja — paused (released)` / `silent 8d (released after 7d)` → release ho chuka
- `unassigned` → koi owner hi nahi
- `unlock_at`: "owner releases it — pause, 7d silence, or hand-over"

### Takeover (naya feature)
- Contacted lead + owner **released** → doosra agent enroll kare → **hand-over**:
  - lead ka `status = contacted` **rehta hai** (dubara cold email NAHI jati)
  - sirf `agent_id` + `campaign_id` badalta hai, naya agent wahin se continue karta hai
  - frontend launch **skip** karta hai jab `handed_over` (warna 400 "No launchable leads")
- **Bulk paths** (filter/batch/source_file) sirf fresh leads lete hain — contacted
  sirf **explicit `lead_ids`** se takeover ho sakta hai.

---

## 4. Lead Ownership — rules (NEW)

Har lead ek "held" hoti hai jab tak owner ke paas valid claim ho. Neeche se
**release** hoti hai:

| Condition | Result |
|---|---|
| Owner koi nahi (`agent_id` NULL) | FREE — koi bhi le sakta hai |
| Owner **paused** | RELEASED (turant) |
| Owner ki **last activity > 7 din** (silence) | RELEASED |
| Owner active + within timeline | HELD (baaki agents blocked, owner name reason ke saath) |

- **Last activity** = max(last outbound, newest email message, inbound reply,
  upload/created date) — inbound reply bhi communication count hoti hai.
- **Timeline days** = Settings → **Lead ownership** → `lead_ownership_days`
  (default **7**, min 1, max 90). Ek naya feature test karte waqt `2` kar do.
- Ownership **follow-up sends par lagu NAHI** — campaigns 7 din se lambe ho sakte hain.
- `stale_leads_sweep` (30d, daily) alag cheez hai: woh Garbage mein bhejta hai.
  Ownership release = sirf claim chhodta hai, status badalta nahi.

**Test flow:**
1. Settings → Lead ownership = `2`
2. Kisi lead ka `last_outbound_at` SQL se 3 din pehle karo (owner active)
   → doosre agent ko enroll karo → **blocked** (`silent 3d`)
3. Owner ko pause → **takeover ho jaye** (`handed_over: 1`)

---

## 5. Campaigns

- **Create:** naam, goal, strategy (B2B…), template mode, email length,
  `what_to_sell` / `what_to_avoid`, target focus/country,
  follow-up hours (default 24h + 48h, max 3 follow-ups).
- **Launch:** `POST /api/campaigns/{id}/launch {lead_ids}` → **strict FIFO** —
  pehli email ~1 delay-step, doosri uske baad, volume ramp hoti hai
  (batch 20–50, Settings → Sending volume).
- **Batches:** har batch ka status `pending → running → completed | paused |
  cancelled` (cancelled = operator ne mid-run roka; dispatch usse skip karta hai — ye P0 fix hai).
- **Launch rule:** sirf `new/enrolled` launchable hain — `contacted` par 400.
  Frontend `handed_over` leads ko launch list se khud nikaalta hai.
- Schedules: campaign apna send-window (business hours) dekhta hai.

**Test:** campaign banao → leads enroll → launch → Mail Records mein sends dikhengi.

---

## 6. Messages (`Inbox`)

- Har thread: lead + agent ka conversation, inbound reply 2 min poll pe aati hai.
- **AI auto-reply:** `auto_reply` task — agent persona se jawab, delays
  (INBOUND_REPLY_DELAY_SECONDS = 900s) ke baad.
- **Escalate / Needs human:** thread pe human ka control — agent khud jawab
  dene band karta hai (`needs_human`, `escalated` flags).
- **ai_paused (human takeover):** us lead par AI ruk jata hai, banda khud likhta hai.
- **Trash route:** not-interested/bounce/garbage yahin se dikhte hain.

---

## 7. Escalation page

- `escalated` + `needs_human` threads — jahan AI ne decide kiya "insaan chahiye"
  (pricing, contract, legal…) ya tumne manually escalate kiya.
- Daily purge (`purge_escalations`) retention ke baad hata deta hai.

---

## 8. Pitch Decker

- Selected leads ke liye short pitch audio/message flow; **Pitch Done** flag
  lead ko Pitch queue se hata deta hai (undo bhi hai).

---

## 9. Knowledge

- Docs upload → chunks + embeddings (OpenAI `text-embedding-3-large`).
- **Note:** `OPENAI_API_KEY` `.env` mein khali hai + pgvector extension nahi hai →
  abhi JSON-fallback embeddings chal rahe hain (search basic rahega). Real AI
  replies ke liye key daalni hogi.

---

## 10. Trash (Garbage)

- Blocked-before-send, bounce, not-interested, MX fail → yahan.
- Retention: **30 din** (Settings → Retention) → daily `purge_garbage` delete.

---

## 11. Mail Records

- Har outbound/inbound ka audit: kisne, kab, kis lead ko, batch #.
- Live feed `since_id` + `agent_id` filter se auto-refresh.

---

## 12. Dashboard

- Totals + timeseries (1d/7d/15d/30d selector → `days` param — P0.2 fix).

---

## 13. SuperAdmin

- **Usage:** API/model usage + cost.
- **Audit log:** login, toggles, bulk actions (paged).
- **Monitoring:** SMTP/IMAP realtime status (paged).

---

## 14. Settings

| Card | Kya control karta hai |
|---|---|
| Sending volume | batch size 20–50, per-agent daily limit |
| Delays | outbound 180–720s, inbound reply 900s |
| Follow-ups | 24h/48h plan, max 3 |
| **Lead ownership** | **`lead_ownership_days` (default 7)** ← naya |
| Retention | garbage purge 30d |

`.env` level (code-mein wired, UI toggle nahi):
`MX_VERIFY_BEFORE_SEND`, `SMTP_VERIFY_MAILBOX`, `GARBAGE_RETENTION_DAYS`,
`OUTBOUND_DELAY_*`, `STALE_LEAD_DAYS` (30 → Garbage backstop).

---

## 15. Automation (Celery beat) — kya kab chalta hai

| Task | Kab | Kya |
|---|---|---|
| `poll_inbox` | har 2 min | IMAP se inbound + auto-reply |
| `dispatch_batch` | launch ke baad queue mein | FIFO batch sends (pauses respect) |
| `followup_sweep` | hourly | 24h/48h follow-ups (paused agent skip) |
| `stale_leads_sweep` | daily | 30d quiet → Garbage |
| `purge_garbage` / `purge_escalations` | daily | retention cleanup |
| `daily_backup` | daily | DB backup |

---

## 16. Aaj ka manual test checklist (naye features)

1. **Login** → `http://localhost:5173`
2. **Upload** `sample_clients.xlsx` (project root) — agent = Osaja, campaign = naya
   → Leads page: sirf Osaja + wo campaign dikhe
3. **Settings → Lead ownership = 2** → save → refresh → wapas 7
4. **Pause Osaja** (Agents ⏸) → Leads: Osaja ke contacted leads doosre agent ko
   enroll karo → **hand-over** message, status `contacted` rahe, **Launch skip**
5. **Ownership block:** Osaja play → doosre agent se wahi lead enroll karo →
   blocked modal reason `Osaja — active` + `unlock_at` line
6. **Silence release:** SQL se kisi lead ka `last_outbound_at` 8 din pehle →
   wahi enroll → released (`silent 8d…`)
7. **P0 pages:** Campaigns / Trash / Mail Records / SuperAdmin / Dashboard
   → console mein koi red error nahi (qs/monitoring/timeseries fixes)
8. **Batch cancel:** chhoti campaign launch → batch cancel button → status
   `cancelled` dikhe, dispatch do na bheje

---

## 17. Troubleshooting

- **`.env` DATABASE_URL:** `postgres:password@localhost:5432/chatversio`
  (native PG ka password `password` hai — `postgres` nahi; DB `chatversio`
  banaya hua hai). venv mein `psycopg` installed.
- **pgvector nahi hai** → embeddings JSON-fallback (features chalte hain, basic).
- **Frontend proxy:** `vite.config.js` → `VITE_API_PROXY` env, default
  `http://localhost:8000` (docker ke liye compose `http://api:8000` set karta hai).
- **401 on API:** session expired → logout/login. OTP off hai.
- **Leads enroll nahi ho rahe:** check karo campaign/agent selected ho, agent
  active ho, aur lead status `new/enrolled` (contacted = takeover chahiye).
- **Email nahi ja rahi:** SMTP config + `OPENAI_API_KEY` alag cheez hai — SMTP
  bharo Agents page par, daily limit check karo.
