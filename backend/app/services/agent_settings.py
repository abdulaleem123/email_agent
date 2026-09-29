"""Which parts of the Agent a campaign's information is allowed to drive.

A CAMPAIGN holds the facts of THIS send: what is being offered, how it is
delivered, who the ideal customer is, which platform rules apply, when the
follow-ups go out.

The AGENT holds the standing configuration: the voice, the targeting lists,
the banned phrases, the extra instructions, the booking link.

The selection box on the campaign screen says WHICH of those agent parts this
campaign's information is allowed to drive. Every part is ON by default, so an
untouched campaign uses the whole agent exactly as it is configured — that is
also what the default Agent prompt below states, so a brand new install and an
untouched campaign agree with each other.

Nothing here is prompt-only. Several of these parts are gates in code as well
(target titles, excluded titles, the unsubscribe link, pricing talk, the
follow-up day/time window) and they honour the same selection.
"""
from __future__ import annotations

from .playbook import split_items

# ── the parts ────────────────────────────────────────────────────────────────
# key    stable id stored in campaigns.agent_parts (comma list)
# label  what the checkbox says
# desc   the one-line meaning, also used as the prompt heading
# rule   the DEFAULT rule — this text is the default Agent prompt
PARTS: list[dict] = [
    dict(
        key="what_you_sell",
        label="What you sell",
        desc="Core offer, value, and proof points.",
        rule=(
            "WHAT YOU SELL — the core offer, its value and the proof behind it, "
            "stated as facts about work already done. Describe the service the way "
            "a practitioner would describe it to a peer: what it is, what changes "
            "for the business, and what has actually been observed. Never an offer, "
            "never a benefit list, never a reason to buy."
        ),
    ),
    dict(
        key="ideal_customer",
        label="Ideal customer profile",
        desc="Context-based targeting.",
        rule=(
            "IDEAL CUSTOMER — write for this profile and nothing else. Judge each "
            "lead against it from their title, company, industry and country: when "
            "they fit, speak to the situation they are actually in; when they do "
            "not fit, keep it short and say nothing about their function. "
            "Context-based targeting means the profile decides the angle, not a "
            "template."
        ),
    ),
    dict(
        key="avoid_phrases",
        label="Avoid phrases",
        desc="Strictly avoid listed phrases.",
        rule=(
            "AVOID PHRASES — strictly avoid every phrase on the configured list, in "
            "the subject and in the body, with no exceptions. The list is enforced "
            "in code after you write, so a hit costs a rewrite anyway. Write like a "
            "person who read their company, not like a campaign."
        ),
    ),
    dict(
        key="platform_rules",
        label="Platform rules",
        desc="Follow all configured platform rules.",
        rule=(
            "PLATFORM RULES — follow every configured platform rule: no URLs or "
            "website address anywhere, no bullet points, no numbered lists, no "
            "bold, no emojis, no exclamation marks, no em-dashes as decoration, "
            "one question at most, and a plain-text body that reads as "
            "correspondence rather than as a campaign."
        ),
    ),
    dict(
        key="extra_instructions",
        label="Extra instructions",
        desc="Apply additional instructions.",
        rule=(
            "EXTRA INSTRUCTIONS — apply every additional instruction configured on "
            "the agent. They outrank anything above that contradicts them, but never "
            "the safety rules: no URLs, no banned phrases, no excluded recipients."
        ),
    ),
    dict(
        key="no_pricing",
        label="No pricing talk",
        desc="Never mention pricing.",
        rule=(
            "NO PRICING TALK — never mention pricing, price, cost, fees, quotes, "
            "discounts, budgets, packages or currency amounts of any kind, in the "
            "subject or the body, in an opening email or a follow-up. If they ask "
            "about price themselves, do not answer it here — a colleague comes back "
            "with the exact details."
        ),
    ),
    dict(
        key="cta",
        label="CTA — booking link",
        desc="Insert the booking link.",
        rule=(
            "CTA — the call to action is the booking link. End on one short, "
            "low-pressure line inviting them to pick a time that suits them. Do not "
            "paste the link yourself: it is inserted under your closing line by "
            "code, so write the invitation as if the link is already there and "
            "never invent a URL."
        ),
    ),
    dict(
        key="excluded_titles",
        label="Excluded titles",
        desc="Skip leads whose titles match the excluded titles.",
        rule=(
            "EXCLUDED TITLES — skip any lead whose job title matches the excluded "
            "titles. Not in an opening email, not in a follow-up, not as a reply, "
            "not as a referral. The same rule is checked in code before anything is "
            "sent, so a matching lead never reaches you."
        ),
    ),
    dict(
        key="target_titles",
        label="Target titles",
        desc="Enroll only leads whose titles match the target titles.",
        rule=(
            "TARGET TITLES — enroll and write only to leads whose job title matches "
            "the target titles. Their title decides who you are speaking to: what "
            "they own, what they are measured on, what they would have to justify. "
            "Speak to that. A lead whose known title is not on the list is never "
            "contacted."
        ),
    ),
    dict(
        key="unsubscribe",
        label="Unsubscribe",
        desc="Remove the unsubscribe link.",
        rule=(
            "UNSUBSCRIBE — no unsubscribe link and no opt-out line is added to these "
            "emails. Never write one yourself, never mention one, and never include "
            "a List-Unsubscribe style footer."
        ),
    ),
    dict(
        key="subject",
        label="Subject (optional)",
        desc="Optional UI instruction; keep subjects to a maximum of 4 words.",
        rule=(
            "SUBJECT — optional instruction, capped at 4 WORDS MAXIMUM. Short, "
            "specific, peer-to-peer, about an operational reality from the research. "
            "Never an ad, never a question, never a banned opener. The subject is "
            "regenerated in code from a region-aware bank, so spend your words on "
            "the body instead."
        ),
    ),
    dict(
        key="body",
        label="Body",
        desc="Keep the email natural, humanized, concise, and inspirational.",
        rule=(
            "BODY — natural, humanized, concise and inspirational. One idea, one "
            "question, short sentences, contractions allowed. Say something that "
            "makes the reader think about their own operation differently, without "
            "hype. AI giveaways are stripped in code, but write clean the first "
            "time: no emojis, no decorative dashes, no lists."
        ),
    ),
    dict(
        key="followups",
        label="Follow-ups",
        desc="Configure follow-up days from Monday to Sunday, follow-up timing, and the total number of follow-ups.",
        rule=(
            "FOLLOW-UPS — the campaign configures which days from Monday to Sunday "
            "a follow-up may go out, the time of day it goes out, and the total "
            "number of follow-ups. Honour the count exactly: never write more "
            "follow-ups than configured, and never treat silence as permission to "
            "keep going."
        ),
    ),
    dict(
        key="not_interested",
        label="Not interested",
        desc="End the follow-up sequence, mark the lead Cold, keep the message in the Messages page, and move the lead to Trash.",
        rule=(
            "NOT INTERESTED — when they decline, the follow-up sequence ends "
            "immediately: no reply, no further email, ever. The lead is marked COLD, "
            "the conversation stays readable in the Messages page, and the lead is "
            "moved to Trash. Accept it gracefully if you are already writing, and "
            "leave the door open without any pushback."
        ),
    ),
    dict(
        key="interested",
        label="Interested",
        desc="Mark the lead Hot and keep the message in the Messages page.",
        rule=(
            "INTERESTED — when they show interest, mark the lead HOT and keep the "
            "message in the Messages page. Move the conversation forward with one "
            "focused next step, answer honestly, and do not oversell the moment."
        ),
    ),
]

PART_KEYS: list[str] = [p["key"] for p in PARTS]
PART_BY_KEY: dict[str, dict] = {p["key"]: p for p in PARTS}

# Days a follow-up may go out, in the order the UI shows them.
WEEKDAYS: list[tuple[str, str]] = [
    ("mon", "Monday"), ("tue", "Tuesday"), ("wed", "Wednesday"),
    ("thu", "Thursday"), ("fri", "Friday"), ("sat", "Saturday"),
    ("sun", "Sunday"),
]
ALL_DAYS: list[str] = [d for d, _ in WEEKDAYS]

# Built-in platform rules — used when the campaign does not override them.
DEFAULT_PLATFORM_RULES = (
    "No URLs, no website address, no calendar link in the body. No bullet "
    "points, no numbered lists, no bold, no emojis, no exclamation marks, no "
    "em-dashes as decoration. At most one question. Plain text that reads like "
    "one person writing to another. Call it a chat agent or a voice agent, never "
    "a chatbot or a virtual assistant, and say realtime where it fits."
)


def parse_parts(raw) -> set[str]:
    """Stored comma list -> the set of part keys.

    An empty / unknown value means EVERY part: that is the default, so a
    campaign created before this field existed keeps using the whole agent."""
    items = {p.strip().lower() for p in split_items(raw)}
    known = {k for k in items if k in PART_BY_KEY}
    if not known:
        return set(PART_KEYS)
    return known


def is_on(campaign, key: str) -> bool:
    """Is this part switched on for this campaign?"""
    if campaign is None:
        return True
    return key in parse_parts(getattr(campaign, "agent_parts", ""))


def enabled_keys(campaign) -> list[str]:
    """Part keys in declaration order, for a stable prompt."""
    if campaign is None:
        return list(PART_KEYS)
    chosen = parse_parts(getattr(campaign, "agent_parts", ""))
    return [k for k in PART_KEYS if k in chosen]


def _lines(text: str) -> str:
    return " ".join((text or "").split())


def default_prompt() -> str:
    """THE DEFAULT AGENT PROMPT — every part, in order.

    Used when there is no campaign to narrow it (inbound replies from an
    unassigned thread, previews, the Agents screen) so a fresh agent states all
    of its settings out loud."""
    return render(PART_KEYS, None)


def campaign_prompt(campaign) -> str:
    """Only the parts this campaign switched on, with this campaign's own
    values inlined. An untouched campaign renders exactly the default prompt."""
    return render(enabled_keys(campaign), campaign)


def render(keys: list[str], campaign) -> str:
    if not keys:
        return ""
    out = [
        "══════════════════════════════════════════════════════════",
        "CAMPAIGN SETTINGS — these are the settings in force for this send",
        "══════════════════════════════════════════════════════════",
    ]
    for key in keys:
        part = PART_BY_KEY[key]
        out.append("")
        out.append(f"── {part['label'].upper()} — {part['desc']}")
        out.append(part["rule"])
        extra = _values(key, campaign)
        if extra:
            out.append(extra)
    return "\n".join(out)


# ── campaign-specific values layered on top of each part's default rule ──────
def _values(key: str, campaign) -> str:
    """The configured value for this part, or '' when it adds nothing."""
    if campaign is None:
        return ""
    g = lambda name, default="": (getattr(campaign, name, default) or default)

    if key == "what_you_sell":
        bits = []
        if _lines(g("what_to_sell")):
            bits.append("CORE OFFER:\n" + _lines(campaign.what_to_sell))
        if _lines(g("offering")):
            bits.append("WHAT ARE YOU OFFERING? (reality-based description — say it "
                        "the way it actually is, never as a pitch):\n"
                        + _lines(campaign.offering))
        if _lines(g("delivery_model")):
            bits.append("DELIVERY MODEL (plain text — how the work is delivered, "
                        "what the client gets and how):\n"
                        + _lines(campaign.delivery_model))
        return "\n".join(bits)

    if key == "ideal_customer":
        bits = []
        if _lines(g("ideal_customer")):
            bits.append("IDEAL CUSTOMER PROFILE:\n" + _lines(campaign.ideal_customer))
        if _lines(g("target_focus")):
            bits.append("PAIN FOCUS (prioritise these):\n"
                        + _lines(campaign.target_focus))
        if _lines(g("target_country")):
            bits.append("MARKET — write for this country's psychology:\n"
                        + _lines(campaign.target_country))
        return "\n".join(bits)

    if key == "platform_rules":
        return ("CONFIGURED PLATFORM RULES:\n"
                + (_lines(campaign.platform_rules) or DEFAULT_PLATFORM_RULES))

    if key == "avoid_phrases":
        return ("NEVER MENTION / DO NOT SELL (this campaign):\n"
                + (_lines(campaign.what_to_avoid)
                   or "nothing further beyond the configured avoid list"))

    if key == "no_pricing" and not getattr(campaign, "no_pricing", True):
        return ""

    if key == "cta":
        link = _lines(g("booking_link")) or _lines(getattr(campaign, "_meeting_url", ""))
        if link:
            return "BOOKING LINK (inserted under your closing line): " + link
        return ""

    if key == "subject":
        from .subjects import subject_word_cap
        return (f"SUBJECT WORD LIMIT FOR THIS CAMPAIGN: "
                f"{subject_word_cap(campaign)} words.")

    if key == "followups":
        bits = []
        plan = _lines(g("followup_plan"))
        if plan:
            bits.append("FOLLOW-UP DAYS AFTER THE LAST EMAIL: " + plan)
        count = getattr(campaign, "followup_count", None)
        if count:
            bits.append(f"TOTAL FOLLOW-UPS: {int(count)}")
        days = _lines(g("followup_days"))
        if days:
            bits.append("FOLLOW-UP MAY ONLY GO OUT ON: "
                        + ", ".join(_day_labels(days)))
        when = _lines(g("followup_time"))
        if when:
            bits.append(f"FOLLOW-UP TIME OF DAY (UTC): {when}")
        return "\n".join(bits)

    if key == "not_interested":
        return ("ON A DECLINE THE SEQUENCE ENDS: no reply, no further email, the "
                "lead is marked Cold, the conversation stays in Messages and the "
                "lead moves to Trash.")

    return ""


def _day_labels(raw: str) -> list[str]:
    wanted = {p.strip().lower()[:3] for p in split_items(raw)}
    return [label for day, label in WEEKDAYS if day in wanted]


def parse_days(raw) -> list[str]:
    """Stored day list -> normalized 3-letter keys, preserving Mon..Sun order."""
    wanted = {p.strip().lower()[:3] for p in split_items(raw)}
    known = [d for d in ALL_DAYS if d in wanted]
    return known or list(ALL_DAYS)


def day_allowed(campaign, now) -> bool:
    """True when a follow-up may go out on `now`'s weekday.

    Empty/unconfigured = every day, which is also what campaigns created
    before this setting existed behave like."""
    raw = (getattr(campaign, "followup_days", "") or "") if campaign else ""
    if not raw.strip():
        return True
    return now.strftime("%a").lower()[:3] in parse_days(raw)


def time_allowed(campaign, now) -> bool:
    """True when a follow-up may go out at `now`'s time of day (UTC).

    Empty/unconfigured = any time, so nothing changes for existing campaigns."""
    raw = (getattr(campaign, "followup_time", "") or "").strip() if campaign else ""
    if not raw:
        return True
    try:
        hh, mm = raw.split(":", 1)
        hh, mm = int(hh), int(mm)
    except (ValueError, AttributeError):
        return True
    return (now.hour * 60 + now.minute) >= (hh * 60 + mm)


def schedule_ok(campaign, now) -> bool:
    return day_allowed(campaign, now) and time_allowed(campaign, now)
