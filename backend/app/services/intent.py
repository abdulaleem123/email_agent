"""Intent + human-review decisions on every inbound message.

One pass over the prospect's text answers three questions the send pipeline
actually needs, in the order they matter:

1. NOT INTERESTED? ("not interested", "we don't want to work", "remove me")
   -> stop everything for this lead. No reply, no follow-ups. The lead goes to
   the Garbage inbox and is purged on the campaign's 30-day clock. Replying
      again here is the single most common way an outbound engine turns a
      polite "no" into a reputation problem, so the answer is silence + park.

2. DOES A HUMAN HAVE TO ANSWER? (pricing, discount numbers, contracts, legal,
   compliance, security questionnaires, "who are you really", company/website
   facts) -> NEVER answer automatically. The agent auto-pauses on the thread and
   the message is escalated for a human. An AI that invents a price or agrees to
   a contract term is a liability, so the rule is hard: no guessing, ever.

3. IS THIS A DEMO SIGNAL? -> a human can book a live session, so reply with the
   real-time demo offer instead of a brochure.

Why a pattern pass and not an LLM call: this runs on EVERY inbound mail, before
any generation, and a wrong answer here either silences a live deal or lets an
agent quote a price. Deterministic rules are auditable and free; the LLM only
writes the words, never the decision.
"""
import re
from dataclasses import dataclass, field

from .scenario_detector import detect_scenario

# ── 1. "not interested" / "we don't want to work" ─────────────────────────────
# Deliberately generous: a soft no, a hard no, a "we're not looking at this",
# a "we don't want to work with you" and a compliance opt-out all mean the same
# thing operationally — stop emailing this person.
_NOT_INTERESTED = [
    r"\bnot interested\b",
    r"\bnot (very )?interested\b",
    r"\bno interest\b",
    r"\buninterested\b",
    r"\bwe'?re not interested\b",
    r"\bwe are not interested\b",
    r"\bnot looking (at|for|into)\b",
    r"\bnot (currently )?(looking|shopping) (around|for)\b",
    r"\bwe don'?t (want|need)\b",
    r"\bwe do not (want|need)\b",
    r"\bdon'?t want to (work|do) (with|this)\b",
    r"\bdo not want to work\b",
    r"\bnot going to (work|proceed|continue)\b",
    r"\bnot (a )?priority\b",
    r"\bnot relevant\b",
    r"\bnot for us\b",
    r"\bnot a (good )?fit\b",
    r"\bpass on this\b",
    r"\bpass(ed)? on\b",
    r"\bno thanks?\b",
    r"\bnot right now\b",
    r"\bnot at this (time|stage|moment)\b",
    r"\bunsubscr(ibe|ibing)\b",
    r"\bremove me\b",
    r"\bstop (emailing|contacting|sending)\b",
    r"\bdo not contact\b",
    r"\bdon'?t contact\b",
    r"\bplease (delete|remove) (my|our) (address|details|record)\b",
    r"\bwe'?ve (got|enough) (a )?(vendor|supplier)s?\b",
    r"\balready (have|got) (something|someone|a solution|a vendor)\b",
    r"\bwe'?re (all )?set\b",
]

# ── 2. never auto-answer: a human owns these ────────────────────────────────
# Each entry is (regex, human_reason). The reason is what the Escalation page
# shows, so it has to tell the operator WHICH of these it was.
_NEEDS_HUMAN: list[tuple[str, str]] = [
    # ── pricing / commercials: an AI must never invent or negotiate a number ──
    (r"\b(what|how much|whats|whats)\s*(is|are|would be)?\s*(the|your|it|this)?\s*"
     r"(pricing|price|cost|costs|rate|rates|fee|fees|charge|charges|"
     r"budget|investment)\b", "pricing-question"),
    (r"\b(price|pricing|cost|rate|fee)s?\s*(list|breakdown|sheet|details|info)\b",
     "pricing-question"),
    (r"\b(send|share|give)\s*(me|us)?\s*(the |your )?(pricing|price list|rate card|"
     r"quotation|quote|proposal|deck with prices)\b", "pricing-question"),
    (r"\bquote\b|\bquotation\b", "pricing-question"),
    (r"\bdiscount\b|\bbetter price\b|\bnegotiate\b|\bspecial rate\b|\bpayment plan\b",
     "pricing-question"),
    (r"\bfree (trial|consultation|audit)\b|\bno obligation\b|\bmoney back\b",
     "pricing-question"),
    (r"\bwho (pays|payment|invoice|do i pay)\b|\bpurchase order\b|\bPO number\b",
     "pricing-question"),
    # ── contract / legal / procurement ──
    (r"\bcontract\b|\bagreement\b|\bterms of service\b|\bmsa\b|\bsow\b",
     "contract-legal"),
    (r"\bindemnit|\bliability\b|\bwarrant(y|ies)\b|\bsla\b|\buptime guarantee\b",
     "contract-legal"),
    (r"\b(nda|non.?disclosure)\b", "contract-legal"),
    (r"\binvoice (address|vat|number|details)\b|\bvat (number|registration)\b",
     "contract-legal"),
    (r"\bprocurement\b|\bvendor (onboarding|registration|portal)\b",
     "contract-legal"),
    # ── security / compliance / privacy ──
    (r"\b(security|compliance) (questionnaire|audit|review|certif|docs?|documents)\b",
     "security-compliance"),
    (r"\bsoc\s?2\b|\biso\s?27001\b|\bgdpr\b|\bhipaa\b|\bpci\b|\bpen test\b",
     "security-compliance"),
    (r"\bdata (processing|residency|retention|protection)\b|\bdpa\b|"
     r"\bdpa\b|\bprivacy policy\b|\bsub.?processors?\b", "security-compliance"),
    # ── "who are you / are you real" + company/website facts ──
    (r"\bwho (are|is) (you|your (company|team|business))\b",
     "company-verification"),
    (r"\bare you (a )?(real|legit|legitimate|scam|bot|human)\b",
     "company-verification"),
    (r"\b(company|registration|incorporation) (name|number|details|address|details)\b",
     "company-verification"),
    (r"\b(where|which) (country|city) (are|is) (you|your (company|business|team))",
     "company-verification"),
    (r"\byour (website|site|address|phone number|office)\b",
     "company-verification"),
    (r"\blegal (name|entity|company name)\b|\bregistered (address|name)\b",
     "company-verification"),
]

# ── 3. demo signal ───────────────────────────────────────────────────────────
_DEMO = [
    r"\bdemo\b", r"\bdemonstrat", r"\bshow me\b", r"\blet'?s (see|chat|talk)\b",
    r"\bwalk me through\b", r"\bscreen ?share\b", r"\blive (session|call|look)\b",
    r"\bcan (i|we) (see|try|test|book)\b", r"\btrial\b",
    r"\bsend (me )?(a )?(meeting|calendar|call) (link|time)\b",
]

# ── 4. INTERESTED -> the lead is HOT and the thread stays in Messages ────────
# Only ever consulted when the message is not a decline: a "not interested"
# wins first, always.
_INTERESTED = [
    r"\bi'?m interested\b", r"\bwe'?re interested\b", r"\binterested in (this|it|hearing)\b",
    r"\bthat sounds (good|interesting|great|useful)\b",
    r"\blet'?s (book|schedule|set up|arrange|talk|chat)\b",
    r"\bbook (a|the|us) (call|meeting|demo|time|session)\b",
    r"\bschedule (a|the) (call|meeting|demo)\b",
    r"\bworth (a )?(chat|call|conversation|discussion)\b",
    r"\bsend (me|us) (a |the )?(proposal|details|information|info|deck)\b",
    r"\bwhen can (we|i) (talk|chat|meet|start)\b",
    r"\btell me more\b", r"\bmore details\b",
    r"\byes (please|that would|lets)\b",
    r"\bgo ahead\b", r"\bcount (me|us) in\b",
    r"\blooks? like a (good )?fit\b",
]


def _hits(text: str, patterns: list[str]) -> list[str]:
    return [p for p in patterns if re.search(p, text)]


@dataclass
class Intent:
    """Everything the pipeline decided about one inbound message."""
    scenario: str = "unknown"          # existing scenario_detector code
    not_interested: bool = False
    needs_human: bool = False
    human_reason: str = ""             # pricing-question | contract-legal | ...
    demo_interest: bool = False
    interested: bool = False           # -> lead marked HOT, thread stays in Messages
    matched: list[str] = field(default_factory=list)

    @property
    def replyable(self) -> bool:
        """False when the agent must not write back on its own."""
        return not (self.not_interested or self.needs_human)

    def as_dict(self) -> dict:
        return {"scenario": self.scenario, "not_interested": self.not_interested,
                "needs_human": self.needs_human, "human_reason": self.human_reason,
                "demo_interest": self.demo_interest,
                "interested": self.interested,
                "replyable": self.replyable}


def classify(text: str) -> Intent:
    """Read one inbound body and decide what happens to the lead.

    Order matters. A "not interested" wins over everything, because a decline
    is a decline even if the same message also mentions price. A human-review
    trigger is checked next so a question we must never answer on our own is
    caught even in a warm, otherwise-replyable note."""
    body = (text or "").lower()
    out = Intent(scenario=detect_scenario(text).code)

    not_int = _hits(body, _NOT_INTERESTED)
    if not_int:
        out.not_interested = True
        out.matched = not_int[:4]

    human = [(p, r) for p, r in _NEEDS_HUMAN if re.search(p, body)]
    if human:
        out.needs_human = True
        # Keep the FIRST match's reason: the list is ordered most-specific
        # first, so "pricing-question" beats a trailing "contract" mention in
        # the same message.
        out.human_reason = human[0][1]
        out.matched += [h[0] for h in human[:3]]

    if _hits(body, _DEMO):
        out.demo_interest = True

    # INTERESTED only when it is NOT a decline — a "no" always wins, and the
    # message itself is never touched, so the conversation stays in Messages.
    if not out.not_interested and _hits(body, _INTERESTED):
        out.interested = True

    return out


def describe(intent: Intent) -> str:
    """One-line, human-readable summary for the Escalation page and the system
    note written onto the lead."""
    if intent.not_interested:
        return ("Prospect said they are not interested - follow-up sequence ended, "
                "lead marked COLD, conversation kept in Messages, lead moved to Trash.")
    if intent.interested:
        return ("Prospect showed interest - lead marked HOT, conversation kept "
                "in Messages.")
    if intent.needs_human:
        return {
            "pricing-question": "Prospect asked about pricing/commercials — never answered by AI, auto-paused for a human.",
            "contract-legal": "Prospect raised contract/legal terms — never answered by AI, auto-paused for a human.",
            "security-compliance": "Prospect asked a security/compliance question — never answered by AI, auto-paused for a human.",
            "company-verification": "Prospect asked who we are / for company details — never answered by AI, auto-paused for a human.",
        }.get(intent.human_reason, "Needs a human answer — agent auto-paused.")
    return ""
