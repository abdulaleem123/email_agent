"""Agentic INBOUND replies via native OpenAI function-calling (tool loop).

Why native tools and not LangChain/MCP: for this one job — answer from the
agent's own knowledge base and, on real interest, hand over a weekend booking
link — a native function-calling loop is lighter, has no extra runtime deps,
and is easy to reason about. The tools below are plain Python; swapping in a
LangChain/MCP toolbelt later only means re-registering the same callables.

Rules honoured here:
- Inbound NEVER uses Tavily (research is outbound-only).
- Answers come from the per-agent knowledge base first (kb_search tool).
- The meeting link is the agent's own Calendly/Meet/Zoom URL, offered for
  WEEKEND slots only, and only when the prospect shows genuine interest.
- Output stays short, human, non-AI-sounding.
"""
import json
from sqlalchemy.orm import Session

from ..config import settings
from .. import models
from . import keys as keysvc, embeddings
from .llm import (_persona_for, BASE_RULES, country_style, MEETING_DAYS_RULE,
                  _thread_history)


def _tools(agent: models.Agent):
    specs = [{
        "type": "function",
        "function": {
            "name": "kb_search",
            "description": "Search THIS agent's knowledge base for facts to answer "
                           "the prospect. Always use before answering a question.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string",
                               "description": "what to look up"}},
                "required": ["query"],
            },
        },
    }]
    if agent.meeting_url:
        specs.append({
            "type": "function",
            "function": {
                "name": "get_meeting_link",
                "description": "Return the agent's booking link. Call ONLY when the "
                               "prospect shows real interest in a call/demo/pricing. "
                               "Weekend (Sat/Sun) slots only.",
                "parameters": {"type": "object", "properties": {}},
            },
        })
    return specs


def _run_tool(db: Session, agent: models.Agent, name: str, args: dict) -> str:
    if name == "kb_search":
        hits = embeddings.search(db, agent.id, args.get("query", ""), k=4)
        return "\n\n".join(hits) if hits else "No matching knowledge found."
    if name == "get_meeting_link":
        return (f"{agent.meeting_url} (offer WEEKEND slots only — Saturday or Sunday)"
                if agent.meeting_url else "No meeting link configured.")
    return "Unknown tool."


def generate_reply_agentic(db: Session, lead: models.Lead,
                           agent: models.Agent) -> tuple[str, str]:
    """Returns (subject, body). Falls back to the plain generator on any error
    or when OpenAI isn't the provider / key missing."""
    key = keysvc.openai_key(db)
    if settings.LLM_PROVIDER.lower() != "openai" or not key:
        from .llm import generate_email
        s, b, _ = generate_email(db, lead, agent, purpose="reply", use_template=False)
        return s, b

    from openai import OpenAI
    client = OpenAI(api_key=key)

    system = (_persona_for(agent) + "\n\n" + BASE_RULES + "\n\n"
              "You are handling an INBOUND reply. Answer from the knowledge base "
              "(use kb_search). Keep it SHORT, clear, human. Do not re-pitch. "
              "If the prospect is interested in talking, call get_meeting_link and "
              "share it naturally.\n\n"
              f"MARKET PSYCHOLOGY:\n{country_style(lead.country)}\n\n"
              + (MEETING_DAYS_RULE if agent.meeting_url else "")
              + "\n\nFinish with a final message. Format: first line 'Subject: ...', "
              "blank line, then the body.")

    convo = [{"role": "system", "content": system},
             {"role": "user", "content": "THREAD SO FAR:\n" + (_thread_history(lead) or "(new)")}]
    tools = _tools(agent)

    tot_in = tot_out = 0
    final_text = ""
    for _ in range(4):                      # bounded tool loop
        resp = client.chat.completions.create(
            model=settings.OPENAI_MODEL, max_tokens=700,
            messages=convo, tools=tools, tool_choice="auto")
        u = getattr(resp, "usage", None)
        if u:
            tot_in += u.prompt_tokens or 0
            tot_out += u.completion_tokens or 0
        msg = resp.choices[0].message
        if msg.tool_calls:
            convo.append({"role": "assistant", "content": msg.content or "",
                          "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
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
    return subject, body
