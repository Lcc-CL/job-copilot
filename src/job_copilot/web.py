"""FastAPI 投递管理 API。

提供岗位 CRUD、投递状态机、事件记录、Dashboard 统计、CSV 导出。

启动:  python -m job_copilot web serve
"""

from __future__ import annotations

import csv
import datetime
import io
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_, case, text
from sqlalchemy.orm import Session

from .database import get_session, init_db, get_engine
from .models import (
    Job, JobScore, Application, ApplicationEvent, SyncRun,
    APPLICATION_STAGES,
)
from .importer import update_application_stage, import_tracking_csv
from .config import DATA_DIR
from .auth import (
    add_session_middleware, register_auth_routes, require_auth,
    get_auth_config, cmd_hash_password,
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

app = FastAPI(
    title="Job Copilot API",
    description="投递管理系统 —— 岗位、投递状态、事件追踪",
    version="0.3.0",
    docs_url=None if os.getenv("APP_ENV") == "production" else "/docs",
    redoc_url=None if os.getenv("APP_ENV") == "production" else "/redoc",
    openapi_url=None if os.getenv("APP_ENV") == "production" else "/openapi.json",
)

# Register auth routes (must be before SessionMiddleware so they can set session)
register_auth_routes(app)

# Auth protection: pure ASGI middleware (before Session so it runs AFTER Session)
# add_middleware is LIFO: first added = innermost, last = outermost
# Desired stack: CORS(outer) → Session → Auth(inner) → App
class AuthASGIMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if (path.startswith("/api/auth/") or
            path.startswith("/api/health") or
            not path.startswith("/api/")):
            await self.app(scope, receive, send)
            return

        session = scope.get("session", {})
        if not session.get("user"):
            from starlette.responses import JSONResponse as JsonResp
            response = JsonResp(status_code=401, content={"detail": "Authentication required"})
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

app.add_middleware(AuthASGIMiddleware)

# Session middleware (after Auth so it runs BEFORE Auth in stack)
add_session_middleware(app)

# CORS (outermost)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


# ============================================================
# Pydantic Schemas
# ============================================================

class JobUpdate(BaseModel):
    jd_status: Optional[str] = None
    recommendation: Optional[str] = None
    greeting_text: Optional[str] = None
    notes: Optional[str] = Field(None, description="用户私人备注")


class ApplicationCreate(BaseModel):
    stage: str = "SHORTLISTED"
    priority: Optional[str] = None
    channel: str = "boss"
    resume_version: Optional[str] = None
    notes: Optional[str] = None


class ApplicationUpdate(BaseModel):
    stage: Optional[str] = None
    priority: Optional[str] = None
    channel: Optional[str] = None
    resume_version: Optional[str] = None
    applied_at: Optional[str] = None
    last_contact_at: Optional[str] = None
    next_follow_up_at: Optional[str] = None
    notes: Optional[str] = None


class EventCreate(BaseModel):
    event_type: str
    from_stage: Optional[str] = None
    to_stage: Optional[str] = None
    content: Optional[str] = None


# ============================================================
# API
# ============================================================

@app.get("/api/health")
def health():
    db_status = "ok"
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {e}"
    status_code = 200 if db_status == "ok" else 503
    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={"status": "ok" if db_status == "ok" else "error", "database": db_status},
        status_code=status_code,
    )


# ---------- Dashboard ----------

@app.get("/api/dashboard/summary")
def dashboard_summary():
    session = get_session()
    try:
        total = session.execute(
            select(func.count(Job.id))
        ).scalar() or 0

        # 推荐状态分布
        recs = dict(session.execute(
            select(Job.recommendation, func.count(Job.id))
            .where(Job.recommendation.isnot(None))
            .group_by(Job.recommendation)
        ).all())

        # 投递阶段分布
        stages = dict(session.execute(
            select(Application.stage, func.count(Application.id))
            .group_by(Application.stage)
        ).all())

        def s(stage: str) -> int:
            return stages.get(stage, 0)

        shortlisted = s("SHORTLISTED")
        greeting_ready = s("GREETING_READY")
        contacted = s("CONTACTED")
        applied = s("APPLIED")
        replied = s("REPLIED")
        interviews = s("INTERVIEW")
        offers = s("OFFER")
        rejected = s("REJECTED")

        today = _today_str()
        due_today = session.execute(
            select(func.count(Application.id)).where(
                Application.next_follow_up_at >= today,
                Application.next_follow_up_at < today + "T23:59:59",
            )
        ).scalar() or 0

        overdue = session.execute(
            select(func.count(Application.id)).where(
                Application.next_follow_up_at < today,
            )
        ).scalar() or 0

        # response_rate = reached REPLIED+ / reached CONTACTED+
        contacted_plus = contacted + applied + replied + interviews + offers
        replied_plus = replied + interviews + offers
        response_rate = (replied_plus / contacted_plus) if contacted_plus > 0 else 0.0

        # interview_rate = reached INTERVIEW+ / reached APPLIED+
        applied_plus = applied + replied + interviews + offers
        interview_plus = interviews + offers
        interview_rate = (interview_plus / applied_plus) if applied_plus > 0 else 0.0

        return {
            "total_jobs": total,
            "shortlisted": shortlisted,
            "greeting_ready": greeting_ready,
            "contacted": contacted,
            "applied": applied,
            "replied": replied,
            "interviews": interviews,
            "offers": offers,
            "rejected": rejected,
            "due_today": due_today,
            "overdue": overdue,
            "response_rate": round(response_rate, 4),
            "interview_rate": round(interview_rate, 4),
            "recommendations": recs,
        }
    finally:
        session.close()


# ---------- Jobs ----------

def _job_row(j: Job, include_score: bool = True) -> dict:
    d = {
        "id": j.id,
        "platform": j.platform,
        "job_id": j.job_id,
        "url": j.url,
        "title": j.title,
        "company": j.company,
        "company_size": j.company_size,
        "industry": j.industry,
        "salary_text": j.salary_text,
        "salary_min": j.salary_min,
        "salary_max": j.salary_max,
        "salary_months": j.salary_months,
        "city": j.city,
        "district": j.district,
        "experience": j.experience,
        "degree": j.degree,
        "tags": j.tags,
        "jd_text": (j.jd_text or "")[:500],  # 截断，避免响应过大
        "jd_status": j.jd_status,
        "original_score": j.original_score,
        "enriched_score": j.enriched_score,
        "recommendation": j.recommendation,
        "greeting_text": j.greeting_text,
        "has_application": j.application is not None,
        "application_id": j.application.id if j.application else None,
        "application_stage": j.application.stage if j.application else None,
    }
    if include_score and j.score:
        d["score"] = {
            "fit_score": j.score.fit_score,
            "verdict": j.score.verdict,
            "archetype": j.score.archetype,
            "authenticity": j.score.authenticity,
            "reasons": j.score.reasons,
            "highlights": j.score.highlights,
            "gaps": j.score.gaps,
        }
    return d


@app.get("/api/jobs")
def list_jobs(
    keyword: Optional[str] = Query(None),
    recommendation: Optional[str] = Query(None),
    jd_status: Optional[str] = Query(None),
    company: Optional[str] = Query(None),
    min_score: Optional[float] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    session = get_session()
    try:
        q = select(Job).outerjoin(JobScore, Job.id == JobScore.job_pk)

        if keyword:
            like = f"%{keyword}%"
            q = q.where(
                Job.title.ilike(like) | Job.company.ilike(like)
            )
        if recommendation:
            q = q.where(Job.recommendation == recommendation)
        if jd_status:
            q = q.where(Job.jd_status == jd_status)
        if company:
            q = q.where(Job.company.ilike(f"%{company}%"))
        if min_score is not None:
            q = q.where(JobScore.fit_score >= min_score)

        total = session.execute(
            select(func.count()).select_from(q.subquery())
        ).scalar() or 0

        rows = session.execute(
            q.order_by(JobScore.fit_score.desc().nullslast(), Job.id.desc())
            .offset(offset).limit(limit)
        ).scalars().all()

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [_job_row(j) for j in rows],
        }
    finally:
        session.close()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int):
    session = get_session()
    try:
        j = session.get(Job, job_id)
        if not j:
            raise HTTPException(404, "岗位不存在")
        return _job_row(j)
    finally:
        session.close()


@app.patch("/api/jobs/{job_id}")
def update_job(job_id: int, body: JobUpdate):
    session = get_session()
    try:
        j = session.get(Job, job_id)
        if not j:
            raise HTTPException(404, "岗位不存在")

        updates = body.model_dump(exclude_unset=True)
        notes = updates.pop("notes", None)

        for k, v in updates.items():
            if hasattr(j, k):
                setattr(j, k, v)

        # Auto-sync jd_status based on jd_text length
        if "jd_text" in updates:
            jd = (j.jd_text or "").strip()
            j.jd_status = "FULL" if len(jd) >= 100 else "PENDING_JD"

        # notes 写入关联的 application
        if notes is not None and j.application:
            j.application.notes = notes
            j.application.updated_at = _now()

        j.updated_at = _now()
        session.commit()
        session.refresh(j)
        return _job_row(j)
    finally:
        session.close()


@app.post("/api/jobs/{job_id}/application", status_code=201)
def create_application(job_id: int, body: ApplicationCreate):
    session = get_session()
    try:
        j = session.get(Job, job_id)
        if not j:
            raise HTTPException(404, "岗位不存在")
        if j.application:
            raise HTTPException(409, "该岗位已有投递记录")

        if body.stage not in APPLICATION_STAGES:
            raise HTTPException(400, f"无效 stage: {body.stage}")

        app = Application(
            job_pk=j.id,
            stage=body.stage,
            priority=body.priority,
            channel=body.channel,
            resume_version=body.resume_version,
            notes=body.notes,
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(app)
        session.flush()

        # 初始事件
        evt = ApplicationEvent(
            application_id=app.id,
            event_type="created",
            from_stage=None,
            to_stage=body.stage,
            occurred_at=_now(),
        )
        session.add(evt)
        session.commit()
        session.refresh(app)

        return _app_row(app)
    finally:
        session.close()


# ---------- Applications ----------

def _app_row(a: Application) -> dict:
    j = a.job
    return {
        "id": a.id,
        "job_pk": a.job_pk,
        "job_title": j.title if j else None,
        "job_company": j.company if j else None,
        "job_url": j.url if j else None,
        "job_recommendation": j.recommendation if j else None,
        "job_enriched_score": j.enriched_score if j else None,
        "job_salary_text": j.salary_text if j else None,
        "job_city": j.city if j else None,
        "job_jd_status": j.jd_status if j else None,
        "job_original_score": j.original_score if j else None,
        "job_greeting_text": j.greeting_text if j else None,
        "stage": a.stage,
        "priority": a.priority,
        "channel": a.channel,
        "resume_version": a.resume_version,
        "applied_at": a.applied_at,
        "last_contact_at": a.last_contact_at,
        "next_follow_up_at": a.next_follow_up_at,
        "notes": a.notes,
        "created_at": a.created_at,
        "updated_at": a.updated_at,
        "events": [_evt_row(e) for e in (a.events or [])],
    }


def _evt_row(e: ApplicationEvent) -> dict:
    return {
        "id": e.id,
        "event_type": e.event_type,
        "from_stage": e.from_stage,
        "to_stage": e.to_stage,
        "content": e.content,
        "occurred_at": e.occurred_at,
    }


@app.get("/api/applications")
def list_applications(
    stage: Optional[str] = Query(None),
    recommendation: Optional[str] = Query(None),
    overdue: Optional[bool] = Query(None),
    due_before: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    session = get_session()
    try:
        q = select(Application).join(Job, Application.job_pk == Job.id)

        if stage:
            q = q.where(Application.stage == stage)
        if recommendation:
            q = q.where(Job.recommendation == recommendation)
        if overdue:
            today = _today_str()
            q = q.where(
                and_(
                    Application.next_follow_up_at.isnot(None),
                    Application.next_follow_up_at < today,
                )
            )
        if due_before:
            q = q.where(
                and_(
                    Application.next_follow_up_at.isnot(None),
                    Application.next_follow_up_at <= due_before,
                )
            )
        if keyword:
            like = f"%{keyword}%"
            q = q.where(
                Job.title.ilike(like) | Job.company.ilike(like)
            )

        total = session.execute(
            select(func.count()).select_from(q.subquery())
        ).scalar() or 0

        rows = session.execute(
            q.order_by(Application.updated_at.desc().nullslast())
            .offset(offset).limit(limit)
        ).scalars().all()

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [_app_row(a) for a in rows],
        }
    finally:
        session.close()


@app.get("/api/applications/{application_id}")
def get_application(application_id: int):
    session = get_session()
    try:
        a = session.get(Application, application_id)
        if not a:
            raise HTTPException(404, "投递记录不存在")
        return _app_row(a)
    finally:
        session.close()


@app.patch("/api/applications/{application_id}")
def update_application(application_id: int, body: ApplicationUpdate):
    session = get_session()
    try:
        a = session.get(Application, application_id)
        if not a:
            raise HTTPException(404, "投递记录不存在")

        updates = body.model_dump(exclude_unset=True)
        new_stage = updates.pop("stage", None)

        for k, v in updates.items():
            if hasattr(a, k):
                setattr(a, k, v)

        # Stage 变化 → 自动写入事件
        if new_stage and new_stage != a.stage:
            update_application_stage(session, a, new_stage,
                                     content="API 手动更新阶段")

        a.updated_at = _now()
        session.commit()
        session.refresh(a)
        return _app_row(a)
    finally:
        session.close()


@app.post("/api/applications/{application_id}/events", status_code=201)
def add_application_event(application_id: int, body: EventCreate):
    session = get_session()
    try:
        a = session.get(Application, application_id)
        if not a:
            raise HTTPException(404, "投递记录不存在")

        # 如果 event 包含 stage_change，更新 app.stage
        if body.event_type == "stage_change" and body.to_stage:
            if body.to_stage not in APPLICATION_STAGES:
                raise HTTPException(400, f"无效 stage: {body.to_stage}")
            a.stage = body.to_stage
            a.updated_at = _now()

        evt = ApplicationEvent(
            application_id=a.id,
            event_type=body.event_type,
            from_stage=body.from_stage,
            to_stage=body.to_stage,
            content=body.content,
            occurred_at=_now(),
        )
        session.add(evt)
        session.commit()
        session.refresh(evt)
        return _evt_row(evt)
    finally:
        session.close()


# ---------- Follow-ups ----------

@app.get("/api/follow-ups")
def follow_ups():
    """返回今日、逾期、未来 7 天需跟进的投递。"""
    session = get_session()
    try:
        today = _today_str()
        # 逾期
        overdue_q = select(Application).where(
            and_(
                Application.next_follow_up_at.isnot(None),
                Application.next_follow_up_at < today,
            )
        ).order_by(Application.next_follow_up_at)
        overdue_list = session.execute(overdue_q).scalars().all()

        # 今日
        due_today_q = select(Application).where(
            and_(
                Application.next_follow_up_at >= today,
                Application.next_follow_up_at < today + "T23:59:59",
            )
        ).order_by(Application.next_follow_up_at)
        due_today_list = session.execute(due_today_q).scalars().all()

        # 未来 7 天（不含今日）
        end = (_today_dt() + datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        upcoming_q = select(Application).where(
            and_(
                Application.next_follow_up_at > today + "T23:59:59",
                Application.next_follow_up_at <= end,
            )
        ).order_by(Application.next_follow_up_at)
        upcoming_list = session.execute(upcoming_q).scalars().all()

        return {
            "overdue": [_app_row(a) for a in overdue_list],
            "due_today": [_app_row(a) for a in due_today_list],
            "upcoming": [_app_row(a) for a in upcoming_list],
        }
    finally:
        session.close()


# ---------- Export ----------

@app.get("/api/export/applications.csv")
def export_applications_csv():
    session = get_session()
    try:
        q = select(Application).order_by(Application.id)
        apps = session.execute(q).scalars().all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "公司", "职位", "阶段", "优先级", "渠道",
            "投递日期", "最后联系", "下次跟进", "备注",
            "职位链接",
        ])
        for a in apps:
            writer.writerow([
                a.id,
                a.job.company if a.job else "",
                a.job.title if a.job else "",
                a.stage,
                a.priority or "",
                a.channel or "",
                a.applied_at or "",
                a.last_contact_at or "",
                a.next_follow_up_at or "",
                a.notes or "",
                a.job.url if a.job else "",
            ])

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=applications-{_today_str()}.csv"
            },
        )
    finally:
        session.close()


# ============================================================
# 辅助
# ============================================================

def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _today_str() -> str:
    return datetime.date.today().isoformat()


def _today_dt() -> datetime.date:
    return datetime.date.today()


# ---------- Follow-up Action ----------

class FollowUpAction(BaseModel):
    content: Optional[str] = None
    next_follow_up_at: Optional[str] = None
    stage: Optional[str] = None


@app.post("/api/applications/{application_id}/follow-up")
def follow_up_action(application_id: int, body: FollowUpAction):
    """原子跟进操作：更新 last_contact_at / next_follow_up_at / stage，写入事件。"""
    session = get_session()
    try:
        a = session.get(Application, application_id)
        if not a:
            raise HTTPException(404, "投递记录不存在")

        now = _now()
        a.last_contact_at = now

        if body.next_follow_up_at is not None:
            a.next_follow_up_at = body.next_follow_up_at if body.next_follow_up_at else None

        old_stage = a.stage
        if body.stage and body.stage != a.stage:
            if body.stage not in APPLICATION_STAGES:
                raise HTTPException(400, f"无效 stage: {body.stage}")
            a.stage = body.stage

        a.updated_at = now

        # 写入事件
        evt = ApplicationEvent(
            application_id=a.id,
            event_type="follow_up",
            from_stage=old_stage,
            to_stage=a.stage,
            content=body.content or "",
            occurred_at=now,
        )
        session.add(evt)
        session.commit()
        session.refresh(a)
        return _app_row(a)
    finally:
        session.close()


# ---------- Resume Tailor ----------

@app.get("/api/resume-profiles")
def list_resume_profiles():
    from .resume_tailor import get_profiles
    return get_profiles()


@app.post("/api/resume-profiles", status_code=201)
def create_resume_profile(body: dict):
    from .resume_tailor import upsert_profile
    return upsert_profile(body)


@app.patch("/api/resume-profiles/{profile_id}")
def update_resume_profile(profile_id: int, body: dict):
    body["id"] = profile_id
    from .resume_tailor import upsert_profile
    return upsert_profile(body)


@app.get("/api/applications/{application_id}/resume-versions")
def list_resume_versions(application_id: int):
    from .resume_tailor import get_versions
    return get_versions(application_id)


@app.post("/api/applications/{application_id}/resume-tailor", status_code=201)
def generate_resume(application_id: int):
    from .resume_tailor import tailor_resume
    result = tailor_resume(application_id)
    if "error" in result:
        status = result.get("status", 400)
        raise HTTPException(status_code=status, detail=result["error"])
    return result


@app.get("/api/resume-versions/{version_id}")
def get_resume_version(version_id: int):
    from .resume_tailor import get_version
    rv = get_version(version_id)
    if not rv:
        raise HTTPException(404, "Version not found")
    return rv


@app.patch("/api/resume-versions/{version_id}")
def update_resume_version(version_id: int, body: dict):
    from .resume_tailor import update_version
    rv = update_version(version_id, body)
    if not rv:
        raise HTTPException(404, "Version not found")
    return rv


@app.post("/api/resume-versions/{version_id}/mark-used")
def mark_version_used(version_id: int):
    from .resume_tailor import mark_used
    rv = mark_used(version_id)
    if not rv:
        raise HTTPException(404, "Version not found")
    return rv


# ============================================================
# SPA fallback (production: serve React frontend)
# ============================================================

if FRONTEND_DIR.exists():
    assets_dir = FRONTEND_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str = ""):
        # /api paths not handled here — already matched by API routes
        file_path = FRONTEND_DIR / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        index = FRONTEND_DIR / "index.html"
        if index.exists():
            return HTMLResponse(index.read_text(encoding="utf-8"))
        return HTMLResponse("Frontend not built.", status_code=404)


# ============================================================
# CLI 支持
# ============================================================

def cmd_init_db() -> str:
    """幂等初始化数据库（创建新表 + 列迁移）。"""
    logs = init_db(drop_applications=False)
    if logs:
        return "✓ 迁移已执行:\n" + "\n".join(f"  - {m}" for m in logs)
    return "✓ 数据库已是最新状态，无需迁移。"


def cmd_import_tracking(csv_path: str) -> str:
    """导入投递追踪 CSV。"""
    import glob
    path = Path(csv_path).expanduser()

    # 目录 → 找最新 CSV
    if path.is_dir():
        files = sorted(glob.glob(str(path / "投递追踪-*.csv")))
        if not files:
            # 也扫 exports 目录
            files = sorted(glob.glob(str(path / "exports" / "投递追踪-*.csv")))
        if not files:
            return f"✗ 目录中未找到投递追踪-*.csv: {path}"
        path = Path(files[-1])

    if not path.exists():
        return f"✗ 文件不存在: {path}"

    stats = import_tracking_csv(path)
    unlinked = stats["unlinked"]
    lines = [
        f"✓ 导入完成: {path.name}",
        f"  新增投递记录: {stats['inserted']}",
        f"  更新投递记录: {stats['updated']}",
        f"  跳过(无变化):  {stats['skipped']}",
        f"  新增事件:      {stats['new_events']}",
        f"  总行数:        {stats['total_rows']}",
    ]
    if unlinked:
        lines.append(f"  ⚠ 无法关联岗位: {unlinked} 行（CSV 链接未匹配到库内岗位）")
    return "\n".join(lines)


def cmd_serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """启动 API 服务（SPA fallback 已在模块级别注册）。"""
    import uvicorn

    print(f"Job Copilot API → http://{host}:{port}")
    if os.getenv("APP_ENV") != "production":
        print(f"API 文档 → http://{host}:{port}/docs")
    uvicorn.run(
        "job_copilot.web:app",
        host=host,
        port=port,
        reload=False,
        log_level="info" if os.getenv("APP_ENV") == "production" else "info",
    )


def cmd_hash_password_cli(password: str) -> str:
    """CLI: 生成密码 hash。"""
    return cmd_hash_password(password)
