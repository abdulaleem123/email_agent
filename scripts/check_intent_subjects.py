"""Smoke test for the two deterministic services: intent + subjects.

Loads them without importing the app package (which needs pydantic_settings and
a live Postgres), so this runs on any machine.
"""
import importlib.util
import pathlib
import sys
import time
import types

root = pathlib.Path(__file__).resolve().parent.parent
svc = root / "backend" / "app" / "services"

pkg = types.ModuleType("svcs")
pkg.__path__ = [str(svc.resolve())]
sys.modules["svcs"] = pkg
for name in ("scenario_detector", "intent", "subjects"):
    spec = importlib.util.find_spec("svcs." + name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["svcs." + name] = mod
    spec.loader.exec_module(mod)

intent = sys.modules["svcs.intent"]
subjects = sys.modules["svcs.subjects"]

fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")
    print(f"{'ok  ' if ok else 'FAIL'} {label}")


print("── not interested → agent goes silent, lead parks in Garbage ──")
for t in ("not interested", "We do not want to work with you",
          "No thanks, please remove me", "stop emailing me",
          "we are not looking for this", "We're all set"):
    r = intent.classify(t)
    check(f"not_interested {t[:34]!r}", r.not_interested, True)
    check(f"  replyable      {t[:34]!r}", r.replyable, False)

print("\n── not interested beats a price mention in the same mail ──")
r = intent.classify("not interested, but what is your pricing?")
check("decline wins over price", (r.not_interested, r.needs_human), (True, True))
check("  replyable", r.replyable, False)

print("\n── price / contract / security / who-are-you → a human, never the AI ──")
for t, reason in (("what is your pricing?", "pricing-question"),
                  ("send me the quote", "pricing-question"),
                  ("do you have a contract?", "contract-legal"),
                  ("how do you handle GDPR data security?", "security-compliance"),
                  ("who are you guys?", "company-verification"),
                  ("what is your website?", "company-verification"),
                  ("can we sign an NDA?", "contract-legal")):
    r = intent.classify(t)
    check(f"needs_human {t[:34]!r}", r.needs_human, True)
    check(f"  reason      {t[:34]!r}", r.human_reason, reason)
    check(f"  replyable   {t[:34]!r}", r.replyable, False)

print("\n── normal mail is left for the agent ──")
for t in ("looks good, let us talk", "we already use a competitor",
          "what are your opening hours?", "sent over the deck, had a look"):
    r = intent.classify(t)
    check(f"replyable {t[:34]!r}", r.replyable, True)

print("\n── demo interest is detected ──")
r = intent.classify("can we get a demo tomorrow?")
check("demo_interest", r.demo_interest, True)
check("  still replyable", r.replyable, True)

print("\n── subjects: <= 4 words, capitalised, no repeats, region-aware ──")


class Lead:
    def __init__(self, country="", company="", title="", messages=()):
        self.country = country
        self.company = company
        self.title = title
        self.industry = ""
        self.messages = list(messages)


class Msg:
    def __init__(self, direction, subject):
        self.direction = direction
        self.subject = subject


class Camp:
    subject_max_words = 4
    followup_plan = "3,7,14"
    strategy_notes = ""
    pain_focus = "support tickets"
    target_focus = "unanswered support email"
    what_to_sell = "chat agents and voice agents"
    industry = ""


lead = Lead(country="United States", company="Northwind Logistics",
            title="Operations Manager", messages=[Msg("out", "Support load")])
c = Camp()
seen = set()
for i in range(6):
    s = subjects.build_subject(lead, c, followup_number=i, used=seen)
    words = len(s.split())
    check(f"followup {i} word count ({s!r})", words <= subjects.MAX_WORDS, True)
    check(f"followup {i} capitalised ({s!r})", s[:1].isupper(), True)
    check(f"followup {i} unique ({s!r})", s.lower() not in seen, True)
    seen.add(s.lower())

print("\n── same campaign, different country → different wording ──")
a = subjects.build_subject(Lead(country="United States", company="Acme Dental"), c)
b = subjects.build_subject(Lead(country="United Arab Emirates", company="Acme Dental"), c)
check("US vs GCC pick different lines", a != b, True)
print(f"  US : {a!r}")
print(f"  GCC: {b!r}")

print("\n── normaliser strips junk and never emits banned openers ──")
for raw, want_max in (("Re: Fwd: Quick question about pricing!!!", subjects.MAX_WORDS),
                      ("Following up on this", subjects.MAX_WORDS),
                      ("Worth a look", subjects.MAX_WORDS)):
    out = subjects._normalise(raw, subjects.MAX_WORDS)
    print(f"     {raw[:30]!r} -> {out!r}")
    # A banned opener is REJECTED outright (""), never repaired by chopping the
    # first word off — that used to turn "Quick check" into "Check".
    first = out.split(" ")[0].lower() if out else ""
    check(f"  usable or rejected {raw[:24]!r}", out == "" or first not in subjects.BANNED_STARTERS, True)
    if out:
        check(f"  <= {want_max}w", len(out.split()) <= want_max, True)
        check(f"  capitalised", out[:1].isupper(), True)
check("banned opener is rejected outright",
      subjects._normalise("Quick check", subjects.MAX_WORDS), "")
check("banned opener is rejected outright 2",
      subjects._normalise("Following up on this", subjects.MAX_WORDS), "")

print("\n── every banked candidate obeys the 4-word rule ──")
for country in ("United States", "United Kingdom", "Germany", "UAE", "India", "Australia"):
    for company in ("", "Acme Dental", "Northwind Logistics", "Riyadh Clinic",
                    "Berlin Dental Group", "Shopify Store"):
        for cand in subjects.subject_bank_preview(Lead(country=country, company=company), c, 20):
            if len(cand.split()) > subjects.MAX_WORDS:
                fails.append(f"{country}/{company}: {cand!r} is {len(cand.split())} words")
                print(f"FAIL {country}/{company}: {cand!r}")
print("ok   all banked candidates are <= 4 words")

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILURE(S)"))
sys.exit(1 if fails else 0)
