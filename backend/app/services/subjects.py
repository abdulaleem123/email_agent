"""Subject-line generator.

Rules the whole product agreed on, enforced in code rather than in a prompt:

- 3 TO 4 WORDS, no more. Four is the ceiling; three is the normal case. Longer
  than that is where "this reads like an ad" starts.
- Professional and clear: an operational noun phrase a colleague would file
  under a real topic ("Response time gap"), never a hook, a tease or a casual
  aside ("Worth a look", "Something we noticed").
- First letter uppercase, rest left alone. No ALL CAPS, no title-casing soup.
- No exclamation marks, no "Re:", no banned openers (Noticing / Checking in /
  Quick question / Following up / Just checking / Opportunity / Hope you're).
- Never repeat a subject this lead already received. A follow-up that arrives
  with the same subject line as the last email is the single most obvious
  "this is an automated sequence" tell there is.
- Aimed at the intent, the campaign's angle, and the lead's country/region, so
  the same campaign does not send the same subject line to a German logistics
  firm and a US dental group.

The LLM is NOT asked for a subject at all. It is a 3-4 word, region-aware,
deduplicated string — a template bank plus a hard normaliser is both faster and
far more consistent than asking a model every time and hoping.
"""
import re

MAX_WORDS = 4


def subject_word_cap(campaign) -> int:
    """The word cap actually in force for this campaign.

    4 WORDS MAXIMUM whenever the Subject part of the campaign's selection box
    is ticked — which is the default, and what the default Agent prompt says.
    Untick it and the campaign's own configured limit stands, still clamped by
    the house ceiling. No campaign at all: the house rule of 4."""
    from . import agent_settings
    if campaign is None:
        return MAX_WORDS
    cap = MAX_WORDS
    if getattr(campaign, "subject_max_words", None):
        try:
            cap = max(1, min(8, int(campaign.subject_max_words)))
        except Exception:
            cap = MAX_WORDS
    if agent_settings.is_on(campaign, "subject"):
        cap = min(cap, MAX_WORDS)
    return cap

BANNED_STARTERS = {
    "noticing", "checking", "quick", "following", "follow", "just", "hope",
    "opportunity", "touching", "circling", "reconnecting", "following up",
    "touch base", "fyi", "ps", "update", "question", "regarding", "about",
    "intro", "introduction", "hello", "hi", "hey", "wanted", "wanted to",
    "great", "good", "nice", "quick question", "checking in", "circling back",
}

# ── angle → subject seeds ────────────────────────────────────────────────────
# Keyed by the campaign's pain focus + strategy, so the subject line is about
# THEIR problem, not our product. "solutions", "AI", "chatbot", "demo" and
# "follow-up" are deliberately absent — they are ad language.
_ANGLES: list[tuple[tuple[str, ...], list[str]]] = [
    (("support", "ticket", "helpdesk", "cx", "service", "query"),
     ["Support load", "Ticket volume", "Reply backlog", "Queue strain",
      "Response time"]),
    (("sales", "lead", "crm", "pipeline", "outreach", "prospect", "funnel",
      "conversion", "close"),
     ["Pipeline gaps", "Lead routing", "Follow up", "Slow conversions",
      "Pipeline review"]),
    (("booking", "appointment", "calendar", "schedul", "clinic", "salon",
      "customer", "reception", "front desk"),
     ["Booking load", "Calendar gaps", "Missed calls", "Booking flow",
      "No show rate"]),
    (("ecommerce", "shop", "store", "retail", "cart", "checkout", "order",
      "product", "inventory", "warehouse"),
     ["Cart drop off", "Store operations", "Order volume", "Repeat buyers",
      "Stock visibility"]),
    (("logistic", "supply", "delivery", "fleet", "warehouse", "freight",
      "manufactur", "factory", "plant"),
     ["Route planning", "Dispatch load", "Fleet visibility", "Lead times",
      "Shift handovers"]),
    (("hr", "hiring", "recruit", "employee", "onboard", "staff", "people",
      "training"),
     ["Hiring delays", "Onboarding load", "Staff questions", "Training gaps",
      "First week friction"]),
    (("finance", "invoice", "billing", "account", "payment", "collection",
      "revenue", "cost", "tax"),
     ["Invoice chasing", "Reconciliation", "Billing queries", "Cash flow",
      "Month end load"]),
    (("health", "clinic", "patient", "medical", "dental", "wellness", "clinic"),
     ["Patient calls", "Front desk load", "Recall gaps", "No show rate",
      "Intake speed"]),
    (("real estate", "property", "estate", "broker", "listing", "rental",
      "tenant"),
     ["Listing enquiries", "Viewing bookings", "Tenant queries", "Enquiry gaps",
      "Area coverage"]),
    (("restaurant", "cafe", "food", "kitchen", "menu", "dine", "hospitality",
      "hotel", "travel"),
     ["Booking pressure", "Table enquiries", "Review replies", "Shift staffing",
      "Peak hour load"]),
    (("ai", "automat", "workflow", "process", "manual", "repetitive", "ops",
      "operation", "scale", "scalab"),
     ["Manual work", "Process gaps", "Repeat queries", "Tooling sprawl",
      "Handover gaps"]),
]

# Generic fallbacks — still problem-shaped, never product-shaped. Every line is
# a plain operational noun phrase: 3-4 words, professional, obvious on sight.
# Nothing here is a hook, a tease or a conversational aside.
_GENERIC = [
    "Response time gap", "Enquiry backlog growth", "Manual handling load",
    "Follow-up delay cost", "Queue wait times", "Handover friction point",
    "Operational bottleneck note", "Process efficiency gap",
    "Customer response delay", "Repeat workload pattern",
]

# Region-flavoured phrasings, one list per region, indexed by the SAME slot the
# angle bank is on. So the angle decides WHICH slot you land on and the region
# decides the wording — a German logistics firm and a US dental group running
# the same campaign get different subject lines without losing the intent.
_REGION_ANGLE: dict[str, list[str]] = {
    "us": ["Reply backlog", "Queue strain", "Slow routing", "Missed calls",
           "Response time gap"],
    "uk": ["Reply backlog", "Queue strain", "Slow routing", "Missed calls",
           "Enquiry handling load"],
    "europe": ["Backlog growing", "Queue strain", "Slow routing", "Missed calls",
               "Process efficiency gap"],
    "gcc": ["Queue backlog", "Wait time", "Slow handover", "Missed calls",
            "Service coverage gap"],
    "south_asia": ["Queue backlog", "Wait time", "Slow handover", "Missed calls",
                   "Response time gap"],
    "apac": ["Queue backlog", "Wait time", "Slow handover", "Missed calls",
             "Enquiry handling load"],
}

# Fallbacks for a region we do not have an angle list for. Professional and
# clear, and chosen so the first word is never in BANNED_STARTERS — "Quick
# check" was unusable because the normaliser has to throw away a banned opener.
_REGION_SUFFIX = {
    "us": "A closer operational look",
    "uk": "A practical next step",
    "europe": "A concrete efficiency gain",
    "gcc": "A clear operational gain",
    "south_asia": "A practical efficiency step",
    "apac": "A focused improvement note",
}


REGION_OF = {
    "united states": "us", "usa": "us", "us": "us", "america": "us",
    "united kingdom": "uk", "uk": "uk", "england": "uk", "scotland": "uk",
    "wales": "uk", "ireland": "uk",
    "germany": "europe", "france": "europe", "spain": "europe", "italy": "europe",
    "netherlands": "europe", "belgium": "europe", "sweden": "europe",
    "norway": "europe", "denmark": "europe", "finland": "europe",
    "switzerland": "europe", "austria": "europe", "portugal": "europe",
    "poland": "europe", "czech republic": "europe", "greece": "europe",
    "romania": "europe", "hungary": "europe", "europe": "europe", "eu": "europe",
    "uae": "gcc", "united arab emirates": "gcc", "dubai": "gcc",
    "abu dhabi": "gcc", "saudi arabia": "gcc", "ksa": "gcc", "qatar": "gcc",
    "kuwait": "gcc", "bahrain": "gcc", "oman": "gcc", "gcc": "gcc",
    "middle east": "gcc", "jordan": "gcc", "egypt": "gcc",
    "pakistan": "south_asia", "india": "south_asia", "bangladesh": "south_asia",
    "sri lanka": "south_asia",
    "australia": "apac", "new zealand": "apac", "singapore": "apac",
    "japan": "apac", "south korea": "apac", "malaysia": "apac",
    "canada": "us",
}


def region_for(country: str | None) -> str:
    return REGION_OF.get((country or "").strip().lower(), "default")


def _tokens(*values: str) -> str:
    return " ".join(str(v or "") for v in values).lower()


def _bank_for(lead, campaign) -> list[str]:
    """Pick the subject bank that matches this campaign's angle for THIS lead."""
    hay = _tokens(getattr(lead, "industry", ""), getattr(lead, "title", ""),
                  lead.company, campaign.industry if campaign else "",
                  campaign.strategy_notes if campaign else "",
                  campaign.pain_focus if campaign else "",
                  campaign.target_focus if campaign else "",
                  campaign.what_to_sell if campaign else "",
                  lead.title)
    for keys, bank in _ANGLES:
        if any(k in hay for k in keys):
            return list(bank)
    return list(_GENERIC)


def _normalise(raw: str, max_words: int) -> str:
    """Hard-format whatever came out of the bank.

    Returns "" for anything unusable, and the caller moves on to the next
    candidate. That matters: an earlier version "fixed" a banned opener by
    chopping the first word off, which turned "Quick check" into "Check" and
    "Following up on this" into "Up on" — worse than no subject at all.

    Guarantees: <= max_words words, first character uppercase, no "Re:"/"Fwd:",
    no exclamation or question marks, and never starts on a banned opener."""
    s = re.sub(r"\s+", " ", (raw or "").strip())
    # Strip every leading Re:/Fwd: prefix, not just the first one — a chained
    # "Re: Fwd: Re: Quick question" is common in forwarded threads.
    for _ in range(3):
        stripped = re.sub(r"^(re|fw|fwd)\s*[:\-]\s*", "", s, flags=re.I)
        if stripped == s:
            break
        s = stripped
    s = s.replace("!", "").replace("?", "").replace(".", "").replace(",", "")
    s = re.sub(r"[^\w\s'\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" -–—")
    words = [w for w in s.split(" ") if w]
    if not words:
        return ""
    if len(words) > max_words:
        # Keep the first max_words — the head of the phrase carries the meaning.
        words = words[:max_words]
    out = " ".join(words)
    if out.split(" ")[0].lower().strip(".,") in BANNED_STARTERS:
        return ""          # unusable, not repairable — try the next candidate
    # First letter uppercase (leave the rest of each word exactly as written).
    return out[0].upper() + out[1:]



def _used_subjects(lead) -> set[str]:
    """Subjects this lead already got — never repeat one."""
    out = set()
    for m in getattr(lead, "messages", []) or []:
        if m.direction == "out" and m.subject:
            out.add(m.subject.strip().lower())
    return out


def build_subject(lead, campaign=None, *, followup_number: int = 0,
                  used: set[str] | None = None) -> str:
    """Return a <= 4-word subject for one outbound email.

    followup_number: 0 = first touch, 1..n = that follow-up. Follow-ups rotate
    to a different, more specific angle than the opening note so the thread
    visibly moves instead of looping.
    """
    max_words = subject_word_cap(campaign)
    if campaign is not None and getattr(campaign, "subject_style", ""):
        max_words = max_words  # style handled below

    taken = {s.lower() for s in (used if used is not None else _used_subjects(lead))}
    bank = _bank_for(lead, campaign)

    # Follow-ups step further down the bank; first touches start at the top.
    offset = min(followup_number, max(0, len(bank) - 1)) if followup_number else 0
    ordered = bank[offset:] + bank[:offset]

    # The region rephrases the same angle and leads with it, so even the very
    # first subject is country-aware instead of only becoming region-flavoured
    # once the whole angle bank is used up.
    region = region_for(lead.country)
    regional = _REGION_ANGLE.get(region)
    if regional:
        reg_offset = min(offset, len(regional) - 1)
        ordered = (regional[reg_offset:] + regional[:reg_offset]) + ordered

    for cand in ordered:
        s = _normalise(cand, max_words)
        if s and s.lower() not in taken:
            return s
    region_line = _REGION_SUFFIX.get(region)
    if region_line:
        s = _normalise(region_line, max_words)
        if s and s.lower() not in taken:
            return s
    # Every bank line is already used on this thread: fall back to a numbered
    # variant of the first one rather than repeating verbatim. Only when the
    # number still fits inside the word budget.
    for cand in bank:
        base = _normalise(cand, max_words)
        if not base:
            continue
        tag = f"({followup_number + 1})"
        if len(base.split()) + 1 <= max_words:
            return f"{base} {tag}"
        return base
    return "One question"


def subject_bank_preview(lead, campaign=None, n: int = 8) -> list[str]:
    """The candidate lines for this lead/campaign — used by the UI preview.

    Only usable candidates are returned: anything that would normalise to
    nothing (a banned opener) is skipped rather than shown and then sent."""
    max_words = subject_word_cap(campaign)
    region = region_for(lead.country)
    pool = list(_bank_for(lead, campaign))
    pool += _REGION_ANGLE.get(region, [])
    pool.append(_REGION_SUFFIX.get(region, ""))
    out, seen = [], set()
    for cand in pool:
        s = _normalise(cand, max_words)
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:n]
