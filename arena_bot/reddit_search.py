import logging
import requests

logger = logging.getLogger("arenabot")

SUBREDDIT = "MechArena"
HEADERS = {"User-Agent": "ArenaBot/1.0 (Discord Mech Arena assistant)"}

META_TRIGGERS = [
    "meta", "tier list", "tier", "best mech", "best weapon", "best pilot",
    "top mech", "top weapon", "op mech", "strongest", "right now", "currently",
    "this season", "update", "patch", "new mech", "new weapon", "nerf", "buff",
    "latest", "2024", "2025", "2026", "recommend", "what should i use",
    "beginner", "start with", "worth it",
]


def needs_reddit(question: str) -> bool:
    q = question.lower()
    return any(t in q for t in META_TRIGGERS)


def _post_to_text(post: dict) -> str:
    data = post.get("data", {})
    title = data.get("title", "")
    selftext = data.get("selftext", "").strip()
    score = data.get("score", 0)
    url = data.get("url", "")
    num_comments = data.get("num_comments", 0)

    text = f"**{title}** (score: {score}, comments: {num_comments})\n"
    if selftext and selftext != "[removed]" and selftext != "[deleted]":
        text += selftext[:500]
    text += f"\nLink: {url}"
    return text


def _top_comments(permalink: str, limit: int = 3) -> str:
    try:
        url = f"https://www.reddit.com{permalink}.json?limit={limit}&sort=top"
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        comments_data = data[1]["data"]["children"] if len(data) > 1 else []
        comments = []
        for c in comments_data:
            body = c.get("data", {}).get("body", "").strip()
            if body and body not in ("[removed]", "[deleted]") and len(body) > 20:
                comments.append(body[:300])
        return "\n".join(f"- {c}" for c in comments[:limit])
    except Exception:
        return ""


def search(question: str, post_limit: int = 5) -> list[str]:
    """
    Fetch top weekly posts from r/MechArena.
    Also grabs top comments from the most relevant post.
    Returns a list of text chunks for the AI context.
    """
    results = []

    # 1) Top posts this week
    try:
        url = f"https://www.reddit.com/r/{SUBREDDIT}/top.json?t=week&limit={post_limit}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        posts = resp.json()["data"]["children"]

        if not posts:
            logger.warning("[REDDIT] No posts found")
            return []

        # Filter to posts relevant to the question
        q_words = [w for w in question.lower().split() if len(w) > 3]
        scored = []
        for post in posts:
            title = post["data"].get("title", "").lower()
            body = post["data"].get("selftext", "").lower()
            score = sum(1 for w in q_words if w in title or w in body)
            scored.append((score, post))
        scored.sort(key=lambda x: x[0], reverse=True)

        # Top posts as text
        for _, post in scored[:3]:
            results.append(_post_to_text(post))

        # Top comments from best matching post
        best_post = scored[0][1] if scored else None
        if best_post:
            permalink = best_post["data"].get("permalink", "")
            if permalink:
                comments = _top_comments(permalink, limit=3)
                if comments:
                    results.append(f"Top community comments:\n{comments}")

        logger.info(f"[REDDIT] Fetched {len(results)} chunks from r/{SUBREDDIT}")

    except requests.exceptions.Timeout:
        logger.warning("[REDDIT] Request timed out")
    except Exception as e:
        logger.warning(f"[REDDIT] Failed: {e}")

    return results


def search_new(limit: int = 5) -> list[str]:
    """Fetch newest posts — useful for patch/update questions."""
    results = []
    try:
        url = f"https://www.reddit.com/r/{SUBREDDIT}/new.json?limit={limit}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        posts = resp.json()["data"]["children"]
        for post in posts[:3]:
            results.append(_post_to_text(post))
        logger.info(f"[REDDIT] Fetched {len(results)} new posts")
    except Exception as e:
        logger.warning(f"[REDDIT] new posts failed: {e}")
    return results
