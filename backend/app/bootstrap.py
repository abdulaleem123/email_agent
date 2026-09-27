"""First-run bootstrap: admin user from .env + the 4 Chatversio agents with
their persona playbooks + per-agent starter knowledge docs."""
from .database import SessionLocal
from .config import settings
from . import models
from .security import hash_password

AGENTS = [
    dict(name="Osaja", role="Senior Sales Strategist",
         description="Consultative enterprise sales. Diagnoses before pitching; "
                     "invites to a free 30-min strategy session framed as value.",
         tone="professional", message_length="medium", daily_send_limit=200,
         signature="Osaja\nSenior Sales Strategist, Chatversio AI"),
    dict(name="Saif", role="Co-Founder, Chatversio AI",
         description="Founder-to-founder B2B outreach. Extremely concise, direct, "
                     "credible. Sells Chatversio AI's specialist chat agents.",
         tone="professional", message_length="short", daily_send_limit=50,
         signature="Saif\nCo-Founder, Chatversio AI"),
    dict(name="Aleem", role="AI Engineer (Freelance)",
         description="Technical peer-to-peer with CTOs/eng leads. Agentic AI, RAG, "
                     "automation. Offers a small first step (audit/prototype).",
         tone="casual", message_length="medium", daily_send_limit=150,
         signature="Aleem\nAI Engineer"),
    dict(name="Dawood", role="Frontend & Full-Stack Developer (Freelance)",
         description="Solo freelancer voice, winning-Upwork-cover-letter style. "
                     "Specific observations, concrete proposals, humble-confident.",
         tone="friendly", message_length="short", daily_send_limit=150,
         signature="Dawood\nFrontend & Full-Stack Developer"),
]

# ── defaults for the targeting / offering / language fields ─────────────────
# Seeded on every agent so the layers are live from the first boot, then left
# alone — the backfill only ever fills a field that is still empty.
#
# WHY YOU is deliberately NOT a pitch: value, proof and outcomes stated as
# things already observed. No offer, no benefit list, no call to action.
DEFAULT_WHY_YOU = {
    "Osaja": "Works with owners who are losing time to repetitive customer "
             "handling and enquiries that go unanswered. Starts from what is "
             "actually slowing the operation down, never from a product. "
             "Observed outcomes: replies in seconds instead of hours, fewer "
             "dropped enquiries, and no extra headcount to carry the load.",
    "Saif": "Founder writing to founder, so the point is made in a line or two. "
            "One focus: the people who already reached out should not be the "
            "ones left waiting. Observed outcomes: an answer the moment someone "
            "writes, the right questions asked before anyone's time is spent, "
            "and a person brought in only when it matters.",
    "Aleem": "A technical peer who has built systems like these in production "
             "and says plainly what will and will not work. Observed outcomes: "
             "the repetitive part of an operational area (support triage, "
             "internal knowledge, data handoffs) stops consuming a team's day, "
             "and a useful first slice shows up before any larger commitment.",
    "Dawood": "Works alone and looks at the actual site or product before "
              "saying anything, then names one specific thing that could work "
              "better. Observed outcomes: a clear scope, one person accountable "
              "end to end, and something working in days rather than a quarter.",
}

# Who this system writes to by default: the people who own the problem.
# Blank titles are never filtered, so a sheet without a title column still
# enrolls. Clear the field to allow every role.
DEFAULT_TARGET_TITLES = (
    "founder, co-founder, owner, managing director, chief, ceo, coo, cto, "
    "cio, cmo, cro, president, vice president, vp, head, director, manager, "
    "lead, principal, partner"
)

# Persona = which of the four voices writes as. Falls back to the name.
def _persona_key(name: str) -> str:
    n = (name or "").strip().lower()
    return n if n in {"osaja", "saif", "aleem", "dawood"} else ""


AGENT_DEFAULT_FIELDS = {
    "target_titles": DEFAULT_TARGET_TITLES,
    "target_location": "",           # adapts to the lead's own country unless set
    "excluded_titles": "",           # e.g. recruiter, intern, student
    "excluded_companies": "",        # e.g. named accounts, competitors, "agency"
    "solutions": "",                 # empty = the whole catalogue is available
    "avoid_phrases": "",             # empty = built-in defaults still apply
    "extra_instructions": "",
}

# (agent_name or None=shared, title, content)
DOCS = [
    (None, "Chatversio AI — what we sell",
     "Chatversio AI builds industry-specialist AI chat agents (real estate, "
     "restaurants, software houses, mobile app dev and more) that live on a "
     "client's website, answer visitors instantly, capture leads and book "
     "meetings 24/7. Multi-tenant SaaS; fast onboarding; agents are trained and "
     "scoped per industry."),
    (None, "Meeting offer",
     "Standard offer across agents: a free 30-minute consultation/strategy "
     "session. Not a sales presentation — we map the client's current process, "
     "find bottlenecks, share practical Agentic AI ideas; they leave with "
     "actionable insights whether or not they buy."),
    ("Osaja", "Osaja — objection handling",
     "Price concern -> anchor on cost of missed leads and manual support hours. "
     "'We already have a chatbot' -> position specialist trained agents vs "
     "generic bots; offer side-by-side comparison. 'Not now' -> plant a "
     "low-effort next step (15-min audit) and ask permission to follow up."),
    ("Saif", "Saif — product one-liner set",
     "One-liners to reuse naturally: 'Each industry gets its own specialist "
     "agent — trained, scoped and ready to convert visitors the moment they "
     "land.' 'We turn website traffic you already pay for into booked "
     "meetings.'"),
    ("Aleem", "Aleem — technical capability sheet",
     "Stack: Python, FastAPI, Celery/Redis, LangGraph, pgvector/hybrid RAG, "
     "OpenAI/Anthropic, voice agents (ElevenLabs), n8n-style automations. "
     "Typical first engagements: support triage automation, internal knowledge "
     "assistant, data-pipeline cleanup, agentic workflow prototype in 1-2 weeks."),
    ("Dawood", "Dawood — portfolio talking points",
     "Recent work: production SaaS dashboards (Next.js 14), marketing sites with "
     "3D/GSAP animation, React admin panels, performance rescues (Core Web "
     "Vitals), Laravel/WordPress customization. Comfortable owning frontend "
     "end-to-end or full-stack solo."),
]

TEMPLATES = [
    ("Osaja", "Osaja — US strategy-session invite", "medium",
     "Hi {first_name}, many teams still handle customer support and repetitive "
     "workflows manually. Teams that adopt the right automation early cut costs "
     "and respond faster. I'd like to invite you to a 30-minute strategy session "
     "— not a sales presentation: we'll map your current processes, identify "
     "bottlenecks and share practical Agentic AI ideas for {company}. If there's "
     "a fit we can talk implementation; if not, you'll still leave with "
     "actionable insights. Open to a brief conversation next week?"),
    ("Saif", "Saif — founder direct", "short",
     "Hi {first_name} — I'm the co-founder of Chatversio AI. We build "
     "industry-specialist chat agents that turn website visitors into booked "
     "leads. Noticed {company} and thought there's a clear fit. Worth a quick "
     "look?"),
    ("Aleem", "Aleem — tech peer intro", "medium",
     "Hi {first_name}, I work on agentic AI and automation for teams like "
     "{company}. Rather than a big engagement, I usually start with a quick "
     "audit or a small prototype so you can judge the value in a week. Happy to "
     "share how similar teams automated their support triage."),
    ("Dawood", "Dawood — cover-letter style", "short",
     "Hi {first_name}, I took a look at {company}'s site and noticed a couple "
     "of things I'd tighten up. I'm a frontend/full-stack dev who works solo — "
     "recent projects include production SaaS dashboards and performance "
     "rescues. Happy to share specifics if useful."),
]


def bootstrap():
    db = SessionLocal()
    try:
        # Admin user always ensured (auth depends on it)
        if db.query(models.User).count() == 0:
            db.add(models.User(email=settings.ADMIN_EMAIL.lower(),
                               password_hash=hash_password(settings.ADMIN_PASSWORD)))
            db.commit()

        # Optional dedicated Super Admin (AI usage + API keys). If not set,
        # the main admin is promoted so the usage page is always reachable.
        if settings.SUPERADMIN_EMAIL and settings.SUPERADMIN_PASSWORD:
            sa = db.query(models.User).filter_by(email=settings.SUPERADMIN_EMAIL.lower()).first()
            if not sa:
                db.add(models.User(email=settings.SUPERADMIN_EMAIL.lower(),
                                   password_hash=hash_password(settings.SUPERADMIN_PASSWORD),
                                   is_admin=True, is_superadmin=True))
                db.commit()
            elif not sa.is_superadmin:
                sa.is_superadmin = True; db.commit()
        else:
            admin = db.query(models.User).filter_by(email=settings.ADMIN_EMAIL.lower()).first()
            if admin and not admin.is_superadmin:
                admin.is_superadmin = True; db.commit()

        if not settings.AUTO_SEED:
            return
        if db.query(models.Agent).count() == 0:
            for spec in AGENTS:
                full = dict(AGENT_DEFAULT_FIELDS)
                full.update(spec)
                full["persona"] = _persona_key(spec["name"])
                full["why_you"] = DEFAULT_WHY_YOU.get(spec["name"], "")
                db.add(models.Agent(**full))
            db.commit()
        agents = {a.name: a.id for a in db.query(models.Agent).all()}

        # ONE-TIME backfill for an install that already had agents before these
        # fields existed: fill whatever is still empty, then never touch them
        # again (a marker key), so anything the operator later clears stays
        # cleared instead of being re-seeded on the next boot.
        if not db.get(models.SettingKV, "agent_targeting_defaults_v1"):
            for a in db.query(models.Agent).all():
                changed = False
                if not (a.persona or "").strip():
                    a.persona = _persona_key(a.name)
                    changed = True
                if not (a.why_you or "").strip():
                    a.why_you = DEFAULT_WHY_YOU.get(a.name, "")
                    changed = True
                if not (a.target_titles or "").strip():
                    a.target_titles = DEFAULT_TARGET_TITLES
                    changed = True
                if changed:
                    db.commit()
            db.add(models.SettingKV(key="agent_targeting_defaults_v1",
                                    value="1"))
            db.commit()
        if db.query(models.KnowledgeDoc).count() == 0:
            for agent_name, title, content in DOCS:
                db.add(models.KnowledgeDoc(
                    agent_id=agents.get(agent_name), title=title, content=content))
            db.commit()
        if db.query(models.Template).count() == 0:
            for agent_name, name, length, body in TEMPLATES:
                db.add(models.Template(agent_id=agents.get(agent_name),
                                       name=name, length=length, body=body))
            db.commit()

        # baseline for secrets-rotation-age tracking (Super Admin nudge only)
        if not db.get(models.SettingKV, "jwt_secret_noted_at"):
            from datetime import datetime
            db.add(models.SettingKV(key="jwt_secret_noted_at",
                                    value=datetime.utcnow().isoformat()))
            db.commit()
    finally:
        db.close()