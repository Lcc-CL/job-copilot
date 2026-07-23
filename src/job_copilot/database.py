"""SQLAlchemy 引擎与会话工厂。

支持 SQLite（默认）和 PostgreSQL（通过 DATABASE_URL 环境变量）。
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, Engine, event
from sqlalchemy.orm import sessionmaker, Session

from .config import DATA_DIR


def _default_db_url() -> str:
    db_path = DATA_DIR / "jobcopilot.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


DATABASE_URL = os.getenv("DATABASE_URL", _default_db_url())


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
        _engine = create_engine(DATABASE_URL, echo=False, **_engine_kwargs(DATABASE_URL))
        # SQLite: 启用 WAL 和级联外键
        if "sqlite" in DATABASE_URL:

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


def init_db(*, drop_applications: bool = False) -> list[str]:
    """初始化数据库：创建表 + 执行幂等迁移。返回迁移日志。"""
    from .models import Base, run_migrations

    engine = get_engine()
    # 先创建基础表（jobs/job_vectors/job_scores 等已有表，IF NOT EXISTS 安全）
    Base.metadata.create_all(bind=engine)
    # 再执行列级迁移（jobs 新列 / application_events / sync_runs）
    logs = run_migrations(engine, drop_applications=drop_applications)

    # 回填：从 job_scores + job_vectors 推导 jobs 新字段
    with engine.begin() as conn:
        # original_score = match 阶段的 embedding 余弦分（暂无直接存储，从已精排岗反向标记）
        # enriched_score = fit_score（精排后的分数）
        result = conn.exec_driver_sql("""
            UPDATE jobs SET
                enriched_score = (SELECT fit_score FROM job_scores WHERE job_scores.job_pk = jobs.id),
                recommendation = CASE
                    WHEN (SELECT verdict FROM job_scores WHERE job_scores.job_pk = jobs.id) = '投'
                        THEN 'APPLY_NOW'
                    WHEN (SELECT verdict FROM job_scores WHERE job_scores.job_pk = jobs.id) = '慎投'
                        THEN 'REVIEW'
                    WHEN (SELECT verdict FROM job_scores WHERE job_scores.job_pk = jobs.id) = '不投'
                        THEN 'SKIP'
                    ELSE 'PENDING_JD'
                END,
                updated_at = COALESCE(jobs.updated_at, (SELECT scored_at FROM job_scores WHERE job_scores.job_pk = jobs.id))
            WHERE EXISTS (SELECT 1 FROM job_scores WHERE job_scores.job_pk = jobs.id)
            AND jobs.recommendation IS NULL
        """)
        backfilled = result.rowcount
        if backfilled:
            logs.append(f"backfill: {backfilled} jobs (score→recommendation)")

    return logs
