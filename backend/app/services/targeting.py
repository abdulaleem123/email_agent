"""Targeting rules — who this agent is allowed to write to.

Two kinds of rule, both configured on the Agent UI and both enforced in code
(not just prompted), because "we never email recruiters" has to hold even when
the model disagrees:

  HARD EXCLUSIONS  excluded_titles / excluded_companies
      Never targeted, never emailed, on any channel, inbound or outbound.
      Matched against the job title, the company name, the website domain and
      the email domain — so "our competitors", "enterprise accounts" or a
      named list of high-value accounts can all be expressed the same way.

  POSITIVE TARGETING  target_titles / target_location
      Who the agent writes to and which market it writes for. A lead whose
      job title is known and does not match is skipped; a lead whose country
      is known and falls outside the target location is skipped. Unknown
      (blank) values are never used to filter — a lead with no title or no
      country on the sheet is still contactable, it is just addressed more
      carefully.

Everything here is also written into the prompt, so the agent understands the
decision instead of only being blocked by it.
"""
import re

from .playbook import split_items
from .subjects import region_for


# ── matching ─────────────────────────────────────────────────────────────────
_NOISE = re.compile(r"[^a-z0-9 ]+")
_ACRONYM_STOP = {"of", "and", "the", "for", "&", "a", "an", "in", "at"}


def _norm(value) -> str:
    """Lowercase, strip punctuation, collapse spaces."""
    return re.sub(r"\s+", " ", _NOISE.sub(" ", str(value or "").lower())).strip()


def _variants(item: str) -> list[str]:
    """'Chief Technical Officer' also matches 'CTO', and vice versa."""
    words = [w for w in _norm(item).split() if w and w not in _ACRONYM_STOP]
    out = [item.strip()]
    if len(words) >= 2:
        acronym = "".join(w[0] for w in words)
        if len(acronym) >= 2:
            out.append(acronym)
    return [v for v in out if v]


def matches(haystack, items) -> str | None:
    """Word-boundary match of any item inside haystack. Returns the item hit.

    Word boundaries matter: 'vp' must never match 'review', and 'head' must
    never match 'ahead'."""
    text = str(haystack or "").strip()
    if not text or not items:
        return None
    for item in items:
        for variant in _variants(item):
            pattern = r"(?<![a-z0-9])" + re.escape(_norm(variant)) + r"(?![a-z0-9])"
            if not _norm(variant):
                continue
            if re.search(pattern, _norm(text)):
                return item
    return None


def _domain(value) -> str:
    v = str(value or "").strip().lower()
    if "@" in v:
        v = v.rsplit("@", 1)[-1]
    v = re.sub(r"^https?://", "", v)
    v = re.sub(r"^www\.", "", v)
    return v.split("/")[0].strip()


# ── the rules ────────────────────────────────────────────────────────────────
def excluded_title_reason(agent, lead) -> str:
    """Hard exclusion: never target these job titles."""
    items = split_items(getattr(agent, "excluded_titles", ""))
    if not items:
        return ""
    hit = matches(getattr(lead, "title", ""), items)
    return f"excluded job title ({hit})" if hit else ""


def excluded_company_reason(agent, lead) -> str:
    """Hard exclusion: named accounts, competitors, or a company TYPE
    ('agency', 'enterprise', 'Fortune 500' …) expressed the same free-text way."""
    items = split_items(getattr(agent, "excluded_companies", ""))
    if not items:
        return ""
    haystacks = [
        getattr(lead, "company", ""),
        _domain(getattr(lead, "website", "")),
        _domain(getattr(lead, "email", "")),
    ]
    for hay in haystacks:
        if not hay:
            continue
        hit = matches(hay, items)
        if hit:
            return f"excluded company ({hit})"
    return ""


def outside_target_titles(agent, lead) -> str:
    """Positive targeting: only these job titles get written to."""
    items = split_items(getattr(agent, "target_titles", ""))
    if not items:
        return ""
    title = (getattr(lead, "title", "") or "").strip()
    if not title:
        return ""                       # unknown -> never filtered out
    return "" if matches(title, items) else "not a target job title"


def outside_target_location(agent, lead) -> str:
    """Positive targeting: only this market/country gets written to."""
    target = (getattr(agent, "target_location", "") or "").strip()
    if not target:
        return ""
    country = (getattr(lead, "country", "") or "").strip()
    if not country:
        return ""                       # unknown -> never filtered out

    target_items = split_items(target)
    if matches(country, target_items):
        return ""
    if matches(target, [country]):
        return ""

    lead_region = region_for(country)
    for item in target_items + [target]:
        if region_for(item) != "default" and region_for(item) == lead_region:
            return ""
    return f"outside target location ({country})"


def exclusion_reason(agent, lead, parts=None) -> str:
    """'' when this lead may be contacted, otherwise why it may not.

    Order matters for the message the operator sees: a hard exclusion is
    reported as an exclusion, never softened into a targeting miss.

    `parts` is the campaign's selection box (agent_settings keys). None means
    "no campaign — every rule applies". A campaign that unticks "Excluded
    titles" or "Target titles" is not bound by that half of the config, which
    is exactly what the checkbox promises."""
    if agent is None:
        return ""
    on = (lambda key: True) if parts is None else (lambda key: key in parts)
    # Named-account / company-type exclusions are never part of the selection
    # box, so they always hold. The other three are switchable per campaign.
    checks = [excluded_company_reason]
    if on("excluded_titles"):
        checks.append(excluded_title_reason)
    if on("target_titles"):
        checks.append(outside_target_titles)
    if on("ideal_customer"):
        checks.append(outside_target_location)
    for check in checks:
        reason = check(agent, lead)
        if reason:
            return reason
    return ""


def targeting_layer(agent) -> str:
    """The prompt half of the same rules: who to write to, where they are,
    who must never be written to — and why."""
    if agent is None:
        return ""
    titles = split_items(getattr(agent, "target_titles", ""))
    location = (getattr(agent, "target_location", "") or "").strip()
    ex_titles = split_items(getattr(agent, "excluded_titles", ""))
    ex_companies = split_items(getattr(agent, "excluded_companies", ""))
    if not (titles or location or ex_titles or ex_companies):
        return ""

    parts = ["TARGETING — who this email is for"]
    if titles:
        parts.append(
            "WRITE TO THESE ROLES: " + ", ".join(titles) + ".\n"
            "Their title decides who you are actually speaking to: what they own, "
            "what they are measured on, what they would have to justify. Speak to "
            "that, address them by name and their real role, and do not write to "
            "the company in general. If the person's title is not one of these, "
            "say nothing about their function and keep it short.")
    if location:
        parts.append(
            "TARGET LOCATION / MARKET: " + location + ".\n"
            "Write for this market, not for a generic international reader: use "
            "the references, the examples, the units, the formality and the "
            "business pacing that belong there. Respect how this country does "
            "business — titles, courtesy, directness, how a first email is opened "
            "and how a next step is offered. Their own country on the lead always "
            "wins over this when the two disagree, because that is where they "
            "actually are.")
    if ex_titles:
        parts.append(
            "NEVER WRITE TO THESE JOB TITLES: " + ", ".join(ex_titles) + ".\n"
            "Not in an opening email, not in a follow-up, not as a reply, not as a "
            "referral. If the thread turns out to be one of these roles, stop "
            "writing and say nothing.")
    if ex_companies:
        parts.append(
            "NEVER CONTACT THESE COMPANIES / COMPANY TYPES: "
            + ", ".join(ex_companies) + ".\n"
            "Named accounts, competitors, partners, high-value accounts we do not "
            "approach, or a whole company type (an agency, an enterprise, a "
            "reseller). If the company, its website or its domain matches, this "
            "thread is closed — no opening, no follow-up, no reply.")
    parts.append(
        "The same rules are checked in code before anything is sent, so a lead "
        "that fails one never reaches you. Follow them anyway: a reply that "
        "should not exist is worse than no reply at all.")
    return "\n".join(parts)
