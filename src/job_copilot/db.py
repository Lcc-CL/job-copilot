"""SQLite 数据层：jobs（采集的职位）与 applications（投递追踪）。

单文件数据库 data/jobcopilot.db。jobs 按 (platform, job_id) 去重，
重复采集时更新时间戳与可变字段（薪资/HR活跃度可能变化）。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from .config import DATA_DIR

DB_PATH = DATA_DIR / "jobcopilot.db"

def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    """Open SQLite; new files are initialized from SQLAlchemy ORM metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists() or path.stat().st_size == 0
    if is_new:
        from sqlalchemy import create_engine
        from .database import init_db

        engine = create_engine(
            f"sqlite:///{path.resolve()}",
            connect_args={"check_same_thread": False},
        )
        try:
            init_db(engine=engine, create_backup=False)
        finally:
            engine.dispose()

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def upsert_job(conn: sqlite3.Connection, job: dict) -> bool:
    """写入一条职位，已存在则更新可变字段。返回是否为新记录。"""
    job = dict(job)
    job.setdefault("collected_at", datetime.now().isoformat(timespec="seconds"))
    if isinstance(job.get("tags"), (list, tuple)):
        job["tags"] = json.dumps(job["tags"], ensure_ascii=False)

    cols = [
        "platform", "job_id", "url", "title", "company", "company_size",
        "industry", "salary_text", "salary_min", "salary_max", "salary_months",
        "city", "district", "experience", "degree", "tags",
        "hr_name", "hr_title", "hr_active", "jd_text",
        "search_keyword", "search_city", "collected_at",
    ]
    values = [job.get(c) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    updatable = [
        "salary_text", "salary_min", "salary_max", "salary_months",
        "hr_name", "hr_title", "hr_active", "collected_at",
    ]
    update_clause = ", ".join(f"{c}=excluded.{c}" for c in updatable)
    # jd_text 只在新值非空时覆盖，避免列表页采集抹掉详情页拿到的全文
    update_clause += ", jd_text=COALESCE(NULLIF(excluded.jd_text, ''), jd_text)"

    cur = conn.execute(
        f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT (platform, job_id) DO UPDATE SET {update_clause}",
        values,
    )
    conn.commit()
    # lastrowid 在 UPDATE 分支不可靠，用 changes+rowid 判断是否新插入
    is_new = cur.lastrowid is not None and conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE id = ? AND collected_at = ?",
        (cur.lastrowid, job["collected_at"]),
    ).fetchone()[0] > 0
    return bool(is_new)


def count_today(conn: sqlite3.Connection, platform: str) -> int:
    """今日已采集条数（用于日限节流）。"""
    today = date.today().isoformat()
    return conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE platform = ? AND collected_at >= ?",
        (platform, today),
    ).fetchone()[0]


def job_stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS total, COUNT(DISTINCT company) AS companies FROM jobs"
    ).fetchone()
    by_platform = {
        r["platform"]: r["n"]
        for r in conn.execute(
            "SELECT platform, COUNT(*) AS n FROM jobs GROUP BY platform"
        )
    }
    return {"total": row["total"], "companies": row["companies"], "by_platform": by_platform}


def save_vector(conn: sqlite3.Connection, job_pk: int, vec, model: str) -> None:
    """存一条职位向量（float32 blob）。"""
    import numpy as np
    v = np.asarray(vec, dtype=np.float32)
    conn.execute(
        "INSERT INTO job_vectors (job_pk, dim, vec, model, embedded_at) "
        "VALUES (?,?,?,?,?) ON CONFLICT (job_pk) DO UPDATE SET "
        "dim=excluded.dim, vec=excluded.vec, model=excluded.model, embedded_at=excluded.embedded_at",
        (job_pk, v.shape[0], v.tobytes(), model, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


def load_vectors(conn: sqlite3.Connection):
    """返回 (job_pks: list[int], matrix: np.ndarray(n,dim))。无向量时矩阵为空。"""
    import numpy as np
    pks, blobs = [], []
    for r in conn.execute("SELECT job_pk, vec FROM job_vectors"):
        pks.append(r["job_pk"])
        blobs.append(np.frombuffer(r["vec"], dtype=np.float32))
    if not blobs:
        return [], np.zeros((0, 0), dtype=np.float32)
    return pks, np.vstack(blobs)


def jobs_missing_vectors(conn: sqlite3.Connection) -> list:
    """返回尚未向量化的职位行（用于增量建索引）。"""
    return [dict(r) for r in conn.execute(
        "SELECT j.* FROM jobs j LEFT JOIN job_vectors v ON j.id = v.job_pk "
        "WHERE v.job_pk IS NULL"
    )]


def save_score(conn: sqlite3.Connection, job_pk: int, s: dict, model: str) -> None:
    conn.execute(
        "INSERT INTO job_scores (job_pk, fit_score, verdict, archetype, seniority_ok, "
        "authenticity, reasons, highlights, gaps, model, scored_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (job_pk) DO UPDATE SET "
        "fit_score=excluded.fit_score, verdict=excluded.verdict, archetype=excluded.archetype, "
        "seniority_ok=excluded.seniority_ok, authenticity=excluded.authenticity, "
        "reasons=excluded.reasons, highlights=excluded.highlights, gaps=excluded.gaps, "
        "model=excluded.model, scored_at=excluded.scored_at",
        (job_pk, s.get("fit_score"), s.get("verdict"), s.get("archetype"),
         1 if s.get("seniority_ok") else 0, s.get("authenticity"),
         json.dumps(s.get("reasons"), ensure_ascii=False),
         json.dumps(s.get("highlights"), ensure_ascii=False),
         json.dumps(s.get("gaps"), ensure_ascii=False),
         model, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


def load_scores(conn: sqlite3.Connection) -> dict:
    """返回 {job_pk: score_row_dict}。"""
    return {r["job_pk"]: dict(r) for r in conn.execute("SELECT * FROM job_scores")}


def parse_salary(text: Optional[str]) -> tuple:
    """解析中文薪资串 → (min元/月, max元/月, 年薪月数)。

    支持: "12-18K" / "12-18K·14薪" / "8千-1.2万" / "300-500元/天" / "面议"。
    解析不了的返回 (None, None, None)，保留原文即可。
    """
    import re

    if not text:
        return None, None, None
    months = None
    m = re.search(r"[·x×](\d{2})薪", text)
    if m:
        months = int(m.group(1))

    def to_yuan(num: str, unit: str) -> int:
        v = float(num)
        if unit in ("K", "k"):
            return int(v * 1000)
        if unit == "万":
            return int(v * 10000)
        if unit == "千":
            return int(v * 1000)
        return int(v)

    m = re.search(r"([\d.]+)(K|k|万|千)?-([\d.]+)(K|k|万|千)(?:·\d+薪)?", text)
    if m:
        lo_num, lo_unit, hi_num, hi_unit = m.groups()
        lo = to_yuan(lo_num, lo_unit or hi_unit)
        hi = to_yuan(hi_num, hi_unit)
        if "天" in text:  # 日薪不折算，避免误导月薪对比
            return None, None, None
        return lo, hi, months
    return None, None, months
