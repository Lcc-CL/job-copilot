"""SQLAlchemy 引擎与会话工厂。

支持 SQLite（默认）和 PostgreSQL（通过 DATABASE_URL 环境变量）。
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine, Engine, event
from sqlalchemy.orm import sessionmaker, Session

from .config import DATA_DIR


def _default_db_url() -> str:
    db_path = DATA_DIR / "jobcopilot.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


def _get_database_url() -> str:
    raw = os.getenv("DATABASE_URL", "").strip()

    if not raw:
        raw = _default_db_url()

    # Normalize URL schemes
    if raw.startswith("postgres://"):
        raw = "postgresql+psycopg://" + raw[len("postgres://"):]
    elif raw.startswith("postgresql://") and "+psycopg" not in raw:
        raw = "postgresql+psycopg://" + raw[len("postgresql://"):]
    elif raw.startswith("postgresql+psycopg://") or raw.startswith("sqlite://"):
        pass  # already valid
    else:
        raise RuntimeError(
            "DATABASE_URL must be a valid SQLite or PostgreSQL URL"
        )

    return raw


def _engine_kwargs(url: str) -> dict:
    kwargs: dict = {}
    if "sqlite" in url:
        kwargs["connect_args"] = {"check_same_thread": False}
    elif "postgresql" in url:
        kwargs["pool_pre_ping"] = True
    return kwargs


_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = _get_database_url()
        _engine = create_engine(url, echo=False, **_engine_kwargs(url))
        # SQLite: 启用 WAL 和级联外键
        if "sqlite" in url:

            @event.listens_for(_engine, "connect")
            def _sqlite_pragma(dbapi_conn, _record):
                dbapi_conn.execute("PRAGMA journal_mode=WAL")
                dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return _engine


def get_session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()


def init_db(
    *,
    engine: Engine | None = None,
    create_backup: bool = True,
) -> list[str]:
    """Initialize or migrate a database to the authoritative ORM schema."""
    from .migrations import run_schema_migrations

    target_engine = engine or get_engine()
    report = run_schema_migrations(
        target_engine,
        create_backup=create_backup,
    )
    return report.messages
