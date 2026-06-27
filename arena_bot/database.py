import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
from models import Base

logger = logging.getLogger("arenabot")

_engine = None
_SessionLocal = None


def _get_engine():
    global _engine, _SessionLocal
    if _engine is not None:
        return _engine

    raw = os.environ.get("DATABASE_URL")
    if not raw:
        raise EnvironmentError(
            "FATAL: DATABASE_URL environment variable is not set. "
            "Set it in Railway → Variables or your .env file."
        )

    url = raw
    # Railway Postgres URLs use postgres:// — SQLAlchemy 2.x needs postgresql://
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    # Add SSL for remote DBs
    if "sslmode" not in url and "localhost" not in url and "127.0.0.1" not in url:
        sep = "&" if "?" in url else "?"
        url += f"{sep}sslmode=require"

    _engine = create_engine(
        url,
        pool_size=3,
        max_overflow=5,
        pool_pre_ping=True,
        pool_recycle=300,
        echo=False,
    )
    _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
    return _engine


def init_db():
    engine = _get_engine()
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    logger.info("✅ Database tables initialized")


def _run_migrations(engine):
    migrations = [
        "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS training_channel_id VARCHAR(30)",
        "ALTER TABLE trained_responses ADD COLUMN IF NOT EXISTS added_by_name VARCHAR(100)",
    ]
    with engine.begin() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
            except Exception as e:
                logger.warning(f"Migration skipped ({sql[:50]}): {e}")


@contextmanager
def get_session():
    if _SessionLocal is None:
        _get_engine()
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
