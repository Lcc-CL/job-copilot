"""SQLAlchemy ORM 模型 —— 岗位、投递、事件、同步运行。

复用现有 jobs / job_scores / job_vectors 表结构，新增 application_events
和 sync_runs。applications 表重新设计以支持完整投递状态机。

所有时间字段存储为 ISO 格式 TEXT（与现有 db.py 的 sqlite3 风格兼容）。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import (
    Integer,
    String,
    Text,
    Float,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SchemaVersion(Base):
    __tablename__ = "schema_version"

    version: Mapped[str] = mapped_column(String, primary_key=True)
    applied_at: Mapped[Optional[str]] = mapped_column(String)


# ============================================================
# 岗位
# ============================================================

class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String, nullable=False, default="boss")
    job_id: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[Optional[str]] = mapped_column(Text)
    title: Mapped[Optional[str]] = mapped_column(String)
    company: Mapped[Optional[str]] = mapped_column(String)
    company_size: Mapped[Optional[str]] = mapped_column(String)
    industry: Mapped[Optional[str]] = mapped_column(String)
    salary_text: Mapped[Optional[str]] = mapped_column(String)
    salary_min: Mapped[Optional[int]] = mapped_column(Integer)
    salary_max: Mapped[Optional[int]] = mapped_column(Integer)
    salary_months: Mapped[Optional[int]] = mapped_column(Integer)
    city: Mapped[Optional[str]] = mapped_column(String)
    district: Mapped[Optional[str]] = mapped_column(String)
    experience: Mapped[Optional[str]] = mapped_column(String)
    degree: Mapped[Optional[str]] = mapped_column(String)
    tags: Mapped[Optional[str]] = mapped_column(Text)
    hr_name: Mapped[Optional[str]] = mapped_column(String)
    hr_title: Mapped[Optional[str]] = mapped_column(String)
    hr_active: Mapped[Optional[str]] = mapped_column(String)
    jd_text: Mapped[Optional[str]] = mapped_column(Text)
    search_keyword: Mapped[Optional[str]] = mapped_column(String)
    search_city: Mapped[Optional[str]] = mapped_column(String)
    collected_at: Mapped[str] = mapped_column(String, nullable=False)

    # --- 新增字段（ALTER TABLE 添加，默认值兼容存量数据）---
    jd_status: Mapped[Optional[str]] = mapped_column(String, default="PENDING_JD")
    original_score: Mapped[Optional[float]] = mapped_column(Float)
    enriched_score: Mapped[Optional[float]] = mapped_column(Float)
    recommendation: Mapped[Optional[str]] = mapped_column(String)
    greeting_text: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[str]] = mapped_column(String)
    updated_at: Mapped[Optional[str]] = mapped_column(String)

    # 关系
    score: Mapped[Optional["JobScore"]] = relationship(back_populates="job", uselist=False)
    vector: Mapped[Optional["JobVector"]] = relationship(back_populates="job", uselist=False)
    application: Mapped[Optional["Application"]] = relationship(back_populates="job", uselist=False)

    __table_args__ = (
        UniqueConstraint("platform", "job_id", name="uq_jobs_platform_job_id"),
    )


class JobVector(Base):
    __tablename__ = "job_vectors"

    job_pk: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    vec: Mapped[bytes] = mapped_column(nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String)
    embedded_at: Mapped[Optional[str]] = mapped_column(String)

    job: Mapped[Job] = relationship(back_populates="vector")


class JobScore(Base):
    __tablename__ = "job_scores"

    job_pk: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    fit_score: Mapped[Optional[float]] = mapped_column(Float)
    verdict: Mapped[Optional[str]] = mapped_column(String)
    archetype: Mapped[Optional[str]] = mapped_column(String)
    seniority_ok: Mapped[Optional[int]] = mapped_column(Integer)
    authenticity: Mapped[Optional[str]] = mapped_column(String)
    reasons: Mapped[Optional[str]] = mapped_column(Text)
    highlights: Mapped[Optional[str]] = mapped_column(Text)
    gaps: Mapped[Optional[str]] = mapped_column(Text)
    model: Mapped[Optional[str]] = mapped_column(String)
    scored_at: Mapped[Optional[str]] = mapped_column(String)

    job: Mapped[Job] = relationship(back_populates="score")


# ============================================================
# 投递
# ============================================================

# 投递阶段枚举（与 schema/migration 保持一致）
APPLICATION_STAGES = [
    "DISCOVERED",
    "SHORTLISTED",
    "GREETING_READY",
    "CONTACTED",
    "APPLIED",
    "REPLIED",
    "INTERVIEW",
    "OFFER",
    "REJECTED",
    "WITHDRAWN",
]


class Application(Base):
    """投递记录 —— 每个岗位最多一条，跟踪从发现到最终结果的完整生命周期。"""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_pk: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id"), nullable=False, unique=True
    )
    stage: Mapped[str] = mapped_column(String, nullable=False, default="DISCOVERED")
    priority: Mapped[Optional[str]] = mapped_column(String)
    channel: Mapped[Optional[str]] = mapped_column(String, default="boss")
    resume_version: Mapped[Optional[str]] = mapped_column(String)
    applied_at: Mapped[Optional[str]] = mapped_column(String)
    last_contact_at: Mapped[Optional[str]] = mapped_column(String)
    next_follow_up_at: Mapped[Optional[str]] = mapped_column(String)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[str]] = mapped_column(String)
    updated_at: Mapped[Optional[str]] = mapped_column(String)

    # 关系
    job: Mapped[Job] = relationship(back_populates="application")
    events: Mapped[list["ApplicationEvent"]] = relationship(
        back_populates="application", order_by="ApplicationEvent.occurred_at"
    )


class ApplicationEvent(Base):
    __tablename__ = "application_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    from_stage: Mapped[Optional[str]] = mapped_column(String)
    to_stage: Mapped[Optional[str]] = mapped_column(String)
    content: Mapped[Optional[str]] = mapped_column(Text)
    occurred_at: Mapped[Optional[str]] = mapped_column(String)

    application: Mapped[Application] = relationship(back_populates="events")


# ============================================================
# 同步运行记录
# ============================================================

# ============================================================
# 简历定制
# ============================================================

class ResumeProfile(Base):
    __tablename__ = "resume_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    content_text: Mapped[Optional[str]] = mapped_column(Text)
    content_structured_json: Mapped[Optional[str]] = mapped_column(Text)
    is_master: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[Optional[str]] = mapped_column(String)
    updated_at: Mapped[Optional[str]] = mapped_column(String)


class ResumeVersion(Base):
    __tablename__ = "resume_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    resume_profile_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("resume_profiles.id", ondelete="SET NULL")
    )
    version_name: Mapped[Optional[str]] = mapped_column(String)
    summary_text: Mapped[Optional[str]] = mapped_column(Text)
    skills_json: Mapped[Optional[str]] = mapped_column(Text)
    experience_bullets_json: Mapped[Optional[str]] = mapped_column(Text)
    gap_analysis_json: Mapped[Optional[str]] = mapped_column(Text)
    full_text: Mapped[Optional[str]] = mapped_column(Text)
    generation_method: Mapped[Optional[str]] = mapped_column(String, default="llm")
    status: Mapped[str] = mapped_column(String, default="DRAFT")
    created_at: Mapped[Optional[str]] = mapped_column(String)
    updated_at: Mapped[Optional[str]] = mapped_column(String)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[Optional[str]] = mapped_column(String)
    finished_at: Mapped[Optional[str]] = mapped_column(String)
    inserted_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="running")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
