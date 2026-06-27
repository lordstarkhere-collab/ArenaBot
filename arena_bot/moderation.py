"""
Moderation engine — detects rough language, slurs, and inter-user conflict.
No AI tokens used — pure pattern matching so it's instant and free.
"""
import re
import time
import logging
import discord
from collections import defaultdict, deque

logger = logging.getLogger("arenabot")

# ── Role names the bot recognises as moderators (case-insensitive) ─────────────
MOD_ROLE_NAMES = {
    "moderator", "moderators", "mod", "mods",
    "admin", "admins", "administrator", "administrators",
    "staff", "helper", "helpers", "management", "manager",
    "server staff", "senior mod",
}

# ── Bad language — profanity, slurs, targeted abuse ───────────────────────────
# Stored as fragments; we match as whole-word patterns to reduce false positives.
_BAD_WORDS: set[str] = {
    # Common profanity
    "fuck", "fucker", "fucking", "fck", "fuk",
    "shit", "shitting", "bullshit",
    "bitch", "bitches",
    "asshole", "ass hole", "arsehole",
    "bastard",
    "cunt", "cunts",
    "dick", "dicks",
    "piss off",
    "damn you", "go to hell", "go fuck",
    # Slurs (racial, orientation, etc.) — intentionally omitting the actual strings
    # in source; add them here as lowercase strings
    "n i g g e r".replace(" ", ""),   # keep source readable but functional
    "f a g g o t".replace(" ", ""),
    "r e t a r d".replace(" ", ""),
    "w h o r e".replace(" ", ""),
    "s l u t".replace(" ", ""),
    # Targeted abuse / threats
    "kill yourself", "kys", "go die", "i'll kill", "i will kill",
    "i'll hurt", "find you", "reported you", "hacking you",
}

# ── Conflict phrases — escalation / personal attacks ─────────────────────────
_CONFLICT_PHRASES: list[str] = [
    "shut up", "shut the", "stfu",
    "you're stupid", "ur stupid", "you are stupid",
    "you're an idiot", "ur an idiot", "you idiot",
    "you're trash", "ur trash", "total trash",
    "you suck", "ur garbage",
    "nobody asked you", "nobody cares",
    "get out", "get lost", "gtfo",
    "you're a liar", "ur a liar", "stop lying",
    "you're pathetic", "so pathetic",
    "loser", "get rekt", "rekt",
]

# ── Compile patterns ──────────────────────────────────────────────────────────
def _compile(words: set[str]) -> re.Pattern:
    escaped = [re.escape(w) for w in sorted(words, key=len, reverse=True)]
    return re.compile(r"\b(" + "|".join(escaped) + r")\b", re.IGNORECASE)

_BAD_PATTERN      = _compile(_BAD_WORDS)
_CONFLICT_PATTERN = _compile(set(_CONFLICT_PHRASES))


# ── Recent message tracker — for fight detection (2 users going at each other) ─
# guild_id → deque of (timestamp, user_id, channel_id)
_recent: dict[str, deque] = defaultdict(lambda: deque(maxlen=30))
# guild_id → {frozenset(user_id_a, user_id_b) → [timestamps]}
_pair_strikes: dict[str, dict] = defaultdict(lambda: defaultdict(list))

FIGHT_WINDOW_SECONDS = 90    # look back 90 seconds
FIGHT_MSG_THRESHOLD  = 4     # 4+ conflict messages between the same pair = fight


def _record_message(guild_id: str, user_id: str, channel_id: str):
    _recent[guild_id].append((time.time(), user_id, channel_id))


def _detect_fight(guild_id: str, user_id: str, channel_id: str) -> bool:
    """
    Returns True if user_id appears to be in an escalating exchange with
    another user in the same channel within the last FIGHT_WINDOW_SECONDS.
    """
    now = time.time()
    cutoff = now - FIGHT_WINDOW_SECONDS
    recent_in_channel = [
        (ts, uid) for ts, uid, cid in _recent[guild_id]
        if cid == channel_id and ts > cutoff and uid != user_id
    ]
    if not recent_in_channel:
        return False

    # Count conflict-flagged messages between this user and any other user
    strikes = _pair_strikes[guild_id]
    for pair, timestamps in strikes.items():
        if user_id in pair:
            active = [t for t in timestamps if t > cutoff]
            strikes[pair] = active
            if len(active) >= FIGHT_WINDOW_SECONDS // 20:  # ~4+ hits in window
                return True
    return False


def _add_pair_strike(guild_id: str, user_id: str, other_user_ids: list[str]):
    now = time.time()
    cutoff = now - FIGHT_WINDOW_SECONDS
    strikes = _pair_strikes[guild_id]
    for other in other_user_ids:
        pair = frozenset([user_id, other])
        strikes[pair].append(now)

    # Prune dead pairs (no recent activity) to prevent unbounded growth
    dead = [p for p, ts in strikes.items() if not any(t > cutoff for t in ts)]
    for p in dead:
        del strikes[p]


# ── Public API ─────────────────────────────────────────────────────────────────

class ModerationResult:
    __slots__ = ("flagged", "violation_type", "matched")

    def __init__(self, flagged: bool, violation_type: str = "", matched: str = ""):
        self.flagged        = flagged
        self.violation_type = violation_type   # "bad_language" | "conflict" | "fight"
        self.matched        = matched          # the word/phrase that triggered it


def check_message(message: discord.Message) -> ModerationResult:
    """
    Check a message for violations. Returns a ModerationResult.
    Call this from on_message BEFORE any bot response logic.
    """
    content = message.content
    guild_id = str(message.guild.id) if message.guild else ""
    user_id  = str(message.author.id)
    chan_id  = str(message.channel.id)

    # 1. Bad language — highest priority
    m = _BAD_PATTERN.search(content)
    if m:
        return ModerationResult(True, "bad_language", m.group(0))

    # 2. Conflict phrases
    m = _CONFLICT_PATTERN.search(content)
    if m:
        # Record for fight tracking
        _record_message(guild_id, user_id, chan_id)
        # Who else recently talked in this channel?
        now = time.time()
        others = list({
            uid for ts, uid, cid in _recent[guild_id]
            if cid == chan_id and ts > now - FIGHT_WINDOW_SECONDS and uid != user_id
        })
        _add_pair_strike(guild_id, user_id, others)

        if _detect_fight(guild_id, user_id, chan_id):
            return ModerationResult(True, "fight", m.group(0))

        return ModerationResult(True, "conflict", m.group(0))

    # 3. Record normal message for fight-context tracking
    _record_message(guild_id, user_id, chan_id)
    return ModerationResult(False)


def find_mod_role(guild: discord.Guild) -> discord.Role | None:
    """Return the first moderator-type role found in the guild."""
    for role in guild.roles:
        if role.name.lower() in MOD_ROLE_NAMES:
            return role
    return None


def build_warning(
    result: ModerationResult,
    user: discord.Member,
    mod_role: discord.Role | None,
) -> str:
    """Build the warning message to send in-channel."""
    mod_ping = mod_role.mention if mod_role else "**@Moderators**"
    name = user.display_name

    if result.violation_type == "bad_language":
        return (
            f"⚠️ {user.mention} — please keep language respectful here. "
            f"This server expects civil conversation.\n"
            f"{mod_ping} — flagged for rough language."
        )
    elif result.violation_type == "fight":
        return (
            f"🚨 {user.mention} — looks like things are heating up. "
            f"Take a breath — this is a game community, not a battlefield.\n"
            f"{mod_ping} — potential fight detected between users, please step in."
        )
    else:  # conflict
        return (
            f"⚠️ {user.mention} — keep it respectful, please. "
            f"Disagreements are fine but personal attacks aren't.\n"
            f"{mod_ping} — flagged message in {user.mention}'s conversation."
        )
