# ArenaBot

A Discord bot that serves as an expert AI assistant for the mobile game **Mech Arena**.  
Created and owned by **Krishna**.

---

## Features

- **Game knowledge** — 41 mechs (wiki data), 36 pilots, 49 implants, 166 weapon variants, all upgrade/purchase costs, events, fortune vaults, shop offers, and more — sourced from the community spreadsheet
- **Live meta** — pulls top weekly posts and comments from Reddit r/MechArena for current meta discussions
- **Web search fallback** — DuckDuckGo search for anything not in the local database
- **Conversational memory** — remembers your full conversation for 2 hours per session
- **Maintainer training** — owners/maintainers can teach the bot custom Q&A pairs via `/learn`
- **@mention anywhere** — mention the bot in any channel for natural human-like chat
- **Per-user cooldown** — 8 second cooldown to protect Groq API rate limits
- **Multi-server** — auto-creates `#arena-bot` and `#arena-training` on every server it joins

---

## Channels the bot creates automatically

| Channel | Purpose |
|---|---|
| `#arena-bot` | Public channel — anyone can ask questions |
| `#arena-training` | Private — maintainers/owner only. Train and test the bot |

---

## Slash Commands

| Command | Who | Description |
|---|---|---|
| `/learn question: … answer: …` | Maintainers + Owner | Teach the bot a Q&A pair |
| `/forget entry_id: …` | Maintainers + Owner | Remove a trained response by ID |
| `/trained` | Maintainers + Owner | List all trained responses |
| `/about` | Everyone | Show bot info and creator credit |

### Training channel shortcut
In `#arena-training`, maintainers can also type:
```
remember: what is the best mech | Panther is currently the top meta mech for ranked.
```
The bot will auto-save it and confirm.

---

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/your-username/arena-bot.git
cd arena-bot
```

### 2. Install dependencies
```bash
cd arena_bot
pip install -r requirements.txt
```

### 3. Set environment variables
Create a `.env` file (never commit this):
```
DISCORD_TOKEN=your_discord_bot_token
DISCORD_CLIENT_ID=your_discord_client_id
GROQ_API_KEY_1=your_first_groq_key
GROQ_API_KEY_2=your_second_groq_key
GROQ_API_KEY_3=your_third_groq_key
SESSION_SECRET=any_random_string
DATABASE_URL=your_postgres_connection_string
```

### 4. Configure owner & maintainers
Edit `arena_bot/config.py`:
```python
OWNER_ID = "your_discord_user_id"
MAINTAINER_IDS = ["maintainer1_id", "maintainer2_id"]
```

### 5. Run the bot
```bash
cd arena_bot
python main.py
```

---

## Project structure

```
arena_bot/
├── main.py              # Entry point — starts the bot
├── bot.py               # Discord event handlers and slash commands
├── config.py            # Owner/maintainer IDs and settings
├── groq_client.py       # Groq AI integration and prompt management
├── groq_rotator.py      # Rotates between 3 Groq API keys on rate limits
├── rag_engine.py        # Retrieval-Augmented Generation — searches knowledge base
├── knowledge_loader.py  # Loads all markdown/database files into memory
├── reddit_search.py     # Pulls top posts from r/MechArena
├── web_search.py        # DuckDuckGo fallback search
├── database.py          # SQLAlchemy DB connection and session management
├── models.py            # DB models: GuildSettings, ConversationHistory, TrainedResponse
└── requirements.txt     # Python dependencies

attached_assets/
└── mech_data/
    └── knowledge/
        ├── mechs/       # 41 individual mech wiki pages (markdown)
        ├── pilots/      # 36 pilot wiki pages (markdown)
        ├── implants/    # 49 implant entries (markdown)
        ├── overviews/   # Mechs, Pilots, Weapons overview pages
        └── database/    # 22 spreadsheet exports (weapons, costs, events, etc.)
```

---

## Data sources

| Data | Source |
|---|---|
| Mech stats | Mech Arena wiki (scraped individually per mech) |
| Weapons, pilots, costs, events, vaults | Community Google Spreadsheet (22 tabs exported to markdown) |
| Current meta | Reddit r/MechArena (live, top weekly posts) |
| Fallback search | DuckDuckGo |

> **Note:** Mech stats come from the wiki only — not the spreadsheet — per design decision.

---

## Tech stack

- **Python 3.11**
- **discord.py 2.x** — Discord bot framework
- **Groq API** (llama-3.3-70b) — LLM with 3-key rotation
- **SQLAlchemy 2.0 + PostgreSQL** — conversation history and trained responses
- **duckduckgo-search** — web search
- **Reddit JSON API** — no auth required, pulls r/MechArena

---

*ArenaBot — Created by Krishna*
