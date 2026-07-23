"""追踪 CSV 幂等导入器。

将投递追踪 CSV 导入 applications 表，按 URL 关联已有岗位，
更新 stage 并自动写入 application_events。
"""

from __future__ import annotations

import csv
import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_session
from .models import (
    Job,
    Application,
    ApplicationEvent,
    SyncRun,
    APPLICATION_STAGES,
)


# CSV 投递状态映射:  CSV字段 → application stage
_STAGE_FROM_CSV: dict[str, str] = {}


def _derive_stage(row: dict) -> str:
    """根据 CSV 行推导投递阶段。"""
    has_greeting = bool((row.get("招呼语") or "").strip())
    date_sent = (row.get("已发日期(填)") or "").strip()
    is_read = (row.get("已读(填1/0)") or "").strip() == "1"
    is_replied = (row.get("回复(填1/0)") or "").strip() == "1"
    is_interview = (row.get("邀约(填1/0)") or "").strip() == "1"

    if is_interview:
        return "INTERVIEW"
    if is_replied:
        return "REPLIED"
    if is_read:
        return "CONTACTED"  # HR 已读但未回复 — 视为已触达
    if date_sent:
        return "APPLIED" if not has_greeting else "CONTACTED"
    if has_greeting:
        return "GREETING_READY"
    return "SHORTLISTED"


def _find_job(session: Session, row: dict) -> Optional[Job]:
    """按 URL 精准匹配岗位，失败时降级为公司+职位+薪资。"""
    url = (row.get("链接") or "").strip()
    company = (row.get("公司") or "").strip()
    title = (row.get("职位") or "").strip()

    # 1. URL 匹配（最可靠）
    if url:
        j = session.execute(
            select(Job).where(Job.url == url)
        ).scalar_one_or_none()
        if j:
            return j

    # 2. 公司 + 职位（降级，可能有多个匹配，取第一个）
    if company and title:
        jobs = session.execute(
            select(Job)
            .where(Job.company == company, Job.title == title)
            .order_by(Job.id)
        ).scalars().all()
        if jobs:
            return jobs[0]

    return None


def import_tracking_csv(csv_path: Path) -> dict:
    """幂等导入投递追踪 CSV → applications。

    去重键：job_pk（每个岗位最多一条 application）。

    返回统计：
      - inserted: 新增 application 数
      - updated:  更新 application 数（基础字段 + stage 推进）
      - new_events: 新增事件数
      - skipped:   无变化跳过数
      - unlinked:  无法关联到岗位的行数
      - total_rows: CSV 数据行数
    """
    csv_path = Path(csv_path).expanduser()
    if not csv_path.exists():
        raise FileNotFoundError(f"追踪 CSV 不存在: {csv_path}")

    session = get_session()
    sync = SyncRun(
        started_at=_now(),
        status="running",
    )
    session.add(sync)
    session.flush()

    stats = {
        "inserted": 0,
        "updated": 0,
        "new_events": 0,
        "skipped": 0,
        "unlinked": 0,
        "total_rows": 0,
    }

    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                stats["total_rows"] += 1
                _import_row(session, row, stats)

        sync.status = "completed"
        sync.finished_at = _now()
        session.commit()
    except Exception as e:
        sync.status = "failed"
        sync.error_message = str(e)[:2000]
        sync.finished_at = _now()
        session.commit()
        raise

    sync.inserted_count = stats["inserted"]
    sync.updated_count = stats["updated"]
    sync.skipped_count = stats["skipped"]
    session.commit()

    return stats


def _import_row(session: Session, row: dict, stats: dict) -> None:
    job = _find_job(session, row)
    if not job:
        stats["unlinked"] += 1
        return

    stage = _derive_stage(row)
    group_tag = (row.get("分组") or "").strip()
    greeting = (row.get("招呼语") or "").strip()
    date_sent = (row.get("已发日期(填)") or "").strip()

    # 查找已有 application
    app = session.execute(
        select(Application).where(Application.job_pk == job.id)
    ).scalar_one_or_none()

    if app is None:
        app = Application(
            job_pk=job.id,
            stage=stage,
            priority=group_tag or None,
            channel="boss",
            applied_at=date_sent or None,
            last_contact_at=date_sent or None,
            notes=greeting or None,
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(app)
        session.flush()
        stats["inserted"] += 1

        # 创建初始事件
        _add_event(session, app, event_type="stage_change",
                   from_stage=None, to_stage=stage,
                   content=f"从 CSV 导入，分组={group_tag}")
        stats["new_events"] += 1
    else:
        # 已有记录，更新
        changed = False
        if greeting and greeting != (app.notes or ""):
            app.notes = greeting
            changed = True
        if group_tag and group_tag != (app.priority or ""):
            app.priority = group_tag
            changed = True
        if date_sent and date_sent != (app.applied_at or ""):
            app.applied_at = date_sent
            changed = True

        # Stage 推进
        if stage != app.stage:
            old_stage = app.stage
            app.stage = stage
            _add_event(session, app, event_type="stage_change",
                       from_stage=old_stage, to_stage=stage,
                       content="CSV 导入更新阶段")
            stats["new_events"] += 1
            changed = True

        if changed:
            app.updated_at = _now()
            stats["updated"] += 1
        else:
            stats["skipped"] += 1


def _add_event(
    session: Session,
    app: Application,
    event_type: str,
    from_stage: Optional[str] = None,
    to_stage: Optional[str] = None,
    content: Optional[str] = None,
) -> ApplicationEvent:
    evt = ApplicationEvent(
        application_id=app.id,
        event_type=event_type,
        from_stage=from_stage,
        to_stage=to_stage,
        content=content,
        occurred_at=_now(),
    )
    session.add(evt)
    return evt


def update_application_stage(
    session: Session, app: Application, new_stage: str, content: str = ""
) -> ApplicationEvent:
    """修改 application stage 并自动写入事件。"""
    if new_stage not in APPLICATION_STAGES:
        raise ValueError(f"无效 stage: {new_stage}，有效值: {APPLICATION_STAGES}")
    old_stage = app.stage
    if old_stage == new_stage:
        return None
    app.stage = new_stage
    app.updated_at = _now()
    return _add_event(
        session, app,
        event_type="stage_change",
        from_stage=old_stage,
        to_stage=new_stage,
        content=content,
    )


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
