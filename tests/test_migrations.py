"""Targeted tests for safe, versioned SQLite schema migrations."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from job_copilot import backup, db
from job_copilot.database import init_db
from job_copilot.migrations import CURRENT_SCHEMA_VERSION, run_schema_migrations


REQUIRED_TABLES = {
    "jobs",
    "job_vectors",
    "job_scores",
    "applications",
    "application_events",
    "sync_runs",
    "resume_profiles",
    "resume_versions",
    "local_accounts",
    "account_audit_events",
    "schema_version",
}

APPLICATION_COLUMNS = {
    "id",
    "job_pk",
    "stage",
    "priority",
    "channel",
    "resume_version",
    "applied_at",
    "last_contact_at",
    "next_follow_up_at",
    "notes",
    "created_at",
    "updated_at",
}


def _engine(path: Path):
    return create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )


def _create_legacy_database(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                job_id TEXT NOT NULL,
                url TEXT,
                title TEXT,
                company TEXT,
                company_size TEXT,
                industry TEXT,
                salary_text TEXT,
                salary_min INTEGER,
                salary_max INTEGER,
                salary_months INTEGER,
                city TEXT,
                district TEXT,
                experience TEXT,
                degree TEXT,
                tags TEXT,
                hr_name TEXT,
                hr_title TEXT,
                hr_active TEXT,
                jd_text TEXT,
                search_keyword TEXT,
                search_city TEXT,
                collected_at TEXT NOT NULL,
                UNIQUE (platform, job_id)
            );
            CREATE TABLE job_vectors (
                job_pk INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                dim INTEGER NOT NULL,
                vec BLOB NOT NULL,
                model TEXT,
                embedded_at TEXT
            );
            CREATE TABLE job_scores (
                job_pk INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                fit_score REAL,
                verdict TEXT,
                archetype TEXT,
                seniority_ok INTEGER,
                authenticity TEXT,
                reasons TEXT,
                highlights TEXT,
                gaps TEXT,
                model TEXT,
                scored_at TEXT
            );
            CREATE TABLE applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_pk INTEGER REFERENCES jobs(id),
                company TEXT,
                title TEXT,
                group_tag TEXT,
                status TEXT NOT NULL DEFAULT '已评估',
                score REAL,
                report_path TEXT,
                applied_at TEXT,
                last_event_at TEXT,
                note TEXT
            );
            CREATE TABLE schema_version (
                version TEXT PRIMARY KEY,
                applied_at TEXT
            );
            INSERT INTO schema_version (version, applied_at)
            VALUES ('20260723-01', '2026-07-23T00:00:00+00:00');
            INSERT INTO jobs (
                id, platform, job_id, title, company, collected_at
            ) VALUES (7, 'legacy', 'legacy-7', '旧职位', '旧公司', '2026-01-01');
            INSERT INTO job_vectors (job_pk, dim, vec, model)
            VALUES (7, 1, X'00000000', 'legacy-vector');
            INSERT INTO job_scores (job_pk, fit_score, verdict, model)
            VALUES (7, 3.5, '慎投', 'legacy-score');
            INSERT INTO applications (
                id, job_pk, company, title, status, note
            ) VALUES (9, 7, '旧公司', '旧职位', '已联系', '旧备注必须保留');
        """)
        conn.commit()
    finally:
        conn.close()


def _integrity(path: Path) -> tuple[str, list[tuple]]:
    conn = sqlite3.connect(path)
    try:
        quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
        return quick_check, foreign_keys
    finally:
        conn.close()


def test_fresh_database_uses_complete_orm_schema(tmp_path):
    path = tmp_path / "fresh.db"
    engine = _engine(path)

    first = run_schema_migrations(engine)
    second = run_schema_migrations(engine)

    assert REQUIRED_TABLES.issubset(set(inspect(engine).get_table_names()))
    app_columns = {column["name"] for column in inspect(engine).get_columns("applications")}
    assert APPLICATION_COLUMNS.issubset(app_columns)
    assert first.backup_path is None
    assert first.applied_versions == ("20260731-01", CURRENT_SCHEMA_VERSION)
    assert second.changes == ()
    assert second.applied_versions == ()
    assert second.backup_path is None
    assert _integrity(path) == ("ok", [])
    engine.dispose()


def test_raw_db_connect_initializes_new_database_from_orm(tmp_path):
    path = tmp_path / "raw-connect.db"
    conn = db.connect(path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert REQUIRED_TABLES.issubset(tables)
    finally:
        conn.close()


def test_legacy_database_upgrade_is_lossless_and_backed_up(tmp_path):
    path = tmp_path / "legacy.db"
    _create_legacy_database(path)
    engine = _engine(path)

    with engine.connect() as conn:
        before = {
            table: conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            for table in ("jobs", "job_vectors", "job_scores", "applications")
        }
    report = run_schema_migrations(engine)

    tables = set(inspect(engine).get_table_names())
    app_columns = {column["name"] for column in inspect(engine).get_columns("applications")}
    with engine.connect() as conn:
        after = {
            table: conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            for table in ("jobs", "job_vectors", "job_scores", "applications")
        }

    assert before == after == {
        "jobs": 1,
        "job_vectors": 1,
        "job_scores": 1,
        "applications": 1,
    }
    assert REQUIRED_TABLES.issubset(tables)
    assert APPLICATION_COLUMNS.issubset(app_columns)
    assert {"status", "note", "company", "title"}.issubset(app_columns)
    with engine.connect() as conn:
        migrated = conn.execute(
            text("SELECT id, job_pk, stage, status, note FROM applications WHERE id=9")
        ).one()
        assert tuple(migrated) == (9, 7, "DISCOVERED", "已联系", "旧备注必须保留")
        versions = {
            row[0] for row in conn.execute(text("SELECT version FROM schema_version"))
        }
        assert versions == {
            "20260723-01",
            "20260731-01",
            CURRENT_SCHEMA_VERSION,
        }

    assert report.backup_path is not None
    assert report.backup_path.exists()
    assert report.backup_path.stat().st_mode & 0o777 == 0o600
    backup_conn = sqlite3.connect(report.backup_path)
    try:
        backup_tables = {
            row[0]
            for row in backup_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "resume_versions" not in backup_tables
        assert backup_conn.execute(
            "SELECT status, note FROM applications WHERE id=9"
        ).fetchone() == ("已联系", "旧备注必须保留")
        assert backup_conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        backup_conn.close()

    assert _integrity(path) == ("ok", [])
    engine.dispose()


def test_missing_resume_tables_are_repaired_even_at_current_version(tmp_path):
    path = tmp_path / "missing-resume.db"
    engine = _engine(path)
    init_db(engine=engine)

    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE resume_versions")
        conn.exec_driver_sql("DROP TABLE resume_profiles")

    repaired = run_schema_migrations(engine)
    no_op = run_schema_migrations(engine)

    tables = set(inspect(engine).get_table_names())
    assert {"resume_profiles", "resume_versions"}.issubset(tables)
    assert repaired.backup_path is not None
    assert "table: resume_profiles" in repaired.changes
    assert "table: resume_versions" in repaired.changes
    assert no_op == type(no_op)((), (), None)
    engine.dispose()


def test_logical_backup_restores_resume_and_schema_version(tmp_path):
    source_path = tmp_path / "source.db"
    source_engine = _engine(source_path)
    init_db(engine=source_engine)

    with source_engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO jobs (id, platform, job_id, title, company, collected_at)
            VALUES (1, 'test', 'backup-job', '备份职位', '备份公司', '2026-01-01')
        """))
        conn.execute(text("""
            INSERT INTO applications (id, job_pk, stage, channel)
            VALUES (1, 1, 'SHORTLISTED', 'test')
        """))
        conn.execute(text("""
            INSERT INTO resume_profiles (id, name, content_text, is_master)
            VALUES (1, '母版', '真实简历内容', 1)
        """))
        conn.execute(text("""
            INSERT INTO resume_versions (
                id, application_id, resume_profile_id, version_name, status
            ) VALUES (1, 1, 1, 'v1', 'DRAFT')
        """))
        conn.execute(text("""
            INSERT INTO local_accounts (
                id, username, password_hash, session_version, source_type
            ) VALUES (1, 'backup-user', 'test-hash-must-not-export', 1, 'database')
        """))
        conn.execute(text("""
            INSERT INTO account_audit_events (
                id, account_id, event_type, details_json, occurred_at
            ) VALUES (1, 1, 'password_changed', '{}', '2026-08-01T00:00:00+00:00')
        """))

    export_path = tmp_path / "backup.json"
    export_message = backup.export_data(str(export_path), engine=source_engine)
    exported = json.loads(export_path.read_text(encoding="utf-8"))

    assert "导出完成" in export_message
    assert exported["tables"]["resume_profiles"][0]["name"] == "母版"
    assert exported["tables"]["resume_versions"][0]["version_name"] == "v1"
    assert "local_accounts" not in exported["tables"]
    assert "account_audit_events" not in exported["tables"]
    assert "test-hash-must-not-export" not in export_path.read_text(encoding="utf-8")
    assert CURRENT_SCHEMA_VERSION in {
        row["version"] for row in exported["tables"]["schema_version"]
    }

    restored_path = tmp_path / "restored.db"
    restored_engine = _engine(restored_path)
    restore_message = backup.import_data(str(export_path), engine=restored_engine)

    assert "导入完成" in restore_message
    with restored_engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM jobs")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM applications")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM resume_profiles")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM resume_versions")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM local_accounts")).scalar_one() == 0
        versions = {
            row[0] for row in conn.execute(text("SELECT version FROM schema_version"))
        }
        assert CURRENT_SCHEMA_VERSION in versions

    assert _integrity(restored_path) == ("ok", [])
    source_engine.dispose()
    restored_engine.dispose()
