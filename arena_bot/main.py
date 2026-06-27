import os
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("arenabot")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger.info("=== ArenaBot Starting ===")

logger.info("Step 1: Validating Groq API keys...")
from groq_rotator import groq

logger.info("Step 2: Initializing database...")
from database import init_db
init_db()

logger.info("Step 3: Loading knowledge base...")
from knowledge_loader import load_all
load_all()

logger.info("Step 4: Starting Discord bot...")
from bot import bot

token = os.environ.get("DISCORD_TOKEN")
if not token:
    logger.error("FATAL: DISCORD_TOKEN environment variable is missing.")
    sys.exit(1)

bot.run(token, log_handler=None)
