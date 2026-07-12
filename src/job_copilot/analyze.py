"""市场画像分析（M3）。

从 jobs 表聚合出：薪资分布（P10/P50/P90）、技能词频、学历/经验门槛、
薪资×经验交叉、招聘公司/行业分布。输出到终端并存 Markdown 报告。

设计取向：只做确定性统计（不调 LLM），结果可复现、可核对。
LLM 解读（换行方向、竞争力判断）留给后续 skills/decide 阶段。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date
from statistics import median
from typing import Optional

from .config import REPORTS_DIR
from . import db

# tags 里混入的非技能词：经验年限、学历——统计技能词频时剔除
_EXP_RE = re.compile(r"^\d+[-\d]*年$|经验不限|应届|在校|不限经验")
_DEGREE_WORDS = {"本科", "大专", "硕士", "博士", "学历不限", "中专", "高中", "初中及以下", "MBA"}
# 过于宽泛、无区分度的词，报告里降噪（可按需增删）
_STOPWORDS = {"经验", "开发经验", "相关经验"}


def _pct(sorted_vals: list, p: float) -> Optional[int]:
    """线性插值百分位。p 取 0~100。"""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return int(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return int(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac)


def _is_skill(tok: str) -> bool:
    tok = (tok or "").strip()
    if not tok or tok in _DEGREE_WORDS or tok in _STOPWORDS:
        return False
    if _EXP_RE.search(tok):
        return False
    return True


def market_report(save: bool = True) -> str:
    conn = db.connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM jobs")]
    n = len(rows)
    if n == 0:
        return "职位库为空，先采集：collect import。"

    # ---- 薪资分布（用 min/max 中点，月薪，单位元）----
    mids, mins, maxs = [], [], []
    for r in rows:
        lo, hi = r.get("salary_min"), r.get("salary_max")
        if lo and hi:
            mids.append((lo + hi) / 2)
            mins.append(lo)
            maxs.append(hi)
    mids.sort(); mins.sort(); maxs.sort()

    def k(v):  # 元 → "XK"
        return f"{v/1000:.1f}K" if v is not None else "—"

    # ---- 技能词频 ----
    skill_counter: Counter = Counter()
    skill_display: dict = {}  # lower → 首次出现的原始大小写
    for r in rows:
        try:
            tags = json.loads(r.get("tags") or "[]")
        except Exception:
            tags = []
        seen = set()
        for t in tags:
            if not _is_skill(t):
                continue
            key = t.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            skill_counter[key] += 1
            skill_display.setdefault(key, t.strip())

    # ---- 学历/经验门槛 ----
    degree_counter = Counter(r.get("degree") for r in rows if r.get("degree"))
    exp_counter = Counter(r.get("experience") for r in rows if r.get("experience"))

    # ---- 薪资 × 经验交叉（中点中位数）----
    exp_salary: dict = {}
    for r in rows:
        e = r.get("experience")
        lo, hi = r.get("salary_min"), r.get("salary_max")
        if e and lo and hi:
            exp_salary.setdefault(e, []).append((lo + hi) / 2)

    def exp_sort_key(e):  # 经验档位大致排序
        m = re.search(r"(\d+)", e or "")
        base = int(m.group(1)) if m else -1
        if "应届" in (e or "") or "在校" in (e or ""):
            base = 0
        if "不限" in (e or ""):
            base = -1
        return base

    # ---- 招聘公司/行业 ----
    industry_counter = Counter(r.get("industry") for r in rows if r.get("industry"))
    size_counter = Counter(r.get("company_size") for r in rows if r.get("company_size"))

    # ==== 组织报告 ====
    L = []
    L.append(f"# 深圳 AI Agent 岗位市场画像")
    L.append("")
    L.append(f"> 样本 {n} 条职位 / {len(set(r.get('company') for r in rows))} 家公司 · "
             f"来源 Boss直聘 · 生成 {date.today().isoformat()}")
    kws = Counter(r.get("search_keyword") for r in rows if r.get("search_keyword"))
    L.append(f"> 采集关键词：" + "、".join(f"{k_}({v})" for k_, v in kws.most_common()))
    L.append("")

    L.append("## 一、薪资分布（月薪中点）")
    L.append("")
    L.append(f"| 分位 | P10 | P25 | P50(中位) | P75 | P90 |")
    L.append(f"|---|---|---|---|---|---|")
    L.append(f"| 月薪 | {k(_pct(mids,10))} | {k(_pct(mids,25))} | **{k(_pct(mids,50))}** "
             f"| {k(_pct(mids,75))} | {k(_pct(mids,90))} |")
    L.append("")
    L.append(f"- 区间下界中位数 {k(_pct(mins,50))}，上界中位数 {k(_pct(maxs,50))}")
    L.append(f"- 有效薪资样本 {len(mids)}/{n} 条")
    L.append("")

    L.append("## 二、薪资 × 经验（各档中位月薪）")
    L.append("")
    L.append("| 经验要求 | 职位数 | 中位月薪 |")
    L.append("|---|---|---|")
    for e in sorted(exp_salary, key=exp_sort_key):
        vals = sorted(exp_salary[e])
        L.append(f"| {e} | {len(vals)} | {k(int(median(vals)))} |")
    L.append("")

    L.append("## 三、技能词频 Top 25（出现在多少条职位中）")
    L.append("")
    L.append("| # | 技能/要求 | 职位数 | 占比 |")
    L.append("|---|---|---|---|")
    for i, (key, c) in enumerate(skill_counter.most_common(25), 1):
        L.append(f"| {i} | {skill_display[key]} | {c} | {c*100//n}% |")
    L.append("")

    L.append("## 四、学历门槛")
    L.append("")
    for d, c in degree_counter.most_common():
        L.append(f"- {d}：{c} 条（{c*100//n}%）")
    L.append("")

    L.append("## 五、经验门槛")
    L.append("")
    for e, c in sorted(exp_counter.items(), key=lambda x: exp_sort_key(x[0])):
        L.append(f"- {e}：{c} 条（{c*100//n}%）")
    L.append("")

    L.append("## 六、招聘行业 Top 10")
    L.append("")
    for ind, c in industry_counter.most_common(10):
        L.append(f"- {ind}：{c} 条")
    L.append("")
    L.append("## 七、公司规模分布")
    L.append("")
    for s, c in size_counter.most_common():
        L.append(f"- {s}：{c} 条")
    L.append("")

    report = "\n".join(L)
    if save:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORTS_DIR / f"市场画像-深圳AIAgent-{date.today().isoformat()}.md"
        path.write_text(report, encoding="utf-8")
        report += f"\n\n---\n报告已保存：{path}"
    return report
