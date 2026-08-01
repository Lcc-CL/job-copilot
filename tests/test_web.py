"""定向测试：数据模型、迁移、导入幂等、stage→event、Dashboard、API smoke。"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

# ---- 使用临时 SQLite 数据库（文件模式，确保跨连接共享） ----
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

from job_copilot.database import get_engine, get_session, init_db
from job_copilot.models import (
    Base, Job, JobScore, JobVector, Application, ApplicationEvent, SyncRun,
    ResumeProfile, ResumeVersion, APPLICATION_STAGES,
)
from job_copilot.web import app as fastapi_app
from job_copilot.importer import update_application_stage

# 重置 engine 缓存，使用测试数据库
import job_copilot.database as _db_mod
_db_mod._engine = None
_db_mod._SessionLocal = None

client = TestClient(fastapi_app)

MASTER_RESUME_TEXT = """# 母版简历

具备 Python、FastAPI 和 SQLite 本地 Web 产品交付经验。

- 负责本地优先求职产品的 API 契约、前端交互与数据持久化验证。
- 使用 TypeScript 构建可维护的 Web 用户界面。
"""

FULL_JD_TEXT = (
    "岗位职责：负责本地优先 Web 产品的 Python、FastAPI、SQLite API 开发与交付；"
    "与 TypeScript 前端协作，确保数据持久化、错误状态和用户操作可审计。"
    "任职要求：熟悉 Python、FastAPI、SQLite、TypeScript，能够编写定向测试并保障接口契约。"
    "该岗位强调真实业务证据、稳定交付和本地数据安全。"
)


def _fake_resume_result() -> dict:
    summary = "具备 Python、FastAPI 和 SQLite 本地 Web 产品交付经验。"
    bullet = "负责本地优先求职产品的 API 契约、前端交互与数据持久化验证。"
    return {
        "tailored_summary": summary,
        "summary_evidence": [{"claim": summary, "source_text": summary}],
        "reordered_skills": ["Python", "FastAPI", "SQLite"],
        "skills_evidence": [
            {"skill": "Python", "source_text": summary},
            {"skill": "FastAPI", "source_text": summary},
            {"skill": "SQLite", "source_text": summary},
        ],
        "experience_bullets": [{
            "original_text": bullet,
            "tailored_text": bullet,
            "reason": "保留母版原文，与 JD 直接相关",
            "evidence_reference": bullet,
            "risk_level": "SAFE",
        }],
        "matched_keywords": ["Python", "FastAPI", "SQLite"],
        "unsupported_requirements": [],
        "hard_blockers": [],
        "warnings": [],
    }


def _seed_resume_application(jd_text: str = FULL_JD_TEXT) -> int:
    session = get_session()
    profile = ResumeProfile(
        name="测试母版简历",
        content_text=MASTER_RESUME_TEXT,
        is_master=1,
        created_at="2026-07-31T00:00:00+00:00",
        updated_at="2026-07-31T00:00:00+00:00",
    )
    job = Job(
        platform="boss",
        job_id=f"resume-{abs(hash(jd_text))}",
        title="Python Web 工程师",
        company="测试公司",
        jd_text=jd_text,
        collected_at="2026-01-01T00:00:00Z",
    )
    session.add_all([profile, job])
    session.commit()
    application = Application(
        job_pk=job.id,
        stage="SHORTLISTED",
        channel="boss",
    )
    session.add(application)
    session.commit()
    application_id = application.id
    session.close()
    return application_id


@pytest.fixture(autouse=True)
def _reset_db():
    """每个测试前重建数据库表。"""
    engine = get_engine()
    Base.metadata.drop_all(bind=engine)
    init_db(engine=engine, create_backup=False)
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
        assert "resume_profiles" in tables
        assert "resume_versions" in tables
        assert "schema_version" in tables

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

    def test_empty_resume_versions_returns_empty_list(self):
        session = get_session()
        j = Job(platform="boss", job_id="resume-empty", title="岗", company="司",
                collected_at="2026-01-01T00:00:00Z")
        session.add(j); session.commit()
        application = Application(job_pk=j.id, stage="SHORTLISTED", channel="boss")
        session.add(application); session.commit()
        application_id = application.id
        session.close()

        r = client.get(f"/api/applications/{application_id}/resume-versions")
        assert r.status_code == 200
        assert r.json() == []

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
# 7. ResumeVersion 严格状态机
# ============================================================

class TestResumeWorkflow:
    def _generate(self, application_id: int) -> dict:
        with patch(
            "job_copilot.resume_tailor._llm_tailor",
            return_value=_fake_resume_result(),
        ) as fake_llm:
            response = client.post(
                f"/api/applications/{application_id}/resume-tailor"
            )
        assert response.status_code == 201, response.text
        fake_llm.assert_called_once()
        return response.json()

    def test_create_resume_version_is_draft_and_listed(self):
        application_id = _seed_resume_application()
        version = self._generate(application_id)

        assert version["status"] == "DRAFT"
        assert version["created_at"]
        assert version["reviewed_at"] is None
        assert version["used_at"] is None
        assert [e["event_type"] for e in version["status_events"]] == [
            "resume_created"
        ]

        listed = client.get(
            f"/api/applications/{application_id}/resume-versions"
        )
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()] == [version["id"]]

    def test_draft_to_reviewed_to_used_records_timestamps_and_events(self):
        application_id = _seed_resume_application()
        version = self._generate(application_id)

        reviewed = client.post(
            f"/api/resume-versions/{version['id']}/review"
        )
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["status"] == "REVIEWED"
        assert reviewed.json()["reviewed_at"]
        assert reviewed.json()["used_at"] is None

        used = client.post(f"/api/resume-versions/{version['id']}/use")
        assert used.status_code == 200, used.text
        payload = used.json()
        assert payload["status"] == "USED"
        assert payload["reviewed_at"]
        assert payload["used_at"]
        assert [e["event_type"] for e in payload["status_events"]] == [
            "resume_created", "resume_reviewed", "resume_used"
        ]
        for event in payload["status_events"]:
            assert event["resume_version_id"] == version["id"]
            assert event["application_id"] == application_id
            assert event["to_status"] in {"DRAFT", "REVIEWED", "USED"}
            assert event["timestamp"]

        refreshed = client.get(f"/api/resume-versions/{version['id']}")
        assert refreshed.status_code == 200
        assert refreshed.json()["status"] == "USED"
        assert refreshed.json()["reviewed_at"] == payload["reviewed_at"]
        assert refreshed.json()["used_at"] == payload["used_at"]

        session = get_session()
        stored = session.get(ResumeVersion, version["id"])
        events = session.query(ApplicationEvent).filter(
            ApplicationEvent.application_id == application_id,
            ApplicationEvent.event_type.in_({
                "resume_created", "resume_reviewed", "resume_used"
            }),
        ).order_by(ApplicationEvent.id).all()
        assert stored.status == "USED"
        assert [(e.from_stage, e.to_stage) for e in events] == [
            (None, "DRAFT"),
            ("DRAFT", "REVIEWED"),
            ("REVIEWED", "USED"),
        ]
        for event in events:
            audit = json.loads(event.content)
            assert audit["resume_version_id"] == version["id"]
            assert audit["application_id"] == application_id
            assert audit["from_status"] == event.from_stage
            assert audit["to_status"] == event.to_stage
            assert audit["timestamp"] == event.occurred_at
        session.close()

    def test_two_versions_keep_independent_events_and_timestamps(self):
        application_id = _seed_resume_application()
        version_a = self._generate(application_id)
        version_b = self._generate(application_id)

        reviewed_a = client.post(
            f"/api/resume-versions/{version_a['id']}/review"
        )
        assert reviewed_a.status_code == 200
        used_a = client.post(
            f"/api/resume-versions/{version_a['id']}/use"
        )
        assert used_a.status_code == 200

        untouched_b = client.get(
            f"/api/resume-versions/{version_b['id']}"
        ).json()
        assert untouched_b["status"] == "DRAFT"
        assert untouched_b["reviewed_at"] is None
        assert untouched_b["used_at"] is None
        assert [e["event_type"] for e in untouched_b["status_events"]] == [
            "resume_created"
        ]
        assert all(
            event["resume_version_id"] == version_b["id"]
            for event in untouched_b["status_events"]
        )

        reviewed_b = client.post(
            f"/api/resume-versions/{version_b['id']}/review"
        )
        assert reviewed_b.status_code == 200
        reviewed_b_payload = reviewed_b.json()
        assert reviewed_b_payload["reviewed_at"]
        assert reviewed_b_payload["used_at"] is None

        refreshed_a = client.get(
            f"/api/resume-versions/{version_a['id']}"
        ).json()
        assert refreshed_a["status"] == "USED"
        assert refreshed_a["reviewed_at"] == reviewed_a.json()["reviewed_at"]
        assert refreshed_a["used_at"] == used_a.json()["used_at"]
        assert all(
            event["resume_version_id"] == version_a["id"]
            for event in refreshed_a["status_events"]
        )

    def test_duplicate_review_and_use_do_not_duplicate_events_or_timestamps(self):
        application_id = _seed_resume_application()
        version = self._generate(application_id)

        reviewed = client.post(
            f"/api/resume-versions/{version['id']}/review"
        )
        assert reviewed.status_code == 200
        reviewed_at = reviewed.json()["reviewed_at"]

        duplicate_review = client.post(
            f"/api/resume-versions/{version['id']}/review"
        )
        assert duplicate_review.status_code == 409
        after_duplicate_review = client.get(
            f"/api/resume-versions/{version['id']}"
        ).json()
        assert after_duplicate_review["reviewed_at"] == reviewed_at
        assert sum(
            event["event_type"] == "resume_reviewed"
            for event in after_duplicate_review["status_events"]
        ) == 1

        used = client.post(f"/api/resume-versions/{version['id']}/use")
        assert used.status_code == 200
        used_at = used.json()["used_at"]

        duplicate_use = client.post(
            f"/api/resume-versions/{version['id']}/use"
        )
        assert duplicate_use.status_code == 409
        after_duplicate_use = client.get(
            f"/api/resume-versions/{version['id']}"
        ).json()
        assert after_duplicate_use["reviewed_at"] == reviewed_at
        assert after_duplicate_use["used_at"] == used_at
        assert sum(
            event["event_type"] == "resume_used"
            for event in after_duplicate_use["status_events"]
        ) == 1

    def test_event_write_failure_rolls_back_status_change(self):
        application_id = _seed_resume_application()
        version = self._generate(application_id)

        def add_invalid_event(session, rv, *_args):
            session.add(ApplicationEvent(
                application_id=rv.application_id,
                event_type=None,
                from_stage="DRAFT",
                to_stage="REVIEWED",
                occurred_at="2026-08-01T00:00:00+00:00",
            ))

        from job_copilot.resume_tailor import review_version
        with patch(
            "job_copilot.resume_tailor._add_resume_event",
            side_effect=add_invalid_event,
        ):
            with pytest.raises(IntegrityError):
                review_version(version["id"])

        session = get_session()
        stored = session.get(ResumeVersion, version["id"])
        review_events = session.query(ApplicationEvent).filter(
            ApplicationEvent.application_id == application_id,
            ApplicationEvent.event_type == "resume_reviewed",
        ).count()
        assert stored.status == "DRAFT"
        assert review_events == 0
        session.close()

    def test_draft_cannot_skip_directly_to_used(self):
        application_id = _seed_resume_application()
        version = self._generate(application_id)

        response = client.post(f"/api/resume-versions/{version['id']}/use")
        assert response.status_code == 409
        assert "DRAFT -> USED" in response.json()["detail"]

    def test_used_cannot_transition_back_to_reviewed(self):
        application_id = _seed_resume_application()
        version = self._generate(application_id)
        assert client.post(
            f"/api/resume-versions/{version['id']}/review"
        ).status_code == 200
        assert client.post(
            f"/api/resume-versions/{version['id']}/use"
        ).status_code == 200

        response = client.post(
            f"/api/resume-versions/{version['id']}/review"
        )
        assert response.status_code == 409
        assert "USED -> REVIEWED" in response.json()["detail"]

    def test_general_patch_cannot_modify_status(self):
        application_id = _seed_resume_application()
        version = self._generate(application_id)

        response = client.patch(
            f"/api/resume-versions/{version['id']}",
            json={"status": "USED"},
        )
        assert response.status_code == 422

        stored = client.get(f"/api/resume-versions/{version['id']}")
        assert stored.json()["status"] == "DRAFT"

    def test_incomplete_jd_version_cannot_be_reviewed(self):
        application_id = _seed_resume_application("Python FastAPI 本地 Web 岗位")
        with patch("job_copilot.resume_tailor._llm_tailor") as llm:
            generated = client.post(
                f"/api/applications/{application_id}/resume-tailor"
            )
        assert generated.status_code == 201, generated.text
        assert generated.json()["status"] == "DRAFT"
        assert generated.json()["generation_method"] == "low_context_rule_based"
        llm.assert_not_called()

        reviewed = client.post(
            f"/api/resume-versions/{generated.json()['id']}/review"
        )
        assert reviewed.status_code == 422
        assert "complete JD" in reviewed.json()["detail"]

    def test_generation_rejects_summary_without_evidence(self):
        application_id = _seed_resume_application()
        invalid_result = _fake_resume_result()
        invalid_result["summary_evidence"] = []

        with patch(
            "job_copilot.resume_tailor._llm_tailor",
            return_value=invalid_result,
        ) as fake_llm:
            response = client.post(
                f"/api/applications/{application_id}/resume-tailor"
            )
        assert response.status_code == 422
        assert "evidence-backed Summary" in response.json()["detail"]
        fake_llm.assert_called_once()

        session = get_session()
        assert session.query(ResumeVersion).count() == 0
        assert session.query(JobScore).count() == 0
        assert session.query(JobVector).count() == 0
        session.close()

    def test_review_rechecks_persisted_evidence(self):
        application_id = _seed_resume_application()
        version = self._generate(application_id)

        session = get_session()
        stored = session.get(ResumeVersion, version["id"])
        gap = json.loads(stored.gap_analysis_json)
        gap["evidence"]["skills"] = []
        stored.skills_json = json.dumps(["Python"], ensure_ascii=False)
        stored.gap_analysis_json = json.dumps(gap, ensure_ascii=False)
        session.commit()
        session.close()

        response = client.post(
            f"/api/resume-versions/{version['id']}/review"
        )
        assert response.status_code == 422
        assert "Skill lacks" in response.json()["detail"]

    def test_resume_endpoints_return_real_auth_and_not_found_statuses(self):
        application_id = _seed_resume_application()
        version = self._generate(application_id)

        with TestClient(fastapi_app) as anonymous_client:
            assert anonymous_client.post(
                f"/api/applications/{application_id}/resume-tailor"
            ).status_code == 401
            assert anonymous_client.post(
                f"/api/resume-versions/{version['id']}/review"
            ).status_code == 401
            assert anonymous_client.post(
                f"/api/resume-versions/{version['id']}/use"
            ).status_code == 401

        assert client.get(
            "/api/applications/99999/resume-versions"
        ).status_code == 404
        assert client.post(
            "/api/resume-versions/99999/review"
        ).status_code == 404
        assert client.post(
            "/api/resume-versions/99999/use"
        ).status_code == 404


# ============================================================
# 8. 现有命令不受影响
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
        conn = db.connect(Path(_tmp_db.name))
        stats = db.job_stats(conn)
        assert stats["total"] >= 1
        assert "boss" in str(stats["by_platform"])

    def test_status_command_runs(self):
        """status 命令不抛异常。"""
        from job_copilot.__main__ import cmd_status
        cmd_status()  # should not raise
