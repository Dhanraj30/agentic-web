"""
Scraper Tool — AgenticWeb
Fast HTTP scraping (no browser needed) + DuckDuckGo web search.
"""
from __future__ import annotations
import logging
import urllib.parse
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


async def scrape(url: str, instruction: str = "", llm_router=None) -> str:
    try:
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "iframe", "aside"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ", strip=True).split())[:4000]
        if not instruction or not llm_router:
            return text[:2000]
        result = llm_router.complete(
            [{"role": "user", "content": f"From this page:\n{text}\n\nExtract: {instruction}"}],
            system="Extract exactly what is asked. Be brief and factual.",
        )
        return result
    except Exception as e:
        return f"Scrape failed for {url}: {e}"


async def search_web(query: str) -> list[dict]:
    endpoints = [
        ("POST", "https://html.duckduckgo.com/html/", {"data": {"q": query}}),
        ("GET", "https://html.duckduckgo.com/html/", {"params": {"q": query}}),
        ("GET", "https://lite.duckduckgo.com/lite/", {"params": {"q": query}}),
    ]
    errors = []

    for method, url, kwargs in endpoints:
        try:
            async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=12.0) as client:
                resp = await client.request(method, url, **kwargs)
                resp.raise_for_status()
            results = _parse_duckduckgo_results(resp.text)
            if results:
                return results
        except Exception as e:
            errors.append(f"{url}: {e}")
            logger.warning("Search provider failed for %s: %s", url, e)

    detail = "; ".join(errors)[:500] or "No parseable results returned"
    return [{"title": "Search failed", "url": "", "snippet": detail}]


def _parse_duckduckgo_results(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for r in soup.select(".result")[:6]:
        title_el = r.select_one(".result__title a")
        snippet_el = r.select_one(".result__snippet")
        if title_el:
            results.append({
                "title": title_el.get_text(strip=True),
                "url": _unwrap_duckduckgo_url(title_el.get("href", "")),
                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
            })

    if results:
        return results

    rows = soup.select("tr")
    for index, row in enumerate(rows):
        link = row.select_one("a.result-link, a[href]")
        if not link:
            continue
        href = _unwrap_duckduckgo_url(link.get("href", ""))
        if not href.startswith(("http://", "https://")):
            continue
        snippet = ""
        for sibling in rows[index + 1:index + 3]:
            text = sibling.get_text(" ", strip=True)
            if text and text != link.get_text(strip=True):
                snippet = text
                break
        results.append({
            "title": link.get_text(strip=True),
            "url": href,
            "snippet": snippet,
        })
        if len(results) >= 6:
            break

    return results


def _unwrap_duckduckgo_url(href: str) -> str:
    if "uddg=" not in href:
        return href
    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
    return parsed.get("uddg", [href])[0]


async def _legacy_search_web(query: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=10.0) as client:
            resp = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
            )
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for r in soup.select(".result")[:6]:
            title_el = r.select_one(".result__title a")
            snippet_el = r.select_one(".result__snippet")
            if title_el:
                href = title_el.get("href", "")
                # DuckDuckGo wraps URLs — extract real URL
                if "uddg=" in href:
                    import urllib.parse
                    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                    href = parsed.get("uddg", [href])[0]
                results.append({
                    "title": title_el.get_text(strip=True),
                    "url": href,
                    "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                })
        return results or [{"title": "No results", "url": "", "snippet": ""}]
    except Exception as e:
        logger.error(f"Search error: {e}")
        return [{"title": "Search failed", "url": "", "snippet": str(e)}]
