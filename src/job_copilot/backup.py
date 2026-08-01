"""数据导出/导入 —— JSON 备份，跨数据库迁移。

导出包含: jobs, applications, application_events, job_scores, sync_runs,
resume_profiles, resume_versions, schema_version
不导出: Cookie, Token, password hashes, SESSION_SECRET, 向量 blob
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Optional

from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session

from .database import get_engine

EXPORT_VERSION = 1


def export_data(output_path: str, *, engine: Optional[Engine] = None) -> str:
    """导出数据到 JSON 文件。"""
    output = Path(output_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)

    target_engine = engine or get_engine()
    session = Session(target_engine)
    data = {
        "version": EXPORT_VERSION,
        "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "tables": {},
    }

    try:
        export_tables = [
            ("jobs", "id"),
            ("applications", "id"),
            ("application_events", "id"),
            ("job_scores", "job_pk"),
            ("sync_runs", "id"),
            ("resume_profiles", "id"),
            ("resume_versions", "id"),
            ("schema_version", "version"),
        ]
        existing_tables = set(inspect(target_engine).get_table_names())
        for table_name, order_column in export_tables:
            if table_name in existing_tables:
                data["tables"][table_name] = _fetch_all(
                    session,
                    f"SELECT * FROM {table_name} ORDER BY {order_column}",
                )

        output.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        counts = {k: len(v) for k, v in data["tables"].items()}
        return f"✓ 导出完成: {output}\n  表统计: {counts}"
    finally:
        session.close()


def import_data(input_path: str, *, engine: Optional[Engine] = None) -> str:
    """幂等导入备份 JSON。不覆盖已有 notes 和更新的 updated_at。"""
    input_path = Path(input_path).expanduser()
    if not input_path.exists():
        return f"✗ 文件不存在: {input_path}"

    data = json.loads(input_path.read_text(encoding="utf-8"))
    if data.get("version") != EXPORT_VERSION:
        return f"✗ 备份版本不兼容: {data.get('version')} (需要 {EXPORT_VERSION})"

    # Ensure schema exists before importing data
    from .database import init_db
    target_engine = engine or get_engine()
    init_db(engine=target_engine)

    tables = data.get("tables", {})
    session = Session(target_engine)
    stats = {"inserted": 0, "updated": 0, "skipped": 0, "conflicts": 0}

    try:
        # Import order follows foreign-key dependencies.
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
        _import_table(session, "resume_profiles", tables.get("resume_profiles", []),
                      pk_cols=["id"], on_conflict="merge", stats=stats)
        _import_table(session, "resume_versions", tables.get("resume_versions", []),
                      pk_cols=["id"], on_conflict="merge", stats=stats)
        _import_table(session, "schema_version", tables.get("schema_version", []),
                      pk_cols=["version"], on_conflict="skip", stats=stats)

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

    table_columns = {
        column["name"]
        for column in inspect(session.get_bind()).get_columns(table_name)
    }

    for row in rows:
        row = {key: value for key, value in row.items() if key in table_columns}
        if not all(column in row for column in pk_cols):
            stats["conflicts"] += 1
            continue
        # Check if row exists by PK
        where = " AND ".join(f"{c}=:{c}" for c in pk_cols)
        existing = session.execute(
            text(f"SELECT * FROM {table_name} WHERE {where}"),
            {c: row[c] for c in pk_cols},
        ).fetchone()

        if existing is None:
            # Insert
            cols = list(row)
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
            set_cols = [c for c in row if c not in pk_cols]
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
            cols = list(row)
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
            set_cols = [c for c in row
                        if c not in pk_cols
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
