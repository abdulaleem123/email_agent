"""Agentic INBOUND replies via native OpenAI function-calling (tool loop).

Rules:
- KB first (kb_search). Optional light research if lead has no company_research.
- Scenario intelligence (not interested, price, demo, etc.).
- Short or medium only. Human. Professional.
- NEVER paste Calendly/Meet/Zoom URLs — say you will share a meeting link shortly.
- No emojis, no decorative hyphens/dashes, no bullet lists.
"""
import json
from sqlalchemy.orm import Session

from ..config import settings
from .. import models
from . import keys as keysvc, embeddings
from .llm import (_persona_for, BASE_RULES, country_style, MEETING_DAYS_RULE,
                  _thread_history, _thread_digest, settings_block)
from .scenario_detector import detect_scenario, build_scenario_instruction


def _tools(agent: models.Agent):
    # KB only — no get_meeting_link (never paste real URLs)
    return [{
        "type": "function",
        "function": {
            "name": "kb_search",
            "description": "Search THIS agent's knowledge base for facts to answer "
                           "the prospect. Always use before answering a question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "what to look up",
                    }
                },
                "required": ["query"],
            },
        },
    }]


def _run_tool(db: Session, agent: models.Agent, name: str, args: dict) -> str:
    if name == "kb_search":
        hits = embeddings.search(db, agent.id, args.get("query", ""), k=4)
        return "\n\n".join(hits) if hits else "No matching knowledge found."
    if name == "get_meeting_link":
        return (
            "Do not paste a link. Write: I will share a meeting link with you "
            "shortly so we can discuss."
        )
    return "Unknown tool."


def generate_reply_agentic(db: Session, lead: models.Lead,
                           agent: models.Agent,
                           campaign: models.Campaign | None = None
                           ) -> tuple[str, str]:
    """Returns (subject, body). Falls back to plain generator on error."""
    key = keysvc.openai_key(db)
    if settings.LLM_PROVIDER.lower() != "openai" or not key:
        from .llm import generate_email
        s, b, _ = generate_email(db, lead, agent, purpose="reply",
                                 use_template=False, campaign=campaign)
        return s, b

    from openai import OpenAI
    client = OpenAI(api_key=key, base_url=keysvc.gateway_url())

    # Light DuckDuckGo if we have no stored research
    if not (lead.company_research or "").strip() and (lead.company or lead.website or lead.email):
        try:
            from . import tavily
            research, pains = tavily.research_lead(
                lead.company, lead.name, lead.website, lead.country,
                db=db, lead_email=lead.email,
            )
            if research:
                lead.company_research = research
                lead.pain_points = pains or lead.pain_points
                db.commit()
        except Exception:
            pass

    length = agent.message_length.value if hasattr(agent.message_length, "value") else (agent.message_length or "short")
    if str(length).lower() not in ("short", "medium"):
        length = "medium"

    last_inbound = next(
        (m.body for m in reversed(lead.messages or []) if m.direction == "in" and not m.is_spam),
        ""
    )
    scenario = detect_scenario(last_inbound)
    scenario_block = build_scenario_instruction(
        scenario, agent.name, lead.name or "the prospect"
    )

    system = (
        _persona_for(agent) + "\n\n" + BASE_RULES + "\n\n"
        + settings_block(campaign) + "\n\n"
        "You are handling an INBOUND reply. Keep it SHORT or MEDIUM only. Human. Professional.\n"
        "Answer from knowledge base. Use scenario intelligence. No sales dump.\n"
        "If they want to talk: offer a LIVE REALTIME demo of the chat or voice agent — "
        "the agent actually talking to a customer, in real time, on their own use case. "
        "Not a brochure, not a deck. Say you will share a link to book it. NEVER paste a URL.\n"
        "Call the product a CHAT AGENT or a VOICE AGENT. Never a chatbot, virtual "
        "assistant, IVR, voice bot or AI rep.\n"
        "STRICT: no emojis, no hyphens as decoration, no bullet lists, no long essays.\n"
        f"Length target: {length}.\n\n"
        f"── SCENARIO INTELLIGENCE ──\n{scenario_block}\n\n"
        f"MARKET PSYCHOLOGY:\n{country_style(lead.country)}\n\n"
        f"COMPANY RESEARCH (if any):\n{(lead.company_research or 'none')[:1200]}\n\n"
        + MEETING_DAYS_RULE
        + "\n\nFinish with a final message. Format: first line 'Subject: ...', "
          "blank line, then the body. Sign with Best regards and the agent name."
    )

    convo = [
        {"role": "system", "content": system},
        {"role": "user", "content": (
            "THREAD SO FAR:\n" + (_thread_history(lead) or "(new)")
            + "\n\nWHERE THE THREAD STANDS:\n" + _thread_digest(lead))},
    ]
    tools = _tools(agent)

    tot_in = tot_out = 0
    tot_spent = 0.0
    final_text = ""
    for _ in range(4):
        resp, spent = keysvc.costed_call(client, ("chat", "completions"),
            model=settings.OPENAI_MODEL,
            max_tokens=450,
            messages=convo,
            tools=tools,
            tool_choice="auto",
        )
        tot_spent += spent or 0.0
        u = getattr(resp, "usage", None)
        if u:
            tot_in += u.prompt_tokens or 0
            tot_out += u.completion_tokens or 0
        msg = resp.choices[0].message
        if msg.tool_calls:
            convo.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
            })
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                result = _run_tool(db, agent, tc.function.name, args)
                convo.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            continue
        final_text = (msg.content or "").strip()
        break

    keysvc.record(db, "openai", "chat", settings.OPENAI_MODEL, agent.id,
                  tot_in, tot_out, cost_usd=tot_spent)

    if not final_text:
        from .llm import generate_email
        s, b, _ = generate_email(db, lead, agent, purpose="reply",
                                 use_template=False, campaign=campaign)
        return s, b

    subject, body = "Re: your message", final_text
    if final_text.lower().startswith("subject:"):
        first, _, rest = final_text.partition("\n")
        subject = first.split(":", 1)[1].strip()[:200]
        body = rest.strip()
    from .llm import _humanize, strip_pricing_talk, has_pricing_talk, apply_cta
    from . import playbook, agent_settings
    # Same hard guarantees as outbound: no URLs / our address, no banned phrase.
    subject = playbook.scrub(_humanize(subject), agent)
    body = playbook.scrub(_humanize(body), agent)
    # NO PRICING TALK — never answered, never written, campaign or not.
    if (campaign is not None and agent_settings.is_on(campaign, "no_pricing")
            and getattr(campaign, "no_pricing", True)):
        if has_pricing_talk(subject):
            subject = strip_pricing_talk(subject)
        if has_pricing_talk(body):
            body = strip_pricing_talk(body)
    # CTA: the booking link is the one URL code is allowed to insert.
    body = apply_cta(body, campaign, agent)
    return subject, body