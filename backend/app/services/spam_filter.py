"""Requirement 1: score-based spam / irrelevance filter.
Anything flagged is routed to the garbage collector (status=garbage,
is_spam=True) and never reaches the leads pipeline or triggers an auto-reply."""
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


SPAM_KEYWORDS = {
    "unsubscribe now": 3, "winner": 2, "lottery": 4, "viagra": 5, "casino": 4,
    "crypto giveaway": 5, "click here": 2, "act now": 2, "100% free": 3,
    "risk-free": 2, "no credit check": 3, "earn money fast": 4, "work from home!!!": 3,
    "limited time offer": 2, "prince": 2, "inheritance": 3, "wire transfer": 3,
    "bitcoin investment": 4, "hot singles": 5, "cheap meds": 5, "seo services": 2,
    "guaranteed ranking": 3, "buy followers": 4,
}

AUTOMATED_SENDERS = ("noreply", "no-reply", "donotreply", "mailer-daemon",
                     "postmaster", "notifications@", "newsletter@", "marketing@")

SPAM_THRESHOLD = 4


def score_email(sender: str, subject: str, body: str) -> tuple[int, str]:
    """Returns (score, reason). score >= SPAM_THRESHOLD => garbage."""
    text = f"{subject}\n{body}".lower()
    sender = (sender or "").lower()
    score, reasons = 0, []

    for kw, w in SPAM_KEYWORDS.items():
        if kw in text:
            score += w
            reasons.append(f"keyword:{kw}")

    if any(tag in sender for tag in AUTOMATED_SENDERS):
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


def is_spam(sender: str, subject: str, body: str) -> tuple[bool, str]:
    score, reason = score_email(sender, subject, body)
    return score >= SPAM_THRESHOLD, reason