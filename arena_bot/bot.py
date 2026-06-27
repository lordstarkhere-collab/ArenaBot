import re
import time
import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands
from database import get_session
from models import GuildSettings, TrainedResponse
from groq_client import get_answer, get_mention_answer, get_training_answer
from config import PRIVILEGED_IDS, OWNER_ID, BOT_AUTHOR, BOT_CHANNEL_NAME, TRAINING_CHANNEL_NAME
from moderation import check_message, find_mod_role, build_warning

logger = logging.getLogger("arenabot")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

COOLDOWN_SECONDS = 8
_cooldowns: dict[str, float] = {}
_COOLDOWN_PRUNE_EVERY = 500   # prune stale entries every N messages
_msg_counter = 0


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_privileged(user_id: str) -> bool:
    return user_id in PRIVILEGED_IDS


async def _get_bot_channel_id(guild_id: str) -> str | None:
    with get_session() as session:
        settings = session.query(GuildSettings).filter_by(guild_id=guild_id).first()
        return settings.bot_channel_id if settings else None


async def _get_training_channel_id(guild_id: str) -> str | None:
    with get_session() as session:
        settings = session.query(GuildSettings).filter_by(guild_id=guild_id).first()
        return settings.training_channel_id if settings else None


# ── Channel setup ─────────────────────────────────────────────────────────────

async def setup_bot_channel(guild: discord.Guild):
    """Create or find #arena-bot and #arena-training."""
    with get_session() as session:
        settings = session.query(GuildSettings).filter_by(guild_id=str(guild.id)).first()
        existing_bot_id = settings.bot_channel_id if settings else None
        existing_train_id = settings.training_channel_id if settings else None

    # ── #arena-bot ──
    bot_channel = guild.get_channel(int(existing_bot_id)) if existing_bot_id else None
    if not bot_channel:
        bot_channel = discord.utils.get(guild.text_channels, name=BOT_CHANNEL_NAME)
    if not bot_channel:
        try:
            bot_channel = await guild.create_text_channel(
                name=BOT_CHANNEL_NAME,
                topic="Chat with ArenaBot! Ask anything about Mech Arena — just type naturally.",
                reason="ArenaBot — Mech Arena AI assistant channel",
            )
            logger.info(f"Created #{BOT_CHANNEL_NAME} in {guild.name}")
            await _send_welcome(bot_channel)
        except discord.Forbidden:
            logger.warning(f"No permission to create #{BOT_CHANNEL_NAME} in {guild.name}")
    else:
        logger.info(f"✅ #{bot_channel.name} already exists in {guild.name}")

    # ── #arena-training (maintainer-only) ──
    train_channel = guild.get_channel(int(existing_train_id)) if existing_train_id else None
    if not train_channel:
        train_channel = discord.utils.get(guild.text_channels, name=TRAINING_CHANNEL_NAME)
    if not train_channel:
        try:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }
            for uid in PRIVILEGED_IDS:
                member = guild.get_member(int(uid))
                if member:
                    overwrites[member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

            train_channel = await guild.create_text_channel(
                name=TRAINING_CHANNEL_NAME,
                topic="Private channel for bot maintainers. Train and test ArenaBot here.",
                overwrites=overwrites,
                reason="ArenaBot — private maintainer training channel",
            )
            logger.info(f"Created #{TRAINING_CHANNEL_NAME} in {guild.name}")
            await train_channel.send(
                f"**ArenaBot Training Channel** — created by **{BOT_AUTHOR}**\n\n"
                "Only maintainers can see this channel.\n\n"
                "**How to train the bot:**\n"
                "- Use `/learn` to teach a specific Q&A pair\n"
                "- Use `/forget` to remove an entry\n"
                "- Use `/trained` to see all entries\n"
                "- Use `/status` to check AI engine health\n"
                "- Type anything here to test how the bot responds\n\n"
                "The bot reads and responds to every message in this channel."
            )
        except discord.Forbidden:
            logger.warning(f"No permission to create #{TRAINING_CHANNEL_NAME} in {guild.name}")
    else:
        logger.info(f"✅ #{train_channel.name} already exists in {guild.name}")

    # Save both channel IDs
    with get_session() as session:
        settings = session.query(GuildSettings).filter_by(guild_id=str(guild.id)).first()
        if not settings:
            settings = GuildSettings(guild_id=str(guild.id), guild_name=guild.name)
            session.add(settings)
        if bot_channel:
            settings.bot_channel_id = str(bot_channel.id)
        if train_channel:
            settings.training_channel_id = str(train_channel.id)
        settings.guild_name = guild.name
        session.commit()


async def _send_welcome(channel: discord.TextChannel):
    embed = discord.Embed(
        title="ArenaBot is ready!",
        description=(
            f"Your **Mech Arena expert AI**. Created by **{BOT_AUTHOR}**.\n\n"
            "Just **type anything** here and I'll answer!\n\n"
            "**I know about:**\n"
            "- Every mech — stats, abilities, upgrades, implants\n"
            "- Every weapon — DPS, range, best pairings\n"
            "- Every pilot — abilities, best mechs to pair\n"
            "- All currencies — how to earn and spend efficiently\n"
            "- Current meta (via Reddit r/MechArena)\n\n"
            "**Example questions:**\n"
            "*\"What's the best mech for ranked?\"*\n"
            "*\"How do I counter Juggernaut?\"*\n"
            "*\"Best loadout for Panther?\"*\n"
            "*\"What's the current meta?\"*\n\n"
            "You can also **@mention me** in any channel to chat!"
        ),
        color=0x00BFFF,
    )
    embed.set_footer(text=f"Created by {BOT_AUTHOR} | Powered by Groq AI (llama-3.3-70b)")
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        pass


# ── Events ────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    logger.info(f"✅ ArenaBot online as {bot.user} (ID: {bot.user.id})")
    try:
        await tree.sync()
        logger.info("Slash commands synced")
    except Exception as e:
        logger.warning(f"Slash command sync failed: {e}")
    for guild in bot.guilds:
        await setup_bot_channel(guild)
    logger.info(f"ArenaBot ready in {len(bot.guilds)} server(s)")


@bot.event
async def on_guild_join(guild: discord.Guild):
    logger.info(f"Joined new server: {guild.name} ({guild.id})")
    await setup_bot_channel(guild)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if not message.guild:
        return

    channel_id_str = str(message.channel.id)
    guild_id_str = str(message.guild.id)
    user_id_str = str(message.author.id)
    content = message.content.strip()

    if not content:
        return

    # ── Fetch stored channel IDs (needed by both owner fast-path and normal flow)
    with get_session() as session:
        settings = session.query(GuildSettings).filter_by(guild_id=guild_id_str).first()
        bot_channel_id = settings.bot_channel_id if settings else None
        training_channel_id = settings.training_channel_id if settings else None

    # ── Owner fast-path (Krishna) — no cooldown, no restrictions ─────────────
    if user_id_str == OWNER_ID:
        lower = content.lower()
        bot_mentioned = bot.user in message.mentions

        # ── Check if this is a repeat/ping command ─────────────────────────
        is_ping_cmd = bool(re.search(r'\b(?:ping|mention|tag)\b', lower))
        is_send_cmd = bool(re.search(r'\b(?:send|say|repeat|write)\b', lower))
        is_owner_cmd = is_ping_cmd or is_send_cmd

        if is_owner_cmd:
            # --- Parse count: "N times" OR "every N sec/min for X sec/min" ---
            interval_m = re.search(r'every\s+(\d+)\s*(sec(?:ond)?s?|min(?:ute)?s?)', lower)
            duration_m = re.search(r'for\s+(\d+)\s*(sec(?:ond)?s?|min(?:ute)?s?)', lower)
            times_m    = re.search(r'(\d+)\s*times?', lower)

            if interval_m and duration_m:
                iv = int(interval_m.group(1))
                iv_sec = iv * 60 if 'min' in interval_m.group(2) else iv
                iv_sec = max(1, iv_sec)
                dv = int(duration_m.group(1))
                dv_sec = dv * 60 if 'min' in duration_m.group(2) else dv
                count    = min(int(dv_sec / iv_sec), 200)
                interval = iv_sec
            elif times_m:
                count    = min(int(times_m.group(1)), 200)
                interval = 0.6
            else:
                count    = 1
                interval = 0.6

            # --- Resolve the target (Discord mention OR username) ---
            mention_in_msg = re.search(r'<@!?\d+>', content)
            if mention_in_msg:
                target = mention_in_msg.group(0)
            elif is_ping_cmd:
                # Try to find by username/display name
                name_m = re.search(r'\b(?:ping|mention|tag)\b\s+@?(\S+)', lower)
                if name_m:
                    uname = name_m.group(1).strip('.,!?')
                    member = discord.utils.find(
                        lambda m: m.name.lower() == uname or m.display_name.lower() == uname,
                        message.guild.members
                    )
                    target = f"<@{member.id}>" if member else f"@{uname}"
                else:
                    target = None
            else:
                # send/say/repeat — extract the message text
                send_m = re.search(
                    r'\b(?:send|say|repeat|write)\b\s+"?(.+?)"?\s*(?:\d+\s*times?|every\s|for\s|$)',
                    content, re.IGNORECASE
                )
                target = send_m.group(1).strip() if send_m else None

            if target:
                for i in range(count):
                    await message.channel.send(target)
                    if i < count - 1:
                        await asyncio.sleep(interval)
            return

        # ── Not a command — only reply via AI if in bot channel OR mentioned ──
        if not bot_mentioned and (not bot_channel_id or channel_id_str != bot_channel_id):
            # Owner is just chatting with someone else — stay silent
            await bot.process_commands(message)
            return

        async with message.channel.typing():
            try:
                if bot_channel_id and channel_id_str == bot_channel_id:
                    with get_session() as session:
                        answer = await get_answer(
                            question=content,
                            session=session,
                            guild_id=guild_id_str,
                            channel_id=channel_id_str,
                            user_id=user_id_str,
                        )
                else:
                    clean = content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip() or content
                    with get_session() as session:
                        answer = await get_mention_answer(
                            question=clean,
                            session=session,
                            guild_id=guild_id_str,
                            channel_id=channel_id_str,
                            user_id=user_id_str,
                            username=message.author.display_name,
                            channel_name=message.channel.name,
                        )
                if len(answer) <= 1900:
                    await message.reply(answer)
                else:
                    parts = [answer[i:i+1900] for i in range(0, len(answer), 1900)]
                    for i, part in enumerate(parts):
                        if i == 0:
                            await message.reply(part)
                        else:
                            await message.channel.send(part)
            except Exception as e:
                logger.error(f"[Owner fast-path] {e}", exc_info=True)
                await message.reply("Something went wrong, try again!")
        return

    # ── Prune stale cooldown entries every 500 messages ───────────────────────
    global _msg_counter
    _msg_counter += 1
    if _msg_counter % _COOLDOWN_PRUNE_EVERY == 0:
        now_prune = time.monotonic()
        stale = [uid for uid, ts in _cooldowns.items() if now_prune - ts > COOLDOWN_SECONDS * 10]
        for uid in stale:
            del _cooldowns[uid]

    # ── Moderation check — runs on every message, every channel ───────────────
    # Skip: training channel (privileged-only), privileged users themselves
    is_training = training_channel_id and channel_id_str == training_channel_id
    if not is_training and not is_privileged(user_id_str):
        result = check_message(message)
        if result.flagged:
            mod_role = find_mod_role(message.guild)
            warning = build_warning(result, message.author, mod_role)
            try:
                await message.channel.send(warning)
            except discord.Forbidden:
                pass
            logger.warning(
                f"[MOD] {message.author} ({user_id_str}) flagged "
                f"for {result.violation_type!r} — matched: {result.matched!r} "
                f"in #{message.channel.name} ({message.guild.name})"
            )
            return  # don't process bot reply for flagged messages

    # ── 1. Training channel — maintainers only ────────────────────────────────
    if training_channel_id and channel_id_str == training_channel_id:
        if not is_privileged(user_id_str):
            return

        lower = content.lower()
        if lower.startswith("remember:") or lower.startswith("teach:"):
            parts = content.split(":", 1)[1].strip().split("|", 1)
            if len(parts) == 2:
                q, a = parts[0].strip(), parts[1].strip()
                with get_session() as session:
                    row = TrainedResponse(
                        question=q, answer=a,
                        added_by_id=user_id_str,
                        added_by_name=str(message.author),
                    )
                    session.add(row)
                    session.commit()
                    row_id = row.id
                await message.reply(f"Got it! Saved as entry **#{row_id}**.\n**Q:** {q}\n**A:** {a}")
                return

        async with message.channel.typing():
            try:
                with get_session() as session:
                    answer = await get_training_answer(       # ← await (async)
                        question=content,
                        session=session,
                        guild_id=guild_id_str,
                        channel_id=channel_id_str,
                        user_id=user_id_str,
                    )
                await message.reply(answer)
            except Exception as e:
                logger.error(f"Training channel error: {e}", exc_info=True)
                await message.reply("Something went wrong. Try again!")
        return

    # ── 2. @mention in any channel ────────────────────────────────────────────
    bot_mentioned = bot.user in message.mentions
    if bot_mentioned and channel_id_str != bot_channel_id:
        clean = content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
        if not clean:
            clean = "Hey! What can you help me with?"

        now = time.monotonic()
        remaining = COOLDOWN_SECONDS - (now - _cooldowns.get(user_id_str, 0.0))
        if remaining > 0:
            try:
                await message.reply(f"Slow down! Try again in {remaining:.0f}s.", delete_after=remaining)
            except discord.HTTPException:
                pass
            return
        _cooldowns[user_id_str] = now

        async with message.channel.typing():
            try:
                with get_session() as session:
                    answer = await get_mention_answer(        # ← await (async)
                        question=clean,
                        session=session,
                        guild_id=guild_id_str,
                        channel_id=channel_id_str,
                        user_id=user_id_str,
                        username=message.author.display_name,
                        channel_name=message.channel.name,
                    )
                await message.reply(answer)
            except Exception as e:
                logger.error(f"Mention reply error: {e}", exc_info=True)
                await message.reply("Something went wrong, try again!")
        return

    # ── 3. #arena-bot channel — main game chat ────────────────────────────────
    if not bot_channel_id or channel_id_str != bot_channel_id:
        await bot.process_commands(message)
        return

    now = time.monotonic()
    remaining = COOLDOWN_SECONDS - (now - _cooldowns.get(user_id_str, 0.0))
    if remaining > 0:
        try:
            await message.reply(f"Please wait {remaining:.0f}s before sending another message.", delete_after=remaining)
        except discord.HTTPException:
            pass
        return
    _cooldowns[user_id_str] = now

    async with message.channel.typing():
        try:
            with get_session() as session:
                answer = await get_answer(                   # ← await (async)
                    question=content,
                    session=session,
                    guild_id=guild_id_str,
                    channel_id=channel_id_str,
                    user_id=user_id_str,
                )
            if len(answer) <= 1900:
                await message.reply(answer)
            else:
                parts = [answer[i:i + 1900] for i in range(0, len(answer), 1900)]
                for i, part in enumerate(parts):
                    if i == 0:
                        await message.reply(part)
                    else:
                        await message.channel.send(part)
        except RuntimeError:
            await message.reply("I'm temporarily busy — please try again in a moment!")
        except Exception as e:
            logger.error(f"Error from {message.author}: {e}", exc_info=True)
            await message.reply("Something went wrong. Try again!")


# ── Slash Commands ────────────────────────────────────────────────────────────

@tree.command(name="learn", description="[Maintainer] Teach the bot a Q&A pair")
@app_commands.describe(
    question="The question or topic trigger",
    answer="The answer the bot should give",
)
async def cmd_learn(interaction: discord.Interaction, question: str, answer: str):
    if not is_privileged(str(interaction.user.id)):
        await interaction.response.send_message("You don't have permission to train the bot.", ephemeral=True)
        return
    with get_session() as session:
        row = TrainedResponse(
            question=question, answer=answer,
            added_by_id=str(interaction.user.id),
            added_by_name=str(interaction.user),
        )
        session.add(row)
        session.commit()
        row_id = row.id
    logger.info(f"[TRAINED] #{row_id} added by {interaction.user}: {question[:60]}")
    await interaction.response.send_message(
        f"Learned! Entry **#{row_id}** saved.\n**Q:** {question}\n**A:** {answer}",
        ephemeral=True,
    )


@tree.command(name="forget", description="[Maintainer] Remove a trained response by ID")
@app_commands.describe(entry_id="ID number from /trained list")
async def cmd_forget(interaction: discord.Interaction, entry_id: int):
    if not is_privileged(str(interaction.user.id)):
        await interaction.response.send_message("You don't have permission to do that.", ephemeral=True)
        return
    with get_session() as session:
        row = session.query(TrainedResponse).filter_by(id=entry_id).first()
        if not row:
            await interaction.response.send_message(f"No entry with ID #{entry_id} found.", ephemeral=True)
            return
        preview = row.question[:60]
        session.delete(row)
        session.commit()
    logger.info(f"[TRAINED] #{entry_id} removed by {interaction.user}")
    await interaction.response.send_message(f"Removed entry **#{entry_id}**: \"{preview}\"", ephemeral=True)


@tree.command(name="trained", description="[Maintainer] List all trained Q&A responses")
async def cmd_trained(interaction: discord.Interaction):
    if not is_privileged(str(interaction.user.id)):
        await interaction.response.send_message("You don't have permission to view this.", ephemeral=True)
        return
    with get_session() as session:
        rows = session.query(TrainedResponse).order_by(TrainedResponse.created_at.desc()).all()
        data = [(r.id, r.question, r.answer, r.added_by_name) for r in rows]
    if not data:
        await interaction.response.send_message("No trained responses yet. Use `/learn` to add some.", ephemeral=True)
        return
    lines = [f"**#{rid}** Q: {q[:45]}... | A: {a[:45]}... | by {by}" for rid, q, a, by in data]
    text = "\n".join(lines)
    if len(text) > 1900:
        text = text[:1900] + "\n... (truncated)"
    await interaction.response.send_message(f"**Trained responses ({len(data)}):**\n{text}", ephemeral=True)


@tree.command(name="status", description="[Maintainer] Show AI engine health and usage stats")
async def cmd_status(interaction: discord.Interaction):
    if not is_privileged(str(interaction.user.id)):
        await interaction.response.send_message("You don't have permission to view this.", ephemeral=True)
        return

    from groq_rotator import groq
    import time as _time
    s = groq.status

    total        = s["total_tokens"]
    prompt       = s["total_prompt_tokens"]
    completion   = s["total_completion_tokens"]
    requests     = s["total_requests"]
    health       = s["health"]
    uptime       = s["uptime"]
    rate_hits    = s["rate_limit_hits"]
    src_tokens   = s["source_tokens"]    # {"arena-bot": N, "mention": N, "training": N}
    src_requests = s["source_requests"]
    recent       = s["recent_log"]       # list of last 5 dicts

    DAILY_CAPACITY = 500_000
    bar_filled = min(20, int((total / DAILY_CAPACITY) * 20))
    bar = "█" * bar_filled + "░" * (20 - bar_filled)
    pct = min(100, round((total / DAILY_CAPACITY) * 100, 1))

    color = 0x00FF88 if health == "Healthy" else (0xFFAA00 if "Reduced" in health else 0xFF4444)
    embed = discord.Embed(title="⚙️ ArenaBot — AI Engine Status", color=color)

    # ── Row 1: health / uptime / requests ──
    embed.add_field(name="Status",           value=f"**{health}**",    inline=True)
    embed.add_field(name="Uptime",           value=uptime,             inline=True)
    embed.add_field(name="Total Requests",   value=f"{requests:,}",    inline=True)

    # ── Row 2: token usage bar ──
    embed.add_field(
        name="Token Usage (since restart)",
        value=f"`{bar}` **{pct}%**\n`{total:,}` / `{DAILY_CAPACITY:,}` tokens",
        inline=False,
    )

    # ── Row 3: prompt / completion / throttles ──
    embed.add_field(name="Prompt Tokens",    value=f"{prompt:,}",      inline=True)
    embed.add_field(name="Response Tokens",  value=f"{completion:,}",  inline=True)
    embed.add_field(name="Throttle Events",  value=str(rate_hits),     inline=True)

    # ── Row 4: where tokens are being spent ──
    def src_line(key: str, label: str) -> str:
        t = src_tokens.get(key, 0)
        r = src_requests.get(key, 0)
        share = f"{round(t / total * 100)}%" if total else "0%"
        return f"**{label}** — {t:,} tokens · {r} msgs ({share})"

    embed.add_field(
        name="Where Tokens Are Used",
        value="\n".join([
            src_line("arena-bot", "📢 #arena-bot"),
            src_line("mention",   "💬 @mentions"),
            src_line("training",  "🔧 Training"),
        ]),
        inline=False,
    )

    # ── Row 5: last 5 message log ──
    if recent:
        source_icons = {"arena-bot": "📢", "mention": "💬", "training": "🔧"}
        now = _time.time()
        lines = []
        for entry in reversed(recent):
            ago_s = int(now - entry["timestamp"])
            if ago_s < 60:
                ago = f"{ago_s}s ago"
            elif ago_s < 3600:
                ago = f"{ago_s // 60}m ago"
            else:
                ago = f"{ago_s // 3600}h ago"
            icon = source_icons.get(entry["source"], "❓")
            lines.append(
                f"{icon} `{entry['total_tokens']}t` · {ago}\n"
                f"└ {entry['preview']}"
            )
        embed.add_field(
            name="Last 5 Requests",
            value="\n".join(lines),
            inline=False,
        )
    else:
        embed.add_field(name="Last 5 Requests", value="No requests yet since restart.", inline=False)

    embed.set_footer(text="Stats reset on restart • Maintainers only")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="about", description="About ArenaBot")
async def cmd_about(interaction: discord.Interaction):
    embed = discord.Embed(
        title="ArenaBot",
        description=(
            f"**Created by:** {BOT_AUTHOR}\n\n"
            "Your Mech Arena AI expert, powered by:\n"
            "- Local game database (wiki + community spreadsheets)\n"
            "- Reddit r/MechArena (live meta discussions)\n"
            "- Groq AI — llama-3.3-70b\n\n"
            f"Type in **#arena-bot** to ask anything, or **@mention me** anywhere!"
        ),
        color=0x00BFFF,
    )
    embed.set_footer(text=f"ArenaBot — Created by {BOT_AUTHOR}")
    await interaction.response.send_message(embed=embed)
