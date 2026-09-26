"""DATABASE_URL 解析：平台无关，只认标准 SQLite / PostgreSQL URL。"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from job_copilot.database import _get_database_url


def _resolve(value: str | None) -> str:
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    if value is not None:
        env["DATABASE_URL"] = value
    with patch.dict(os.environ, env, clear=True):
        return _get_database_url()


def test_unset_falls_back_to_sqlite_in_data_dir():
    url = _resolve(None)
    assert url.startswith("sqlite:///")
    assert url.endswith("/data/jobcopilot.db")


def test_blank_falls_back_to_sqlite():
    assert _resolve("   ").startswith("sqlite:///")


@pytest.mark.parametrize("raw", [
    "postgres://u:p@db:5432/jobcopilot",
    "postgresql://u:p@db:5432/jobcopilot",
    "postgresql+psycopg://u:p@db:5432/jobcopilot",
])
def test_postgres_urls_are_normalized_to_psycopg(raw):
    assert _resolve(raw) == "postgresql+psycopg://u:p@db:5432/jobcopilot"


def test_platform_variable_names_are_not_resolved():
    """不再兼容某个托管平台把变量名当作 DATABASE_URL 值的写法。"""
    with patch.dict(os.environ, {"POSTGRES_URI": "postgresql://u:p@db/x"}):
        with pytest.raises(RuntimeError, match="valid SQLite or PostgreSQL URL"):
            _resolve("POSTGRES_URI")
