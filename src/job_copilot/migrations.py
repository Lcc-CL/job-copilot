"""Versioned, idempotent schema migrations for Job Copilot.

SQLAlchemy ORM metadata is the authoritative schema.  Migrations only bridge
existing databases to that schema without dropping legacy tables or columns.
"""

from __future__ import annotations

import datetime
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import Engine, inspect, text

from .models import Base


CURRENT_SCHEMA_VERSION = "20260731-01"


@dataclass(frozen=True)
class Migration:
    version: str
    description: str
    upgrade: Callable[[Engine], list[str]]


@dataclass(frozen=True)
class MigrationReport:
    changes: tuple[str, ...]
    applied_versions: tuple[str, ...]
    backup_path: Optional[Path]

    @property
    def messages(self) -> list[str]:
        messages: list[str] = []
        if self.backup_path:
            messages.append(f"backup: {self.backup_path}")
        messages.extend(self.changes)
        messages.extend(f"schema_version: {version}" for version in self.applied_versions)
        return messages


def _existing_tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def _applied_versions(engine: Engine) -> set[str]:
    if "schema_version" not in _existing_tables(engine):
        return set()
    with engine.connect() as conn:
        return {
            row[0]
            for row in conn.execute(text("SELECT version FROM schema_version"))
        }


def _schema_has_drift(engine: Engine) -> bool:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    expected_tables = set(Base.metadata.tables)
    if not expected_tables.issubset(existing_tables):
        return True

    for table_name, table in Base.metadata.tables.items():
        existing_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        expected_columns = {column.name for column in table.columns}
        if not expected_columns.issubset(existing_columns):
            return True
    return False


def _sql_literal(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return None


def _safe_default(column) -> Optional[str]:
    default = column.default
    if default is None or not default.is_scalar:
        return None
    return _sql_literal(default.arg)


def _add_missing_orm_columns(engine: Engine) -> list[str]:
    changes: list[str] = []
    preparer = engine.dialect.identifier_preparer

    for table_name, table in Base.metadata.tables.items():
        inspector = inspect(engine)
        if table_name not in set(inspector.get_table_names()):
            continue

        existing_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        missing_columns = [
            column for column in table.columns if column.name not in existing_columns
        ]
        if not missing_columns:
            continue

        with engine.begin() as conn:
            for column in missing_columns:
                if column.primary_key:
                    raise RuntimeError(
                        f"Cannot safely add missing primary key column "
                        f"{table_name}.{column.name}"
                    )

                column_type = column.type.compile(dialect=engine.dialect)
                default = _safe_default(column)
                default_clause = f" DEFAULT {default}" if default is not None else ""
                conn.exec_driver_sql(
                    f"ALTER TABLE {preparer.quote(table_name)} "
                    f"ADD COLUMN {preparer.quote(column.name)} "
                    f"{column_type}{default_clause}"
                )
                changes.append(f"column: {table_name}.{column.name}")

    return changes


def _align_with_orm(engine: Engine) -> list[str]:
    before_tables = _existing_tables(engine)
    Base.metadata.create_all(bind=engine)
    after_tables = _existing_tables(engine)

    changes = [f"table: {name}" for name in sorted(after_tables - before_tables)]
    changes.extend(_add_missing_orm_columns(engine))

    if _schema_has_drift(engine):
        raise RuntimeError("Schema still differs from SQLAlchemy ORM metadata after migration")
    return changes


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=CURRENT_SCHEMA_VERSION,
        description="align legacy SQLite schema and add resume tables",
        upgrade=_align_with_orm,
    ),
)


def create_sqlite_backup(engine: Engine) -> Optional[Path]:
    """Create a consistent timestamped SQLite snapshot, including WAL data."""
    if engine.dialect.name != "sqlite":
        return None

    database = engine.url.database
    if not database or database == ":memory:":
        return None

    source_path = Path(database).expanduser().resolve()
    if not source_path.exists() or source_path.stat().st_size == 0:
        return None

    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = source_path.with_name(f"{source_path.name}.bak-{timestamp}")

    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    target = sqlite3.connect(str(backup_path))
    try:
        source.backup(target)
        quick_check = target.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise RuntimeError(f"Backup integrity check failed: {quick_check}")
    except Exception:
        if backup_path.exists():
            backup_path.unlink()
        raise
    finally:
        target.close()
        source.close()

    backup_path.chmod(0o600)
    return backup_path


def run_schema_migrations(
    engine: Engine,
    *,
    create_backup: bool = True,
) -> MigrationReport:
    """Apply pending migrations and repair schema drift safely.

    Existing SQLite files are backed up before the first schema change. Every
    migration is idempotent, and an already-current database returns a no-op
    report without creating another backup.
    """
    existing_tables = _existing_tables(engine)
    applied_versions = _applied_versions(engine)
    pending = [m for m in MIGRATIONS if m.version not in applied_versions]
    has_drift = _schema_has_drift(engine)

    if not pending and not has_drift:
        return MigrationReport((), (), None)

    backup_path = None
    if create_backup and existing_tables:
        backup_path = create_sqlite_backup(engine)

    changes: list[str] = []
    versions_recorded: list[str] = []

    migrations_to_run = pending or [MIGRATIONS[-1]]
    for migration in migrations_to_run:
        changes.extend(migration.upgrade(engine))
        if migration.version not in applied_versions:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO schema_version (version, applied_at) "
                        "VALUES (:version, :applied_at)"
                    ),
                    {
                        "version": migration.version,
                        "applied_at": datetime.datetime.now(
                            datetime.timezone.utc
                        ).isoformat(),
                    },
                )
            applied_versions.add(migration.version)
            versions_recorded.append(migration.version)

    return MigrationReport(
        tuple(changes),
        tuple(versions_recorded),
        backup_path,
    )
