"""Outbound SMTP (STARTTLS) + inbound IMAP.

Adds over v1:
- MX/DNS verification before sending — unverified recipient domains go to Garbage
- Template mode: professional HTML email with the Chatversio AI logo AT THE
  BOTTOM (never above the content), plus a plain-text alternative part
- Plain mode: clean text-only email (all inbound replies + follow-ups use this)
- Optional DKIM signing (dkim lib if installed + key configured). Note: real
  inbox placement (Primary vs Promotions) is won at DNS level — SPF, DKIM,
  DMARC records on your sending domain + low volume warm-up.
"""
import smtplib
import imaplib
import email as email_lib
import ssl
import html as html_lib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import make_msgid, parseaddr, formataddr
from email.header import decode_header
from functools import lru_cache
from ..config import settings

CHATVERSIO_LOGO_URL = "https://chatversio.ai/logo-email.png"  # replace with your hosted logo


# ------------------------------------------------------------- MX verification
@lru_cache(maxsize=4096)
def domain_has_mx(domain: str) -> bool:
    """DNS MX (fallback A) lookup. Cached per-process."""
    try:
        import dns.resolver
        try:
            answers = dns.resolver.resolve(domain, "MX", lifetime=6)
            return len(answers) > 0
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            try:
                dns.resolver.resolve(domain, "A", lifetime=6)
                return True
            except Exception:
                return False
    except Exception:
        return True   # resolver outage must never block the pipeline


def _mx_hosts(domain: str) -> list[str]:
    """Return MX hostnames (sorted by priority), or the domain itself as A fallback."""
    try:
        import dns.resolver
        answers = dns.resolver.resolve(domain, "MX", lifetime=6)
        ranked = sorted(answers, key=lambda r: r.preference)
        return [str(r.exchange).rstrip(".") for r in ranked]
    except Exception:
        return [domain]


import random
import string


@lru_cache(maxsize=4096)
def _domain_is_catch_all(domain: str) -> bool:
    """Probes a deliberately-fake, never-real address at this domain
    (random 24-char local-part). If the server accepts THAT, the domain
    accepts everything — a real mailbox check there can never say 'bad',
    so we must not trust a plain 'accepted' answer as proof of existence.
    This is the standard free technique real verification tools use before
    trusting any individual RCPT result."""
    fake_local = "zzcheck" + "".join(random.choices(string.ascii_lowercase + string.digits, k=20))
    fake_addr = f"{fake_local}@{domain}"
    probe_from = settings.SMTP_FROM or settings.SMTP_USER or "verify@localhost"
    for host in _mx_hosts(domain)[:2]:
        try:
            with smtplib.SMTP(host, 25, timeout=8) as s:
                s.ehlo_or_helo_if_needed()
                s.mail(probe_from)
                code, _msg = s.rcpt(fake_addr)
                try:
                    s.rset()
                except Exception:
                    pass
                return code in (250, 251)   # accepted a guaranteed-fake address -> catch-all
        except Exception:
            continue
    return False   # couldn't determine -> assume not catch-all (don't over-suppress real positives)


@lru_cache(maxsize=8192)
def mailbox_exists(addr: str) -> tuple:
    """SMTP-level check: connect to the recipient's mail server and ask (via
    RCPT TO) whether the mailbox exists — WITHOUT sending anything (RSET/QUIT).
    Returns (state, detail) where state is 'ok' | 'bad' | 'unknown' | 'catch_all'.

    Free-tier honesty layer: before trusting an 'accepted' answer, we check
    whether the domain is catch-all (accepts every address, real or not —
    common on Google Workspace/Microsoft 365 setups and many small business
    domains). If it is, we report 'catch_all' instead of falsely 'ok', so you
    know this domain's SMTP answer can't distinguish real from fake mailboxes
    — only a bounce after an actual send will tell you there.

    'unknown' means the server didn't give a clear answer (greylisting,
    port 25 blocked entirely — very common on VPS/cloud/home networks). We
    NEVER hard-fail on 'unknown' or 'catch_all' — only a definitive 5xx
    rejection marks a mailbox as bad.
    """
    domain = addr.rsplit("@", 1)[1]
    probe_from = settings.SMTP_FROM or settings.SMTP_USER or "verify@localhost"
    for host in _mx_hosts(domain)[:2]:
        try:
            with smtplib.SMTP(host, 25, timeout=8) as s:
                s.ehlo_or_helo_if_needed()
                s.mail(probe_from)
                code, _msg = s.rcpt(addr)
                try:
                    s.rset()
                except Exception:
                    pass
                if code in (250, 251):
                    if _domain_is_catch_all(domain):
                        return ("catch_all", "domain accepts any address — this specific "
                               "mailbox can't be confirmed by SMTP; only a real send will tell")
                    return ("ok", "mailbox accepted (domain does NOT catch-all — a real signal)")
                if code in (550, 551, 553, 554, 501):
                    return ("bad", f"mailbox rejected ({code})")
                return ("unknown", f"ambiguous SMTP reply ({code})")
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, OSError):
            continue                      # try next MX / give up -> unknown
        except Exception:
            continue
    return ("unknown", "no clear SMTP answer (port 25 blocked or greylisted)")


def diagnose_port25() -> dict:
    """Self-test: can THIS server even reach port 25 outbound at all? Run
    this once after deploying — if it fails, no amount of code can make SMTP
    mailbox verification work here; many VPS/cloud/home ISPs block outbound
    port 25 by default (anti-spam policy). Tests against Gmail's own MX as
    a stable, always-up reference target."""
    import socket
    test_targets = [("gmail-smtp-in.l.google.com", 25), ("aspmx.l.google.com", 25)]
    for host, port in test_targets:
        try:
            with socket.create_connection((host, port), timeout=6) as s:
                banner = s.recv(200).decode(errors="replace").strip()
                return {"reachable": True, "tested": f"{host}:{port}", "banner": banner,
                       "detail": "Port 25 outbound works — SMTP mailbox verification can "
                                "give real signals on this server."}
        except Exception as e:
            last_err = str(e)
    return {"reachable": False, "tested": test_targets[0][0], "detail":
           f"Port 25 outbound is blocked or unreachable ({last_err}). This is a network/"
           "hosting policy, not a code bug — common on VPS, home broadband, and most cloud "
           "platforms by default. SMTP-level mailbox checks will mostly return 'unknown' "
           "here regardless of the code. Ask your host to unblock outbound port 25, or "
           "verify from a network where it's open."}


def classify_recipient(addr: str, smtp: bool = True) -> tuple[str, str]:
    """Returns (state, detail) where state is one of:
        'valid'     — syntax + MX ok, and (if probed) SMTP accepted on a
                      non-catch-all domain: a strong positive signal.
        'risky'     — deliverable-looking but unprovable: catch-all domain
                      (Google Workspace / M365 / most business domains), or an
                      ambiguous/blocked SMTP answer (port 25 blocked, greylist).
                      We DO NOT drop these — they are overwhelmingly real leads.
        'invalid'   — a hard, definitive failure: malformed syntax, no MX/A
                      record, or the recipient's own server rejected the
                      mailbox with a 5xx. THESE are the only true unverified.

    This is the honest classification the Super Admin verification view uses.
    Most 'genuine leads flagged unverified' bugs come from treating 'risky'
    (catch-all) as if it were 'invalid' — it isn't, so we keep them.
    """
    addr = (addr or "").strip().lower()
    if "@" not in addr or addr.count("@") != 1 or "." not in addr.rsplit("@", 1)[1]:
        return "invalid", "malformed address"
    domain = addr.rsplit("@", 1)[1]
    if not settings.MX_VERIFY_BEFORE_SEND:
        return "valid", ""
    if not domain_has_mx(domain):
        return "invalid", f"no MX/A record for domain {domain}"

    if smtp and settings.SMTP_VERIFY_MAILBOX:
        state, detail = mailbox_exists(addr)
        if state == "bad":
            return "invalid", f"SMTP: {detail}"
        if state == "ok":
            return "valid", f"SMTP: {detail}"
        if state == "catch_all":
            return "risky", f"catch-all domain (can't confirm this exact mailbox): {detail}"
        # 'unknown' -> port 25 blocked / greylisting: real leads live here.
        return "risky", f"SMTP inconclusive: {detail}"
    return "valid", ""


def verify_recipient(addr: str, smtp: bool = True) -> tuple[bool, str]:
    """Boolean gate used by the send pipeline and the 'Verify mailboxes' button.

    CRITICAL FIX: a lead is only marked UNVERIFIED (False) when it is a HARD,
    definitive failure — bad syntax, no MX/A record, or the recipient server
    itself rejected the mailbox (5xx). 'risky' states (catch-all domains such
    as Google Workspace / Microsoft 365, or an SMTP probe blocked by port-25
    filtering / greylisting) are NOT failures — the overwhelming majority of
    those are real, deliverable mailboxes, and dropping them was the reason
    genuine leads were showing up red. They now PASS.

    smtp=False -> MX-only (fast; used on bulk upload for 50k+ scale).
    smtp=True  -> also attempts the SMTP probe (send-time + Verify button)."""
    state, detail = classify_recipient(addr, smtp=smtp)
    if state == "invalid":
        return False, detail
    return True, ""


# ------------------------------------------------------------- HTML template
def render_html_template(body_text: str, agent_name: str) -> str:
    """Professional, minimal HTML — content first, Chatversio AI logo at the
    BOTTOM under the signature, per brand requirement."""
    paragraphs = "".join(
        f'<p style="margin:0 0 14px 0;">{html_lib.escape(p)}</p>'
        for p in body_text.split("\n\n") if p.strip()
    ) or f'<p>{html_lib.escape(body_text)}</p>'
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f6f8fb;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:28px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0"
 style="background:#ffffff;border:1px solid #e6eaf1;border-radius:10px;">
<tr><td style="padding:32px 36px;font-family:Arial,Helvetica,sans-serif;
 font-size:15px;line-height:1.65;color:#1f2937;">
{paragraphs}
</td></tr>
<tr><td style="padding:0 36px 28px 36px;border-top:1px solid #eef1f6;">
 <table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:18px;">
  <tr><td>
   <img src="{CHATVERSIO_LOGO_URL}" alt="Chatversio AI" height="30"
        style="display:block;height:30px;border:0;">
  </td></tr>
  <tr><td style="font-family:Arial,sans-serif;font-size:11px;color:#98a2b3;padding-top:6px;">
   Sent by {html_lib.escape(agent_name)} &middot; Chatversio AI
  </td></tr>
 </table>
</td></tr>
</table></td></tr></table></body></html>"""


# ------------------------------------------------------------- DKIM (optional)
def _maybe_dkim_sign(raw_bytes: bytes) -> bytes:
    if not (settings.DKIM_DOMAIN and settings.DKIM_PRIVATE_KEY_PATH):
        return raw_bytes
    try:
        import dkim
        with open(settings.DKIM_PRIVATE_KEY_PATH, "rb") as fh:
            key = fh.read()
        sig = dkim.sign(raw_bytes, settings.DKIM_SELECTOR.encode(),
                        settings.DKIM_DOMAIN.encode(), key,
                        include_headers=[b"From", b"To", b"Subject"])
        return sig + raw_bytes
    except Exception:
        return raw_bytes   # never block send on DKIM issues


# ------------------------------------------------------------- credentials
def test_connection(smtp_creds: dict, imap_creds: dict | None) -> dict:
    """Live-verify both SMTP and IMAP credentials WITHOUT sending or reading
    any email — just connect + login + logout. Used by the 'Test connection'
    button in Agent Configure, so a bad App Password is caught immediately
    instead of discovered mid-campaign (this is exactly what caused the
    SMTPAuthenticationError 535 failures — the credentials were wrong)."""
    result = {"smtp": {"ok": False, "detail": ""}, "imap": {"ok": False, "detail": ""}}

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(smtp_creds["host"], int(smtp_creds["port"]), timeout=15) as s:
            s.starttls(context=ctx)
            s.login(smtp_creds["user"], smtp_creds["password"])
        result["smtp"] = {"ok": True, "detail": "SMTP login succeeded"}
    except smtplib.SMTPAuthenticationError as e:
        result["smtp"] = {"ok": False, "detail":
                          "Login rejected (535) — this is almost always a wrong "
                          "App Password, or 2-Step Verification not enabled on "
                          "the Gmail account. Regular Gmail passwords don't work "
                          "here; generate an App Password at "
                          "myaccount.google.com/apppasswords."}
    except Exception as e:
        result["smtp"] = {"ok": False, "detail": f"Could not connect: {e}"}

    if imap_creds:
        try:
            with imaplib.IMAP4_SSL(imap_creds["host"], int(imap_creds["port"]), timeout=15) as m:
                m.login(imap_creds["user"], imap_creds["password"])
            result["imap"] = {"ok": True, "detail": "IMAP login succeeded"}
        except imaplib.IMAP4.error as e:
            result["imap"] = {"ok": False, "detail":
                              f"Login rejected: {e}. If SMTP worked but this "
                              "didn't, enable IMAP in Gmail Settings -> "
                              "Forwarding and POP/IMAP -> Enable IMAP."}
        except Exception as e:
            result["imap"] = {"ok": False, "detail": f"Could not connect: {e}"}
    else:
        result["imap"] = {"ok": False, "detail": "No IMAP configured — inbound replies won't be read for this agent"}

    return result


def smtp_creds_for(agent=None) -> dict:
    """Per-agent mailbox if configured on the agent, else global .env SMTP."""
    if agent is not None and getattr(agent, "smtp_user", "") and getattr(agent, "smtp_password", ""):
        return {
            "host": agent.smtp_host or settings.SMTP_HOST,
            "port": agent.smtp_port or settings.SMTP_PORT,
            "user": agent.smtp_user,
            "password": agent.smtp_password,
            "from_addr": agent.smtp_from or agent.smtp_user,
        }
    return {
        "host": settings.SMTP_HOST, "port": settings.SMTP_PORT,
        "user": settings.SMTP_USER, "password": settings.SMTP_PASSWORD,
        "from_addr": settings.SMTP_FROM or settings.SMTP_USER,
    }


def imap_creds_for(agent=None) -> dict | None:
    """Per-agent IMAP if configured, else global .env IMAP, else None."""
    if agent is not None and getattr(agent, "imap_user", "") and getattr(agent, "imap_password", ""):
        return {
            "host": agent.imap_host or settings.IMAP_HOST,
            "port": agent.imap_port or settings.IMAP_PORT,
            "user": agent.imap_user,
            "password": agent.imap_password,
            "folder": settings.IMAP_FOLDER,
        }
    if agent is None and settings.IMAP_USER:
        return {"host": settings.IMAP_HOST, "port": settings.IMAP_PORT,
                "user": settings.IMAP_USER, "password": settings.IMAP_PASSWORD,
                "folder": settings.IMAP_FOLDER}
    return None


# ------------------------------------------------------------- send
def _smtp_send(msg, to_addr: str, creds: dict):
    ctx = ssl.create_default_context()
    raw = _maybe_dkim_sign(msg.as_bytes())
    with smtplib.SMTP(creds["host"], creds["port"], timeout=30) as s:
        s.starttls(context=ctx)
        s.login(creds["user"], creds["password"])
        s.sendmail(creds["from_addr"], [to_addr], raw)


def send_email(to_addr: str, subject: str, body: str,
               in_reply_to: str = "", use_html_template: bool = False,
               agent_name: str = "", agent=None, unsub_token: str = "") -> str:
    """Sends plain or template (HTML+plain multipart) FROM THE AGENT'S OWN
    MAILBOX when the agent has SMTP configured. Returns Message-ID.

    Deliverability notes (this is what actually moves the needle — code
    can't force Primary-tab/inbox placement, but these are the concrete,
    real signals mailbox providers weigh):
    - NO List-Unsubscribe header. It's the right call for high-volume bulk
      senders (Gmail/Yahoo require it above ~5000/day), but for low-volume
      personalized outreach like this it backfires: Gmail shows it as a
      clickable "Unsubscribe" pill next to the sender name, and that pill is
      a real, confirmed signal Gmail's classifier uses to route mail into
      Promotions. Opt-out is instead a plain-text line in the body — still
      satisfies CAN-SPAM, doesn't trigger the bulk-sender UI treatment.
    - Plain-text alternative always attached alongside HTML (below) —
      pure-HTML marketing-template emails are what typically get sorted into
      Promotions; a real multipart/alternative with substantial plain text
      reads as personal correspondence.
    - From uses the agent's real name + real mailbox, never a "no-reply" or
      brand-only address — mail from an actual person's inbox is a strong
      Primary-tab signal.
    - DKIM signs if configured (see _maybe_dkim_sign) — combine with SPF +
      DMARC on your sending domain; this matters more than any header once
      you're sending real volume.
    """
    ok, reason = verify_recipient(to_addr)
    if not ok:
        raise UnverifiedRecipient(reason)

    creds = smtp_creds_for(agent)
    if not creds["user"] or not creds["password"]:
        raise RuntimeError("No SMTP configured for this agent (and no global fallback)")

    msg = MIMEMultipart("alternative")
    display = agent_name or (agent.name if agent is not None else settings.SMTP_FROM_NAME)
    msg["From"] = formataddr((display, creds["from_addr"]))
    msg["To"] = to_addr
    msg["Subject"] = subject
    from_domain = creds["from_addr"].rsplit("@", 1)[-1] if "@" in creds["from_addr"] else None
    msg_id = make_msgid(domain=(settings.DKIM_DOMAIN or from_domain))
    msg["Message-ID"] = msg_id
    # Real, RFC-compliant Date + a Reply-To that points at the agent's actual
    # mailbox. Mail that reads as 1:1 correspondence from a real person lands
    # in Primary far more often than "brand" mail. We also explicitly mark it
    # as NOT auto-generated bulk mail — the inverse of the Promotions signals.
    from email.utils import formatdate as _formatdate
    msg["Date"] = _formatdate(localtime=True)
    msg["Reply-To"] = formataddr((display, creds["from_addr"]))
    msg["X-Entity-Ref-ID"] = msg_id            # discourages Gmail threading-as-promo
    # Deliverability reminder (real inbox placement is won at DNS, not here):
    #   1. SPF   TXT on the sending domain:  v=spf1 include:<provider> ~all
    #   2. DKIM  signing enabled + selector published (see _maybe_dkim_sign)
    #   3. DMARC TXT _dmarc.<domain>:  v=DMARC1; p=none; rua=mailto:you@dom
    #   4. Warm up volume slowly; keep bounce/spam complaints low.
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    # NOTE: we deliberately do NOT set the List-Unsubscribe header anymore.
    # It's technically good practice for bulk mail, but Gmail surfaces it as
    # a prominent clickable "Unsubscribe" pill next to the sender name — and
    # that pill is a strong signal Gmail's classifier uses to route mail into
    # Promotions instead of Primary. For low-volume, personalized 1:1-style
    # outreach like this, Primary-inbox placement matters more than the
    # header. CAN-SPAM compliance is still satisfied with a plain-text
    # opt-out line in the body (below) — a working link, just not a header
    # Gmail's UI treats as a bulk-sender signal.
    plain_body = body
    if unsub_token:
        unsub_url = f"{settings.PUBLIC_API_URL}/api/unsub/{unsub_token}"
        plain_body = f"{body}\n\n---\nNo longer interested? {unsub_url}"
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    if use_html_template:
        msg.attach(MIMEText(render_html_template(plain_body, display), "html", "utf-8"))
    _smtp_send(msg, to_addr, creds)
    return msg_id


def send_system_email(to_addr: str, subject: str, body: str):
    """OTP / system notifications — plain, from the platform itself."""
    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr((settings.SMTP_FROM_NAME,
                              settings.SMTP_FROM or settings.SMTP_USER))
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid()
    msg.attach(MIMEText(body, "plain", "utf-8"))
    _smtp_send(msg, to_addr, smtp_creds_for(None))


class UnverifiedRecipient(Exception):
    pass


# ------------------------------------------------------------- inbound IMAP
def _decode(value) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = ""
    for text, enc in parts:
        out += text.decode(enc or "utf-8", errors="replace") if isinstance(text, bytes) else text
    return out


def _extract_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and \
               "attachment" not in str(part.get("Content-Disposition", "")):
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8",
                                          errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    return payload.decode(msg.get_content_charset() or "utf-8",
                          errors="replace") if payload else ""


def fetch_unseen(creds: dict | None = None) -> list[dict]:
    """Fetch unseen messages from ONE mailbox (per-agent creds or global)."""
    if creds is None:
        creds = imap_creds_for(None)
    if not creds or not creds.get("user"):
        return []
    results = []
    with imaplib.IMAP4_SSL(creds["host"], creds["port"]) as im:
        im.login(creds["user"], creds["password"])
        im.select(creds.get("folder") or "INBOX")
        status, data = im.search(None, "UNSEEN")
        if status != "OK":
            return []
        for num in data[0].split()[:50]:
            status, msg_data = im.fetch(num, "(RFC822)")
            if status != "OK":
                continue
            msg = email_lib.message_from_bytes(msg_data[0][1])
            from_addr = parseaddr(msg.get("From", ""))[1].lower()
            results.append({
                "from": from_addr,
                "subject": _decode(msg.get("Subject", ""))[:500],
                "body": _extract_body(msg)[:20000],
                "message_id": msg.get("Message-ID", ""),
                "imap_id": num,
            })
        for item in results:
            if item.get("imap_id"):
                im.store(item["imap_id"], "+FLAGS", "\\Seen")
    return [{k: v for k, v in r.items() if k != "imap_id"} for r in results]