"""LLM 精排：对粗筛候选做 Block A-G 核心评估（M6.1）。

粗筛（embed 余弦）负责"从401条召回候选"，精排（本模块）负责"判断契合度与该不该投"。
用 DeepSeek + skills/job-eval 的 Block A-G 决策相关块，输出结构化分数：
匹配度1-5、投/慎投/不投、角色画像、资历是否够、真实性、理由、简历该突出点、缺口。

约束（红线1）：简历匹配只依据母版简历真实内容，不臆造候选人没有的经历。
列表页无 JD 全文，评估基于 标题+行业+技能标签+经验+学历+薪资 等结构化信号
（这已足够识别"标题写大模型、实为Android"这类粗筛假阳性）。
"""

from __future__ import annotations

import json
from datetime import date

from .config import RESUME_DIR, REPORTS_DIR, load_config
from . import db, match, llm

SYSTEM = """你是资深技术招聘顾问，帮一位【AI应用/Agent工程】转行候选人判断岗位是否值得投。
严格基于提供的候选人简历事实，不得臆造简历中没有的经历。
只输出 JSON，字段：
- fit_score: 1-5 的匹配度，据 JD 与简历的实际契合度客观判断，不必刻意压低或抬高：
  5=高度契合优先投；4=契合可投；3=模棱两可/利弊相当；2=偏不合适；1=基本不匹配。
- verdict: 由 fit_score 代码推导（fit≥4→投 / =3→慎投 / ≤2→不投），无需你给
  （注：2026-07 留出集验证发现"强制果断"会让模型过度拒绝、过拟合开发集，故回退为客观打分）
- archetype: 该岗真实画像，从 [AI应用工程, Agent工程, 大模型算法研究, 后端工程, 前端/全栈, 数据工程, 其它] 选一个（看技能标签实质，别被标题误导）
- seniority_ok: true/false（候选人资历是否够得着；候选人=本科转行、约1年AI项目经验）
- authenticity: "高" | "中" | "低"（岗位真实性/幽灵职位嫌疑，据薪资是否异常宽、描述是否空泛判断）
- reasons: 3条以内简短中文理由（数组）
- highlights: 若投，简历应突出的2-3个真实点（数组，须来自简历）
- gaps: 关键缺口2-3个（数组）

【额外判断信号（据此调整 fit_score / verdict / reasons）】
1. **低代码平台岗**：若职位以 n8n、coze、扣子、纯 Dify 拖拽编排 为主要工作（而非用代码写 Agent/后端），工程含量偏低。对"想做硬核 AI 工程、补工程能力"的候选人，契合度应下调（fit 至少降 1 档），reasons 注明"偏低代码、工程成长有限"。真正用 Python/框架写 Agent 的岗不受此影响。
2. **外包/人力外包公司**：若公司是软件外包/人力外派性质（典型如 微创软件、软通动力、中软国际、博彦、文思海辉 等，或 JD 含 驻场/外派/人力外包/乙方常驻甲方 字样），对转行候选人成长与稳定性有风险，verdict 倾向"慎投"、authenticity/reasons 注明"疑似外包，需向HR确认用工性质"。判断不确定时据公司名与业务描述合理推断。"""

USER_TMPL = """【候选人简历（唯一事实依据）】
{resume}

【待评岗位】
职位：{title}
公司：{company}（{industry}，{size}）
薪资：{salary}　经验要求：{exp}　学历：{degree}　城市：{city}
技能标签：{tags}

请按系统指令输出该岗的 JSON 评估。特别注意：技能标签能暴露岗位真实画像——
若标签是 Android/Kotlin/前端/纯算法(深度学习/多模态/强化学习/图像/语音)等，
说明标题里的"大模型/AI"是包装，archetype 要如实归类、fit_score 相应下调。"""


def _resume_text() -> str:
    p = RESUME_DIR / "母版简历.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _verdict_from_fit(fit) -> str:
    """由 fit_score 确定性推导 verdict，保证分数与结论一致（根除 LLM 自相矛盾）。"""
    try:
        f = float(fit)
    except (TypeError, ValueError):
        return "慎投"
    if f >= 4:
        return "投"
    if f <= 2:
        return "不投"
    return "慎投"


def score_one(conn, r: dict, resume: str, model: str) -> dict:
    """评估单个职位并存库，返回评分 dict。"""
    user = USER_TMPL.format(
        resume=resume[:3500],
        title=r.get("title") or "", company=r.get("company") or "",
        industry=r.get("industry") or "", size=r.get("company_size") or "",
        salary=r.get("salary_text") or "", exp=r.get("experience") or "",
        degree=r.get("degree") or "", city=r.get("city") or "",
        tags="、".join(match._tags_of(r)),
    )
    s = llm.chat_json(SYSTEM, user, model=model, max_tokens=2500)
    s["verdict"] = _verdict_from_fit(s.get("fit_score"))  # 代码层强制 fit↔verdict 一致
    db.save_score(conn, r["id"], s, model)
    return s


def score_top(top_k: int = 20, resume: str = "", skip_scored: bool = False) -> str:
    conn = db.connect()
    resume = resume or _resume_text()
    if not resume:
        return "未找到母版简历，无法精排。"
    if skip_scored:
        # 跳过已精排的岗，取粗筛排序里接下来的 top_k 个新候选（分批扩投，不重复花 API）
        done = {r[0] for r in conn.execute("SELECT job_pk FROM job_scores").fetchall()}
        pool = match.ranked_matches(top_k=top_k + len(done), filtered=True)
        cands = [(sim, r) for sim, r in pool if r["id"] not in done][:top_k]
    else:
        cands = match.ranked_matches(top_k=top_k, filtered=True)
    if not cands:
        return "无候选职位。先 collect import 并 match（--skip-scored 时可能已全部精排过）。"

    cfg = load_config()
    model = cfg.llm["model_analysis"]
    print(f"→ LLM 精排 {len(cands)} 个候选（模型 {model}，逐个评估，约每条十几秒）…")

    results = []
    for i, (sim, r) in enumerate(cands, 1):
        try:
            s = score_one(conn, r, resume, model)
            results.append((sim, s, r))
            print(f"  [{i}/{len(cands)}] {r.get('title','')[:24]} → "
                  f"fit={s.get('fit_score')} {s.get('verdict')} ({s.get('archetype')})")
        except Exception as e:
            print(f"  [{i}/{len(cands)}] {r.get('title','')[:24]} → 评分失败：{type(e).__name__} {str(e)[:80]}")

    if not results:
        return "全部评分失败（检查 API/网络）。"

    # 精排：按 fit_score 降序，同分按粗筛相似度
    results.sort(key=lambda x: (-(x[1].get("fit_score") or 0), -x[0]))
    return _report(results)


def _report(results: list) -> str:
    L = [f"# 职位精排（LLM Block A-G · {date.today().isoformat()}）", ""]
    L.append(f"> {len(results)} 个粗筛候选经 DeepSeek 精评 · 按匹配度排序 · "
             "匹配度=LLM判定(1-5)，粗筛=embed余弦")
    L.append("")
    L.append("| 匹配度 | 建议 | 画像 | 够得着 | 真实性 | 职位 | 公司 | 薪资 | 粗筛分 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for sim, s, r in results:
        L.append(
            f"| **{s.get('fit_score','?')}** | {s.get('verdict','?')} | {s.get('archetype','?')} "
            f"| {'✓' if s.get('seniority_ok') else '✗'} | {s.get('authenticity','?')} "
            f"| {r.get('title','')} | {r.get('company','')} | {r.get('salary_text','')} | {sim:.3f} |")
    L.append("")
    L.append("## 逐岗理由（匹配度≥4 优先投）")
    L.append("")
    for sim, s, r in results:
        if (s.get("fit_score") or 0) < 3:
            continue
        L.append(f"### {s.get('fit_score')}/5 · {s.get('verdict')} · {r.get('title','')}（{r.get('company','')}）")
        for x in (s.get("reasons") or []):
            L.append(f"- {x}")
        if s.get("highlights"):
            L.append(f"- **简历突出**：{'；'.join(s['highlights'])}")
        if s.get("gaps"):
            L.append(f"- **缺口**：{'；'.join(s['gaps'])}")
        L.append("")

    report = "\n".join(L)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    # 同日多批不覆盖：已存在则加 -2/-3 后缀
    path = REPORTS_DIR / f"精排-{date.today().isoformat()}.md"
    _n = 2
    while path.exists():
        path = REPORTS_DIR / f"精排-{date.today().isoformat()}-{_n}.md"
        _n += 1
    path.write_text(report, encoding="utf-8")
    return report + f"\n\n---\n已保存：{path}"
