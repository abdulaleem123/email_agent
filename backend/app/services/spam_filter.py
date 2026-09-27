"""Core email-quality filter — ONE place that decides which messages and
recipients are worthless, and WHY (so the monitor can show the real reason:
"promotion", "role-account: info@", "system-notification: zoho.com",
"disposable-address", etc).

THREE buckets, deliberately kept apart:
- ESCALATION  (a human must look): meeting/scheduling links, promotions,
  role-account replies, delivery failures and blocked outbound. NOT spam,
  NOT garbage — they live on their own page, the agent never replies to
  them, and they self-purge after ESCALATION_RETENTION_DAYS.
- SPAM/GARBAGE (worthless forever): scammy keyword junk, link-stuffed
  blasts, shouty one-line ads. Auto-purged on the garbage retention clock.
- REAL MAIL: everything else. Becomes a lead / triggers an auto-reply.

Two uses, same logic:
- INBOUND  (poll_inbox): anything flagged is recorded with the right bucket —
  escalation rows carry is_escalation, junk carries is_spam — and neither
  ever triggers an auto-reply.
- OUTBOUND (campaigns / follow-ups / auto-reply / manual send / enroll /
  upload): addresses that are role accounts (info@/support@/noreply@...),
  system-notification aliases (Zoho/Hostinger technical mail) or throwaway
  disposables are blocked BEFORE sending — escalated instead of sent, so the
  agent never communicates with them.

Reason strings are data-driven lists + small heuristics (not buried in any
prompt — prompts are untouched)."""
import re

BOUNCE_SENDER_PATTERNS = ("mailer-daemon", "postmaster", "mail delivery subsystem",
                          "delivery status notification", "mail delivery system")
BOUNCE_SUBJECT_PATTERNS = ("undeliverable", "delivery status notification",
                           "returned mail", "mail delivery failed", "failure notice",
                           "delivery has failed", "message not delivered")


def is_bounce(sender: str, subject: str) -> bool:
    """True if this inbound message IS a bounce/non-delivery notification,
    not a real reply. SMTP-level mailbox verification (RCPT probing) is
    unreliable in practice -- many networks block outbound port 25 entirely,
    and major providers (Gmail included) frequently accept RCPT TO without
    confirming the mailbox actually exists, only bouncing AFTER a real send
    attempt. A parsed bounce is the most reliable real-world signal that a
    lead's address is dead."""
    s = (sender or "").lower()
    subj = (subject or "").lower()
    return (any(p in s for p in BOUNCE_SENDER_PATTERNS)
            or any(p in subj for p in BOUNCE_SUBJECT_PATTERNS))


_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def extract_bounced_recipient(body: str, known_emails: set) -> str | None:
    """Bounce bodies vary wildly by provider, so instead of parsing a fixed
    format, pull every email address out of the body and return the first
    one that matches one of OUR own leads -- that's the failed recipient."""
    found = set(m.group(0).lower() for m in _EMAIL_RE.finditer(body or ""))
    for addr in found:
        if addr in known_emails:
            return addr
    return None


# ---------------------------------------------------------------------------
# Data-driven filters (public/common lists — extend freely, no code changes)
# ---------------------------------------------------------------------------

# Well-known role / protected / throwaway-folder local-parts. A real person
# arranged for each of these (info@, support@, sales@, admin@...) almost never
# reads cold outreach, and noreply@/donotreply@ physically cannot reply.
ROLE_LOCAL_PARTS = {
    "noreply", "donotreply", "noemail", "admin", "administrator", "webmaster",
    "postmaster", "hostmaster", "mailer", "daemon", "abuse", "info", "support",
    "help", "helpdesk", "contact", "hello", "hi", "mail", "email", "office",
    "sales", "marketing", "newsletter", "updates", "updates", "notification",
    "notifications", "welcome", "register", "registration", "gettingstarted",
    "team", "accounts", "accounting", "billing", "invoice", "invoices",
    "feedback", "careers", "jobs", "hr", "test", "testing", "demo", "it",
    "itsupport", "security", "complaints", "privacy", "press", "media",
    "enquiries", "enquiry", "inquiry", "inquiries", "reservations", "service",
    "services", "supplier", "customerservice", "customer", "customers",
    "noc", "ops", "operations", "procurement", "legal", "compliance",
    "training", "resume", "speaker", "sponsorship", "robot", "bots", "autobot",
    "automation", "system", "sysadmin", "root", "alert", "alerts",
    "mailerdaemon", "business", "general", "director", "management",
    "unsubscribe", "optout",
}

# Providers whose AUTOMATED technical mail the agent must never answer
# (Zoho invoices/security alerts, Hostinger server/domain notices...).
# A normal person emailing from the same domain is NOT blocked — the sender
# alias or the subject must actually look like a system notification.
SYSTEM_NOTIFICATION_DOMAINS = {
    "zoho.com", "zohomail.com", "hostinger.com", "hostinger.net",
}

# Notification-style aliases on those domains (normalized: no - _ . digits)
NOTIF_LOCAL_PARTS = {
    "noreply", "donotreply", "noemail", "notification", "notifications",
    "billing", "invoice", "invoices", "alerts", "alert", "security", "abuse",
    "support", "helpdesk", "system", "it", "admin", "mailer", "daemon",
}

NOTIF_SUBJECT_HITS = (
    "invoice", "payment", "billing", "receipt", "renewal", "expir",
    "alert", "maintenance", "quota", "verification", "notification",
    "subscription", "hosting", "server", "domain", "dns", "ssl",
    "upgrade", "suspended", "usage", "cpu", "memory", "disk",
    "statement", "credit", "awaiting", "security", "action required",
    "account notice", "service notice",
)

# Widely-shared list of disposable / throwaway mail domains — senders that
# exist for 10 minutes are never real leads.
DISPOSABLE_DOMAINS = {
    "mailinator.com", "10minutemail.com", "guerrillamail.com", "guerrillamail.net",
    "temp-mail.org", "temp-mail.io", "tempmail.com", "tempmailo.com", "yopmail.com",
    "yopmail.fr", "sharklasers.com", "maildrop.cc", "getnada.com", "nothingmail.com",
    "mytemp.email", "mailnesia.com", "mailcatch.com", "throwawaymail.com",
    "throwaway.email", "discard.email", "spam4.me", "spambox.us", "emailondeck.com",
    "inboxbear.com", "mintemail.com", "trashmail.com", "trashmail.de", "tmpmail.org",
    "fakeinbox.com", "maileater.com", "meltmail.com", "mailexpire.com", "fakemail.net",
    "fakemailgenerator.com", "mailmetrash.com", "e4ward.com", "mvrht.net",
    "grr.la", "nwytg.net", "jnxjn.com", "okclmail.com", "35si.com", "hola-aqui.com",
    "moakt.com", "pp.ua", "pvyv.com", "zippymail.info",
}

# Strong marketing markers — presence is nearly conclusive proof of a promo.
PROMO_STRONG = (
    "unsubscribe", "you are receiving this email because",
    "to stop receiving these", "why am i getting this",
    "you are receiving this because you signed up",
)

# Ordinary promo vocabulary (need a few together, never one word alone).
PROMO_MARKETING = (
    "sale", "discount", "coupon", "voucher", "promo", "promotion", "promotional",
    "clearance", "flash sale", "limited time offer", "free trial", "% off",
    "free shipping", "gift card", "rewards", "loyalty", "new arrivals",
    "new collection", "shop now", "buy now", "claim your", "offer ends",
    "promo code", "coupon code", "newsletter", "we miss you", "come back",
    "abandoned cart", "exclusive offer", "special offer", "upgrade to premium",
    "referral", "affiliate", "black friday", "cyber monday", "mid-season",
    "annual sale", "back in stock", "in stock now", "best price",
    "ad", "ads", "advert", "sponsored", "advertisement",
)

# ---------------------------------------------------------------------------
# Legacy keyword spam scoring (kept for the obvious scam-type junk)
# ---------------------------------------------------------------------------
SPAM_KEYWORDS = {
    "unsubscribe now": 3, "winner": 2, "lottery": 4, "viagra": 5, "casino": 4,
    "crypto giveaway": 5, "click here": 2, "act now": 2, "100% free": 3,
    "risk-free": 2, "no credit check": 3, "earn money fast": 4, "work from home!!!": 3,
    "limited time offer": 2, "prince": 2, "inheritance": 3, "wire transfer": 3,
    "bitcoin investment": 4, "hot singles": 5, "cheap meds": 5, "seo services": 2,
    "guaranteed ranking": 3, "buy followers": 4,
}

SPAM_THRESHOLD = 4


def _normalize_local(local: str) -> str:
    """info2@ -> info, no-reply@ -> noreply, support.2024@ -> support."""
    l = (local or "").split("+", 1)[0].lower()
    l = l.rstrip("0123456789-_. ").strip(".-_ ")
    return l.replace("-", "").replace("_", "").replace(".", "")


def _match_role(local: str) -> str | None:
    key = _normalize_local(local)
    if len(key) < 3:
        return None
    if key == "noreply":
        return "noreply"
    return key if key in ROLE_LOCAL_PARTS else None


def _is_system_notification(sender: str, subject: str, body: str) -> bool:
    domain = (sender or "").lower().rpartition("@")[2]
    if domain not in SYSTEM_NOTIFICATION_DOMAINS:
        return False
    local = _normalize_local((sender or "").lower().split("@")[0])
    if local in NOTIF_LOCAL_PARTS:
        return True
    text = f"{subject}\n{body}".lower()
    return any(k in text for k in NOTIF_SUBJECT_HITS)


def _is_promotion(subject: str, body: str) -> bool:
    text = f"{subject}\n{body}".lower()
    if any(p in text for p in PROMO_STRONG):
        return True
    hits = sum(1 for p in PROMO_MARKETING if p in text)
    return hits >= 3


def score_email(sender: str, subject: str, body: str) -> tuple[int, str]:
    """Returns (score, reason). score >= SPAM_THRESHOLD => garbage."""
    text = f"{subject}\n{body}".lower()
    sender = (sender or "").lower()
    score, reasons = 0, []

    for kw, w in SPAM_KEYWORDS.items():
        if kw in text:
            score += w
            reasons.append(f"keyword:{kw}")

    if any(tag in sender for tag in ("noreply", "no-reply", "donotreply",
                                     "mailer-daemon", "postmaster",
                                     "notifications@", "newsletter@", "marketing@")):
        score += 4
        reasons.append("automated-sender")

    if len(re.findall(r"https?://", text)) >= 6:
        score += 3
        reasons.append("link-stuffed")

    letters = [c for c in subject if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7 and len(letters) > 8:
        score += 2
        reasons.append("shouting-subject")

    if not body.strip():
        score += 2
        reasons.append("empty-body")

    return score, ", ".join(reasons[:5])


def classify_email(sender: str, subject: str, body: str) -> tuple[bool, str]:
    """Junk-for-good: scam keywords, link-stuffed blasts, automated senders with
    no real content, empty shells. These are worthless forever, so they go to
    the Garbage pool and auto-purge on the garbage retention clock.

    Deliberately NO role-account / promotion / disposable / system-notification
    checks here any more — those moved to classify_escalation(), because "worth
    a human's eyes" and "worthless junk" are different verdicts and the team
    wants the first group on the Escalation page, not in Garbage."""
    score, reason = score_email(sender, subject, body)
    if score >= SPAM_THRESHOLD:
        return True, reason or "spam"
    return False, ""


def is_spam(sender: str, subject: str, body: str) -> tuple[bool, str]:
    return classify_email(sender, subject, body)


def block_reason_for_recipient(email: str) -> str:
    """Reason an OUTBOUND target must never be contacted — checked before any
    send to noreply@/info@/support@-style aliases, system-notification
    aliases and disposable throwaway mailboxes. No content available here,
    only the address itself; returns "" when the address is fine to use."""
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return ""
    local, _, domain = email.rpartition("@")
    domain = domain.strip()

    role = _match_role(local)
    if role:
        return f"role-account: {email}"

    if domain in DISPOSABLE_DOMAINS:
        return f"disposable-address: {domain}"

    if domain in SYSTEM_NOTIFICATION_DOMAINS:
        if _normalize_local(local) in NOTIF_LOCAL_PARTS:
            return f"system-notification: {domain}"

    return ""


# ---------------------------------------------------------------------------
# ESCALATION — "a human must decide", which is NOT the same as "spam"
# ---------------------------------------------------------------------------

# Scheduling / meeting-link hosts. A cold email that comes back as a booking
# link is not a conversation the agent should answer by itself — the human
# either takes the call or ignores it. Everything here escalates.
MEETING_LINK_DOMAINS = (
    "calendly.com", "cal.com", "calendly.net", "savvycal.com", "rezpit.com",
    "acuityscheduling.com", "scheduler.zoom.us", "zoom.us", "jitsi.meet",
    "meet.google.com", "teams.microsoft.com", "hubspot.meet", "hubspotlinks.com",
    "yours.truly", "helium10.com", "nozomin.com", "confirmed.co", "mkto.run",
    "gotomeeting.com", "webex.com", "whereby.com", "around.co", "tidycal.com",
    "timebutlr.com", "goodtime.io", "senja.io", "finsweet.io",
)

# Body/subject phrases that mean "here is a slot, book it" even when the link
# is behind a redirect we can't see.
MEETING_PHRASES = (
    "book a call", "book a meeting", "book a demo", "book time", "schedule a call",
    "schedule a meeting", "schedule a demo", "pick a time", "pick a slot",
    "select a time", "choose a time", "find a time", "set up a call",
    "set up a meeting", "grab a time", "reserve a time", "book a slot",
    "here's my calendar", "here is my calendar", "my calendar link",
    "booking link", "calendly link", "calendar link", "invitation to schedule",
    "invite to schedule", "time slot", "available slots", "i have a few slots",
    "let us find a time", "let's find a time", "15-minute call",
    "15 minute call", "30-minute call", "30 minute call", "discovery call",
    "intro call", "quick call", "walk me through your calendar",
    "here are some times", "i can do", "does this work for you",
    "let me know if this time works", "confirm the time", "rsvp",
)

# Scheduling-assistant senders — a bot, not a person. Escalate, never reply.
MEETING_BOT_LOCAL_PARTS = {
    "scheduler", "calendar", "calendly", "savvycal", "rezpit", "acuity",
    "no-reply-calendar", "noreply-calendar", "notif-calendar", "meetings",
    "invites", "invitation", "demo-booking", "bookings", "scheduling",
}


def is_meeting_link(subject: str, body: str) -> bool:
    """True when the message is a meeting / scheduling invite rather than a
    real reply. Detected from the link host, a scheduling-bot sender alias, or
    the usual booking phrasing in the subject+body."""
    text = f"{subject or ''}\n{body or ''}".lower()
    if any(d in text for d in MEETING_LINK_DOMAINS):
        return True
    hits = sum(1 for p in MEETING_PHRASES if p in text)
    # One phrase plus a bare link is enough; two phrases are enough alone.
    if hits >= 2:
        return True
    if hits == 1 and ("http://" in text or "https://" in text):
        return True
    return False


def classify_escalation(sender: str, subject: str, body: str) -> tuple[bool, str]:
    """Does this INBOUND message need a human instead of an auto-reply?

    Covers exactly what the team asked to keep out of both Mail Records and
    Garbage: delivery failures, meeting links, promotions, role-account
    replies (info@/support@/noreply@), system notifications and disposables.
    Returns (escalate, human-readable reason)."""
    sender = (sender or "").lower()
    subject = subject or ""
    body = body or ""

    if is_bounce(sender, subject):
        return True, "delivery-failed"

    if is_meeting_link(subject, body):
        local = _normalize_local(sender.split("@")[0]) if "@" in sender else ""
        if local in {_normalize_local(p) for p in MEETING_BOT_LOCAL_PARTS}:
            return True, "meeting-link:scheduler-bot"
        return True, "meeting-link"

    local, _, domain = sender.rpartition("@")
    if _match_role(local):
        return True, f"role-account: {sender}"
    if domain in SYSTEM_NOTIFICATION_DOMAINS:
        if (_normalize_local(local) in NOTIF_LOCAL_PARTS
                or _is_system_notification(sender, subject, body)):
            return True, f"system-notification: {domain}"
    if domain in DISPOSABLE_DOMAINS:
        return True, f"disposable-address: {domain}"
    if _is_promotion(subject, body):
        return True, "promotion"

    return False, ""


# Human labels for the Escalation page's reason filter chips.
ESCALATION_REASONS = (
    "meeting-link",
    "promotion",
    "delivery-failed",
    "role-account",
    "system-notification",
    "disposable-address",
    "blocked-outbound",
    "unverified-recipient",
    "send-failed",
)