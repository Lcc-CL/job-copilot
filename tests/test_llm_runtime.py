from __future__ import annotations

import logging
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from job_copilot import db, enrich, llm, score
from job_copilot.llm_runtime import (
    LLMDryRun,
    LLMRuntimeError,
    get_runtime,
    split_persisted_model,
)


def _config(*, api_key: str = "test-key", base_url: str = "https://llm.invalid"):
    return SimpleNamespace(llm={
        "provider": "test-provider",
        "api_key": api_key,
        "base_url": base_url,
        "model_analysis": "analysis-model",
        "model_drafting": "draft-model",
    })


def test_unconfigured_mode_defaults_to_dry_run():
    with patch.dict(os.environ, {}, clear=False), patch(
        "job_copilot.llm_runtime.load_config", return_value=_config()
    ):
        os.environ.pop("LLM_MODE", None)
        runtime = get_runtime("score")
    assert runtime.mode == "dry-run"
    assert runtime.network_enabled is False


def test_fake_mode_is_deterministic_and_never_builds_network_client():
    with patch.dict(os.environ, {"LLM_MODE": "fake"}), patch(
        "job_copilot.llm_runtime.load_config", return_value=_config()
    ), patch("job_copilot.llm._get_client") as get_client:
        first = llm.chat_json(
            "system", "user", operation="score",
            fake_response={"fit_score": 3},
        )
        second = llm.chat_json(
            "system", "user", operation="score",
            fake_response={"fit_score": 3},
        )

    get_client.assert_not_called()
    assert first == second
    assert first["_llm_source"] == "fake"


def test_dry_run_validates_request_without_network():
    with patch.dict(os.environ, {"LLM_MODE": "dry-run"}), patch(
        "job_copilot.llm_runtime.load_config", return_value=_config()
    ), patch("job_copilot.llm._get_client") as get_client:
        with pytest.raises(LLMDryRun) as caught:
            llm.chat_json(
                "system", "user", operation="resume_tailor", max_tokens=8000
            )

    get_client.assert_not_called()
    preview = caught.value.preview
    assert preview["status"] == "dry-run"
    assert preview["request"]["validated"] is True
    assert preview["request"]["network_request_sent"] is False


@pytest.mark.parametrize(
    ("api_key", "base_url", "code"),
    [
        ("", "https://llm.invalid", "LLM_API_KEY_MISSING"),
        ("test-key", "", "LLM_BASE_URL_MISSING"),
    ],
)
def test_live_requires_key_and_base_url(api_key, base_url, code):
    with patch.dict(os.environ, {"LLM_MODE": "live"}), patch(
        "job_copilot.llm_runtime.load_config",
        return_value=_config(api_key=api_key, base_url=base_url),
    ), patch("job_copilot.llm._get_client") as get_client:
        with pytest.raises(LLMRuntimeError) as caught:
            llm.chat_json("system", "user", operation="score")

    get_client.assert_not_called()
    assert caught.value.code == code


def test_stubbed_live_result_is_marked_live_without_external_request():
    response = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content='{"fit_score": 4}')
    )])
    completions = SimpleNamespace(create=Mock(return_value=response))
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    with patch.dict(os.environ, {"LLM_MODE": "live"}), patch(
        "job_copilot.llm_runtime.load_config", return_value=_config()
    ), patch("job_copilot.llm._get_client", return_value=client):
        result = llm.chat_json("system", "user", operation="score")

    assert result["_llm_source"] == "live"
    completions.create.assert_called_once()


def test_audit_log_contains_metadata_but_not_secrets_or_prompt(caplog):
    caplog.set_level(logging.INFO, logger="job_copilot.llm.audit")
    secret = "never-log-this-key"
    private_prompt = "PRIVATE RESUME CONTENT"
    with patch.dict(os.environ, {"LLM_MODE": "fake"}), patch(
        "job_copilot.llm_runtime.load_config",
        return_value=_config(api_key=secret),
    ):
        llm.chat_json(
            "system", private_prompt, operation="resume_tailor",
            fake_response={"result": "ok"},
        )

    log_text = caplog.text
    assert "llm_call_audit" in log_text
    assert '"mode": "fake"' in log_text
    assert '"operation": "resume_tailor"' in log_text
    assert secret not in log_text
    assert private_prompt not in log_text
    assert "Authorization" not in log_text


def test_fake_score_is_persisted_with_source_marker(tmp_path):
    conn = db.connect(tmp_path / "score.db")
    try:
        conn.execute(
            "INSERT INTO jobs (platform, job_id, title, company, collected_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test", "runtime-1", "测试岗位", "测试公司", "2026-08-01"),
        )
        conn.commit()
        job_id = conn.execute(
            "SELECT id FROM jobs WHERE job_id='runtime-1'"
        ).fetchone()[0]

        with patch.dict(os.environ, {"LLM_MODE": "fake"}), patch(
            "job_copilot.llm_runtime.load_config", return_value=_config()
        ):
            result = score.score_one(
                conn,
                {"id": job_id, "title": "测试岗位", "company": "测试公司"},
                "Python FastAPI",
                "analysis-model",
            )

        stored_model = conn.execute(
            "SELECT model FROM job_scores WHERE job_pk = ?", (job_id,)
        ).fetchone()[0]
        assert result["source"] == "fake"
        assert split_persisted_model(stored_model) == ("fake", "analysis-model")
    finally:
        conn.close()


def test_dry_run_score_does_not_write_job_score(tmp_path):
    conn = db.connect(tmp_path / "dry-run-score.db")
    try:
        conn.execute(
            "INSERT INTO jobs (platform, job_id, title, company, collected_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test", "runtime-2", "测试岗位", "测试公司", "2026-08-01"),
        )
        conn.commit()
        job_id = conn.execute(
            "SELECT id FROM jobs WHERE job_id='runtime-2'"
        ).fetchone()[0]

        with patch.dict(os.environ, {"LLM_MODE": "dry-run"}), patch(
            "job_copilot.llm_runtime.load_config", return_value=_config()
        ):
            with pytest.raises(LLMDryRun):
                score.score_one(
                    conn,
                    {"id": job_id, "title": "测试岗位", "company": "测试公司"},
                    "Python FastAPI",
                    "analysis-model",
                )

        assert conn.execute("SELECT COUNT(*) FROM job_scores").fetchone()[0] == 0
    finally:
        conn.close()


def test_enrich_fake_and_dry_run_follow_the_same_gate(tmp_path):
    conn = db.connect(tmp_path / "enrich.db")
    try:
        conn.execute(
            "INSERT INTO jobs (platform, job_id, title, company, jd_text, collected_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "test",
                "runtime-3",
                "测试岗位",
                "测试公司",
                "完整岗位职责和任职要求。" * 20,
                "2026-08-01",
            ),
        )
        conn.commit()
        row = dict(conn.execute(
            "SELECT * FROM jobs WHERE job_id='runtime-3'"
        ).fetchone())

        with patch.dict(os.environ, {"LLM_MODE": "dry-run"}), patch(
            "job_copilot.llm_runtime.load_config", return_value=_config()
        ):
            preview = enrich.rescore_one(
                conn, row, "Python FastAPI", "analysis-model"
            )
        assert preview["source"] == "dry-run"
        assert conn.execute("SELECT COUNT(*) FROM job_scores").fetchone()[0] == 0

        with patch.dict(os.environ, {"LLM_MODE": "fake"}), patch(
            "job_copilot.llm_runtime.load_config", return_value=_config()
        ):
            result = enrich.rescore_one(
                conn, row, "Python FastAPI", "analysis-model"
            )
        stored_model = conn.execute(
            "SELECT model FROM job_scores WHERE job_pk = ?", (row["id"],)
        ).fetchone()[0]
        assert result["source"] == "fake"
        assert split_persisted_model(stored_model) == ("fake", "analysis-model")
    finally:
        conn.close()
