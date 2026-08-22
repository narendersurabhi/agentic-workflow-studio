from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/agentic")

engine = create_engine(
    DATABASE_URL,
    # pool_pre_ping sends SELECT 1 on every checkout — one extra round-trip per request.
    # Use pool_recycle instead: connections are proactively replaced after 30 min,
    # which prevents staleness without paying a round-trip on every hot request.
    pool_pre_ping=False,
    pool_recycle=1800,
    # 20 persistent + 20 overflow = 40 max concurrent DB connections.
    # The SSE endpoint holds a connection for the full stream duration (~2-3 s),
    # and the orchestrator also holds connections during event handling.
    pool_size=20,
    max_overflow=20,
    # Fail fast if the pool is truly exhausted rather than waiting 30 s.
    pool_timeout=10,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass
