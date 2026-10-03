"""Subject-line generator.

Rules the whole product agreed on, enforced in code rather than in a prompt:

- 3 WORDS is the length we aim for, 4 is the absolute ceiling. Nothing — no
  campaign, no prompt, no model draft — ever goes past 4 words. Three is where
  a subject still reads as a topic; four is the last step before "this reads
  like an ad".
- Professional and strong, in the language that industry actually uses: an
  operational noun phrase a colleague would file under a real topic
  ("Response Time Gap"), grounded in what we know about the lead's company and
  what the campaign sells — never a hook, a tease or a casual aside
  ("Worth A Look", "Something We Noticed"), and never AI/marketing fluff
  (unlock, boost, seamless, revolutionary).
- Sentence case: the FIRST word capitalised, every other word lowercase — the
  house look for subjects ("Customer inquiries unanswered"). Short ALL-CAPS
  acronyms (AI, CRM, B2B) stay as they are. No full ALL CAPS (spam filters
  read it as shouting), no run-on sentence case, no Title Case.
- No exclamation marks, no "Re:", no banned openers (Noticing / I noticed /
  I see / Checking in / Quick question / Following up / Just checking /
  Opportunity / Hope you're).
- ABOUT THE EMAIL THAT IS BEING SENT. The model drafts the subject together
  with the body — `fit_llm_subject` hardens that draft into the house format
  and rejects it when nothing usable is left, in which case the bank below is
  the fallback. A subject that does not match its body is the first thing a
  reader notices.
- Never repeat a subject this lead already received. A follow-up that arrives
  with the same subject line as the last email is the single most obvious
  "this is an automated sequence" tell there is.
- Aimed at the intent, the campaign's angle, and the lead's country/region, so
  the same campaign does not send the same subject line to a German logistics
  firm and a US dental group.

Two layers: the model proposes a line about its own email, the code decides
whether it is usable. Nothing raw ever reaches the send path.
"""
import re

MAX_WORDS = 3            # what a subject is AIMED at — the normal length
HARD_MAX_WORDS = 4       # never crossed, by anything, ever


def subject_word_cap(campaign) -> int:
    """The word cap actually in force for this campaign.

    3 words is the aim; 4 is the hard ceiling. A campaign may ask for fewer
    than the default, and may go up to 4, but nothing pushes past 4 — the
    house rule is enforced here, not trusted to the prompt. No campaign at
    all: the default of 3."""
    from . import agent_settings
    if campaign is None:
        return MAX_WORDS
    cap = MAX_WORDS
    if getattr(campaign, "subject_max_words", None):
        try:
            cap = max(1, min(HARD_MAX_WORDS, int(campaign.subject_max_words)))
        except Exception:
            cap = MAX_WORDS
    if agent_settings.is_on(campaign, "subject"):
        cap = min(cap, HARD_MAX_WORDS)
    return cap

BANNED_STARTERS = {
    "noticing", "noticed", "notice", "see", "saw", "looking", "explored",
    "researched", "checking", "quick", "following", "follow", "just", "hope",
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
      ["Cart drop-off", "Store operations", "Order volume", "Repeat buyers",
       "Stock visibility"]),
    (("logistic", "supply", "delivery", "fleet", "warehouse", "freight",
      "manufactur", "factory", "plant"),
     ["Route planning", "Dispatch load", "Fleet visibility", "Lead times",
      "Shift handovers"]),
    (("hr", "hiring", "recruit", "employee", "onboard", "staff", "people",
      "training"),
      ["Hiring delays", "Onboarding load", "Staff questions", "Training gaps",
       "Onboarding friction"]),
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
# a plain operational noun phrase: 3 words, professional, obvious on sight —
# never a hook, a tease or a conversational aside, and never AI fluff.
# Nothing here is a hook, a tease or a conversational aside.
_GENERIC = [
    "Response time gap", "Enquiry backlog growth", "Manual handling load",
    "Reply delay cost", "Queue wait times", "Handover friction",
    "Process bottleneck", "Process efficiency gap",
    "Response delay", "Repeat workload",
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

# Fallbacks for a region we do not have an angle list for. Professional,
# clear, and short enough to survive the 3-word aim — every line is a plain
# operational noun phrase whose first word is never in BANNED_STARTERS.
_REGION_SUFFIX = {
    "us": "Reply backlog trend",
    "uk": "Enquiry handling pattern",
    "europe": "Process efficiency step",
    "gcc": "Service coverage gap",
    "south_asia": "Response time trend",
    "apac": "Queue wait pattern",
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
    """Pick the subject bank that matches this campaign's angle for THIS lead.

    The haystack is the campaign (what it sells, who it targets, its pain
    focus) PLUS what research found about the lead themselves — their
    industry, their stated pain points and the DuckDuckGo notes. So the
    fallback bank stays tied to the actual company, not a generic list."""
    hay = _tokens(getattr(lead, "industry", ""), getattr(lead, "title", ""),
                  lead.company, campaign.industry if campaign else "",
                  campaign.strategy_notes if campaign else "",
                  campaign.pain_focus if campaign else "",
                  campaign.target_focus if campaign else "",
                  campaign.what_to_sell if campaign else "",
                  getattr(campaign, "offering", "") if campaign else "",
                  getattr(campaign, "ideal_customer", "") if campaign else "",
                  getattr(lead, "pain_points", ""),
                  getattr(lead, "company_research", ""),
                  lead.title)
    for keys, bank in _ANGLES:
        if any(k in hay for k in keys):
            return list(bank)
    return list(_GENERIC)


# Words that make a subject read like a machine wrote it — marketing verbs and
# hype adjectives that never show up in a colleague's real subject line. Any
# candidate containing one is thrown away whole, never repaired into something
# weaker: "Seamless Support Load" does not become "Support Load", it goes.
_AI_FLUFF = {
    "unlock", "unlocks", "unleash", "supercharge", "revolutionize",
    "revolutionise", "revolutionary", "transform", "transforming", "empower",
    "elevate", "boost", "boosts", "skyrocket", "seamless", "seamlessly",
    "synergy", "synergies", "discover", "explore", "maximize", "maximise",
    "optimize", "optimise", "innovative", "cuttingedge", "turbocharge",
    "dominate", "effortless", "effortlessly", "gamechanger", "nextlevel",
    "magic", "leverage", "worldclass", "bestinclass",
    # product language: a subject never says "pain" — it names the topic
    "pain", "pains", "painpoint", "painpoints",
}


def _fluff_hit(words: list[str]) -> bool:
    for w in words:
        clean = w.strip(".,!?;:'\"()[]-–—").replace("'", "").replace("-", "").lower()
        if clean in _AI_FLUFF:
            return True
    return False


def _normalise(raw: str, max_words: int) -> str:
    """Hard-format whatever came out of the bank.

    Returns "" for anything unusable, and the caller moves on to the next
    candidate. That matters: an earlier version "fixed" a banned opener by
    chopping the first word off, which turned "Quick check" into "Check" and
    "Following up on this" into "Up on" — worse than no subject at all.

    Guarantees: <= max_words words, SENTENCE CASE (first word capitalised,
    every other word lowercase, short ALL-CAPS acronyms like "AI" left alone),
    no "Re:"/"Fwd:", no exclamation or question marks, never starts on a
    banned opener, and never contains AI/marketing fluff."""
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
    if words[0].lower().strip(".,") in BANNED_STARTERS:
        return ""          # unusable, not repairable — try the next candidate
    if _fluff_hit(words):
        return ""          # reads like an ad — try the next candidate
    # SENTENCE CASE — first word capitalised, everything else lowercase;
    # short ALL-CAPS acronyms (AI, CRM, B2B) are left alone.
    _ACRONYMS = {"ai", "crm", "b2b", "b2c", "saas", "seo", "ppc", "kpi",
                 "api", "faq", "cv", "ux", "ui", "erp", "iot"}

    def _case(w: str, first: bool) -> str:
        if w.isupper() and 2 <= len(w) <= 4:
            return w
        if w.lower().strip("'-") in _ACRONYMS:
            return w.upper()
        if first:
            return w[:1].upper() + w[1:].lower()
        return w.lower()
    return " ".join(_case(w, i == 0) for i, w in enumerate(words))



def _used_subjects(lead) -> set[str]:
    """Subjects this lead already got — never repeat one."""
    out = set()
    for m in getattr(lead, "messages", []) or []:
        if m.direction == "out" and m.subject:
            out.add(m.subject.strip().lower())
    return out


# Words that carry no meaning on their own: articles, prepositions, pronouns.
# Dropped when a drafted line runs over the word budget, so "Response time as
# Acme scales" becomes "Response time scales" instead of "Response time as".
_WEAK_WORDS = {
    "a", "an", "the", "at", "for", "to", "of", "in", "on", "onto", "over",
    "with", "as", "when", "whenever", "while", "and", "or", "but", "if",
    "so", "than", "then", "that", "this", "these", "those", "it", "its",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "can", "could", "should",
    "your", "their", "our", "my", "you", "we", "i", "he", "she", "they",
    "from", "by", "into", "about", "per", "after", "before", "without",
    # light verbs and glue words that carry no topic on their own — dropped
    # when a research line is cut down to a subject ("support inquiries GO
    # unanswered" must not become "Support Inquiries Go")
    "go", "goes", "going", "come", "comes", "coming", "make", "makes",
    "keep", "keeps", "take", "takes", "get", "gets", "become", "becomes",
    "need", "needs", "want", "wants", "still", "also", "very", "really",
    "often", "how", "why", "what", "where", "who", "which",
}


def _bare(word: str) -> str:
    """Lowercased, punctuation-free core of a word. Apostrophes are removed
    outright so "Northwind's" and "northwind" compare equal."""
    return word.strip(".,!?;:'\"()[]-–—").replace("'", "").replace("’", "").lower()


def _lead_tokens(lead) -> set[str]:
    """Lowercased words that identify THIS lead — company, person, domains.

    A drafted line often ends with the company's name ("Response time as Acme
    scales"); the subject has to read the same for every lead, so those tokens
    come out before the word budget is applied."""
    if lead is None:
        return set()
    blobs = [getattr(lead, "company", "") or "",
             getattr(lead, "name", "") or "",
             getattr(lead, "website", "") or "",
             getattr(lead, "email", "") or ""]
    out = set()
    for blob in blobs:
        for tok in re.split(r"[^A-Za-z0-9]+", blob):
            if len(tok) >= 4:
                out.add(tok.lower())
    return out


def _is_lead_word(word: str, drop: set[str]) -> bool:
    """True when the word IS the lead (company / person / domain), in any
    form the model may have written it: "Northwind", "Northwind's",
    "Logistics"."""
    if not drop:
        return False
    b = _bare(word)
    if len(b) < 4:
        return False
    if b in drop:
        return True
    return b.endswith("s") and b[:-1] in drop      # plural / possessive


def _fit_words(words: list[str], max_words: int) -> list[str] | None:
    """Bring a word list inside the budget WITHOUT chopping it mid-phrase.

    Duplicates go first ("Support load support"), then, only if the line is
    still too long, the words that carry no meaning — articles, prepositions,
    pronouns ("Customer response delay at Acme Corp" -> "Customer response
    delay"). Returns None when it still doesn't fit: cutting at word N turns
    "How your team handles support load" into "How team handles", which reads
    worse than no subject at all, so the caller takes a clean line from the
    bank instead."""
    seen: set[str] = set()
    deduped: list[str] = []
    for w in words:
        b = _bare(w)
        if b in seen:
            continue
        seen.add(b)
        deduped.append(w)
    if len(deduped) <= max_words:
        return deduped
    strong = [w for w in deduped if _bare(w) not in _WEAK_WORDS]
    seen2: set[str] = set()
    out: list[str] = []
    for w in strong:
        b = _bare(w)
        if b in seen2:
            continue
        seen2.add(b)
        out.append(w)
    return out if len(out) <= max_words else None


def fit_llm_subject(raw: str, *, max_words: int = MAX_WORDS, lead=None,
                    taken: set[str] | None = None) -> str:
    """Harden a subject the model drafted next to its body into house format.

    Taking the line from the model is what makes it ABOUT THE EMAIL — the
    subject and the body are written in one pass, so they agree instead of the
    subject being picked from a bank and the body written about something
    else. The model does not get to decide the FORMAT; this does:

    * at most `max_words` words (3 the aim, 4 the ceiling) — the lead's
      company/person/domain tokens come out first, then duplicates, then weak
      words; if the line still runs over, it is rejected rather than chopped
      mid-phrase,
    * sentence case — an ALL CAPS line reads as shouting and trips spam
      filters, so it is lowered before anything else; only the first word
      comes back capitalised,
    * no Re:/Fwd:, no punctuation, no banned opener, no AI/marketing fluff,
      never a repeat.

    Returns "" when nothing usable is left; the caller then falls back to the
    bank. Two things send it there on purpose: a banned opener ("Quick
    question about your team") is rejected outright, never repaired — chopping
    the first word off turned "Quick check" into "Check", which is worse than
    no subject at all — and a line that still runs over the word budget after
    cleaning, because chopping a phrase mid-way ("How team handles") reads
    worse than a clean line from the bank."""
    s = re.sub(r"\s+", " ", (raw or "").strip())
    if not s:
        return ""
    letters = [ch for ch in s if ch.isalpha()]
    if letters and all(ch.isupper() for ch in letters):
        s = s.lower()
    # Strip every leading Re:/Fwd: prefix BEFORE the word budget is applied —
    # otherwise the prefixes count as words and "Re: Fwd: Missed calls" comes
    # back as just "Missed".
    for _ in range(3):
        stripped = re.sub(r"^(re|fw|fwd)\s*[:\-]\s*", "", s, flags=re.I)
        if stripped == s:
            break
        s = stripped
    drop = _lead_tokens(lead)
    words = [w for w in s.split(" ") if not _is_lead_word(w, drop)]
    if not words:
        return ""
    fitted = _fit_words(words, max_words)
    if fitted is None:
        return ""
    out = _normalise(" ".join(fitted), max_words)
    if not out:
        return ""
    if taken and out.lower() in {t.lower() for t in taken}:
        return ""
    return out


def research_subject(lead, *, max_words: int = MAX_WORDS,
                     taken: set[str] | None = None) -> str:
    """A topic line pulled from THIS lead's research — pain points first,
    DuckDuckGo notes second.

    The model's own subject is tried before this and the generic bank after
    this: the research is the whole reason a specific line can be written at
    all, so its words get first shot at the fallback. Everything still runs
    through `_normalise`, so the house format (word cap, sentence case, no banned
    opener, no fluff) holds — returns "" when nothing usable is left and the
    caller moves on to the bank."""
    taken = {t.lower() for t in (taken or set())}
    drop = _lead_tokens(lead)
    blobs = [getattr(lead, "pain_points", "") or "",
             getattr(lead, "company_research", "") or ""]
    for blob in blobs:
        # Pain points arrive as bullet lines, research as prose — split both
        # into clauses and try the head content words of each as a candidate.
        lines = [ln.strip(" -*•\t") for ln in re.split(r"[\n;.]+", blob)
                 if ln and ln.strip()]
        for line in lines:
            content = [w for w in line.split()
                       if _bare(w) not in _WEAK_WORDS
                       and not _is_lead_word(w, drop)]
            if len(content) < 2:
                continue
            cand = _normalise(" ".join(content[:max_words]), max_words)
            if cand and cand.lower() not in taken:
                return cand
    return ""


def build_subject(lead, campaign=None, *, followup_number: int = 0,
                  used: set[str] | None = None) -> str:
    """Return a short subject (3 words the aim, 4 the ceiling) for one email.

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
