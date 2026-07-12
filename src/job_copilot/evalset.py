"""评测集构建（M6 的评测基建，补"评测"技能缺口）。

评测集 = 一组 (职位, 该投/不投) 的人工标注，作为"标准答案"，用来客观衡量
匹配/精排的质量（precision@k 等），而不是凭感觉说"排得挺准"。

方法要点（简历可写的方法论）：
- **分层抽样**：不能只标高分岗（那样只能测 precision、测不出漏掉的好岗）。
  从高/中/低分各抽一些，才能同时看准确率与召回。
- **标准答案由人给**：该投/不投是求职者的主观判断，机器不能代劳——这正是评测集的价值。
- **冻结复用**：标一次，之后每次改匹配算法都用同一套标注复算，才能对比"改进了没有"。

make_worksheet() 生成 CSV 标注表（带 BOM，Excel 直接打开），用户填「该投」列即可。
"""

from __future__ import annotations

import csv
import glob
from datetime import date

from .config import DATA_DIR
from . import match

EVAL_DIR = DATA_DIR / "eval"


def _already_labeled_ids() -> set:
    """读所有历史标注表，收集已标注过的 job_id（用于留出集去重，防数据泄漏）。"""
    import csv
    ids = set()
    for f in glob.glob(str(EVAL_DIR / "标注表*.csv")):
        try:
            for r in csv.DictReader(open(f, encoding="utf-8-sig")):
                if (r.get("该投(填1/0)") or "").strip() != "":
                    ids.add(r.get("job_id"))
        except Exception:
            pass
    return ids


def make_worksheet(n_top: int = 15, n_mid: int = 10, n_low: int = 5,
                   tag: str = "", exclude_labeled: bool = False) -> str:
    """分层抽样生成标注表：高分 n_top + 中分 n_mid + 低分 n_low 条。

    exclude_labeled=True 时排除历史已标注岗——用于生成留出测试集（prompt 从没见过的数据）。
    tag 给文件名加后缀（如 "holdout"），便于区分 dev 集与 test 集。
    """
    ranked = match.ranked_matches(top_k=10000, filtered=True)  # 全部过滤后候选，按分排序
    if not ranked:
        return "无候选职位，先 collect import 并 match。"

    if exclude_labeled:
        skip = _already_labeled_ids()
        ranked = [(s, r) for s, r in ranked if r.get("job_id") not in skip]
        print(f"（已排除 {len(skip)} 个历史标注岗，留出集从剩余 {len(ranked)} 个抽取）")

    N = len(ranked)
    picks = []
    # 高分段：前 n_top
    for i in range(min(n_top, N)):
        picks.append(("高", i, ranked[i]))
    # 中分段：中间均匀取 n_mid
    mid_start, mid_end = N // 3, 2 * N // 3
    mid_pool = list(range(mid_start, mid_end))
    if mid_pool:
        step = max(1, len(mid_pool) // max(1, n_mid))
        for j in mid_pool[::step][:n_mid]:
            picks.append(("中", j, ranked[j]))
    # 低分段：末尾 n_low
    for i in range(max(0, N - n_low), N):
        picks.append(("低", i, ranked[i]))

    # 去重（按 job 主键），保持顺序
    seen, rows = set(), []
    for band, rank, (score, r) in picks:
        jid = r.get("job_id")
        if jid in seen:
            continue
        seen.add(jid)
        tags = [t for t in match._tags_of(r)
                if not any(x in t for x in ("年", "本科", "大专", "硕士", "博士"))]
        rows.append({
            "分数段": band,
            "粗筛排名": rank + 1,
            "相似度": f"{score:.3f}",
            "该投(填1/0)": "",
            "备注": "",
            "职位": r.get("title") or "",
            "公司": r.get("company") or "",
            "薪资": r.get("salary_text") or "",
            "经验": r.get("experience") or "",
            "技能标签": "、".join(tags[:6]),
            "job_id": r.get("job_id") or "",
            "链接": r.get("url") or "",
        })

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"-{tag}" if tag else ""
    path = EVAL_DIR / f"标注表{suffix}-{date.today().isoformat()}.csv"
    cols = ["分数段", "粗筛排名", "相似度", "该投(填1/0)", "备注",
            "职位", "公司", "薪资", "经验", "技能标签", "job_id", "链接"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:  # BOM 便于 Excel
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    band_cnt = {}
    for r in rows:
        band_cnt[r["分数段"]] = band_cnt.get(r["分数段"], 0) + 1
    msg = [
        f"✓ 标注表已生成：{path}",
        f"  共 {len(rows)} 条（高分 {band_cnt.get('高',0)} / 中分 {band_cnt.get('中',0)} / 低分 {band_cnt.get('低',0)}）",
        "",
        "下一步（你来做，约 30 分钟）：",
        "  1. 用 Excel/Numbers 打开这个 CSV",
        "  2. 逐行看职位，在「该投(填1/0)」列填 1=该投 / 0=不投（拿不准填 0.5）",
        "     判断口径建议：AI应用/Agent工程 + 经验≤3年可投 + 薪资≥12k + 非纯算法/非纯前端",
        "  3. 存盘后告诉我，我用它算 precision@k、对比粗筛vs精排",
    ]
    return "\n".join(msg)
