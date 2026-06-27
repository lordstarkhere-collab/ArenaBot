from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base
from datetime import datetime, timezone

Base = declarative_base()


def _utcnow():
    return datetime.now(timezone.utc)


class GuildSettings(Base):
    __tablename__ = "guild_settings"
    id = Column(Integer, primary_key=True)
    guild_id = Column(String(30), unique=True, nullable=False, index=True)
    guild_name = Column(String(200))
    bot_channel_id = Column(String(30))
    training_channel_id = Column(String(30))
    joined_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)


class ConversationHistory(Base):
    __tablename__ = "conversation_history"
    id = Column(Integer, primary_key=True)
    guild_id = Column(String(30), index=True)
    channel_id = Column(String(30), index=True)
    user_id = Column(String(30), index=True)
    role = Column(String(10))
    content = Column(Text)
    created_at = Column(DateTime, default=_utcnow)


class TrainedResponse(Base):
    """
    Maintainer-taught Q&A pairs. The bot checks these first
    and includes any matches in its context window.
    """
    __tablename__ = "trained_responses"
    id = Column(Integer, primary_key=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    added_by_id = Column(String(30), nullable=False)
    added_by_name = Column(String(100))
    created_at = Column(DateTime, default=_utcnow)
