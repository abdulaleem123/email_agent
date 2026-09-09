"""Web research via DuckDuckGo (free, no API key required).

ADVANCED SEARCH PIPELINE:
1. DDG HTML search   — real web results (title + snippet) from actual pages
2. DDG Instant API   — fallback: AbstractText + RelatedTopics (Wikipedia-style)

Passes (for every lead research call):
A. Company overview        — what the business does, industry, products/services
B. Person/role context     — seniority, responsibilities, background
C. Industry pain points    — manual bottlenecks AI/automation addresses in this sector
D. AI adoption signals     — does the company ALREADY use chatbot / automation / AI?
E. Recent news/events      — fundraising, launches, problems, hiring signals

Pain points are distilled by the LLM into 3-5 concrete bullets.
Results are cached per lead/company to avoid repeated searches.
"""
import re
import httpx
from ..config import settings

# ── DuckDuckGo endpoints ──────────────────────────────────────────────────────
DDG_HTML_URL    = "https://html.duckduckgo.com/html/"
DDG_INSTANT_URL = "https://api.duckduckgo.com/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _ddg_html_search(query: str, max_results: int = 6) -> list[dict]:
    """
    Advanced DDG search — fetches the actual HTML results page and extracts
    real web snippets (title + body + URL).  Returns list of
    {"title": str, "url": str, "content": str}.

    Falls back to empty list on any error (caller must handle).
    """
    try:
        resp = httpx.get(
            DDG_HTML_URL,
            params={"q": query, "kl": "us-en"},
            headers=_HEADERS,
            timeout=20,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return []
        html = resp.text

        results = []
        # DDG HTML page structure: each result is in a div.result
        # Title in <a class="result__a">, snippet in <a class="result__snippet">
        # Simple regex extraction (no BS4 dependency)
        blocks = re.split(r'<div class=["\']result["\']', html)
        for block in blocks[1:]:  # skip first empty split
            # Title
            title_m = re.search(r'class=["\']result__a["\'][^>]*>(.*?)</a>', block, re.S)
            title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ""

            # URL
            url_m = re.search(r'href=["\']([^"\']+)["\']', block)
            url = url_m.group(1) if url_m else ""
            # DDG wraps URLs — extract actual URL from uddg= param
            uddg_m = re.search(r'uddg=([^&"\']+)', url)
            if uddg_m:
                from urllib.parse import unquote
                url = unquote(uddg_m.group(1))

            # Snippet
            snip_m = re.search(r'class=["\']result__snippet["\'][^>]*>(.*?)</a>', block, re.S)
            snippet = re.sub(r'<[^>]+>', '', snip_m.group(1)).strip() if snip_m else ""

            if title or snippet:
                results.append({"title": title, "url": url, "content": snippet})
            if len(results) >= max_results:
                break

        return results
    except Exception:
        return []


def _ddg_instant(query: str, max_results: int = 5) -> dict:
    """Fallback: DDG Instant Answer API (Wikipedia-style, free, low quality)."""
    try:
        r = httpx.get(
            DDG_INSTANT_URL,
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=20,
        )
        d = r.json()
    except Exception:
        return {"answer": "", "results": []}

    results = []
    for t in (d.get("RelatedTopics") or []):
        txt = t.get("Text") or ""
        if not txt and t.get("Topics"):
            for st in t["Topics"]:
                if st.get("Text"):
                    results.append({"title": "", "content": st["Text"], "url": ""})
        elif txt:
            results.append({"title": t.get("FirstURL", ""), "content": txt, "url": ""})
        if len(results) >= max_results:
            break
    return {
        "answer": d.get("AbstractText") or d.get("Answer") or "",
        "results": results,
    }


def _ddg_search(query: str, max_results: int = 6) -> dict:
    """
    Unified search: tries advanced HTML search first, falls back to Instant API.
    Returns {"answer": str, "results": [{"title", "content", "url"}]}.
    """
    html_results = _ddg_html_search(query, max_results)
    if html_results:
        return {"answer": "", "results": html_results}
    # Fallback
    return _ddg_instant(query, max_results)


# Kept for backwards compatibility
class TavilyQuota(Exception):
    pass


_db = None  # set per research_lead call


def _search(query: str, domains=None, max_results: int = 6) -> dict:
    from . import keys as keysvc
    if _db is not None:
        try:
            keysvc.record(_db, "duckduckgo", "search", "ddg-advanced")
        except Exception:
            pass
    return _ddg_search(query, max_results)


def _fmt(data: dict, cap: int = 400) -> list[str]:
    """Format search results into readable text snippets."""
    parts = []
    if data.get("answer"):
        parts.append(data["answer"][:cap])
    for item in data.get("results", [])[:5]:
        content = (item.get("content") or "")[:cap]
        title   = (item.get("title") or "")[:80]
        url     = (item.get("url") or "")[:120]
        if content:
            line = f"[{title}]" if title else ""
            if url and not url.startswith("http"):
                pass  # skip DDG internal links
            elif url:
                line += f" ({url})"
            line += f": {content}"
            parts.append(line.strip(": "))
    return parts


def research_lead(
    company: str,
    person: str = "",
    website: str = "",
    country: str = "",
    db=None,
    lead_email: str = "",
) -> tuple[str, str]:
    """
    Advanced 5-pass DuckDuckGo research pipeline.
    Returns (research_text, pain_points_text). Fully cached per email/company.

    Passes:
      A. Company overview + products/services
      B. Person/role context (if name known)
      C. Industry pain points for AI/automation
      D. AI adoption signals (chatbot, CRM, automation tools in use)
      E. Recent news — funding, launches, hiring, problems
    """
    global _db
    _db = db

    if not (company or website):
        return "", ""

    # ── Cache lookup ──────────────────────────────────────────────────────────
    cache_key = (
        (lead_email or "").strip().lower()
        or (website or company)
            .lower()
            .replace("https://", "")
            .replace("http://", "")
            .split("/")[0][:350]
    )
    if db is not None and cache_key:
        from .. import models
        hit = db.query(models.ResearchCache).filter_by(cache_key=cache_key).first()
        if hit:
            return hit.research, hit.pain_points

    domain = ""
    if website:
        domain = (
            website.replace("https://", "")
                   .replace("http://", "")
                   .split("/")[0]
        )

    loc = f" in {country}" if country else ""
    research_parts: list[str] = []
    pain_parts:     list[str] = []
    ai_parts:       list[str] = []
    news_parts:     list[str] = []

    # ── Pass A: Company overview ──────────────────────────────────────────────
    try:
        q = f'"{company}" company services products customers industry{loc}'
        research_parts += _fmt(_search(q, domains=[domain] if domain else None))
    except Exception:
        pass

    # ── Pass A2: Company website / about page ─────────────────────────────────
    if domain:
        try:
            q2 = f'site:{domain} about services solutions'
            research_parts += _fmt(_search(q2), cap=300)
        except Exception:
            pass

    # ── Pass B: Person / role context ─────────────────────────────────────────
    if person and company:
        try:
            q = f'"{person}" {company} role responsibilities background LinkedIn'
            research_parts += _fmt(_search(q, max_results=4), cap=280)
        except Exception:
            pass

    # ── Pass C: Industry pain points for AI / automation ─────────────────────
    try:
        q = (
            f"{company} industry challenges manual processes customer support "
            f"operations inefficiency bottleneck{loc} how AI automation helps"
        )
        pain_parts += _fmt(_search(q, max_results=5), cap=350)
    except Exception:
        pass

    # ── Pass C2: Sector-specific pain (use company name + problem keywords) ───
    try:
        q = (
            f'"{company}" problems slow response customer complaints staff workload '
            f"scalability growing team"
        )
        pain_parts += _fmt(_search(q, max_results=4), cap=300)
    except Exception:
        pass

    # ── Pass D: AI adoption signals ───────────────────────────────────────────
    try:
        q = (
            f'"{company}" chatbot AI assistant automation CRM live chat '
            f"technology stack customer support tools"
        )
        ai_parts += _fmt(
            _search(q, domains=[domain] if domain else None, max_results=5),
            cap=300,
        )
    except Exception:
        pass

    # ── Pass E: Recent news / events ─────────────────────────────────────────
    try:
        q = f'"{company}" 2024 2025 news funding launch product hiring expansion'
        news_parts += _fmt(_search(q, max_results=4), cap=280)
    except Exception:
        pass

    # ── Assemble research blob ────────────────────────────────────────────────
    research = "\n".join(research_parts)[:3000]

    if ai_parts:
        research += (
            "\n\nAI ADOPTION SIGNALS (does the company already use "
            "AI / chatbot / automation? judge from these):\n"
            + "\n".join(ai_parts)[:1200]
        )

    if news_parts:
        research += (
            "\n\nRECENT COMPANY NEWS / SIGNALS:\n"
            + "\n".join(news_parts)[:800]
        )

    research = research[:4500]

    # ── Distil pain points via LLM ────────────────────────────────────────────
    pains_raw = "\n".join(pain_parts)[:2800]
    pains = pains_raw
    if pains_raw:
        try:
            from . import llm as llm_service
            pains = llm_service.distill_pain_points(
                company, country, research, pains_raw, db=db
            )
        except Exception:
            pass

    # ── Cache & return ────────────────────────────────────────────────────────
    if db is not None and cache_key and (research or pains):
        from .. import models
        db.add(
            models.ResearchCache(
                cache_key=cache_key, research=research, pain_points=pains
            )
        )
        db.commit()

    return research, pains