"""
Bot ownership and maintainer configuration.
"""

# Krishna's Discord user ID — sole owner & creator of ArenaBot
OWNER_ID = "1442058583129722986"

# Maintainer Discord user IDs
MAINTAINER_IDS: list[str] = [
    "1464176807661146173",   # Maintainer 1
    # Maintainer 2 is the owner (already included via OWNER_ID)
]

# Combined set of all privileged users
PRIVILEGED_IDS: set[str] = {OWNER_ID} | set(MAINTAINER_IDS)

BOT_AUTHOR = "Krishna"
SESSION_MEMORY_HOURS = 2    # conversation context resets after 2 hours

BOT_CHANNEL_NAME = "arena-bot"
TRAINING_CHANNEL_NAME = "arena-training"
