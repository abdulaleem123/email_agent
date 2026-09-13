"""Unified Scenario Detection Service.

Detects the prospect's intent/objection from inbound message text and returns
a structured scenario with a recommended response strategy.

Used by the agentic inbound reply pipeline so every objection gets a
purpose-built response — not a generic KB dump.

Scenarios detected:
  not_interested      — "not interested", "remove me", "unsubscribe"
  already_have        — "we already use X", "we have a solution"
  wants_demo          — "show me", "can I see it", "demo please"
  price_too_high      — "too expensive", "can't afford", "out of budget"
  wants_discount      — "any discount", "better price", "negotiate"
  needs_time          — "call me next month", "not now", "later"
  send_info_email     — "send me more info", "email me details"
  general_interest    — positive signal but no clear next step
  neutral_question    — question about product/service without objection
  unknown             — fallback
"""
import re
from dataclasses import dataclass


# ── Scenario definitions ──────────────────────────────────────────────────────

@dataclass
class Scenario:
    code: str
    label: str
    tone: str          # how the reply should feel
    goal: str          # what the reply should achieve
    kb_needed: bool    # should we search KB before replying?
    offer_meeting: bool  # should we surface the meeting link?


SCENARIOS: dict[str, Scenario] = {
    "not_interested": Scenario(
        code="not_interested",
        label="Not Interested",
        tone="respectful, brief, leave-door-open",
        goal="Acknowledge gracefully. Don't push. Plant one curiosity seed. Offer to reconnect later.",
        kb_needed=False,
        offer_meeting=False,
    ),
    "already_have": Scenario(
        code="already_have",
        label="Already Have a Solution",
        tone="curious, non-confrontational",
        goal="Ask one sharp question that exposes a gap their current tool likely misses. Don't dismiss them.",
        kb_needed=True,
        offer_meeting=True,
    ),
    "wants_demo": Scenario(
        code="wants_demo",
        label="Wants Demo / To See It",
        tone="enthusiastic, efficient",
        goal="Confirm interest. Share meeting link naturally. Keep it short.",
        kb_needed=False,
        offer_meeting=True,
    ),
    "price_too_high": Scenario(
        code="price_too_high",
        label="Price Too High",
        tone="empathetic, value-focused",
        goal="Reframe around ROI or cost of the problem. Don't defend price directly. Offer a discovery call.",
        kb_needed=True,
        offer_meeting=True,
    ),
    "wants_discount": Scenario(
        code="wants_discount",
        label="Wants Discount / Better Price",
        tone="warm, solution-oriented",
        goal="Don't give a discount in email. Shift to a call where you can understand their situation better.",
        kb_needed=False,
        offer_meeting=True,
    ),
    "needs_time": Scenario(
        code="needs_time",
        label="Needs More Time",
        tone="patient, low-pressure",
        goal="Respect the timeline. Offer one specific follow-up date. Don't disappear.",
        kb_needed=False,
        offer_meeting=False,
    ),
    "send_info_email": Scenario(
        code="send_info_email",
        label="Send Info by Email",
        tone="helpful, concise",
        goal="Send 2-3 punchy bullet points from KB. End with a soft CTA to book a call.",
        kb_needed=True,
        offer_meeting=True,
    ),
    "general_interest": Scenario(
        code="general_interest",
        label="General Interest",
        tone="warm, momentum-building",
        goal="Build on the positive signal. Ask one qualifying question. Offer meeting link naturally.",
        kb_needed=True,
        offer_meeting=True,
    ),
    "neutral_question": Scenario(
        code="neutral_question",
        label="Question About Product/Service",
        tone="knowledgeable, concise",
        goal="Answer clearly from KB. End with an invitation to talk if they want to go deeper.",
        kb_needed=True,
        offer_meeting=True,
    ),
    "unknown": Scenario(
        code="unknown",
        label="Unknown / Unclear",
        tone="natural, helpful",
        goal="Acknowledge and ask a clarifying question. Pull relevant KB context.",
        kb_needed=True,
        offer_meeting=False,
    ),
    
    
        "inbound_call": Scenario(
        code="inbound_call", label="Prospect Called Us",
        tone="receptive, diagnostic, not outbound-salesy",
        goal="They initiated. Ask what they are trying to solve before explaining what we do. Offer mockup by email if relevant.",
        kb_needed=True, offer_meeting=True,
    ),
    "why_contacting": Scenario(
        code="why_contacting", label="Why Are You Contacting Me?",
        tone="transparent, brief, research-backed",
        goal="One specific research-based reason. No generic pitch. Confirm if the problem is real for them.",
        kb_needed=False, offer_meeting=False,
    ),
    "what_do_you_do": Scenario(
        code="what_do_you_do", label="What Exactly Do You Do?",
        tone="plain, concrete, problem-first",
        goal="We build working systems around their workflow — not resell tools. Tie to their pain if known.",
        kb_needed=True, offer_meeting=False,
    ),
    "wants_proof": Scenario(
        code="wants_proof", label="Wants Proof",
        tone="evidence-led, calm",
        goal="Offer a working mockup/example for THEIR situation by email — not generic claims.",
        kb_needed=True, offer_meeting=True,
    ),
    "how_it_works": Scenario(
        code="how_it_works", label="How Would It Work?",
        tone="practical, step-by-step",
        goal="Describe a concrete flow for their business. Offer mockup by email before a meeting.",
        kb_needed=True, offer_meeting=True,
    ),
    "cheaper_competitor": Scenario(
        code="cheaper_competitor", label="Cheaper Competitor",
        tone="premium, non-defensive",
        goal="Differentiate on customization, ownership, implementation, working prototype — not price war.",
        kb_needed=True, offer_meeting=True,
    ),
    "cold_outreach": Scenario(
        code="cold_outreach", label="Cold Outreach",
        tone="curious consultant, not pushy",
        goal="Research-based opening. Validate one real problem. Demo-first: offer mockup by email before meeting.",
        kb_needed=True, offer_meeting=True,
    ),
}


# ── Signal patterns ───────────────────────────────────────────────────────────

_PATTERNS: list[tuple[str, list[str]]] = [
    ("not_interested", [
        r"\bnot interested\b", r"\bno thanks\b", r"\bno thank you\b",
        r"\bunsubscribe\b", r"\bremove me\b", r"\bstop emailing\b",
        r"\bplease remove\b", r"\bdon'?t contact\b", r"\bnot relevant\b",
        r"\bnot for us\b", r"\bpass on this\b",
    ]),
    ("already_have", [
        r"\balready (have|use|using|got)\b", r"\bcurrently use\b",
        r"\bwe('ve| have) (a |an )?(tool|solution|system|platform|software|vendor|provider)\b",
        r"\bwe('re| are) (set|covered|good|fine)\b",
        r"\bwe use \w+\b",
        r"\bsatisfied with\b", r"\bworking with\b",
    ]),
    ("wants_demo", [
        r"\bshow me\b", r"\bsee it\b", r"\bsee a demo\b", r"\bdemo\b",
        r"\bwalk me through\b", r"\bhow does it (look|work)\b",
        r"\bcan (I|we) (see|try|test)\b", r"\btrial\b",
    ]),
    ("price_too_high", [
        r"\btoo expensive\b", r"\bout of budget\b", r"\bcan'?t afford\b",
        r"\bcost(s)? too (much|high)\b", r"\bnot in (the |our )?budget\b",
        r"\bprice(d)? too high\b", r"\bover budget\b",
    ]),
    ("wants_discount", [
        r"\bdiscount\b", r"\bbetter (price|deal|offer|rate)\b",
        r"\bnegotiate\b", r"\bflexible on price\b", r"\bspecial (rate|price)\b",
        r"\bany (deal|promo|promotion)\b",
    ]),
    ("needs_time", [
        r"\bnot (right )?now\b", r"\blater\b", r"\bnext (month|quarter|year|week)\b",
        r"\bcall me (back |again )?(in|after)\b", r"\breach out (in|after)\b",
        r"\btoo busy\b", r"\bcheck back\b", r"\btiming (isn'?t|is not)\b",
        r"\bq[1-4]\b", r"\bnot the right time\b",
    ]),
    ("send_info_email", [
        r"\bsend (me |us )?(more |some )?(info|information|details|material|brochure|deck)\b",
        r"\bemail (me|us) (more|the|some)\b", r"\bforward (me|us)\b",
        r"\bshare (more|the details|some info)\b",
    ]),
    ("general_interest", [
        r"\bsounds interesting\b", r"\btell me more\b", r"\binterested\b",
        r"\bwould like to (know|learn|hear)\b", r"\bopen to (a )?chat\b",
        r"\bcurious\b", r"\blike to discuss\b", r"\bsounds (good|great|promising)\b",
    ]),
    ("neutral_question", [
        r"\bhow does\b", r"\bwhat (is|are|does)\b", r"\bcan (it|you)\b",
        r"\bdo you (have|offer|support)\b", r"\bwhat('s| is) the (difference|price|cost|benefit)\b",
        r"\bwill it\b", r"\bintegrat\b",
    ]),
    
    
        # --- Pitch Decker / call-note scenarios (extra) ---
    ("inbound_call", [
        r"\b(they|he|she|client|prospect) (called|called in|phoned|rang)\b",
        r"\binbound call\b", r"\bthey called us\b", r"\bpicked up (our|the) (phone|call)\b",
        r"\bcalled (our|the) (office|company|number)\b",
    ]),
    ("why_contacting", [
        r"\bwhy (are you|did you) (calling|contacting|reaching)\b",
        r"\bhow did you (get|find) (my|our)\b", r"\bwhere did you get (my|this)\b",
    ]),
    ("what_do_you_do", [
        r"\bwhat (exactly )?do you (do|offer|build|sell)\b",
        r"\bwhat is (it|this|your (product|service|company))\b",
    ]),
    ("wants_proof", [
        r"\bproof\b", r"\bcase stud(y|ies)\b", r"\bresults?\b", r"\broi\b",
        r"\bexamples?\b", r"\breferences?\b", r"\bsuccess stor",
    ]),
    ("how_it_works", [
        r"\bhow (would|does|will) (it|this|that) work\b",
        r"\bhow (do|would) you (implement|build|integrate)\b",
    ]),
    ("cheaper_competitor", [
        r"\bcheaper\b", r"\bloss expensive\b", r"\banother (company|vendor|agency).{0,40}(cheaper|less)\b",
        r"\bcompetitor\b", r"\bsomeone else (offers|quoted)\b",
    ]),
]


def detect_scenario(message_text: str) -> Scenario:
    """
    Detect the prospect's scenario from inbound message text.
    Returns the best matching Scenario dataclass.
    Uses a simple pattern-priority matching — no LLM needed for this step.
    """
    text = (message_text or "").lower()

    for scenario_code, patterns in _PATTERNS:
        for pat in patterns:
            if re.search(pat, text):
                return SCENARIOS[scenario_code]

    return SCENARIOS["unknown"]


def build_scenario_instruction(scenario: Scenario, agent_name: str, lead_name: str) -> str:
    """
    Build the scenario-specific instruction block to inject into the
    agentic system prompt. This replaces the generic 'answer from KB' instruction.
    """
    lines = [
        f"SCENARIO DETECTED: {scenario.label}",
        f"TONE: {scenario.tone}",
        f"YOUR GOAL: {scenario.goal}",
        "",
    ]

    if scenario.code == "not_interested":
        lines += [
            "DO NOT re-pitch. DO NOT list features. One sentence acknowledging their choice.",
            "Optional: one low-pressure sentence like 'Happy to reach out again if things change'.",
            "Keep total reply under 4 sentences.",
        ]
    elif scenario.code == "already_have":
        lines += [
            "Use kb_search to find ONE gap or advantage that their existing tool likely misses.",
            "Ask: 'Just curious — does [their tool] handle [specific gap]?' — make it conversational.",
            "Never say 'our solution is better'. Find the gap, let them think.",
        ]
    elif scenario.code == "wants_demo":
        lines += [
            "Call get_meeting_link immediately (if available).",
            "One short sentence expressing you'd love to show them.",
            "Share the link naturally: 'Here's a link to grab a slot: [link]'",
        ]
    elif scenario.code == "price_too_high":
        lines += [
            "Use kb_search to find ROI data, cost-savings examples, or value proof points.",
            "Reframe: 'I hear you — can I ask what the current [problem] is costing you?'",
            "Offer a call to understand their situation before discussing pricing.",
        ]
    elif scenario.code == "wants_discount":
        lines += [
            "Don't give a price in email. Redirect to a call.",
            "'Happy to walk through options — pricing really depends on your setup. Worth a quick call?'",
        ]
    elif scenario.code == "needs_time":
        lines += [
            "Respect the timeline completely. Don't push.",
            "Offer one specific touchpoint: 'Shall I ping you in [X weeks]?'",
            "Keep the reply to 2-3 sentences max.",
        ]
    elif scenario.code == "send_info_email":
        lines += [
            "Use kb_search for 2-3 concrete benefits/facts to include.",
            "Format as a short, punchy 3-bullet list (no bullet symbols needed — just natural prose).",
            "End with: 'Happy to walk through this live if you'd prefer — just grab a slot here: [link]'",
        ]
    elif scenario.code == "general_interest":
        lines += [
            "Acknowledge their interest warmly but briefly.",
            "Use kb_search to pull one relevant fact/outcome that fits their context.",
            "Ask one qualifying question (company size, current process, or timeline).",
            "Offer meeting link naturally at the end.",
        ]
    elif scenario.code == "neutral_question":
        lines += [
            "Use kb_search to get the most accurate answer.",
            "Answer directly and concisely — don't over-explain.",
            "End with an invitation: 'Happy to go deeper on this — want to grab 20 mins?'",
        ]
    else:
        lines += [
            "Use kb_search before replying.",
            "Ask a clarifying question to understand what they actually need.",
        ]

    return "\n".join(lines)


# ── Pitch Decker scenario strategies (call transcript generation) ─────────────

PITCH_STRATEGY: dict[str, str] = {
    "cold_outreach": (
        "COLD OUTREACH: Open with one specific research observation. State you are not "
        "calling with a generic AI pitch. Validate whether PRIMARY_PAIN is real. "
        "If yes → propose a concrete mockup emailed for them to review before any meeting. "
        "If no → honest exit."
    ),
    "inbound_call": (
        "THEY CALLED YOU: Do not sound like cold outbound. First ask what they are trying "
        "to solve. Only then explain you build working systems (not resell tools). "
        "Offer mockup by email; meeting only if they want."
    ),
    "not_interested": (
        "NOT INTERESTED: Do not keep selling. Ask once: problem not relevant, or already "
        "have a solution? If still no → thank them and end. No pressure."
    ),
    "already_have": (
        "ALREADY HAVE A SOLUTION: Curious, not confrontational. One sharp question about "
        "a gap (integration, ownership, edge cases). Do not trash their vendor."
    ),
    "price_too_high": (
        "PRICE TOO HIGH: Do NOT discount first. Ask: budget limit or value unclear? "
        "Offer smaller scope / phased start. Preserve premium quality."
    ),
    "wants_discount": (
        "WANTS LOWER PRICE: Same as price — reduce scope/phases, not quality. "
        "No blind discount."
    ),
    "cheaper_competitor": (
        "CHEAPER COMPETITOR: We may not be cheapest by design. Differentiate: custom "
        "workflow, ownership, implementation, working prototype, outcome. Offer to show "
        "the difference with a mockup before they decide."
    ),
    "wants_demo": (
        "WANTS DEMO: Prefer mockup/example emailed first so they review asynchronously, "
        "then short meeting if useful."
    ),
    "wants_proof": (
        "WANTS PROOF: No vague claims. Offer a scenario-specific mockup grounded in research."
    ),
    "how_it_works": (
        "HOW IT WORKS: Concrete steps for THEIR workflow from research. Then offer mockup by email."
    ),
    "why_contacting": (
        "WHY CONTACTING: One honest research-based reason. Confirm relevance. No pitch dump."
    ),
    "what_do_you_do": (
        "WHAT DO YOU DO: Short — build working AI systems around real workflows, not tool resale. "
        "Tie to their context if known."
    ),
    "needs_time": (
        "NEEDS TIME: Respect fully. Agree a specific follow-up window. No push."
    ),
    "send_info_email": (
        "SEND INFO BY EMAIL: Agree to send a short mockup/concept note tailored to them. "
        "Meeting only if they ask after reviewing."
    ),
    "general_interest": (
        "INTERESTED: One qualifying question, then offer mockup by email before meeting."
    ),
    "neutral_question": (
        "NEUTRAL QUESTION: Answer directly from research/KB. Soft offer of mockup or short call."
    ),
    "unknown": (
        "DEFAULT: Consultant discovery. Research-grounded. Problem first. Mockup before meeting when relevant."
    ),
}


def pitch_strategy_for(code: str) -> str:
    return PITCH_STRATEGY.get(code) or PITCH_STRATEGY["unknown"]


def detect_pitch_scenario(notes_or_text: str | None = None, *, inbound_call: bool = False) -> Scenario:
    """
    Scenario for Pitch Decker generation.
    - inbound_call=True → inbound_call scenario
    - notes_or_text set → pattern match (objections, etc.)
    - else → cold_outreach
    """
    if inbound_call:
        return SCENARIOS.get("inbound_call") or SCENARIOS["unknown"]
    if notes_or_text and notes_or_text.strip():
        return detect_scenario(notes_or_text)
    return SCENARIOS.get("cold_outreach") or SCENARIOS["unknown"]