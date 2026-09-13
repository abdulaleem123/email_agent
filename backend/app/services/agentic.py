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
                  _thread_history)
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
                           agent: models.Agent) -> tuple[str, str]:
    """Returns (subject, body). Falls back to plain generator on error."""
    key = keysvc.openai_key(db)
    if settings.LLM_PROVIDER.lower() != "openai" or not key:
        from .llm import generate_email
        s, b, _ = generate_email(db, lead, agent, purpose="reply", use_template=False)
        return s, b

    from openai import OpenAI
    client = OpenAI(api_key=key)

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
        "You are handling an INBOUND reply. Keep it SHORT or MEDIUM only. Human. Professional.\n"
        "Answer from knowledge base. Use scenario intelligence. No sales dump.\n"
        "If not interested: respect it. We have no problem with that. We only solve real problems.\n"
        "If they want to talk: say you will share a meeting link shortly. NEVER paste a URL.\n"
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
        {"role": "user", "content": "THREAD SO FAR:\n" + (_thread_history(lead) or "(new)")},
    ]
    tools = _tools(agent)

    tot_in = tot_out = 0
    final_text = ""
    for _ in range(4):
        resp = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            max_tokens=450,
            messages=convo,
            tools=tools,
            tool_choice="auto",
        )
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

    keysvc.record(db, "openai", "chat", settings.OPENAI_MODEL, agent.id, tot_in, tot_out)

    if not final_text:
        from .llm import generate_email
        s, b, _ = generate_email(db, lead, agent, purpose="reply", use_template=False)
        return s, b

    subject, body = "Re: your message", final_text
    if final_text.lower().startswith("subject:"):
        first, _, rest = final_text.partition("\n")
        subject = first.split(":", 1)[1].strip()[:200]
        body = rest.strip()
    from .llm import _humanize
    return _humanize(subject), _humanize(body)