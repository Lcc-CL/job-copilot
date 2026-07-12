"""投递效果统计（M5 · 竞争力实证核心）。

读投递追踪表，算漏斗（已发→已读→回复→邀约）与分组对照，输出：
- **已读不回率**（HR 看了不回的比例）= 竞争力信号：某档已读不回率飙高，说明你在该档没竞争力。
- 分组（冲刺/稳妥/保底）对照：回复率随薪资档如何变化 → 定位你当前市场水位。

数据来源：data/exports/投递追踪-*.csv（可多批累积，按 链接/公司+职位 去重）。
"""

from __future__ import annotations

import csv
import glob
from collections import defaultdict
from datetime import date

from .config import DATA_DIR, REPORTS_DIR

TRACK_GLOB = str(DATA_DIR / "exports" / "投递追踪-*.csv")
GROUP_ORDER = ["冲刺", "稳妥", "保底"]


def _truthy(v) -> bool:
    return str(v or "").strip() in ("1", "1.0", "是", "y", "Y", "true", "True")


def _load() -> list:
    rows, seen = [], set()
    for f in sorted(glob.glob(TRACK_GLOB)):
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            key = (r.get("链接") or "").strip() or (r.get("公司", "") + r.get("职位", ""))
            if key in seen:
                continue
            seen.add(key)
            rows.append(r)
    return rows


def _bucket(rows: list) -> dict:
    sent = len([r for r in rows if (r.get("已发日期(填)") or "").strip()])
    read = len([r for r in rows if _truthy(r.get("已读(填1/0)"))])
    reply = len([r for r in rows if _truthy(r.get("回复(填1/0)"))])
    invite = len([r for r in rows if _truthy(r.get("邀约(填1/0)"))])
    return {"发": sent or len(rows), "读": read, "回": reply, "邀": invite}


def _pct(a, b) -> str:
    return f"{a*100//b}%" if b else "—"


def report() -> str:
    rows = _load()
    if not rows:
        return "未找到投递追踪表。先 greet 生成、投递后填写 data/exports/投递追踪-*.csv。"

    by_group = defaultdict(list)
    for r in rows:
        by_group[(r.get("分组") or "未分组").strip()].append(r)

    overall = _bucket(rows)
    L = [f"# 投递竞争力报告（{date.today().isoformat()}）", ""]
    L.append(f"> 累计投递 {overall['发']} 条 · 数据来源你填写的投递追踪表")
    L.append("")

    # 总漏斗
    L.append("## 一、总漏斗")
    L.append("")
    L.append("| 阶段 | 数量 | 占已发 |")
    L.append("|---|---|---|")
    s = overall["发"]
    L.append(f"| 已发 | {overall['发']} | 100% |")
    L.append(f"| 已读 | {overall['读']} | {_pct(overall['读'], s)} |")
    L.append(f"| 回复 | {overall['回']} | {_pct(overall['回'], s)} |")
    L.append(f"| 邀约 | {overall['邀']} | {_pct(overall['邀'], s)} |")
    L.append("")
    ghost = overall["读"] - overall["回"]
    L.append(f"- **已读不回率 = {_pct(ghost, overall['读'])}**"
             f"（{ghost}/{overall['读']}：HR 看了但没回，是竞争力的直接信号）")
    L.append("")

    # 分组对照
    L.append("## 二、分组对照（竞争力随薪资档的变化）")
    L.append("")
    L.append("| 组 | 已发 | 已读 | 回复 | 邀约 | 回复率 | 已读不回率 |")
    L.append("|---|---|---|---|---|---|---|")
    for g in GROUP_ORDER + [k for k in by_group if k not in GROUP_ORDER]:
        if g not in by_group:
            continue
        b = _bucket(by_group[g])
        ghost_g = b["读"] - b["回"]
        L.append(f"| {g} | {b['发']} | {b['读']} | {b['回']} | {b['邀']} "
                 f"| {_pct(b['回'], b['发'])} | {_pct(ghost_g, b['读'])} |")
    L.append("")

    # 解读
    total_signal = overall["读"] + overall["回"] + overall["邀"]
    L.append("## 三、解读")
    L.append("")
    if total_signal == 0:
        L.append("- ⏳ **暂无反馈数据**（招呼刚发出，HR 已读/回复通常 1–3 天到）。")
        L.append("- 等你在追踪表填了「已读/回复/邀约」后重跑 `stats`，即出竞争力结论。")
        L.append("- 届时看点：① 哪个薪资档已读不回率飙高=你在该档没竞争力；"
                 "② 回复率在哪档断崖=你当前市场水位的天花板。")
    else:
        L.append("- 对比三档的**回复率**：若保底≫稳妥≫冲刺断崖式下降，说明你现市场水位约在回复率还健康的那一档。")
        L.append("- **已读不回率**高的档=HR 看了不感兴趣，是最该改进的方向（简历/招呼语/或岗位选择）。")
        if overall["邀"]:
            L.append(f"- 已拿到 {overall['邀']} 个邀约——进入面试准备（interview-prep 技能）。")
    L.append("")
    L.append("> 样本量提示：单批 15 条噪声大，多投几批累积后分组对照才稳。")

    report_text = "\n".join(L)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"投递竞争力报告-{date.today().isoformat()}.md"
    path.write_text(report_text, encoding="utf-8")
    return report_text + f"\n\n---\n已保存：{path}"
