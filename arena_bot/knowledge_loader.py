import os
import re
import logging
from pathlib import Path

logger = logging.getLogger("arenabot")

# Allow override via env var for Railway / Docker deployments
_env_dir = os.environ.get("KNOWLEDGE_DIR")
KNOWLEDGE_DIR = Path(_env_dir) if _env_dir else Path(__file__).parent.parent / "attached_assets" / "mech_data" / "knowledge"

SKIP_FILES = {
    "index.md", "by-category.md", "by-rarity.md", "by-energy.md",
    "unspecialized.md",
}

knowledge: dict[str, dict] = {
    "mechs": {},
    "pilots": {},
    "implants": {},
    "weapons_db": {},
    "overviews": {},
    "database": {},
}

mech_names: list[str] = []
pilot_names: list[str] = []
implant_names: list[str] = []
weapon_names: list[str] = []


def _slug(name: str) -> str:
    return name.lower().strip()


def _load_folder(folder: str, store: dict, skip: set[str] | None = None) -> list[str]:
    skip = skip or SKIP_FILES
    folder_path = KNOWLEDGE_DIR / folder
    loaded_names = []
    if not folder_path.exists():
        return loaded_names
    for f in sorted(folder_path.glob("*.md")):
        if f.name in skip:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        name = f.stem.replace("-", " ")
        store[_slug(name)] = {"name": name, "content": text, "file": str(f), "stem": f.stem}
        loaded_names.append(_slug(name))
    return loaded_names


def _extract_weapon_names_from_db(content: str) -> list[str]:
    names = []
    seen = set()
    for line in content.splitlines():
        m = re.match(r"\|\s*([A-Z][A-Za-z\s]+\d+)\s*\|", line)
        if m:
            n = m.group(1).strip().lower()
            if n not in seen:
                seen.add(n)
                names.append(n)
    return names


def load_all():
    global mech_names, pilot_names, implant_names, weapon_names

    logger.info("📚 Loading knowledge base from markdown files...")

    # --- Mechs: wiki pages ONLY (per user instruction) ---
    mech_names = _load_folder("mechs", knowledge["mechs"])
    logger.info(f"  ✅ Mechs: {len(knowledge['mechs'])} wiki pages loaded")

    # --- Pilots: wiki pages ---
    pilot_names = _load_folder("pilots", knowledge["pilots"])
    logger.info(f"  ✅ Pilots: {len(knowledge['pilots'])} wiki pages loaded")

    # --- Implants: wiki extracted pages ---
    implant_skip = SKIP_FILES.copy()
    implant_names = _load_folder("implants", knowledge["implants"], skip=implant_skip)
    logger.info(f"  ✅ Implants: {len(knowledge['implants'])} entries loaded")

    # --- Overviews ---
    _load_folder("overviews", knowledge["overviews"], skip={"index.md"})
    logger.info(f"  ✅ Overviews: {len(knowledge['overviews'])} pages loaded")

    # --- ALL database (spreadsheet) files ---
    db_skip = {"index.md", "weapon-dps-detail.md", "weapon-dps-calc.md"}
    db_path = KNOWLEDGE_DIR / "database"
    if db_path.exists():
        for f in sorted(db_path.glob("*.md")):
            if f.name in db_skip:
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            knowledge["database"][f.stem] = {
                "name": f.name,
                "content": text,
                "file": str(f),
                "stem": f.stem,
            }
            if "weapon" in f.stem:
                weapon_names.extend(_extract_weapon_names_from_db(text))

    weapon_names = list(dict.fromkeys(weapon_names))
    logger.info(f"  ✅ Database files: {len(knowledge['database'])} files loaded")
    logger.info(f"  ✅ Weapon variants indexed: {len(weapon_names)}")

    total = sum(len(v) for v in knowledge.values())
    logger.info(f"✅ Knowledge base fully loaded — {total} total entries")


# ── Accessors ─────────────────────────────────────────────────────────────────

def get_mech(name: str) -> str | None:
    key = _slug(name)
    entry = knowledge["mechs"].get(key)
    return entry["content"] if entry else None


def get_pilot(name: str) -> str | None:
    key = _slug(name)
    entry = knowledge["pilots"].get(key)
    return entry["content"] if entry else None


def get_implant(name: str) -> str | None:
    key = _slug(name)
    for stored_key, entry in knowledge["implants"].items():
        if key in stored_key or stored_key in key:
            return entry["content"]
    return None


def get_db(stem: str) -> str | None:
    entry = knowledge["database"].get(stem)
    return entry["content"] if entry else None


def get_overview(name: str) -> str | None:
    key = _slug(name)
    entry = knowledge["overviews"].get(key)
    return entry["content"] if entry else None


def fuzzy_match_mech(query: str) -> list[str]:
    q = query.lower()
    return [n for n in mech_names if n in q or q in n]


def fuzzy_match_pilot(query: str) -> list[str]:
    q = query.lower()
    return [n for n in pilot_names if n in q or q in n]


def fuzzy_match_weapon(query: str) -> list[str]:
    q = query.lower()
    return [n for n in weapon_names if n in q or q in n]


def keyword_search_all(query: str, max_results: int = 3) -> list[str]:
    """Fallback: score every loaded entry by keyword overlap."""
    q_words = [w for w in query.lower().split() if len(w) > 3]
    if not q_words:
        return []

    scored = []
    seen_files: set[str] = set()

    for category in knowledge.values():
        for entry in category.values():
            file_path = entry["file"]
            # Skip files already scored to prevent double-counting across categories
            if file_path in seen_files:
                continue
            seen_files.add(file_path)
            content_lower = entry["content"].lower()
            score = sum(1 for w in q_words if w in content_lower)
            if score > 0:
                scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [entry["content"][:2000] for _, entry in scored[:max_results]]
