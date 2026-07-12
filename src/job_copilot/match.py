"""JD ↔ 简历 语义匹配打分（M6 核心）。

流程：
1. build_index()：把每条职位的 title+行业+技能标签 向量化，存 job_vectors。
2. match()：把求职者画像（母版简历技能段 + 意向岗位）向量化，
   与所有职位向量算余弦相似度，排序输出 Top-N。

向量存储当前用 SQLite blob + numpy 暴力检索（401 条量级毫秒级）。
pgvector 到位后只需替换 db.load_vectors / save_vector 的后端，本文件不动。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import numpy as np

from .config import RESUME_DIR, load_config
from . import db, embed


def _job_text(r: dict) -> str:
    """职位的可向量化文本：标题 + 行业 + 技能标签（列表页无 JD 全文，用这些代表）。"""
    parts = [r.get("title") or "", r.get("industry") or ""]
    try:
        tags = json.loads(r.get("tags") or "[]")
    except Exception:
        tags = []
    # 剔除经验/学历噪声标签
    skills = [t for t in tags if not re.search(r"^\d+[-\d]*年$", t) and
              t not in {"本科", "大专", "硕士", "博士", "学历不限"}]
    parts.append(" ".join(skills))
    return "。".join(p for p in parts if p)


# 算法研究岗标志（对本科转行不友好，过滤）——与技能诊断口径一致
_ALGO_TAGS = {"发表算法相关优秀论文", "强化学习", "多模态算法", "自然语言处理算法",
              "图像算法", "语音算法", "深度学习", "大模型算法", "模型加速/性能优化", "视觉算法"}
_ENG_TAGS = {"python", "java", "golang", "go", "mysql", "redis", "docker", "postgresql",
             "linux", "ai agent", "agent", "llm", "rag", "微服务", "后端", "spring",
             "langchain", "dify", "工作流开发", "算法工程化经验"}
# 非开发岗标题关键词（过滤）
_NONDEV_TITLE = ("讲师", "培训", "教育", "前端", "frontend", "测试工程师", "销售",
                 "产品经理", "运营", "实施", "售前", "客户经理")
# 可接受的经验档（转行/初级友好）
_JUNIOR_EXP = ("应届", "在校", "1年以内", "1-3年", "经验不限", "不限")


def _tags_of(r: dict) -> list:
    try:
        return [t.strip() for t in json.loads(r.get("tags") or "[]")]
    except Exception:
        return []


def _is_algorithm_role(r: dict) -> bool:
    tags = set(_tags_of(r))
    tags_l = set(t.lower() for t in tags)
    algo = len(tags & _ALGO_TAGS)
    eng = len(tags_l & _ENG_TAGS)
    if "发表算法相关优秀论文" in tags:
        return True
    return algo >= 2 and algo > eng


def _passes_filters(r: dict, salary_floor: int) -> bool:
    # 经验门槛：只留初级/转行友好档
    exp = r.get("experience") or ""
    if exp and not any(k in exp for k in _JUNIOR_EXP):
        return False
    # 薪资地板：上界已知且低于地板则排除；未知薪资保留
    smax = r.get("salary_max")
    if smax is not None and smax < salary_floor:
        return False
    # 非开发岗标题
    title = (r.get("title") or "").lower()
    if any(k.lower() in title for k in _NONDEV_TITLE):
        return False
    # 算法研究岗
    if _is_algorithm_role(r):
        return False
    return True


def _profile_text() -> str:
    """求职者画像文本：母版简历「技能清单」段 + 意向岗位关键词。"""
    cfg = load_config()
    keywords = "、".join(cfg.me.get("keywords", []))
    resume = ""
    for name in ("母版简历.md",):
        p = RESUME_DIR / name
        if p.exists():
            resume = p.read_text(encoding="utf-8")
            break
    skills_section = ""
    if resume:
        m = re.search(r"##\s*技能清单(.+?)(?:\n##\s|\Z)", resume, re.S)
        if m:
            skills_section = re.sub(r"[#*`>\-]", " ", m.group(1))
    query = f"意向岗位：{keywords}。技能：{skills_section}".strip()
    # bge 输入别太长，截断到约 500 字
    return query[:500]


def build_index(rebuild: bool = False) -> None:
    conn = db.connect()
    if rebuild:
        conn.execute("DELETE FROM job_vectors")
        conn.commit()
    todo = db.jobs_missing_vectors(conn)
    if not todo:
        total = conn.execute("SELECT COUNT(*) FROM job_vectors").fetchone()[0]
        print(f"✓ 索引已是最新，无需向量化（库内 {total} 条已建向量）。")
        return
    print(f"→ 向量化 {len(todo)} 条职位（本地 bge-small-zh，首次约几十秒）…")
    texts = [_job_text(r) for r in todo]
    vecs = embed.embed(texts)
    for r, v in zip(todo, vecs):
        db.save_vector(conn, r["id"], v, embed.MODEL_NAME)
    print(f"✓ 完成，新增 {len(todo)} 条向量。")


def ranked_matches(top_k: int = 20, filtered: bool = True) -> list:
    """返回排序后的匹配列表 [(score, job_row), ...]，供文本/HTML 报告共用。"""
    conn = db.connect()
    build_index()
    pks, matrix = db.load_vectors(conn)
    if len(pks) == 0:
        return []

    id2row = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM jobs")}
    salary_floor = int(load_config().me.get("salary_expect_min", 0))

    # 元数据硬过滤（在向量检索前缩候选集，标准 RAG 做法）
    keep = [i for i, pk in enumerate(pks)
            if (not filtered) or _passes_filters(id2row.get(pk, {}), salary_floor)]
    if not keep:
        return []
    sub_pks = [pks[i] for i in keep]
    sub_matrix = matrix[keep]

    qvec = embed.embed_one(_profile_text())
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        sims = (sub_matrix @ qvec).astype(np.float64)

    order = np.argsort(-sims)[:top_k]
    return [(float(sims[i]), id2row.get(sub_pks[i], {})) for i in order]


def match(top_k: int = 20, min_score: float = 0.0, filtered: bool = True) -> str:
    conn = db.connect()
    total = conn.execute("SELECT COUNT(*) FROM job_vectors").fetchone()[0]
    results = ranked_matches(top_k=top_k, filtered=filtered)
    if not results:
        return "无可匹配职位，先采集并 build。"

    lines = [f"# 职位匹配 Top {top_k}（本地语义相似度）", ""]
    tag = "过滤后" if filtered else "未过滤"
    lines.append(f"> 求职画像 vs {total} 条职位（{tag}候选）· 模型 bge-small-zh-v1.5 · 分数=余弦相似度")
    lines.append("")
    lines.append("| # | 分数 | 职位 | 公司 | 薪资 | 经验 | 技能标签 |")
    lines.append("|---|---|---|---|---|---|---|")
    for rank, (score, r) in enumerate(results, 1):
        if score < min_score:
            break
        skills = "、".join([t for t in _tags_of(r)
                            if not re.search(r"^\d+[-\d]*年$|本科|大专|硕士|博士", t)][:5])
        lines.append(
            f"| {rank} | {score:.3f} | {r.get('title','')} | {r.get('company','')} "
            f"| {r.get('salary_text','')} | {r.get('experience','')} | {skills} |"
        )
    return "\n".join(lines)
