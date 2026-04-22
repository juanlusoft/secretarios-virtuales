from __future__ import annotations

import re

import httpx

_DDG_URL = "https://html.duckduckgo.com/html/"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; secretarios-virtuales/1.0)",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}
_MAX_RESULTS = 5


class DuckDuckGoClient:
    async def search(self, query: str, max_results: int = _MAX_RESULTS) -> str:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.post(_DDG_URL, data={"q": query}, headers=_HEADERS)
        if resp.status_code != 200:
            return f"Error buscando '{query}': HTTP {resp.status_code}"

        results = _parse_ddg_html(resp.text, max_results)
        if not results:
            return f"Sin resultados para '{query}'."
        lines = [f"Resultados para '{query}':"]
        for i, (title, snippet, url) in enumerate(results, 1):
            lines.append(f"\n{i}. **{title}**\n{snippet}\n🔗 {url}")
        return "\n".join(lines)


def _parse_ddg_html(html: str, max_results: int) -> list[tuple[str, str, str]]:
    results = []
    title_pattern = re.compile(r'class="result__title"[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
    snippet_pattern = re.compile(r'class="result__snippet"[^>]*>(.*?)</span>', re.DOTALL)

    titles = title_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for (url, raw_title), raw_snippet in zip(titles[:max_results], snippets[:max_results]):
        title = re.sub(r"<[^>]+>", "", raw_title).strip()
        snippet = re.sub(r"<[^>]+>", "", raw_snippet).strip()
        results.append((title, snippet, url))
    return results
