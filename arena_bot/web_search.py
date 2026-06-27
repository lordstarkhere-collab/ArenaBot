import logging
from duckduckgo_search import DDGS

logger = logging.getLogger("arenabot")

# Always append this so results are Mech Arena specific
SITE_HINT = "Mech Arena"

# Keywords that signal the user wants current / live info
REALTIME_TRIGGERS = [
    "current meta", "best right now", "latest", "new mech", "new weapon",
    "update", "patch", "season", "tier list", "top mechs", "top weapons",
    "2024", "2025", "2026", "right now", "nowadays", "this season",
]


def needs_web_search(question: str) -> bool:
    q = question.lower()
    return any(t in q for t in REALTIME_TRIGGERS)


def search(question: str, max_results: int = 3) -> list[str]:
    """
    Search DuckDuckGo for Mech Arena info.
    Returns a list of result snippets (title + body).
    """
    query = f"{SITE_HINT} {question}"
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                title = r.get("title", "")
                body = r.get("body", "")
                href = r.get("href", "")
                snippet = f"{title}\n{body}\nSource: {href}"
                results.append(snippet)
        logger.info(f"[WEB] Found {len(results)} results for: {question[:60]!r}")
    except Exception as e:
        logger.warning(f"[WEB] DuckDuckGo search failed: {e}")
    return results
