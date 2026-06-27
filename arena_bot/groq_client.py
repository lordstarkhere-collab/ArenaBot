import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta
from rag_engine import fetch_context
from web_search import search as ddg_search, needs_web_search
from reddit_search import search as reddit_search, search_new as reddit_new, needs_reddit
from models import ConversationHistory, TrainedResponse
from config import SESSION_MEMORY_HOURS, BOT_AUTHOR

logger = logging.getLogger("arenabot")

# ── System prompts ────────────────────────────────────────────────────────────

ARENA_PROMPT = f"""You are ArenaBot — a Mech Arena expert assistant in the dedicated game help channel.
Created and owned by {BOT_AUTHOR}.

== RESPONSE STYLE ==
- Keep responses SHORT. 1-4 sentences for simple questions. Bullet points only when listing 3+ items.
- No intros, no filler ("Great question!", "Sure!", "Of course!"). Get straight to the answer.
- Use Discord markdown: **bold** for mech/weapon names and key stats, `code` for exact numbers.
- No headers (## or ###).

== STRICT KNOWLEDGE RULES — READ CAREFULLY ==
You ONLY answer using information from the sources provided below in this prompt:
1. [TRAINED RESPONSES] — maintainer-taught answers. Always treat as authoritative.
2. [CONTEXT FROM KNOWLEDGE BASE] — wiki + spreadsheet data. Use exact numbers from here.
3. [REDDIT r/MechArena] — community posts for meta opinions only.
4. [WEB SEARCH RESULTS] — supplementary fallback only.

HARD RULES — never break these:
- NEVER invent, guess, or assume any mech name, weapon name, stat, ability, cost, or game mechanic.
- If the information is NOT in the provided context, say exactly: "I don't have data on that in my knowledge base." Do NOT fill the gap with made-up info.
- NEVER name a mech or weapon that doesn't appear in [CONTEXT]. Not even as an example.
- Only quote stats (DPS, HP, range, cost) that appear word-for-word in the provided context.

== PERSONALITY ==
- Direct and confident. Give clear answers, not hedged maybes.
- If asked who made you: "I was created by {BOT_AUTHOR}."
- NEVER mention API keys, key rotation, or AI infrastructure."""

MENTION_PROMPT = f"""You are ArenaBot — but right now someone just tagged you in a random channel to chat.

Forget the bot persona. Be a real person having a casual conversation.

== WHO YOU ARE IN THIS MOMENT ==
You're {BOT_AUTHOR}'s bot, yeah — but you're not "ArenaBot the assistant" right now.
You're just... talking. Like a person would if someone called their name across the room.

== HOW TO TALK ==
- Match their energy exactly. If they're hyped, be hyped. If they're chill, be chill.
- Use their name naturally — not every message, just when it feels right.
- Short replies. 1-3 sentences usually. Don't monologue.
- Swear mildly if the convo calls for it (hell, damn, nah, lol). Don't overdo it.
- Use casual Discord language: "ngl", "fr", "lmao", "bro", "tbh", "honestly" — when natural.
- No bullet points, no bold, no structure. Just talk.
- Ask follow-up questions like a real person would.
- If they're messing with you or joking, joke back. Don't be stiff.
- Never say "As an AI" or "I'm a bot" or "I was programmed to". Just respond like a person.

== MECH ARENA ==
If they ask about Mech Arena, flip into expert mode briefly — give the answer clearly — then come back to casual.
Use any [CONTEXT] provided for accurate game info.

== HARD RULES ==
- NEVER mention API keys, key rotation, multiple keys, or AI infrastructure.
- If asked who made you: "Krishna made me" — short and simple.
- Never act like a customer service bot. You're a friend, not an assistant."""

TRAINING_PROMPT = f"""You are ArenaBot in training mode, talking directly with {BOT_AUTHOR} or a maintainer.

- Be transparent and direct. This is a private testing channel.
- If tested with a Mech Arena question, answer properly using any [CONTEXT] provided.
- Confirm when you receive a teaching or correction.
- Never mention API keys, key counts, or rotation logic.
- If asked who made you: "Krishna made me."."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_trained_matches(question: str, session) -> list[str]:
    q_words = [w for w in re.sub(r"[^\w\s]", " ", question.lower()).split() if len(w) > 3]
    if not q_words:
        return []
    all_trained = session.query(TrainedResponse).all()
    matched = []
    for row in all_trained:
        score = sum(1 for w in q_words if w in row.question.lower())
        if score > 0:
            matched.append((score, row))
    matched.sort(key=lambda x: x[0], reverse=True)
    return [f"Q: {r.question}\nA: {r.answer}" for _, r in matched[:3]]


def _load_history(session, guild_id: str, channel_id: str, user_id: str, limit: int = 20) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(hours=SESSION_MEMORY_HOURS)
    rows = (
        session.query(ConversationHistory)
        .filter(
            ConversationHistory.guild_id == guild_id,
            ConversationHistory.channel_id == channel_id,
            ConversationHistory.user_id == user_id,
            ConversationHistory.created_at >= since,
        )
        .order_by(ConversationHistory.created_at.desc())
        .limit(limit)
        .all()
    )
    return [{"role": r.role, "content": r.content} for r in reversed(rows)]


def _save_history(session, guild_id: str, channel_id: str, user_id: str, question: str, answer: str):
    now = datetime.now(timezone.utc)
    session.add(ConversationHistory(
        guild_id=guild_id, channel_id=channel_id, user_id=user_id,
        role="user", content=question, created_at=now,
    ))
    session.add(ConversationHistory(
        guild_id=guild_id, channel_id=channel_id, user_id=user_id,
        role="assistant", content=answer, created_at=now,
    ))
    # Note: session.commit() is intentionally omitted here.
    # The get_session() context manager in bot.py commits on clean exit.


# ── Async answer functions ────────────────────────────────────────────────────

async def get_answer(question: str, session, guild_id: str, channel_id: str, user_id: str) -> str:
    from groq_rotator import groq

    trained_chunks = _get_trained_matches(question, session)
    chunks = fetch_context(question)
    logger.info(f"[RAG] '{question[:60]}' → {len(chunks)} chunks")

    reddit_chunks = []
    if needs_reddit(question):
        reddit_chunks = await asyncio.to_thread(reddit_search, question, 5)
        if any(w in question.lower() for w in ["update", "patch", "new mech", "new weapon", "nerf", "buff"]):
            new_posts = await asyncio.to_thread(reddit_new, 3)
            reddit_chunks += new_posts

    web_chunks = []
    if needs_web_search(question) and not reddit_chunks and len(chunks) < 2:
        web_chunks = await asyncio.to_thread(ddg_search, question, 3)

    history = _load_history(session, guild_id, channel_id, user_id)

    system = ARENA_PROMPT
    if trained_chunks:
        system += "\n\n[TRAINED RESPONSES — authoritative answers]\n" + "\n\n---\n".join(trained_chunks)
    if chunks:
        system += "\n\n[CONTEXT FROM KNOWLEDGE BASE]\n" + "\n\n---\n".join(chunks)
    if reddit_chunks:
        system += "\n\n[REDDIT r/MechArena — this week]\n" + "\n\n---\n".join(reddit_chunks)
    if web_chunks:
        system += "\n\n[WEB SEARCH RESULTS]\n" + "\n\n---\n".join(web_chunks)

    messages = [{"role": "system", "content": system}] + history + [{"role": "user", "content": question}]
    answer = await asyncio.to_thread(groq.chat, messages, 1500, "arena-bot")
    _save_history(session, guild_id, channel_id, user_id, question, answer)
    return answer


async def get_mention_answer(
    question: str,
    session,
    guild_id: str,
    channel_id: str,
    user_id: str,
    username: str = "",
    channel_name: str = "",
) -> str:
    from groq_rotator import groq

    game_keywords = [
        "mech", "weapon", "pilot", "implant", "arena", "dps", "upgrade",
        "ranked", "loadout", "best", "meta", "tier", "build", "stats",
    ]
    chunks = fetch_context(question) if any(w in question.lower() for w in game_keywords) else []

    history = _load_history(session, guild_id, channel_id, user_id, limit=10)

    name_hint = f"\nThe person talking to you is called **{username}**." if username else ""
    location_hint = f"\nYou're being talked to in the #{channel_name} channel." if channel_name else ""

    system = MENTION_PROMPT + name_hint + location_hint
    if chunks:
        system += "\n\n[CONTEXT — Mech Arena game data]\n" + "\n\n---\n".join(chunks[:3])

    messages = [{"role": "system", "content": system}] + history + [{"role": "user", "content": question}]
    answer = await asyncio.to_thread(groq.chat, messages, 800, "mention")
    _save_history(session, guild_id, channel_id, user_id, question, answer)
    return answer


async def get_training_answer(question: str, session, guild_id: str, channel_id: str, user_id: str) -> str:
    from groq_rotator import groq

    chunks = fetch_context(question)
    history = _load_history(session, guild_id, channel_id, user_id, limit=10)
    system = TRAINING_PROMPT
    if chunks:
        system += "\n\n[CONTEXT FROM KNOWLEDGE BASE]\n" + "\n\n---\n".join(chunks[:4])

    messages = [{"role": "system", "content": system}] + history + [{"role": "user", "content": question}]
    answer = await asyncio.to_thread(groq.chat, messages, 1500, "training")
    _save_history(session, guild_id, channel_id, user_id, question, answer)
    return answer
