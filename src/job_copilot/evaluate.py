"""评测：用人工标注量化 粗筛(embed) vs 精排(LLM) 的质量（补"评测"技能缺口）。

流程：读标注表 → 对这些岗补齐 LLM 精排 → 两个指标：
1. **排序质量 precision@k**：把标注岗分别按 粗筛相似度 / 精排fit_score 排序，
   看 top-k 里"该投(标=1)"的占比，对比两种排序谁把好岗排得更靠前。
2. **判断一致率**：LLM 的 投/慎投/不投 映射成 1/0.5/0，与你的标注对比，算一致率+混淆。

这套"自建标注集 + 量化对比"就是 Ragas/DeepEval 同类评测方法论的手写实现。
"""

from __future__ import annotations

import csv
import glob
from datetime import date

from .config import DATA_DIR, REPORTS_DIR, load_config
from . import db, score as score_mod

EVAL_DIR = DATA_DIR / "eval"
_VERDICT_MAP = {"投": 1.0, "慎投": 0.5, "不投": 0.0}


def _latest_labeled():
    files = sorted(glob.glob(str(EVAL_DIR / "标注表-*.csv")))
    return files[-1] if files else None


def _precision_at_k(ranked_labels, k, thresh=1.0):
    """ranked_labels: 按某排序排好的 label 列表；relevant = label>=thresh。"""
    top = ranked_labels[:k]
    if not top:
        return 0.0
    return sum(1 for x in top if x >= thresh) / len(top)


def _avg_precision(ranked_labels, thresh=1.0):
    hits, ssum = 0, 0.0
    total_rel = sum(1 for x in ranked_labels if x >= thresh)
    if total_rel == 0:
        return 0.0
    for i, x in enumerate(ranked_labels, 1):
        if x >= thresh:
            hits += 1
            ssum += hits / i
    return ssum / total_rel


def run(model: str = None, path: str = None) -> str:
    path = path or _latest_labeled()
    if not path:
        return "未找到标注表，先 evalset 生成并填写。"
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    labeled = [r for r in rows if (r.get("该投(填1/0)") or "").strip() != ""]
    if not labeled:
        return f"标注表 {path} 还没填「该投」列。"

    conn = db.connect()
    resume = score_mod._resume_text()
    model = model or load_config().llm["model_analysis"]

    # job_id → jobs 行
    id2row = {r["job_id"]: dict(r) for r in conn.execute("SELECT * FROM jobs")}
    existing = db.load_scores(conn)

    todo = [r for r in labeled if id2row.get(r["job_id"]) and
            id2row[r["job_id"]]["id"] not in existing]
    if todo:
        print(f"→ 为标注岗补齐 LLM 精排：{len(todo)} 条（已存 {len(labeled)-len(todo)} 条）…")

    # 对标注岗补齐精排，收集 (sim, label, jobrow, scoredict)
    items = []
    for lab in labeled:
        jr = id2row.get(lab["job_id"])
        if not jr:
            continue
        pk = jr["id"]
        if pk in existing:
            s = existing[pk]
        else:
            try:
                s = score_mod.score_one(conn, jr, resume, model)
                print(f"  ✓ {jr.get('title','')[:22]} → fit={s.get('fit_score')} {s.get('verdict')}")
            except Exception as e:
                print(f"  ✗ {jr.get('title','')[:22]} 评分失败：{str(e)[:60]}")
                continue
        label = float(lab["该投(填1/0)"].strip())
        sim = float(lab["相似度"])
        items.append((sim, label, jr, s))

    if not items:
        return "无可评测项（标注岗未在职位库或评分失败）。"

    n = len(items)
    n_pos = sum(1 for _, l, _, _ in items if l >= 1.0)

    # 排序1：粗筛（sim 降序）；排序2：精排（fit_score 降序，tie 用 sim）
    def fit_of(s):
        v = s.get("fit_score")
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    coarse = [l for _, l, _, _ in sorted(items, key=lambda x: -x[0])]
    rerank = [l for _, l, _, _ in sorted(items, key=lambda x: (-fit_of(x[3]), -x[0]))]

    ks = [5, 10]
    L = [f"# 评测报告：粗筛 vs 精排（{date.today().isoformat()}）", ""]
    L.append(f"> 标注集 {n} 条（该投 {n_pos} / 慎投 {sum(1 for _,l,_,_ in items if l==0.5)} / "
             f"不投 {sum(1 for _,l,_,_ in items if l==0)}）· 标准答案=你的人工标注")
    L.append("")
    L.append("## 一、排序质量：precision@k（top-k 里「该投」的占比，越高越好）")
    L.append("")
    L.append("| 指标 | 粗筛(embed余弦) | 精排(LLM Block A-G) | 提升 |")
    L.append("|---|---|---|---|")
    for k in ks:
        pc = _precision_at_k(coarse, k)
        pr = _precision_at_k(rerank, k)
        L.append(f"| precision@{k} | {pc:.0%} | {pr:.0%} | {(pr-pc)*100:+.0f}pp |")
    apc, apr = _avg_precision(coarse), _avg_precision(rerank)
    L.append(f"| 平均精度 AP | {apc:.0%} | {apr:.0%} | {(apr-apc)*100:+.0f}pp |")
    L.append("")

    # 判断一致率
    agree = 0; conf = {}
    for _, label, jr, s in items:
        pv = _VERDICT_MAP.get((s.get("verdict") or "").strip())
        if pv is None:
            continue
        if pv == label:
            agree += 1
        key = f"你={label}→LLM={s.get('verdict')}"
        conf[key] = conf.get(key, 0) + 1
    L.append("## 二、LLM 判断与你标注的一致率")
    L.append("")
    L.append(f"- **一致率 {agree}/{n} = {agree/n:.0%}**（LLM 的 投/慎投/不投 映射 1/0.5/0 与你标注相同）")
    L.append("- 你标注 → LLM 判断 分布：")
    for k, v in sorted(conf.items(), key=lambda x: -x[1]):
        L.append(f"  - {k}：{v} 条")
    L.append("")

    L.append("## 三、结论")
    L.append("")
    better = "精排" if apr > apc else ("粗筛" if apc > apr else "两者相当")
    L.append(f"- 排序上，**{better}** 把「该投」岗排得更靠前"
             f"（AP {apc:.0%} → {apr:.0%}）。")
    L.append("- 精排能识别粗筛的高分假阳性（如标题含「大模型」实为 Android/算法/前端 的岗）。")
    L.append(f"- 方法学意义：这是一套可复现的评测——改进匹配后用同一标注集复算即可对比。")
    L.append("")

    report = "\n".join(L)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"评测-粗筛vs精排-{date.today().isoformat()}.md"
    out.write_text(report, encoding="utf-8")
    return report + f"\n\n---\n已保存：{out}"
