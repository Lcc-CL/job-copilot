"""定向测试：数据模型、迁移、导入幂等、stage→event、Dashboard、API smoke。"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# ---- 使用临时 SQLite 数据库（文件模式，确保跨连接共享） ----
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

from job_copilot.database import get_engine, get_session, init_db
from job_copilot.models import (
    Base, Job, JobScore, JobVector, Application, ApplicationEvent, SyncRun,
    APPLICATION_STAGES,
)
from job_copilot.web import app as fastapi_app
from job_copilot.importer import update_application_stage

# 重置 engine 缓存，使用测试数据库
import job_copilot.database as _db_mod
_db_mod._engine = None
_db_mod._SessionLocal = None

client = TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def _reset_db():
    """每个测试前重建数据库表。"""
    engine = get_engine()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from job_copilot.models import run_migrations
    run_migrations(engine)
    client.cookies.clear()
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    assert login.status_code == 200
    yield
    client.cookies.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="session", autouse=True)
def _cleanup_tmp_db():
    yield
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass


# ============================================================
# 1. 数据模型创建
# ============================================================

class TestModelCreation:
    def test_tables_exist(self):
        engine = get_engine()
        from sqlalchemy import inspect
        tables = inspect(engine).get_table_names()
        assert "jobs" in tables
        assert "job_scores" in tables
        assert "job_vectors" in tables
        assert "applications" in tables
        assert "application_events" in tables
        assert "sync_runs" in tables

    def test_job_columns(self):
        engine = get_engine()
        from sqlalchemy import inspect
        cols = {c["name"] for c in inspect(engine).get_columns("jobs")}
        for name in ["jd_status", "recommendation", "greeting_text",
                     "original_score", "enriched_score", "created_at", "updated_at"]:
            assert name in cols, f"jobs 缺少列: {name}"


# ============================================================
# 2. SQLite 初始化测试
# ============================================================

class TestInitDB:
    def test_init_db_idempotent(self):
        logs1 = init_db()
        logs2 = init_db()
        # 第二次执行不应有迁移日志（已是最新）
        assert len(logs2) == 0, f"init-db not idempotent: {logs2}"

    def test_jobs_new_columns_default(self):
        session = get_session()
        j = Job(
            platform="boss", job_id="test-1", title="测试岗",
            company="测试公司", collected_at="2026-01-01T00:00:00Z",
        )
        session.add(j)
        session.commit()
        j2 = session.get(Job, j.id)
        assert j2.jd_status == "PENDING_JD"
        assert j2.recommendation is None
        session.close()


# ============================================================
# 3. CSV 幂等导入测试
# ============================================================

class TestCSVImport:
    def _seed_job(self, session, url, company, title):
        j = Job(platform="boss", job_id=f"test-{url[-10:]}", url=url,
                company=company, title=title,
                collected_at="2026-01-01T00:00:00Z")
        session.add(j)
        session.commit()
        return j.id

    def test_import_idempotent(self):
        """重复导入同一 CSV 不产生重复 application。"""
        from job_copilot.importer import import_tracking_csv

        session = get_session()
        self._seed_job(session,
                       "https://www.zhipin.com/job_detail/test1.html",
                       "测试公司", "AI工程师")

        # 创建临时 CSV
        csv_content = (
            "分组,公司,职位,薪资,招呼语,已发日期(填),已读(填1/0),回复(填1/0),邀约(填1/0),链接\r\n"
            '稳妥,测试公司,AI工程师,15-25K,你好测试,2026-07-01,1,0,0,'
            "https://www.zhipin.com/job_detail/test1.html\r\n"
        )
        tmp = Path(tempfile.mktemp(suffix=".csv"))
        tmp.write_text(csv_content, encoding="utf-8-sig")

        stats1 = import_tracking_csv(tmp)
        assert stats1["inserted"] == 1
        assert stats1["new_events"] == 1
        assert stats1["unlinked"] == 0

        stats2 = import_tracking_csv(tmp)
        assert stats2["inserted"] == 0
        assert stats2["skipped"] == 1  # 无变化跳过
        assert stats2["new_events"] == 0

        tmp.unlink()
        session.close()

    def test_import_with_unlinked(self):
        """CSV 行无法关联到岗位时计入 unlinked。"""
        from job_copilot.importer import import_tracking_csv

        csv_content = (
            "分组,公司,职位,薪资,招呼语,已发日期(填),已读(填1/0),回复(填1/0),邀约(填1/0),链接\r\n"
            '稳妥,不存在公司,不存在职位,15-25K,测试,2026-07-01,0,0,0,'
            "https://www.zhipin.com/job_detail/nonexist.html\r\n"
        )
        tmp = Path(tempfile.mktemp(suffix=".csv"))
        tmp.write_text(csv_content, encoding="utf-8-sig")

        stats = import_tracking_csv(tmp)
        assert stats["unlinked"] == 1
        assert stats["inserted"] == 0

        tmp.unlink()


# ============================================================
# 4. Stage → Event 测试
# ============================================================

class TestStageEvent:
    def test_stage_change_creates_event(self):
        session = get_session()
        j = Job(platform="boss", job_id="evt-1", title="测", company="测",
                collected_at="2026-01-01T00:00:00Z")
        session.add(j); session.commit()

        app = Application(job_pk=j.id, stage="SHORTLISTED")
        session.add(app); session.commit()

        # Stage change via helper
        evt = update_application_stage(session, app, "CONTACTED",
                                       content="发送招呼语")
        session.commit()

        assert evt is not None
        assert evt.event_type == "stage_change"
        assert evt.from_stage == "SHORTLISTED"
        assert evt.to_stage == "CONTACTED"
        assert "发送招呼语" in evt.content

        # Verify app stage updated
        session.refresh(app)
        assert app.stage == "CONTACTED"
        session.close()

    def test_same_stage_no_event(self):
        session = get_session()
        j = Job(platform="boss", job_id="evt-2", title="测", company="测",
                collected_at="2026-01-01T00:00:00Z")
        session.add(j); session.commit()

        app = Application(job_pk=j.id, stage="APPLIED")
        session.add(app); session.commit()

        evt = update_application_stage(session, app, "APPLIED")
        assert evt is None
        session.close()


# ============================================================
# 5. Dashboard 指标测试
# ============================================================

class TestDashboard:
    def test_empty_dashboard(self):
        r = client.get("/api/dashboard/summary")
        assert r.status_code == 200
        d = r.json()
        assert d["total_jobs"] == 0
        assert d["response_rate"] == 0.0
        assert d["interview_rate"] == 0.0

    def test_dashboard_with_data(self):
        session = get_session()
        j = Job(platform="boss", job_id="dash-1", title="岗", company="司",
                collected_at="2026-01-01T00:00:00Z", recommendation="APPLY_NOW")
        session.add(j); session.commit()

        app = Application(job_pk=j.id, stage="INTERVIEW", channel="boss")
        session.add(app); session.commit()
        session.close()

        r = client.get("/api/dashboard/summary")
        assert r.status_code == 200
        d = r.json()
        assert d["total_jobs"] == 1
        assert d["interviews"] == 1
        # INTERVIEW counts toward both contacted_plus and replied_plus
        assert d["response_rate"] == 1.0  # 1 replied_plus / 1 contacted_plus
        assert d["interview_rate"] == 1.0  # 1 interview+ / 1 applied+

    def test_response_rate_calculation(self):
        session = get_session()
        for i, stage in enumerate(["CONTACTED", "CONTACTED", "REPLIED", "OFFER"]):
            j = Job(platform="boss", job_id=f"rr-{i}", title=f"岗{i}", company="司",
                    collected_at="2026-01-01T00:00:00Z")
            session.add(j); session.commit()
            app = Application(job_pk=j.id, stage=stage, channel="boss")
            session.add(app); session.commit()
        session.close()

        r = client.get("/api/dashboard/summary")
        d = r.json()
        # contacted=2, replied=1, offers=1 → replied_plus=2, contacted_plus=4
        assert d["contacted"] == 2
        assert d["replied"] == 1
        assert d["offers"] == 1
        assert d["response_rate"] == 0.5  # 2/4 = 0.5


# ============================================================
# 6. API CRUD smoke test
# ============================================================

class TestAPICRUD:
    def test_health(self):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_docs(self):
        r = client.get("/docs")
        assert r.status_code == 200

    def test_create_and_get_job(self):
        # Seed a job directly
        session = get_session()
        j = Job(platform="boss", job_id="api-1", title="API测试岗",
                company="API测试公司", collected_at="2026-01-01T00:00:00Z")
        session.add(j); session.commit()
        jid = j.id
        session.close()

        r = client.get(f"/api/jobs/{jid}")
        assert r.status_code == 200
        assert r.json()["title"] == "API测试岗"

    def test_patch_job(self):
        session = get_session()
        j = Job(platform="boss", job_id="api-2", title="岗", company="司",
                collected_at="2026-01-01T00:00:00Z")
        session.add(j); session.commit()
        jid = j.id
        session.close()

        r = client.patch(f"/api/jobs/{jid}",
                         json={"recommendation": "APPLY_NOW"})
        assert r.status_code == 200
        assert r.json()["recommendation"] == "APPLY_NOW"

    def test_patch_and_get_full_jd_persists_exactly(self):
        session = get_session()
        j = Job(platform="boss", job_id="api-jd", title="JD测试岗", company="测试公司",
                collected_at="2026-01-01T00:00:00Z")
        session.add(j); session.commit()
        jid = j.id
        session.close()

        jd_text = (
            "岗位职责：\n"
            + "负责本地优先求职产品的需求分析、前后端协作与交付质量保障；" * 18
            + "\n任职要求：具备 Python、TypeScript、SQLite 和 API 契约测试经验。"
        )
        assert len(jd_text) > 500

        patched = client.patch(f"/api/jobs/{jid}", json={"jd_text": jd_text})
        assert patched.status_code == 200
        assert patched.json()["jd_text"] == jd_text
        assert patched.json()["jd_status"] == "FULL"

        fetched = client.get(f"/api/jobs/{jid}")
        assert fetched.status_code == 200
        assert fetched.json()["jd_text"] == jd_text

        session = get_session()
        stored = session.get(Job, jid)
        assert stored is not None
        assert stored.jd_text == jd_text
        assert session.query(JobScore).count() == 0
        assert session.query(JobVector).count() == 0
        session.close()

    @pytest.mark.parametrize("invalid_jd", [None, "", "   \n\t", "内容太短"])
    def test_patch_job_rejects_invalid_jd(self, invalid_jd):
        session = get_session()
        j = Job(platform="boss", job_id="bad-jd", title="岗", company="司",
                collected_at="2026-01-01T00:00:00Z", jd_text="原有的有效职位描述内容，长度足够用于验证不会被错误覆盖。")
        session.add(j); session.commit()
        jid = j.id
        original = j.jd_text
        session.close()

        r = client.patch(f"/api/jobs/{jid}", json={"jd_text": invalid_jd})
        assert r.status_code == 422

        session = get_session()
        assert session.get(Job, jid).jd_text == original
        session.close()

    @pytest.mark.parametrize("alias", ["jd", "description"])
    def test_patch_job_rejects_unknown_jd_alias(self, alias):
        session = get_session()
        j = Job(platform="boss", job_id="bad-alias", title="岗", company="司",
                collected_at="2026-01-01T00:00:00Z")
        session.add(j); session.commit()
        jid = j.id
        session.close()

        r = client.patch(
            f"/api/jobs/{jid}",
            json={alias: "这是一段不应被静默接受为 JD 的长文本。" * 10},
        )
        assert r.status_code == 422

    def test_patch_job_not_found(self):
        r = client.patch(
            "/api/jobs/99999",
            json={"jd_text": "这是一段长度足够但对应职位不存在的完整职位描述。" * 5},
        )
        assert r.status_code == 404

    def test_patch_job_requires_authentication(self):
        session = get_session()
        j = Job(platform="boss", job_id="auth-jd", title="岗", company="司",
                collected_at="2026-01-01T00:00:00Z")
        session.add(j); session.commit()
        jid = j.id
        session.close()

        with TestClient(fastapi_app) as anonymous_client:
            r = anonymous_client.patch(
                f"/api/jobs/{jid}",
                json={"jd_text": "这是一段长度足够但未认证用户无权保存的完整职位描述。" * 5},
            )
        assert r.status_code == 401

    def test_create_application(self):
        session = get_session()
        j = Job(platform="boss", job_id="api-3", title="岗", company="司",
                collected_at="2026-01-01T00:00:00Z")
        session.add(j); session.commit()
        jid = j.id
        session.close()

        r = client.post(f"/api/jobs/{jid}/application",
                        json={"stage": "SHORTLISTED", "channel": "boss"})
        assert r.status_code == 201
        assert r.json()["stage"] == "SHORTLISTED"
        assert len(r.json()["events"]) == 1

    def test_duplicate_application_rejected(self):
        session = get_session()
        j = Job(platform="boss", job_id="api-4", title="岗", company="司",
                collected_at="2026-01-01T00:00:00Z")
        session.add(j); session.commit()
        jid = j.id
        session.close()

        r1 = client.post(f"/api/jobs/{jid}/application",
                         json={"stage": "SHORTLISTED"})
        assert r1.status_code == 201
        r2 = client.post(f"/api/jobs/{jid}/application",
                         json={"stage": "SHORTLISTED"})
        assert r2.status_code == 409

    def test_list_applications(self):
        r = client.get("/api/applications")
        assert r.status_code == 200
        assert "items" in r.json()

    def test_export_csv(self):
        r = client.get("/api/export/applications.csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]

    def test_follow_ups(self):
        r = client.get("/api/follow-ups")
        assert r.status_code == 200
        d = r.json()
        assert "overdue" in d
        assert "due_today" in d

    def test_job_not_found(self):
        r = client.get("/api/jobs/99999")
        assert r.status_code == 404

    def test_application_not_found(self):
        r = client.get("/api/applications/99999")
        assert r.status_code == 404


# ============================================================
# 7. 现有命令不受影响
# ============================================================

class TestExistingCommandsUnaffected:
    def test_job_stats_still_works(self):
        """db.py stats 在迁移后仍可用。"""
        from job_copilot import db
        session = get_session()
        j = Job(platform="boss", job_id="legacy-1", title="测", company="测",
                collected_at="2026-01-01T00:00:00Z")
        session.add(j); session.commit()
        session.close()

        # Use the raw sqlite3 connection from db.py
        conn = db.connect()
        stats = db.job_stats(conn)
        assert stats["total"] >= 1
        assert "boss" in str(stats["by_platform"])

    def test_status_command_runs(self):
        """status 命令不抛异常。"""
        from job_copilot.__main__ import cmd_status
        cmd_status()  # should not raise
