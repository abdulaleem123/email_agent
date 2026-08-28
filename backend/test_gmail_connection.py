"""Standalone Gmail SMTP + IMAP test — run this BEFORE configuring an agent's
mailbox in the app, so you catch credential/App-Password issues in 10 seconds
instead of debugging through the full campaign pipeline.

Usage:
    python test_gmail_connection.py you@gmail.com "your 16-char app password"

What it does:
1. Connects to smtp.gmail.com:587, logs in, sends yourself a real test email.
2. Connects to imap.gmail.com:993, logs in, lists your 3 most recent
   INBOX subjects (proves IMAP read access works too).

If step 1 fails: your App Password is wrong, or 2-Step Verification isn't on.
If step 2 fails: same credentials, but IMAP might be disabled in Gmail
settings (Settings -> Forwarding and POP/IMAP -> Enable IMAP).
"""
import imaplib
import smtplib
import ssl
import sys
from email.mime.text import MIMEText
from email.utils import make_msgid


def test_smtp(email_addr: str, app_password: str) -> bool:
    print(f"[SMTP] Connecting to smtp.gmail.com:587 as {email_addr} ...")
    try:
        msg = MIMEText("This is a test email from Chatversio AI's connection checker. "
                       "If you received this, SMTP is working correctly.")
        msg["Subject"] = "Chatversio AI — SMTP test"
        msg["From"] = email_addr
        msg["To"] = email_addr
        msg["Message-ID"] = make_msgid()

        ctx = ssl.create_default_context()
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as s:
            s.starttls(context=ctx)
            s.login(email_addr, app_password)
            s.sendmail(email_addr, [email_addr], msg.as_bytes())
        print("[SMTP] ✅ Sent successfully — check your inbox for the test email.")
        return True
    except smtplib.SMTPAuthenticationError:
        print("[SMTP] ❌ Login rejected. Common causes:")
        print("       - You used your normal Gmail password instead of an App Password")
        print("       - 2-Step Verification isn't enabled on this account")
        print("       - The App Password was copied with extra spaces")
        return False
    except Exception as e:
        print(f"[SMTP] ❌ Failed: {e}")
        return False


def test_imap(email_addr: str, app_password: str) -> bool:
    print(f"\n[IMAP] Connecting to imap.gmail.com:993 as {email_addr} ...")
    try:
        with imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=15) as m:
            m.login(email_addr, app_password)
            m.select("INBOX", readonly=True)
            typ, data = m.search(None, "ALL")
            ids = data[0].split()[-3:]  # last 3
            print(f"[IMAP] ✅ Logged in. {len(data[0].split())} messages in INBOX. "
                 "Most recent subjects:")
            for i in reversed(ids):
                typ, msg_data = m.fetch(i, "(BODY[HEADER.FIELDS (SUBJECT)])")
                subj = msg_data[0][1].decode(errors="replace").replace("Subject:", "").strip()
                print(f"         - {subj or '(no subject)'}")
        return True
    except imaplib.IMAP4.error as e:
        print(f"[IMAP] ❌ Failed: {e}")
        print("       If SMTP worked but this didn't: Gmail Settings -> "
             "Forwarding and POP/IMAP -> Enable IMAP -> Save Changes")
        return False
    except Exception as e:
        print(f"[IMAP] ❌ Failed: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python test_gmail_connection.py you@gmail.com \"app password\"")
        sys.exit(1)
    email_addr, app_password = sys.argv[1], sys.argv[2].replace(" ", "")
    smtp_ok = test_smtp(email_addr, app_password)
    imap_ok = test_imap(email_addr, app_password)
    print(f"\n{'='*50}")
    print(f"SMTP (outbound): {'OK' if smtp_ok else 'FAILED'}")
    print(f"IMAP (inbound):  {'OK' if imap_ok else 'FAILED'}")
    if smtp_ok and imap_ok:
        print("\nBoth work — safe to enter these exact credentials into the agent's")
        print("Configure -> Mailbox settings in Chatversio AI.")
    sys.exit(0 if (smtp_ok and imap_ok) else 1)