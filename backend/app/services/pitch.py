"""Pitch Decker — generates a realistic sales-call TRANSCRIPT for a lead.

Flow (one request, same as the email pipeline's building blocks):
1. Cached Tavily advanced research on the lead (company name + website + person
   + country). Zero extra credits if already researched for email outreach.
2. OpenAI role-play: Osaja (or any sales-led agent) runs a region-aware
   conversation using the same US / UK / UAE / KSA / EU psychology as emails,
   handling objections and steering to a close.
3. Returns (summary, transcript). The router stores it as a PitchRecord.

Every LLM call is recorded in ApiUsage for the Super Admin page.
"""
from sqlalchemy.orm import Session

from ..config import settings
from .. import models
from . import tavily, keys as keysvc
from .llm import (_persona_for, country_style, SALES_COMPETITIVE_PLAYBOOK,
                  _call_llm, _knowledge_context)


PITCH_SYSTEM = """You are writing a realistic SALES-CALL TRANSCRIPT (a role-play),
not an email. Two speakers:
  {agent} — the salesperson (voice + psychology below)
  {lead_name} — the prospect at {company} ({country})

Rules:
- Make it feel like a real, natural phone/discovery call: short back-and-forth
  turns, interruptions, real objections ("we already have something", "no budget
  right now", "send me an email"), and {agent} handling them with the sales
  playbook — diagnosing, building a curiosity gap, anchoring on ONE real pain.
- Ground every claim in the RESEARCH + PAIN POINTS + AI ADOPTION SIGNALS below.
  If they already use AI, {agent} finds the gap and pitches the upgrade; if not,
  {agent} pitches the pain fix. Sell the 30-min strategy session as the next step.
- Write for the prospect's REGION PSYCHOLOGY (below). A KSA/UAE call opens with
  respect and relationship; a US call is efficient and outcome-first; UK is
  understated; EU is precise. Match it.
- The call ENDS IN A SOFT CLOSE: the prospect agrees to the strategy session
  (weekend slot) OR to a clear next step. Keep it believable, not magic.
- Do NOT sound AI-generated. Natural, human, concise turns.

OUTPUT FORMAT (exactly):
SUMMARY: <2-3 sentence recap of how the call went and why it closed>
---
{agent}: ...
{lead_name}: ...
{agent}: ...
(continue the alternating transcript to the close)"""


def generate_pitch(db: Session, lead: models.Lead,
                   agent: models.Agent) -> tuple[str, str]:
    """Returns (summary, transcript). Uses cached Tavily + OpenAI role-play."""
    # 1) research (cached — no extra Tavily credits if already done)
    research, pains = lead.company_research or "", lead.pain_points or ""
    if not research and (lead.company or lead.website):
        try:
            research, pains = tavily.research_lead(
                lead.company, lead.name, lead.website, lead.country,
                db=db, lead_email=lead.email)
            lead.company_research = research
            lead.pain_points = pains
            db.commit()
        except Exception:
            pass

    lead_name = lead.name or "the prospect"
    system = (_persona_for(agent) + "\n\n" + SALES_COMPETITIVE_PLAYBOOK + "\n\n"
              + PITCH_SYSTEM.format(agent=agent.name, lead_name=lead_name,
                                    company=lead.company or "their company",
                                    country=lead.country or "unknown region"))

    context = f"""LEAD
Person: {lead_name} | Title: {lead.title or 'unknown'}
Company: {lead.company or 'unknown'} | Website: {lead.website or 'n/a'}
Country: {lead.country or 'unknown'} | Phone: {lead.phone or 'n/a'}

REGION PSYCHOLOGY (write the call for this market):
{country_style(lead.country)}

COMPANY RESEARCH (Tavily):
{research or 'none'}

PAIN POINTS:
{pains or 'none extracted'}

AGENT KNOWLEDGE BASE (what we sell / can say):
{_knowledge_context(db, agent.id) or 'none'}

Write the transcript now."""

    text = _call_llm(system, context, max_tokens=1400, db=db, agent_id=agent.id)

    summary, transcript = "", text
    if "---" in text:
        head, _, body = text.partition("---")
        summary = head.replace("SUMMARY:", "").strip()
        transcript = body.strip()
    elif text.upper().startswith("SUMMARY:"):
        first, _, rest = text.partition("\n")
        summary = first.split(":", 1)[1].strip()
        transcript = rest.strip()
    return summary[:1200], transcript


ASK_SYSTEM = """You are {agent}, being asked a direct question by your own team
(not the prospect) about how to handle {lead_name} at {company}. Answer as a
sharp, experienced colleague would — short, concrete, practical. Ground your
answer in the research, pain points, and prior pitch transcript below when
relevant. If the question is about objections, give the exact line to use.
2-5 sentences. No fluff, no "as an AI", just the answer."""


def ask_about_lead(db: Session, lead: models.Lead, agent: models.Agent,
                   question: str, prior_transcript: str = "") -> str:
    """Free-form Q&A: team asks Osaja (or any agent) a question about a
    specific lead — e.g. 'how do I handle the pricing objection here?' — and
    gets a short, grounded answer using the same research/KB context."""
    system = ASK_SYSTEM.format(agent=agent.name, lead_name=lead.name or "the prospect",
                               company=lead.company or "their company")
    context = f"""LEAD: {lead.name or 'unknown'} at {lead.company or 'unknown'} ({lead.country or 'unknown'})
RESEARCH: {lead.company_research or 'none'}
PAIN POINTS: {lead.pain_points or 'none'}
KNOWLEDGE BASE: {_knowledge_context(db, agent.id) or 'none'}
PRIOR PITCH TRANSCRIPT (if any): {(prior_transcript or 'none')[:2000]}

TEAM QUESTION: {question.strip()[:600]}"""
    return _call_llm(system, context, max_tokens=400, db=db, agent_id=agent.id).strip()