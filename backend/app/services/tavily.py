"""Advanced Tavily research: company + person + website + country.

Passes:
1. Company overview (their own site preferred)
2. Person/role context (public professional info only)
3. Industry pain points automation/AI could solve
4. AI ADOPTION SIGNALS — does the company ALREADY use AI/chatbot/automation?
   -> If NO AI found: agents pitch pains + agentic-AI solution.
   -> If AI found:   agents find the gaps/faults in it and pitch improvement
                     + sales growth (handled in llm.py sales playbook).
Pain points are distilled by the LLM into 3-5 concrete bullets."""
import httpx
from ..config import settings

TAVILY_URL = "https://api.tavily.com/search"
DDG_URL = "https://api.duckduckgo.com/"


def _ddg_search(query: str, max_results: int = 5) -> dict:
    """Free, no-key fallback used when Tavily is missing or its credits are
    finished. Returns the SAME shape Tavily returns (answer + results[]), so
    _fmt() and every caller work unchanged. Keeps outbound + pitch alive on
    DuckDuckGo instead of pausing the whole system when Tavily runs out."""
    try:
        r = httpx.get(DDG_URL, params={"q": query, "format": "json",
                                       "no_html": 1, "skip_disambig": 1}, timeout=20)
        d = r.json()
    except Exception:
        return {"answer": "", "results": []}
    results = []
    for t in (d.get("RelatedTopics") or []):
        txt = t.get("Text") or ""
        if not txt and t.get("Topics"):
            for st in t["Topics"]:
                if st.get("Text"):
                    results.append({"title": "", "content": st["Text"]})
        elif txt:
            results.append({"title": t.get("FirstURL", ""), "content": txt})
        if len(results) >= max_results:
            break
    return {"answer": d.get("AbstractText") or d.get("Answer") or "", "results": results}


class TavilyQuota(Exception):
    """Key missing/invalid/exhausted — outbound campaigns auto-pause on this."""


_db = None          # set per research_lead call for key lookup + usage record


def _search(query: str, domains=None, max_results=5) -> dict:
    from . import keys as keysvc
    api_key = keysvc.tavily_key(_db) if _db is not None else settings.TAVILY_API_KEY
    # Tavily first (richer). On no-key / credits-finished / any error, fall back
    # to DuckDuckGo so outbound + pitch NEVER stop — they just get lighter
    # research. This function no longer raises TavilyQuota.
    if api_key:
        try:
            payload = {
                "api_key": api_key,
                "query": query,
                "search_depth": settings.TAVILY_DEPTH or "advanced",
                "max_results": max_results,
                "include_answer": True,
            }
            if domains:
                payload["include_domains"] = domains
            r = httpx.post(TAVILY_URL, json=payload, timeout=40)
            if r.status_code in (401, 402, 403, 429, 432):
                raise TavilyQuota(f"Tavily rejected the request (HTTP {r.status_code})")
            r.raise_for_status()
            if _db is not None:
                keysvc.record(_db, "tavily", "search", "tavily-advanced")
            return r.json()
        except Exception:
            pass   # -> DuckDuckGo fallback below
    data = _ddg_search(query, max_results)
    if _db is not None:
        try:
            keysvc.record(_db, "duckduckgo", "search", "ddg-fallback")
        except Exception:
            pass
    return data


def _fmt(data: dict, cap: int = 350) -> list[str]:
    parts = []
    if data.get("answer"):
        parts.append(data["answer"])
    for item in data.get("results", [])[:4]:
        snippet = (item.get("content") or "")[:cap]
        if snippet:
            parts.append(f"- {item.get('title','')}: {snippet}")
    return parts


def research_lead(company: str, person: str = "", website: str = "",
                  country: str = "", db=None, lead_email: str = "") -> tuple[str, str]:
    """Returns (research_text, pain_points_text). research_text includes an
    'AI ADOPTION SIGNALS:' section the email brain branches on.

    CACHED: one Tavily research per email/company EVER — a second campaign or
    another agent hits the DB cache and burns zero credits.
    Raises TavilyQuota when the key is missing/exhausted (outbound auto-pauses;
    inbound never uses Tavily so replies keep working)."""
    global _db
    _db = db
    if not (company or website):
        return "", ""

    cache_key = (lead_email or "").strip().lower() or \
        (website or company).lower().replace("https://", "").replace("http://", "").split("/")[0][:350]
    if db is not None and cache_key:
        from .. import models
        hit = db.query(models.ResearchCache).filter_by(cache_key=cache_key).first()
        if hit:
            return hit.research, hit.pain_points

    domain = ""
    if website:
        domain = website.replace("https://", "").replace("http://", "").split("/")[0]

    research_parts, pain_parts, ai_parts = [], [], []
    loc = f" in {country}" if country else ""

    # Pass 1 — what the company is and does
    try:
        q1 = f"{company} company overview services products industry{loc}"
        research_parts += _fmt(_search(q1, domains=[domain] if domain else None))
    except TavilyQuota:
        raise
    except Exception:
        pass

    # Pass 2 — role/person context
    if person and company:
        try:
            q2 = f'"{person}" {company} role responsibilities'
            research_parts += _fmt(_search(q2, max_results=3), cap=250)
        except Exception:
            pass

    # Pass 3 — industry pain points automation/AI could solve
    try:
        industry_q = (f"{company} industry challenges manual processes "
                      f"customer support operations bottlenecks{loc} "
                      "where AI automation helps")
        pain_parts += _fmt(_search(industry_q, max_results=4), cap=300)
    except Exception:
        pass

    # Pass 4 — AI adoption signals: do they already use AI / chatbot / automation?
    try:
        ai_q = (f"{company} website chatbot AI assistant live chat automation "
                f"customer support technology stack")
        ai_parts += _fmt(_search(ai_q, domains=[domain] if domain else None,
                                 max_results=4), cap=300)
    except Exception:
        pass

    research = "\n".join(research_parts)[:2600]
    if ai_parts:
        research += ("\n\nAI ADOPTION SIGNALS (does the company already use "
                     "AI/chatbot/automation? judge from these):\n"
                     + "\n".join(ai_parts)[:1200])
    pains_raw = "\n".join(pain_parts)[:2500]

    pains = pains_raw
    if pains_raw:
        try:
            from . import llm as llm_service
            pains = llm_service.distill_pain_points(company, country, research, pains_raw,
                                                    db=db)
        except Exception:
            pass
    research = research[:4000]
    if db is not None and cache_key and (research or pains):
        from .. import models
        db.add(models.ResearchCache(cache_key=cache_key, research=research,
                                    pain_points=pains))
        db.commit()
    return research, pains