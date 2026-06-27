import re
import logging
import knowledge_loader as kb

logger = logging.getLogger("arenabot")

MAX_CHUNK = 1800


def _trim(text: str, n: int = MAX_CHUNK) -> str:
    return text[:n] + "..." if len(text) > n else text


# ── Full-database relevance search ────────────────────────────────────────────

def _score_entry(entry: dict, q_words: list[str]) -> float:
    """Score a knowledge entry by keyword overlap (0 = no match)."""
    content_lower = entry["content"].lower()
    name_lower = entry.get("stem", entry.get("name", "")).lower()

    score = 0.0
    for word in q_words:
        count = content_lower.count(word)
        if count:
            score += 1 + min(count - 1, 3) * 0.2   # hit in content
        if word in name_lower:
            score += 3.0                              # hit in filename = big boost

    return score


def search_all(question: str, top_n: int = 8) -> list[tuple[float, dict]]:
    """Score every loaded entry against the question. Returns sorted (score, entry) list."""
    q_words = [w for w in re.sub(r"[^\w\s]", " ", question.lower()).split() if len(w) > 2]
    if not q_words:
        return []

    scored = []
    seen_stems = set()
    for category in kb.knowledge.values():
        for entry in category.values():
            stem = entry.get("stem", entry.get("file", ""))
            if stem in seen_stems:
                continue
            seen_stems.add(stem)
            s = _score_entry(entry, q_words)
            if s > 0:
                scored.append((s, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top_n]


# ── Targeted boosts (added ON TOP of full search, deduped) ───────────────────

def _boost_stems(question: str) -> list[str]:
    """Return DB stems that should always be added for this question type."""
    q = question.lower()
    boosts = []

    # Weapons
    if any(w in q for w in ["weapon", "gun", "rifle", "dps", "damage", "range", "cannon"]):
        boosts += ["weapons-top-dps", "weapons-by-base", "weapons-by-category", "weapon-range"]

    # Pilots
    if any(w in q for w in ["pilot", "driver"]):
        boosts += ["pilot-stats"]

    # Upgrade costs
    if any(w in q for w in ["upgrade", "level", "max out", "rank"]):
        boosts += ["costs-upgrades", "mech-upgrade-costs", "costs-upgrades-pilot", "implants-upgrades"]

    # Purchase / unlock
    if any(w in q for w in ["buy", "unlock", "cost", "price", "a-coin", "credit", "gearhub", "purchase"]):
        boosts += ["cost-purchases"]

    # Income / farming
    if any(w in q for w in ["farm", "earn", "income", "f2p", "free", "daily", "weekly", "grind"]):
        boosts += ["weekly-incomes"]

    # Implants
    if any(w in q for w in ["implant", "mod", "part", "implant upgrade"]):
        boosts += ["implants-parts", "implants-upgrades"]

    # Events / vaults
    if any(w in q for w in ["event", "vault", "key", "fortune"]):
        boosts += ["events-5key", "events-regular", "fortune-vaults"]

    # Shop
    if any(w in q for w in ["shop", "offer", "deal", "bundle", "pack"]):
        boosts += ["shop-offers"]

    # Awards
    if any(w in q for w in ["award", "achievement", "badge", "trophy"]):
        boosts += ["awards"]

    # Damage profiles
    if any(w in q for w in ["splash", "aoe", "indirect", "direct", "damage profile"]):
        boosts += ["damage-profiles"]

    # Calendar / schedule
    if any(w in q for w in ["calendar", "schedule", "rotation", "when"]):
        boosts += ["calendar", "events-regular"]

    # Bots
    if any(w in q for w in ["bot name", "bot list", "ai player", "bots"]):
        boosts += ["bots"]

    return boosts


# ── Main entry point ──────────────────────────────────────────────────────────

def fetch_context(question: str, max_chunks: int = 6) -> list[str]:
    """
    Always searches the FULL knowledge base by keyword relevance.
    Also injects targeted DB files for common query types.
    Returns up to max_chunks text blocks for the LLM context.
    """
    chunks: list[str] = []
    used_stems: set[str] = set()

    # 1) Full relevance search across every loaded entry
    top_results = search_all(question, top_n=max_chunks + 4)
    for score, entry in top_results:
        stem = entry.get("stem", entry.get("file", ""))
        if stem in used_stems:
            continue
        used_stems.add(stem)
        label = entry.get("stem", entry.get("name", "DATA"))
        chunks.append(f"[{label.upper()}]\n{_trim(entry['content'])}")
        if len(chunks) >= max_chunks:
            break

    # 2) Inject targeted boosts for well-known query patterns
    for stem in _boost_stems(question):
        if stem in used_stems:
            continue
        content = kb.get_db(stem)
        if not content:
            continue
        used_stems.add(stem)
        chunks.append(f"[{stem.upper()}]\n{_trim(content)}")
        if len(chunks) >= max_chunks + 2:   # allow a couple of extras for boosts
            break

    if not chunks:
        logger.warning(f"No context found for: {question!r}")

    logger.debug(f"Fetched {len(chunks)} context chunks for: {question!r}")
    return chunks
