"""招呼语生成（M7）。

为高契合岗生成 Boss直聘 定制招呼语——**只重组母版简历真实内容**（红线1），
针对该 JD 讲"为什么合适"。输出到审阅文件，用户改定后**自己在Boss发**（红线2，工具不代发）。

Boss直聘 招呼语特点：短（100-150字内）、开头点出对该公司/岗位的具体钩子、
一条最相关的真实经历、一句软性推进。忌空泛套话。
"""

from __future__ import annotations

import csv
import json
from datetime import date

from .config import RESUME_DIR, REPORTS_DIR, DATA_DIR, load_config
from . import db, llm, score as score_mod


def _group_of(salary_max) -> str:
    """按薪资上界分组（=冲刺程度，用于已读不回率分组对照）。"""
    s = salary_max or 0
    if s >= 30000:
        return "冲刺"
    if s >= 22000:
        return "稳妥"
    return "保底"

SYSTEM = """你是求职者本人在 Boss直聘 给 HR 发第一条招呼语。要求：
- **只用候选人简历里的真实经历和数字，绝不编造或夸大**（这是硬红线）
- **不得出现任何公司名称**：既不写目标公司名，也不写候选人自己任职过的东家名。
  描述经历用行业泛称（如"在某跨境电商团队""在某制造业企业"），让内容聚焦做过什么、成果如何。
- 100-150 字，口语但专业，不用"贵公司""久仰"套话
- 结构：①点出对这个岗位/方向的具体兴趣或匹配点 ②举一条最相关的真实经历（带具体成果，但不带公司名） ③一句软推进（如"想进一步了解这个岗位"）
- 若候选人为转行/跨行背景，不回避，用已有的真实落地成果正面立住
只输出 JSON：{"greeting": "招呼语正文", "hook": "本条主打的匹配点一句话"}"""

USER_TMPL = """【候选人简历（唯一事实依据，不得超出此范围）】
{resume}

【目标岗位】
{title} @ {company}　{salary}　{exp}
技能标签：{tags}
此岗匹配点（精排给出，供参考）：{highlights}

请生成这条招呼语的 JSON。"""


def generate(min_fit: int = 4, limit: int = 20) -> str:
    conn = db.connect()
    resume = score_mod._resume_text()
    if not resume:
        return "未找到母版简历。"
    rows = conn.execute(
        """SELECT s.fit_score, s.highlights, j.* FROM job_scores s JOIN jobs j ON j.id=s.job_pk
           WHERE s.fit_score >= ? ORDER BY s.fit_score DESC""", (min_fit,)
    ).fetchall()
    rows = [dict(r) for r in rows][:limit]
    if not rows:
        return f"没有 fit>={min_fit} 的岗位。先跑 score 精排。"

    model = load_config().llm["model_drafting"]  # 文案用 flash 更快
    print(f"→ 为 {len(rows)} 个高契合岗生成招呼语（不含公司名，模型 {model}）…")

    # 先分组，再按 组→薪资 排序输出
    for r in rows:
        r["_group"] = _group_of(r.get("salary_max"))
    order = {"冲刺": 0, "稳妥": 1, "保底": 2}
    rows.sort(key=lambda r: (order.get(r["_group"], 9), -(r.get("salary_max") or 0)))

    L = [f"# 招呼语草稿 + 分组（{date.today().isoformat()}）", ""]
    L.append("> 只重组你简历真实内容、**不含任何公司名** · 发送前逐条审阅，**你本人在 Boss 手动发送**")
    L.append("> 分组=按薪资档（冲刺≥30K / 稳妥22-29K / 保底<22K），用于已读不回率分组对照")
    L.append("")
    track_rows = []
    cur_group = None
    for i, r in enumerate(rows, 1):
        if r["_group"] != cur_group:
            cur_group = r["_group"]
            L.append(f"\n---\n# 【{cur_group}组】\n")
        try:
            highlights = json.loads(r.get("highlights") or "[]")
        except Exception:
            highlights = []
        user = USER_TMPL.format(
            resume=resume[:3500], title=r.get("title") or "", company=r.get("company") or "",
            salary=r.get("salary_text") or "", exp=r.get("experience") or "",
            tags="、".join([t for t in json.loads(r.get("tags") or "[]")][:8]),
            highlights="；".join(highlights) if highlights else "（无）",
        )
        try:
            out = llm.chat_json(SYSTEM, user, model=model, max_tokens=1200)
            greeting = out.get("greeting", "").strip()
        except Exception as e:
            greeting = f"[生成失败：{type(e).__name__}]"
        print(f"  [{i}/{len(rows)}] [{r['_group']}] {r.get('company','')[:12]} ✓")
        L.append(f"## {i}. {r.get('title','')} @ {r.get('company','')}")
        L.append(f"- 薪资 {r.get('salary_text','')}｜经验 {r.get('experience','')}｜fit {r.get('fit_score')}｜"
                 f"[职位链接]({r.get('url','')})")
        L.append("")
        L.append("> " + greeting.replace("\n", "\n> "))
        L.append("")
        track_rows.append({
            "分组": r["_group"], "公司": r.get("company") or "", "职位": r.get("title") or "",
            "薪资": r.get("salary_text") or "", "招呼语": greeting,
            "已发日期(填)": "", "已读(填1/0)": "", "回复(填1/0)": "", "邀约(填1/0)": "",
            "链接": r.get("url") or "",
        })

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"招呼语-{date.today().isoformat()}.md"
    path.write_text("\n".join(L), encoding="utf-8")

    # 投递追踪表（你发完填状态，后续 stats 算已读不回率）
    track_dir = DATA_DIR / "exports"
    track_dir.mkdir(parents=True, exist_ok=True)
    track_path = track_dir / f"投递追踪-{date.today().isoformat()}.csv"
    cols = ["分组", "公司", "职位", "薪资", "招呼语", "已发日期(填)", "已读(填1/0)",
            "回复(填1/0)", "邀约(填1/0)", "链接"]
    with open(track_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader(); w.writerows(track_rows)

    from collections import Counter
    gc = Counter(r["_group"] for r in rows)
    return (f"✓ {len(rows)} 条招呼语已生成（不含公司名）：{path}\n"
            f"  分组：{dict(gc)}\n"
            f"✓ 投递追踪表：{track_path}\n"
            f"  流程：审阅招呼语 → 你在 Boss 手动发 → 追踪表填 已发/已读/回复 → 我算已读不回率。")
