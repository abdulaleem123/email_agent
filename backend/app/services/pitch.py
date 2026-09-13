"""Pitch Decker — generates a realistic, scenario-aware sales-call TRANSCRIPT.

PIPELINE (for every pitch request):
1. Fresh DuckDuckGo ADVANCED search  — 5 targeted passes on the lead:
      A. Company overview + products/services (real web results)
      B. Person / role context
      C. Industry pain points AI/automation addresses
      D. AI adoption signals (does the company ALREADY use chatbot/automation?)
      E. Recent news — funding, launches, problems, hiring signals

2. GPT-4o-mini (hardcoded — NOT the shared LLM config) synthesises:
      - A SCENARIO BRIEF:  what exactly this company does, what's likely broken,
        whether they already have AI or not, and one concrete fix.
      - A TRANSCRIPT:      a realistic region-aware call where the agent walks
        through the scenario brief, handles real objections, and closes on a
        strategy session.

The pitch is NEVER a generic template. Every claim, every objection, every
angle is grounded in the search data retrieved seconds before generation.
Every LLM call is recorded in ApiUsage for the Super Admin page.
"""

import logging
import re
from sqlalchemy.orm import Session
from .scenario_detector import detect_pitch_scenario, pitch_strategy_for
from ..config import settings
from .. import models
from . import keys as keysvc
from .llm import (_persona_for, country_style, SALES_COMPETITIVE_PLAYBOOK,
                  _knowledge_context)

log = logging.getLogger(__name__)

# ── Model config ──────────────────────────────────────────────────────────────
PITCH_MODEL = "gpt-4o-mini"  # hardcoded — pitch always uses this model


def _call_pitch_llm(
    system: str,
    user_content: str,
    max_tokens: int = 1600,
    db: Session | None = None,
    agent_id: int | None = None,
) -> str:
    """
    Dedicated LLM caller for pitch generation.
    ALWAYS uses GPT-4o-mini regardless of the global LLM_PROVIDER config.
    Falls back to the shared _call_llm only if OpenAI key is unavailable.
    """
    from fastapi import HTTPException
    from openai import (OpenAI, AuthenticationError, RateLimitError,
                        APIConnectionError, APIError)

    api_key = keysvc.openai_key(db) if db is not None else settings.OPENAI_API_KEY
    if not api_key:
        raise HTTPException(
            400,
            "No OpenAI key set — add it in Super Admin → API Keys. "
            "Pitch generation requires GPT-4o-mini."
        )

    client = OpenAI(api_key=api_key)
    try:
        resp = client.chat.completions.create(
            model=PITCH_MODEL,
            max_tokens=max_tokens,
            temperature=0.7,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_content},
            ],
        )
    except AuthenticationError:
        raise HTTPException(
            400,
            "OpenAI rejected the key — invalid or revoked. "
            "Re-check it in Super Admin → API Keys."
        )
    except RateLimitError:
        raise HTTPException(
            429,
            "OpenAI rate limit or quota exceeded — check your OpenAI account billing."
        )
    except APIConnectionError:
        raise HTTPException(
            502,
            "Could not reach OpenAI — check the server's internet connection."
        )
    except APIError as exc:
        raise HTTPException(502, f"OpenAI error: {exc}")

    if db is not None and resp.usage:
        keysvc.record(
            db, "openai", "chat", PITCH_MODEL, agent_id,
            resp.usage.prompt_tokens, resp.usage.completion_tokens,
        )

    return (resp.choices[0].message.content or "").strip()


# ── Scenario analysis ─────────────────────────────────────────────────────────
SCENARIO_SYSTEM = """\
You are a senior sales intelligence analyst working for an AI solutions partner.
Your job is to read raw DuckDuckGo web-research about a company and produce a
tight SCENARIO BRIEF that a consultant can use on a discovery call.

CRITICAL RULES:
- Use ONLY facts present in the research. Never invent clients, tools, numbers, or problems.
- If the research is thin or shows no clear operational pain, set PRIMARY_PAIN to
  "NO CLEAR PAIN — website/operations look solid; only light enhancement/upgrade possible"
  and recommend a soft, honest angle (not a forced problem).
- Prefer concrete operational friction (manual processes, response time, document
  handling, knowledge gaps, repetitive work) over vague "they need AI".

Output exactly this structure (no preamble, no markdown headings):

COMPANY_SNAPSHOT: <1-2 sentences: what they do, who they serve, size signal, website presence>
CURRENT_AI_STATUS: <none | basic | advanced — and a one-line reason grounded in research>
PRIMARY_PAIN: <the single most concrete operational problem OR the "NO CLEAR PAIN…" line above>
SECONDARY_PAIN: <one more real signal if it exists, otherwise "none">
RECOMMENDED_ANGLE: <specific opening angle quoting a real detail from research; if no pain, suggest a light enhancement conversation>
OBJECTION_LIKELY: <most likely objection + one-line natural counter>
NEWS_HOOK: <any recent news/event that makes now a good time — or "none">
WEBSITE_NOTE: <one short observation about their website/online presence if useful, else "none">

Be specific. Never invent facts."""


def _build_scenario_brief(
    company: str,
    country: str,
    research: str,
    pains: str,
    db: Session | None = None,
    agent_id: int | None = None,
) -> str:
    """Run a fast GPT-4o-mini pass to extract a scenario brief from raw research."""
    user = (
        f"COMPANY: {company or 'unknown'}\n"
        f"COUNTRY: {country or 'unknown'}\n\n"
        f"RAW RESEARCH:\n{research[:3500]}\n\n"
        f"RAW PAIN SIGNALS:\n{pains[:1500]}"
    )
    try:
        return _call_pitch_llm(
            SCENARIO_SYSTEM, user, max_tokens=500, db=db, agent_id=agent_id
        )
    except Exception as exc:
        log.warning("Scenario brief failed: %s", exc)
        return f"PRIMARY_PAIN: {pains[:300] or 'unknown'}"


# ── Main pitch prompt ─────────────────────────────────────────────────────────
PITCH_SYSTEM = """\
You are writing a realistic DISCOVERY-CALL TRANSCRIPT (role-play), not a sales email
and not marketing copy. Sound like a human consultant who researched the company
and is checking whether a practical AI/automation idea is actually useful.

Two speakers:
  {agent}     — AI solutions consultant (not a pushy salesperson)
  {lead_name} — the prospect at {company} ({country})

═══════════ CORE PHILOSOPHY ═══════════
Research deeply. Speak simply. Ask intelligently. Solve first. Sell second.
Order of priority: Relevance → Trust → Problem → Solution → Value → Next step.
Never force a sale. If there is no genuine problem we can solve, say so honestly.

═══════════ MANDATORY RULES ═══════════

1. SCENARIO-GROUNDED: Every claim comes from the SCENARIO BRIEF + RESEARCH below.
   Never invent facts, clients, results, or tools. If research shows they already
   have a chatbot/automation, acknowledge it and look for the real gap. If PRIMARY_PAIN
   is "NO CLEAR PAIN…", the agent does NOT invent a problem. Instead they say something
   natural like: "From what I could see online, your setup looks solid. The only thing
   that might still be useful is a light enhancement or upgrade on X — but only if that
   actually matters to you right now. If not, no problem at all."

2. HUMAN, CONSULTANT TONE: Short turns. Contractions. Partial sentences. "yeah",
   "right", "got it". No scripted marketing language, no "we are a leading AI company",
   no list of 10 services. The agent is a technical problem-solver checking relevance.

3. OPENING (cold-call style, natural):
   "{agent} greets, confirms name, briefly mentions they researched {company} because of
   one specific observation (NEWS_HOOK or RECOMMENDED_ANGLE or website detail), then says
   they are not calling with a generic pitch — they just want to understand if this is
   actually a problem for them."

4. ONE ANCHOR ONLY: Focus on PRIMARY_PAIN (or the honest no-pain line). Depth over breadth.
   Ask intelligent questions: how they handle it today, whether it's manual, how much time
   it takes, whether they already use any AI for it.

5. REGION PSYCHOLOGY: Match opening/closing tone to the market (GCC = respect + relationship,
   US = outcome-first, UK = understated, EU = precise). Use the REGION PROFILE given.

6. WEBSITE / COMPANY PRESENCE: If WEBSITE_NOTE or research mentions the website, the agent
   can naturally reference it ("I had a look at your site…") so the prospect feels the
   research is real. Do not invent a logo or fake screenshot.

7. CONVERSATION SCENARIO (mandatory — follow the injected SCENARIO STRATEGY block):
   Adapt the entire dialogue to that scenario (cold vs inbound call, not interested,
   price, already have solution, demo, proof, etc.). Do NOT use one generic sales script.
   Price/cheaper-competitor: never race to the bottom; reduce scope or show working mockup.
   Not interested: understand once, then exit politely if still no.

8. DEMO-FIRST: When the problem is real, the agent should prefer:
   "I can put together a small working example/mockup for your situation and email it —
    you review it first; if useful we do a short meeting; if not, no problem."
   Meeting is secondary to a concrete artifact.

9. NOT AI-SOUNDING: No bullet answers, no "as an AI", no corporate brochure voice.

OUTPUT FORMAT (exact — no deviations):
SUMMARY: <2-3 sentences: scenario, whether a real problem existed, outcome>
MOCKUP: <if relevant: 5-10 lines describing a concrete mockup/demo concept for THIS prospect's workflow, grounded in research; if not relevant write "none">
---
{agent}: ...
{lead_name}: ...
{agent}: ...
(alternate until natural end)"""


PICKUP_SYSTEM = """\
You are writing a REALISTIC CALL TRANSCRIPT that matches the agent's call notes EXACTLY.
This is not a sales script — it is a reconstruction of what actually happened.

Two speakers:
  {agent}     — AI solutions consultant
  {lead_name} — the prospect at {company} ({country})

Rules:
- The transcript MUST reflect the mood, objections, and outcome in AGENT NOTES.
  If notes say "not interested" → ends with no commitment, polite exit.
  If notes say "booked a call" → ends with a clear booking.
  If notes say "busy / call later" → ends with a callback agreement.
- Use real details from RESEARCH and SCENARIO BRIEF only where they fit the notes.
- Natural, short, human turns. No invented happy endings or forced closes.
- Match region psychology from REGION PROFILE.
- If the notes imply no real pain was found, the agent stays honest and does not invent one.

OUTPUT FORMAT:
SUMMARY: <2-3 sentences matching exactly what the notes describe>
MOCKUP: <5-10 line mockup concept for this prospect if relevant, else "none">
---
{agent}: ...
{lead_name}: ...
(alternate to the ending described in notes)"""


def _parse_transcript(text: str) -> tuple[str, str]:
    """Split LLM output into (summary_with_mockup, transcript)."""
    summary, transcript = "", text
    if "---" in text:
        head, _, body = text.partition("---")
        summary = head.strip()
        transcript = body.strip()
    elif text.upper().startswith("SUMMARY:"):
        first, _, rest = text.partition("\n")
        summary = first.split(":", 1)[1].strip()
        transcript = rest.strip()
    summary = summary.replace("SUMMARY:", "").strip()
    return summary[:2500], transcript


# ── Public API ────────────────────────────────────────────────────────────────

def generate_pitch(
    db: Session,
    lead: models.Lead,
    agent: models.Agent,
) -> tuple[str, str]:
    """
    Full pipeline:
      1. Fresh DuckDuckGo advanced research (5 passes, cache BYPASSED so pitch
         always uses the latest web data — cache is written back after).
      2. GPT-4o-mini scenario brief extraction.
      3. GPT-4o-mini transcript generation grounded in the brief.

    Returns (summary, transcript).
    """
    from . import tavily

    # ── Step 1: Fresh advanced research ──────────────────────────────────────
    # Bypass cache by calling research_lead with a fresh search.
    # We invalidate any stale cache entry so fresh data is written back.
    research, pains = "", ""
    if lead.company or lead.website:
        try:
            # Invalidate old cache entry so we always get fresh web data for pitch
            if db is not None:
                cache_key = (
                    (lead.email or "").strip().lower()
                    or (lead.website or lead.company or "")
                        .lower()
                        .replace("https://", "")
                        .replace("http://", "")
                        .split("/")[0][:350]
                )
                if cache_key:
                    old = db.query(models.ResearchCache).filter_by(
                        cache_key=cache_key
                    ).first()
                    if old:
                        db.delete(old)
                        db.commit()

            research, pains = tavily.research_lead(
                lead.company, lead.name, lead.website, lead.country,
                db=db, lead_email=lead.email,
            )
            lead.company_research = research
            lead.pain_points       = pains
            db.commit()
        except Exception as exc:
            log.warning("Research failed for lead %s: %s", lead.id, exc)
            # Fall back to whatever is already stored
            research = lead.company_research or ""
            pains    = lead.pain_points or ""

    # ── Step 2: Scenario brief (GPT-4o-mini, fast pass) ──────────────────────
    scenario_brief = _build_scenario_brief(
        lead.company, lead.country, research, pains,
        db=db, agent_id=agent.id,
    )

    pitch_sc = detect_pitch_scenario(None, inbound_call=False)
    strategy = pitch_strategy_for(pitch_sc.code)
    
    # ── Step 3: Full transcript (GPT-4o-mini) ─────────────────────────────────
    lead_name = lead.name or "the prospect"

    system = (
        _persona_for(agent)
        + "\n\n"
        + SALES_COMPETITIVE_PLAYBOOK
        + "\n\n"
        + PITCH_SYSTEM.format(
            agent=agent.name,
            lead_name=lead_name,
            company=lead.company or "their company",
            country=lead.country or "unknown region",
        )
    )

    context = f"""SCENARIO STRATEGY ({pitch_sc.code}):
{strategy}

SCENARIO BRIEF (extracted from live web research — use this as your call guide):
{scenario_brief}

LEAD
Person : {lead_name} | Title: {lead.title or 'unknown'}
Company: {lead.company or 'unknown'} | Website: {lead.website or 'n/a'}
Country: {lead.country or 'unknown'} | Phone: {lead.phone or 'n/a'}

REGION PSYCHOLOGY (shape the call tone to this market):
{country_style(lead.country)}

FULL RESEARCH (DuckDuckGo advanced search — {len(research)} chars):
{research or 'none retrieved'}

PAIN POINTS (distilled by AI from research):
{pains or 'none extracted'}

AGENT KNOWLEDGE BASE (what Chatversio AI sells):
{_knowledge_context(db, agent.id) or 'none'}

IMPORTANT:
- Follow SCENARIO STRATEGY for the whole dialogue.
- If PRIMARY_PAIN is "NO CLEAR PAIN…", do NOT invent a problem. Be honest and offer only a light enhancement/upgrade if it makes sense, otherwise end politely.
- You may naturally mention their website if it helps show you researched them.
- Sound like a human consultant, not a sales script.
- Include MOCKUP line in the output when a concrete demo concept applies.
Now write the full transcript. Anchor every claim in the SCENARIO BRIEF above.
Do NOT use any claim not supported by the research."""

    text = _call_pitch_llm(
        system, context, max_tokens=1800, db=db, agent_id=agent.id
    )
    return _parse_transcript(text)


def generate_pickup_transcript(
    db: Session,
    lead: models.Lead,
    agent: models.Agent,
    call_notes: str,
) -> tuple[str, str]:
    """
    Generate a transcript that matches what ACTUALLY happened on a call.
    Still grounded in research + scenario brief, but the outcome follows
    the agent's plain-English notes exactly.
    """
    from . import tavily

    research = lead.company_research or ""
    pains    = lead.pain_points or ""

    # Fresh research if we have nothing
    if not research and (lead.company or lead.website):
        try:
            research, pains = tavily.research_lead(
                lead.company, lead.name, lead.website, lead.country,
                db=db, lead_email=lead.email,
            )
            lead.company_research = research
            lead.pain_points       = pains
            db.commit()
        except Exception:
            pass

    scenario_brief = _build_scenario_brief(
        lead.company, lead.country, research, pains,
        db=db, agent_id=agent.id,
    )
    
    notes = (call_notes or "").strip()
    inbound = bool(re.search(r"\b(they|he|she|client)\s+called\b|\binbound\b", notes, re.I))
    pitch_sc = detect_pitch_scenario(notes, inbound_call=inbound)
    strategy = pitch_strategy_for(pitch_sc.code)

    lead_name = lead.name or "the prospect"

    system = PICKUP_SYSTEM.format(
        agent=agent.name,
        lead_name=lead_name,
        company=lead.company or "their company",
        country=lead.country or "unknown region",
    )

    context = f"""AGENT NOTES (what actually happened — match this exactly):
{call_notes}

SCENARIO DETECTED: {pitch_sc.label} ({pitch_sc.code})
SCENARIO STRATEGY:
{strategy}

SCENARIO BRIEF (use where consistent with the notes):
{scenario_brief}

LEAD
Person : {lead_name} | Title: {lead.title or 'unknown'}
Company: {lead.company or 'unknown'}
Country: {lead.country or 'unknown'} | Phone: {lead.phone or 'n/a'}

REGION PROFILE:
{country_style(lead.country)}

RESEARCH:
{research[:2500] or 'none'}

Write the transcript now. The outcome MUST match the agent notes above.
Include MOCKUP line when a concrete demo concept applies."""

    text = _call_pitch_llm(
        system, context, max_tokens=1600, db=db, agent_id=agent.id
    )
    return _parse_transcript(text)


# ── Q&A ───────────────────────────────────────────────────────────────────────
ASK_SYSTEM = """\
You are {agent}, being asked a direct question by your own sales team
(not the prospect) about how to handle {lead_name} at {company}.

Answer as a sharp, experienced colleague — short, concrete, practical.
Ground your answer in the SCENARIO BRIEF, research, pain points, and
prior pitch transcript below. If the question is about objections, give
the EXACT line to use on the call.

2-5 sentences. No fluff. No "as an AI"."""


def ask_about_lead(
    db: Session,
    lead: models.Lead,
    agent: models.Agent,
    question: str,
    prior_transcript: str = "",
) -> str:
    """Free-form Q&A grounded in the lead's research and prior pitch."""
    research = lead.company_research or ""
    pains    = lead.pain_points or ""

    scenario_brief = _build_scenario_brief(
        lead.company, lead.country, research, pains,
        db=db, agent_id=agent.id,
    ) if research else ""
    
    sc = detect_pitch_scenario(question)
    strategy = pitch_strategy_for(sc.code)

    system = ASK_SYSTEM.format(
        agent=agent.name,
        lead_name=lead.name or "the prospect",
        company=lead.company or "their company",
    )

    context = (
        f"ACTIVE SCENARIO STRATEGY ({sc.code}):\n{strategy}\n\n"
        f"SCENARIO BRIEF:\n{scenario_brief}\n\n"
        f"LEAD: {lead.name or 'unknown'} at {lead.company or 'unknown'} ({lead.country or 'unknown'})\n"
        f"RESEARCH: {research[:1800]}\n"
        f"PAIN POINTS: {pains[:600]}\n"
        f"KNOWLEDGE BASE: {_knowledge_context(db, agent.id)[:800] or 'none'}\n"
        f"PRIOR TRANSCRIPT (if any): {(prior_transcript or 'none')[:2000]}\n\n"
        f"TEAM QUESTION: {question.strip()[:600]}"
    )

    return _call_pitch_llm(
        system, context, max_tokens=450, db=db, agent_id=agent.id
    ).strip()