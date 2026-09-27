"""Chatversio AI playbook — what the agents know and how they are allowed to
talk about it.

Source of truth: what Chatversio AI actually builds and runs for clients
(the nine service lines below, plus the outcomes and proof behind each).
The public website is where that was gathered from, but the ADDRESS is never
part of an email, a subject, a signature or a pitch — the agent talks about
outcomes in plain language and never pastes a link.

Nothing in here is a sales script. Every entry states a real operational
problem, the outcome of fixing it, and the proof that it has been done. The
agent picks ONE solution per company, from what it can actually see in the
research, and writes about the problem first.
"""
import re

# ── the solution catalogue ───────────────────────────────────────────────────
# id        stable key used by the UI checkbox list
# label     how the solution is named internally (never pasted verbatim)
# when      the observable situations that call for it (triggers)
# outcome   what changes for the business, in plain words
# proof     why it is believable — real behaviour, not a promise
SOLUTIONS = [
    {
        "id": "customer_support",
        "label": "Customer Support Agents",
        "when": "a support or help desk team answering the same questions by hand; "
                "a ticket backlog; slow replies after hours or at the weekend; "
                "different agents giving different answers to the same question",
        "outcome": "Customers get an accurate answer the moment they ask, at any "
                   "hour, and the team stops losing hours to the same repeats.",
        "proof": "Runs 24/7, answers consistently, and hands the conversation to a "
                 "person the moment it needs one.",
    },
    {
        "id": "lead_capture",
        "label": "Lead Generation Agents",
        "when": "visitors leaving a website without leaving details; enquiry forms "
                "nobody answers in time; paid traffic that never turns into a "
                "conversation; leads arriving at night or at the weekend",
        "outcome": "The people already visiting get spoken to while they are still "
                   "there, so fewer of them disappear without a trace.",
        "proof": "Meets the visitor in the moment, asks the qualifying questions, "
                 "and puts the details straight into the pipeline.",
    },
    {
        "id": "sales_automation",
        "label": "Sales Automation Agents",
        "when": "follow-ups that depend on somebody remembering; deals stalling "
                "between stages; a slow first response to a new enquiry; a pipeline "
                "nobody is actually working",
        "outcome": "Nothing sits waiting on someone's memory — every enquiry gets "
                   "its next step while the interest is still warm.",
        "proof": "Works the same conversation rules every time, day or night, "
                 "without dropping the thread.",
    },
    {
        "id": "whatsapp_social",
        "label": "WhatsApp, Instagram & Social Agents",
        "when": "enquiries arriving on WhatsApp, Instagram or Facebook and going "
                "unanswered; DMs nobody has time to get to; messages split across "
                "several phones and nobody sure who answered what",
        "outcome": "Messages on the channels customers already use get answered in "
                   "the moment instead of whenever someone gets to them.",
        "proof": "One conversation history across WhatsApp, Instagram and Facebook, "
                 "answered in the customer's own language.",
    },
    {
        "id": "website_assistant",
        "label": "Website AI Assistants",
        "when": "a website that can only repeat what is on its pages; visitors with "
                "questions that are not in the FAQ; a contact form being the only "
                "option on offer",
        "outcome": "The website stops being a brochure and starts answering the "
                   "questions people actually have while they are on it.",
        "proof": "Answers from the business's own material, books the next step, "
                 "and knows when to bring in a person.",
    },
    {
        "id": "appointment_booking",
        "label": "Appointment Booking Agents",
        "when": "bookings still made by phone or message; back-and-forth to find a "
                "time; no-shows from unconfirmed appointments; a reception desk "
                "juggling the diary between calls",
        "outcome": "People book the time themselves and get reminded, so the diary "
                   "fills without the phone tagging.",
        "proof": "Handles booking and rescheduling automatically, in the customer's "
                 "own words, without double-booking.",
    },
    {
        "id": "voice_ai",
        "label": "Voice AI Assistants",
        "when": "phone lines missed when staff are busy; hours spent answering the "
                "same call questions; calls outside office hours going to "
                "voicemail; callers hanging up before anyone picks up",
        "outcome": "Every call is answered on the first ring, at any hour, and the "
                   "caller gets what they called for instead of a voicemail.",
        "proof": "Answers, understands, qualifies and routes in natural speech, "
                 "and passes to a person when it should.",
    },
    {
        "id": "multilingual",
        "label": "Multilingual Agents",
        "when": "customers writing in several languages; staff switching between "
                "languages all day; second-language replies that come out cold or "
                "unclear",
        "outcome": "Every customer gets answered properly in the language they "
                   "wrote in, without hiring separately for each language.",
        "proof": "Same conversation quality across languages, decided by the "
                 "customer's own message.",
    },
    {
        "id": "internal_helpdesk",
        "label": "Internal Helpdesk & HR Agents",
        "when": "staff IT tickets piling up in an inbox; the same HR questions "
                "asked again and again; onboarding questions eating the People "
                "team's day",
        "outcome": "Routine internal requests get answered straight away, so the "
                   "people doing the answering get their day back.",
        "proof": "Reads the internal knowledge it is given, answers the common "
                 "cases, and routes the rest to the right person.",
    },
]

SOLUTION_IDS = [s["id"] for s in SOLUTIONS]


def solution_labels(ids) -> list[str]:
    wanted = {i.strip().lower() for i in (ids or []) if i and i.strip()}
    if not wanted:
        return [s["label"] for s in SOLUTIONS]
    return [s["label"] for s in SOLUTIONS if s["id"] in wanted]


def selected_solutions(raw: str) -> list[dict]:
    """The solutions this agent is allowed to present. Empty config = all."""
    wanted = {p.strip().lower() for p in split_items(raw)}
    if not wanted:
        return list(SOLUTIONS)
    return [s for s in SOLUTIONS if s["id"] in wanted]


# ── persona choices (the four voices the product ships with) ────────────────
PERSONAS = [
    {"id": "osaja", "name": "Osaja",
     "voice": "Consultative, calm, curious. Diagnoses before suggesting anything."},
    {"id": "saif", "name": "Saif",
     "voice": "Founder to founder. Extremely short, direct, credible."},
    {"id": "aleem", "name": "Aleem",
     "voice": "Technical peer. Specific, grounded, no buzzwords."},
    {"id": "dawood", "name": "Dawood",
     "voice": "Solo developer. Personal, proof-driven, one observation at a time."},
]


# ── phrases that must never appear in a subject or a body ───────────────────
# Applied ON TOP of whatever the agent itself configured, always, in code.
# These are the words that make an email read like a campaign instead of a
# person, plus the hype vocabulary that says "this was written by a machine".
DEFAULT_AVOID_PHRASES = [
    # hype / campaign vocabulary
    "revolutionary", "game-changing", "game changer", "cutting-edge",
    "cutting edge", "best-in-class", "world-class", "state of the art",
    "next-level", "transformative", "disruptive", "unlock", "supercharge",
    "skyrocket", "synergy", "seamlessly", "robust", "leverage", "elevate",
    "guaranteed", "free consultation", "limited time", "special offer",
    "no obligation", "act now", "don't miss out", "exclusive offer",
    "increase your revenue", "take your business to the next level",
    # openers that instantly read as automation
    "i hope this email finds you well", "i hope you are doing well",
    "i hope you're doing well", "just checking in", "touch base",
    "circling back", "following up on my previous email",
    "i am reaching out to offer", "i wanted to introduce",
    "i wanted to touch base", "wanted to reach out",
    # agency / corporate framing
    "we are an agency", "our services include", "we specialize in",
    "we specialise in", "we would love to work with you",
    "please do not hesitate", "we are excited to", "our team offers",
    "we can help you with", "do the needful", "kindly revert",
    # calls to action that read like a campaign
    "schedule a call today", "book a demo today", "click here",
    "learn more", "sign up now", "get started today",
]


def avoid_phrases(agent) -> list[str]:
    """Defaults + whatever the agent configured. Deduped, case kept for display,
    matched case-insensitively."""
    out, seen = [], set()
    for raw in (list(DEFAULT_AVOID_PHRASES) + split_items(getattr(agent, "avoid_phrases", ""))):
        p = " ".join(str(raw).split())
        if not p:
            continue
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


# ── helpers ──────────────────────────────────────────────────────────────────
def split_items(text) -> list[str]:
    """Comma / newline / semicolon / pipe separated list -> clean items."""
    if not text:
        return []
    if isinstance(text, (list, tuple, set)):
        return [str(t).strip() for t in text if str(t).strip()]
    parts = re.split(r"[,;\n|]+", str(text))
    return [p.strip() for p in parts if p and p.strip()]


def _phrase_pattern(phrases: list[str]):
    chunks = []
    for p in phrases:
        p = p.strip()
        if not p:
            continue
        esc = re.escape(p)
        # whole-word for single short tokens so "ROI" never eats "PROVIDED"
        if " " not in p and len(p) <= 14:
            chunks.append(r"\b" + esc + r"\b")
        else:
            chunks.append(esc)
    if not chunks:
        return None
    return re.compile("|".join(sorted(chunks, key=len, reverse=True)), re.IGNORECASE)


def contains_any(text: str, phrases) -> bool:
    if not text:
        return False
    pat = _phrase_pattern([str(p) for p in phrases])
    return bool(pat and pat.search(text))


def hits(text: str, phrases) -> list[str]:
    """Which of the phrases are actually present (for logging / UI)."""
    out = []
    for p in phrases or []:
        if contains_any(text, [p]):
            out.append(p)
    return out


# Every URL is removed from outbound copy: we never paste links, and our own
# address must never appear in a subject, a body or a signature.
_ANY_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)
_OUR_DOMAIN_RE = re.compile(
    r"\b(?:https?://)?(?:www\.)?chatversio[\w-]*\.(?:[a-z0-9-]+\.)?[a-z]{2,}"
    r"[^\s<>\"']*", re.IGNORECASE)


def _blank_url(match) -> str:
    """Drop the link, keep the sentence's own punctuation after it."""
    text = match.group(0)
    keep = text[len(text.rstrip(".,;:!?")):]
    return " " + keep


def _strip_urls(text: str) -> str:
    text = _OUR_DOMAIN_RE.sub(_blank_url, text)
    return _ANY_URL_RE.sub(_blank_url, text)


def scrub(text: str, agent=None) -> str:
    """Hard guarantee, runs on EVERY outbound copy.

    1. strips our own website address (and any other URL) out of the text,
    2. strips every avoid phrase, defaults + the agent's own list,
    3. tidies the punctuation the removal left behind.

    Prompt rules alone are not enough — this is the code-level backstop that
    makes "never appear" mean never.
    """
    if not text:
        return text
    phrases = avoid_phrases(agent) if agent is not None else list(DEFAULT_AVOID_PHRASES)
    pat = _phrase_pattern(phrases)
    out = _strip_urls(text)
    if pat:
        out = pat.sub(" ", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r" +\n", "\n", out)
    out = re.sub(r"\n +", "\n", out)
    # removals leave punctuation behind: "Hi John, ." must not become "Hi John,."
    out = re.sub(r"[,;:]\s*\.+", ".", out)
    out = re.sub(r"([.!?])\s*\1+", r"\1", out)
    out = re.sub(r"([,;:]) +(?=[,;.!?])", r"\1", out)
    out = re.sub(r" +([,.;:!?])", r"\1", out)
    # a line that lost all of its wording is a leftover, not content — but the
    # blank lines between paragraphs are structure and stay
    lines = [ln for ln in out.split("\n")
             if not ln.strip() or re.search(r"[A-Za-z0-9]", ln)]
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


# ── prompt layers ────────────────────────────────────────────────────────────
def no_website_rule() -> str:
    return (
        "NEVER SHOW OUR WEBSITE: do not write our address, any domain, any URL, "
        "any QR code and never \"visit our site\" / \"check us out online\". "
        "There is no link in this email, not for the product, not for a calendar, "
        "not for a portfolio. If a next step makes sense, say you will share the "
        "details yourself. Refer to the company only as Chatversio AI, in words."
    )


def solution_layer(agent) -> str:
    """Which solution to present, decided per company — never a service list."""
    chosen = selected_solutions(getattr(agent, "solutions", ""))
    if not chosen:
        return ""
    lines = [
        "SOLUTION CATALOGUE — pick ONE per company, from what you can see:",
        "",
    ]
    for s in chosen:
        lines.append(f"- {s['label']}")
        lines.append(f"  use when: {s['when']}")
        lines.append(f"  outcome: {s['outcome']}")
        lines.append(f"  proof: {s['proof']}")
    lines += [
        "",
        "HOW TO CHOOSE (this is a decision, not a menu):",
        "- Read the company research, the person's title and their country, then "
        "choose the ONE solution that maps to a problem you can actually see in "
        "their business. Not the flagship one. Not the one you wrote last.",
        "- Open on the problem. Present the solution as the plain-words fix for "
        "THAT problem (\"the calls going to voicemail\", \"the WhatsApp messages "
        "nobody gets to\"), in the language their market uses.",
        "- Never name more than one solution. Never list what the company does. "
        "Never describe a package, a plan or a price.",
        "- If nothing in the catalogue maps to a real problem you can see, write "
        "about the problem and leave the solution out entirely.",
        "- Always as a chat agent or a voice agent that runs in realtime. Never a "
        "chatbot, virtual assistant, IVR, voice bot or automated workflow.",
    ]
    return "\n".join(lines)


def why_you_layer(agent) -> str:
    """'Why you?' — value, proof and business outcomes. Never a pitch."""
    text = (getattr(agent, "why_you", "") or "").strip()
    if not text:
        return ""
    return (
        "WHY YOU — value, proof and outcomes (facts about the work, never a pitch):\n"
        + text
        + "\nUse this only where it earns its place: state the outcome as something "
          "that has already been observed, and let the reader judge it. Never "
          "present it as an offer, a benefit list or a reason to buy. If it sounds "
          "like a claim, it does not go in."
    )


def avoid_layer(agent) -> str:
    phrases = avoid_phrases(agent)
    if not phrases:
        return ""
    shown = ", ".join(phrases[:60])
    more = "" if len(phrases) <= 60 else f" (+{len(phrases) - 60} more)"
    return (
        "NEVER WRITE THESE WORDS OR PHRASES — in the subject or the body, any "
        "agent, any email, no exceptions:\n"
        + shown + more
        + "\nThis list is enforced in code after you write: anything you use is "
          "removed and the email is rebuilt, so a hit costs you a rewrite anyway. "
          "Write like a person who read their company, not like a campaign."
    )
