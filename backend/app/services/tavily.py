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
import time
import httpx
from ..config import settings

# ── DuckDuckGo endpoints ──────────────────────────────────────────────────────
DDG_HTML_URL    = "https://html.duckduckgo.com/html/"
DDG_LITE_URL    = "https://lite.duckduckgo.com/lite/"
DDG_INSTANT_URL = "https://api.duckduckgo.com/"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
# Wikipedia asks for a UA that identifies the bot and gives a contact address;
# a plain browser UA gets a 403 "robot policy" reply instead of JSON.
RESEARCH_UA = "ChatversioResearchBot/1.0 (https://chatversio.ai; ops@chatversio.ai) httpx"
_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept-Language": "en-US,en;q=0.9",
}

# DDG answers a bot IP with HTTP 202 + a "select all squares containing a duck"
# page instead of results. Recognising it stops us burning retries on a
# challenge we cannot solve.
_CHALLENGE_MARKERS = (
    "complete the following challenge",
    "Unfortunately, bots use DuckDuckGo too",
    "anomaly detection",
    "images not loading",
)

_STRIP_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip(html: str) -> str:
    return _WS_RE.sub(" ", _STRIP_RE.sub(" ", html or "")).strip()


# DDG result markup. NOTE the block pattern: real markup is
# `class="result results_links results_links_deep web-result"`, so an exact
# `class="result"` match never fires — which silently returned [] on every
# single query and emptied the whole research stage.
_DDG_BLOCK = re.compile(r'<div[^>]*class="[^"]*\bresult\b[^"]*"', re.I)
_DDG_A_OPEN = re.compile(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*>', re.I)
_DDG_TITLE = re.compile(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*>(.*?)</a>',
                        re.S | re.I)
_DDG_SNIP = re.compile(r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
                       re.S | re.I)
_HREF = re.compile(r'href="([^"]+)"')
_UDDG = re.compile(r"uddg=([^&\"]+)")


def _parse_ddg_html(html: str, max_results: int = 6) -> list[dict]:
    results = []
    for block in _DDG_BLOCK.split(html)[1:]:
        title_m = _DDG_TITLE.search(block)
        if not title_m:
            continue
        title = _strip(title_m.group(1))
        url = ""
        open_m = _DDG_A_OPEN.search(block)
        if open_m:
            href_m = _HREF.search(open_m.group(0))
            if href_m:
                url = href_m.group(1)
                uddg = _UDDG.search(url)
                if uddg:
                    from urllib.parse import unquote
                    url = unquote(uddg.group(1))
        snip_m = _DDG_SNIP.search(block)
        snippet = _strip(snip_m.group(1)) if snip_m else ""
        if title or snippet:
            results.append({"title": title, "url": url, "content": snippet})
        if len(results) >= max_results:
            break
    return results


def _ddg_html_search(query: str, max_results: int = 6) -> list[dict]:
    """
    Real web results (title + snippet + URL) from DDG's HTML endpoint.

    Falls back to an empty list on any error (caller must handle). Returns []
    immediately when the IP is serving a bot challenge — no point retrying
    into a CAPTCHA.
    """
    for attempt in range(2):
        try:
            resp = httpx.get(
                DDG_HTML_URL,
                params={"q": query, "kl": "us-en"},
                headers=_HEADERS,
                timeout=20,
                follow_redirects=True,
            )
        except Exception:
            return []
        text = resp.text or ""
        if any(m in text for m in _CHALLENGE_MARKERS):
            return []
        if resp.status_code == 200:
            got = _parse_ddg_html(text, max_results)
            if got:
                return got
            if "result__a" in text:
                return []
        if attempt == 0:
            time.sleep(1.0)
    return []


def _ddg_lite_search(query: str, max_results: int = 6) -> list[dict]:
    """Second DDG surface — lighter markup, different rate limits."""
    try:
        resp = httpx.post(
            DDG_LITE_URL,
            data={"q": query},
            headers=_HEADERS,
            timeout=20,
            follow_redirects=True,
        )
    except Exception:
        return []
    text = resp.text or ""
    if resp.status_code != 200 or any(m in text for m in _CHALLENGE_MARKERS):
        return []
    links = re.findall(
        r'<a[^>]*rel="nofollow"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', text, re.S | re.I)
    snips = re.findall(
        r'<td[^>]*class="[^"]*result-snippet[^"]*"[^>]*>(.*?)</td>', text, re.S | re.I)
    out = []
    for i, (href, title_html) in enumerate(links[:max_results]):
        url = href
        uddg = _UDDG.search(url)
        if uddg:
            from urllib.parse import unquote
            url = unquote(uddg.group(1))
        if not url.startswith("http"):
            continue
        snip = _strip(snips[i]) if i < len(snips) else ""
        out.append({"title": _strip(title_html), "url": url, "content": snip})
    return out


def _ddg_instant(query: str, max_results: int = 5) -> dict:
    """Fallback: DDG Instant Answer API (Wikipedia-style, free, low quality)."""
    try:
        r = httpx.get(
            DDG_INSTANT_URL,
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            headers={"User-Agent": BROWSER_UA},
            timeout=20,
        )
        if r.status_code != 200 or not (r.text or "").strip():
            return {"answer": "", "results": []}
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
    Unified DuckDuckGo search: HTML endpoint, then lite, then Instant API.
    Returns {"answer": str, "results": [{"title", "content", "url"}]}.
    """
    html_results = _ddg_html_search(query, max_results)
    if html_results:
        return {"answer": "", "results": html_results}
    lite_results = _ddg_lite_search(query, max_results)
    if lite_results:
        return {"answer": "", "results": lite_results}
    return _ddg_instant(query, max_results)


def _wikipedia_search(query: str, max_results: int = 4) -> list[dict]:
    """Keyless fallback used when DuckDuckGo is unreachable.

    DuckDuckGo answers a datacentre IP with an HTTP 202 CAPTCHA, which is
    exactly how a lead ends up with a blank COMPANY RESEARCH block and a
    draft that opens on "many companies struggle...". Wikipedia's search API
    still answers, so the model always has something real about the company.
    """
    try:
        r = httpx.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search", "srsearch": query,
                    "srlimit": max_results, "format": "json", "utf8": 1},
            headers={"User-Agent": RESEARCH_UA, "Accept": "application/json"},
            timeout=20,
            follow_redirects=True,
        )
        if r.status_code != 200 or not (r.text or "").strip():
            return []
        hits = (r.json().get("query") or {}).get("search") or []
    except Exception:
        return []
    out = []
    for hit in hits[:max_results]:
        title = hit.get("title") or ""
        if not title:
            continue
        out.append({
            "title": "Wikipedia: " + title,
            "url": "https://en.wikipedia.org/wiki/" + title.replace(" ", "_"),
            "content": _strip(hit.get("snippet") or ""),
        })
    return out


def _site_snapshot(website: str, max_chars: int = 2500) -> str:
    """Read the lead's OWN website — their title, description and headings.

    Used as the last resort when every search engine is blocked or empty.
    This is the one source that cannot be about the wrong company, and it
    gives the model the lead's own words to open on.
    """
    if not website:
        return ""
    url = website.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"},
            timeout=20,
            follow_redirects=True,
        )
        if resp.status_code >= 400:
            return ""
        html = resp.text or ""
    except Exception:
        return ""

    parts = []
    title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if title_m and _strip(title_m.group(1)):
        parts.append("PAGE TITLE: " + _strip(title_m.group(1))[:200])
    desc_m = re.search(
        r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)', html, re.I)
    if desc_m and desc_m.group(1).strip():
        parts.append("META DESCRIPTION: " + _strip(desc_m.group(1))[:500])

    headings = []
    for h in re.findall(r"<h[123][^>]*>(.*?)</h[123]>", html, re.S | re.I):
        t = _strip(h)
        if 3 <= len(t) <= 120 and t not in headings:
            headings.append(t)
        if len(headings) >= 14:
            break
    if headings:
        parts.append("MAIN HEADINGS:\n- " + "\n- ".join(headings))

    body = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer)[^>]*>.*?</\1>",
                  " ", html)
    body = _strip(body)
    if body:
        parts.append("PAGE TEXT:\n" + body[:max_chars])
    return "\n".join(parts).strip()[:6000]


# Kept for backwards compatibility
class TavilyQuota(Exception):
    pass


_db = None  # set per research_lead call


def _search(query: str, domains=None, max_results: int = 6) -> dict:
    """DuckDuckGo first (it is the primary engine), Wikipedia when DDG is
    blocked or empty so a pass never comes back blank for no reason."""
    from . import keys as keysvc
    if _db is not None:
        try:
            keysvc.record(_db, "duckduckgo", "search", "ddg-advanced")
        except Exception:
            pass
    data = _ddg_search(query, max_results)
    if not (data.get("results") or data.get("answer")):
        wiki = _wikipedia_search(query, max_results)
        if wiki:
            data = {"answer": "", "results": wiki}
    return data


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

    # ── The lead's OWN website, always ────────────────────────────────────────
    # Search engines can come back empty (bot challenges, rate limits, a company
    # too small to be indexed) and their snippets are always someone else's
    # words. Their own title, description and headings are about this company
    # and this company alone — which is what stops a draft opening on
    # "many companies struggle...". Cached with the rest of the research.
    if website:
        snapshot = _site_snapshot(website)
        if snapshot:
            research += ("\n\nCOMPANY WEBSITE (their own copy — "
                         "quote it back to them):\n" + snapshot)

    research = research[:6000]

    # ── Distil pain points via LLM ────────────────────────────────────────────
    pains_raw = "\n".join(pain_parts)[:2800]
    if not pains_raw and research:
        # No dedicated pain pass survived either — let the model read the
        # research itself rather than leave PAIN POINTS as "none extracted".
        pains_raw = research[:2800]
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