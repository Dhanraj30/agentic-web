"""
Scraper Tool — AgenticWeb
Fast HTTP scraping (no browser needed) + DuckDuckGo web search.
"""
from __future__ import annotations
import logging
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
