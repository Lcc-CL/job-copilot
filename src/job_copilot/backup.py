"""数据导出/导入 —— JSON 备份，跨数据库迁移。

导出包含: jobs, applications, application_events, job_scores, sync_runs, schema_version
不导出: Cookie, Token, password hashes, SESSION_SECRET, 向量 blob
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from .database import get_session, get_engine

EXPORT_VERSION = 1


def export_data(output_path: str) -> str:
    """导出数据到 JSON 文件。"""
    output = Path(output_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)

    session = get_session()
    engine = get_engine()
    data = {
        "version": EXPORT_VERSION,
        "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "tables": {},
    }

    try:
        # jobs
        rows = _fetch_all(session, "SELECT * FROM jobs ORDER BY id")
        data["tables"]["jobs"] = rows

        # applications
        rows = _fetch_all(session, "SELECT * FROM applications ORDER BY id")
        data["tables"]["applications"] = rows

        # application_events
        rows = _fetch_all(session, "SELECT * FROM application_events ORDER BY id")
        data["tables"]["application_events"] = rows

        # job_scores (only metadata, not vectors)
        rows = _fetch_all(session, "SELECT * FROM job_scores ORDER BY job_pk")
        data["tables"]["job_scores"] = rows

        # sync_runs
        rows = _fetch_all(session, "SELECT * FROM sync_runs ORDER BY id")
        data["tables"]["sync_runs"] = rows

        # schema_version tracking
        try:
            rows = _fetch_all(session, "SELECT * FROM alembic_version")
            data["tables"]["alembic_version"] = rows
        except Exception:
            pass  # table may not exist

        output.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        counts = {k: len(v) for k, v in data["tables"].items()}
        return f"✓ 导出完成: {output}\n  表统计: {counts}"
    finally:
        session.close()


def import_data(input_path: str) -> str:
    """幂等导入备份 JSON。不覆盖已有 notes 和更新的 updated_at。"""
    input_path = Path(input_path).expanduser()
    if not input_path.exists():
        return f"✗ 文件不存在: {input_path}"

    data = json.loads(input_path.read_text(encoding="utf-8"))
    if data.get("version") != EXPORT_VERSION:
        return f"✗ 备份版本不兼容: {data.get('version')} (需要 {EXPORT_VERSION})"

    # Ensure schema exists before importing data
    from .database import init_db
    init_db()

    tables = data.get("tables", {})
    session = get_session()
    stats = {"inserted": 0, "updated": 0, "skipped": 0, "conflicts": 0}

    try:
        # Import order: jobs → job_scores → applications → application_events → sync_runs
        _import_table(session, "jobs", tables.get("jobs", []),
                      pk_cols=["id"], on_conflict="update", stats=stats,
                      preserve_cols=[])  # Don't overwrite user fields on jobs
        _import_table(session, "job_scores", tables.get("job_scores", []),
                      pk_cols=["job_pk"], on_conflict="upsert", stats=stats)
        _import_table(session, "applications", tables.get("applications", []),
                      pk_cols=["id"], on_conflict="merge", stats=stats,
                      preserve_cols=["notes", "stage", "next_follow_up_at", "last_contact_at"])
        _import_table(session, "application_events", tables.get("application_events", []),
                      pk_cols=["id"], on_conflict="skip", stats=stats)
        _import_table(session, "sync_runs", tables.get("sync_runs", []),
                      pk_cols=["id"], on_conflict="skip", stats=stats)

        if tables.get("alembic_version"):
            try:
                _import_table(session, "alembic_version", tables["alembic_version"],
                              pk_cols=["version_num"], on_conflict="skip", stats=stats)
            except Exception:
                pass

        session.commit()

        return (
            f"✓ 导入完成: {input_path.name}\n"
            f"  新增: {stats['inserted']}  更新: {stats['updated']}"
            f"  跳过: {stats['skipped']}  冲突: {stats['conflicts']}"
        )
    except Exception as e:
        session.rollback()
        return f"✗ 导入失败: {e}"
    finally:
        session.close()


def _fetch_all(session, sql: str) -> list[dict]:
    rows = session.execute(text(sql)).fetchall()
    return [dict(r._mapping) for r in rows]


def _import_table(session, table_name: str, rows: list[dict],
                  pk_cols: list[str], on_conflict: str, stats: dict,
                  preserve_cols: Optional[list[str]] = None):
    if not rows:
        return

    for row in rows:
        # Check if row exists by PK
        where = " AND ".join(f"{c}=:{c}" for c in pk_cols)
        existing = session.execute(
            text(f"SELECT * FROM {table_name} WHERE {where}"),
            {c: row[c] for c in pk_cols},
        ).fetchone()

        if existing is None:
            # Insert
            cols = [c for c in row.keys() if c in row]
            placeholders = ", ".join(f":{c}" for c in cols)
            try:
                session.execute(
                    text(f"INSERT INTO {table_name} ({', '.join(cols)}) VALUES ({placeholders})"),
                    {c: row[c] for c in cols},
                )
                stats["inserted"] += 1
            except Exception:
                stats["conflicts"] += 1
        elif on_conflict == "skip":
            stats["skipped"] += 1
        elif on_conflict == "update":
            # Update all non-PK cols
            set_cols = [c for c in row.keys() if c not in pk_cols and c in row]
            if not set_cols:
                stats["skipped"] += 1
                continue
            set_clause = ", ".join(f"{c}=:{c}" for c in set_cols)
            try:
                session.execute(
                    text(f"UPDATE {table_name} SET {set_clause} WHERE {where}"),
                    {c: row[c] for c in set_cols + pk_cols},
                )
                stats["updated"] += 1
            except Exception:
                stats["conflicts"] += 1
        elif on_conflict == "upsert":
            # Try insert, on conflict update
            cols = [c for c in row.keys() if c in row]
            placeholders = ", ".join(f":{c}" for c in cols)
            set_cols = [c for c in cols if c not in pk_cols]
            set_clause = ", ".join(f"{c}=excluded.{c}" for c in set_cols)
            try:
                session.execute(text(
                    f"INSERT INTO {table_name} ({', '.join(cols)}) VALUES ({placeholders}) "
                    f"ON CONFLICT ({', '.join(pk_cols)}) DO UPDATE SET {set_clause}"
                ), {c: row[c] for c in cols})
                stats["inserted"] += 1  # ON CONFLICT DO UPDATE counts as insert here
            except Exception:
                stats["conflicts"] += 1
        elif on_conflict == "merge":
            # Update all non-PK cols EXCEPT preserved user fields
            set_cols = [c for c in row.keys()
                        if c not in pk_cols and c in row
                        and c not in (preserve_cols or [])]
            if not set_cols:
                stats["skipped"] += 1
                continue
            set_clause = ", ".join(f"{c}=COALESCE({table_name}.{c}, :{c})" for c in set_cols)
            try:
                session.execute(
                    text(f"UPDATE {table_name} SET {set_clause} WHERE {where}"),
                    {c: row[c] for c in set_cols + pk_cols},
                )
                stats["updated"] += 1
            except Exception:
                stats["conflicts"] += 1
