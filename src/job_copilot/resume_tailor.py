"""简历定制引擎 —— LLM 生成 + 规则降级。

事实红线：只重组母版简历已有内容，不得生成虚假经历/技能/数字。
"""

from __future__ import annotations

import datetime
import json
from typing import Optional

from sqlalchemy import text as sa_text
from .database import get_session
from .models import Application, Job, ResumeProfile, ResumeVersion
from .config import load_config, RESUME_DIR


TAILOR_SYSTEM = """你是高级简历顾问。根据母版简历和岗位JD，定制简历。

红线：只能重组母版已有内容，不得添加不存在的工作经历、项目、技能、学历、公司、时间、量化数字。

输出JSON：
{
  "tailored_summary": "2-3句职业摘要",
  "reordered_skills": ["按JD匹配度排序的技能列表"],
  "experience_bullets": [
    {
      "original_text": "原文",
      "tailored_text": "定制后",
      "reason": "修改理由",
      "evidence_reference": "母版证据来源",
      "risk_level": "SAFE|REVIEW|BLOCKED"
    }
  ],
  "matched_keywords": ["匹配关键词"],
  "unsupported_requirements": ["JD要求但无证据的要求"],
  "hard_blockers": ["硬性不匹配"],
  "full_resume_text": "完整简历文本",
  "warnings": ["注意事项"]
}

risk_level规则:
- SAFE: 纯重排或表达优化，有明确证据
- REVIEW: 包含合理推断，需人工确认
- BLOCKED: 缺少事实证据，不要放进full_resume_text"""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _resume_text(profile_id: Optional[int] = None) -> str:
    """读取母版简历文本（过滤内部元数据）。"""
    text = ""
    if profile_id:
        session = get_session()
        try:
            rp = session.get(ResumeProfile, profile_id)
            text = rp.content_text or "" if rp else ""
        finally:
            session.close()
    else:
        for name in ["母版简历.md", "resume.md", "README.md"]:
            p = RESUME_DIR / name
            if p.exists():
                text = p.read_text(encoding="utf-8")
                break

    # Filter internal metadata lines (merge sources, fact boundaries, system notes)
    import re
    lines = text.split("\n")
    filtered = []
    skip_patterns = [
        r"^# .*母版简历.*事实来源",
        r"^> 合并自",
        r"^> 本文件是",
        r"^> `\[待补充\]`",
        r"^\[待补充\]",
        r"^> \*",
    ]
    for line in lines:
        if any(re.match(p, line) for p in skip_patterns):
            continue
        filtered.append(line)
    return "\n".join(filtered)


def _get_or_create_master_profile() -> ResumeProfile:
    session = get_session()
    try:
        master = session.query(ResumeProfile).filter(
            ResumeProfile.is_master == 1
        ).first()
        if not master:
            text = _resume_text()
            master = ResumeProfile(
                name="母版简历",
                content_text=text,
                is_master=1,
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(master)
            session.commit()
            session.refresh(master)
        return master
    finally:
        session.close()


def tailor_resume(application_id: int) -> dict:
    """为指定 Application 生成定制简历版本。"""
    session = get_session()
    try:
        app = session.get(Application, application_id)
        if not app:
            return {"error": "Application not found", "status": 404}
        if not app.job:
            return {"error": "No job linked", "status": 400}

        job = app.job
        master = _get_or_create_master_profile()
        resume = master.content_text or ""

        if not resume.strip():
            return {"error": "Master resume is empty", "status": 400}

        jd_text = (job.jd_text or "").strip()
        title = job.title or ""
        company = job.company or ""

        # JD quality gate: require >= 100 chars for full generation
        has_full_jd = len(jd_text) >= 100

        # Read score data
        score_data = {}
        if app.job and app.job.score:
            s = app.job.score
            score_data = {
                "matched_evidence": _parse_json(s.highlights),
                "missing_requirements": _parse_json(s.gaps),
            }

        # Generate: only use LLM if JD is complete
        if has_full_jd:
            try:
                result = _llm_tailor(resume, jd_text, title, company, score_data)
                method = "llm"
            except Exception:
                result = _rule_tailor(resume, jd_text, title, company, score_data)
                method = "rule_based"
        else:
            result = _rule_tailor(resume, jd_text, title, company, score_data)
            method = "low_context_rule_based"

        # Create version
        version_name = f"{company}-{title}-{datetime.date.today().isoformat()}"
        bullets = result.get("experience_bullets", [])
        # Restore original_text from master for each bullet with source_id
        bullets = _restore_original_texts(bullets, resume)

        rv = ResumeVersion(
            application_id=application_id,
            resume_profile_id=master.id,
            version_name=version_name,
            summary_text=result.get("tailored_summary", ""),
            skills_json=json.dumps(result.get("reordered_skills", []), ensure_ascii=False),
            experience_bullets_json=json.dumps(bullets, ensure_ascii=False),
            gap_analysis_json=json.dumps({
                "matched_keywords": result.get("matched_keywords", []),
                "unsupported": result.get("unsupported_requirements", []),
                "hard_blockers": result.get("hard_blockers", []),
                "warnings": result.get("warnings", []),
                "context_quality": "FULL" if has_full_jd else "LOW",
            }, ensure_ascii=False),
            full_text=result.get("full_resume_text", ""),
            generation_method=method,
            status="DRAFT",
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(rv)
        session.commit()
        session.refresh(rv)

        return _version_row(rv)
    finally:
        session.close()


def _restore_original_texts(bullets: list, master: str) -> list:
    """Restore original_text from master resume, ignoring LLM rewrites."""
    import re as _re

    def _norm(text: str) -> str:
        """Normalize for fuzzy matching: unicode, case, whitespace, punctuation."""
        import unicodedata
        text = unicodedata.normalize("NFKC", text or "")
        text = text.lower().strip()
        text = _re.sub(r"\s+", " ", text)
        text = _re.sub(r"[，,。.！!？?：:；;、""''\"\"（）()【】\[\]《》<>]", "", text)
        # Full-width to half-width
        result = []
        for ch in text:
            code = ord(ch)
            if 0xFF01 <= code <= 0xFF5E:
                result.append(chr(code - 0xFEE0))
            else:
                result.append(ch)
        return "".join(result).strip()

    master_norm = _norm(master)
    for b in bullets:
        source_id = b.get("source_id")
        orig = b.get("original_text", "")

        # If source_id is provided, look up from master (future: structured lookup)
        # For now: fuzzy match original_text against master to verify
        if len(orig) > 20:
            norm_orig = _norm(orig)
            # Check if a meaningful substring exists in master
            found = norm_orig[:40] in master_norm if len(norm_orig) >= 40 else norm_orig in master_norm
            if not found:
                # Try sliding 30-char window
                found = any(
                    norm_orig[i:i + 30] in master_norm
                    for i in range(0, max(1, len(norm_orig) - 30), 10)
                )
            if not found:
                b["risk_level"] = "BLOCKED"
                b["reason"] = (b.get("reason", "") + " [BLOCKED: original_text not found in master resume]").strip()

    return bullets


def _llm_tailor(resume: str, jd: str, title: str, company: str, score: dict) -> dict:
    from .llm import chat_json
    cfg = load_config()
    model = cfg.llm.get("model_drafting", "deepseek-v4-flash")

    user = (
        f"【母版简历】\n{resume[:3000]}\n\n"
        f"【岗位】{title} @ {company}\n"
        f"【JD】\n{jd[:2000]}\n\n"
        f"【已匹配证据】{json.dumps(score.get('matched_evidence', []), ensure_ascii=False)}\n"
        f"【缺失要求】{json.dumps(score.get('missing_requirements', []), ensure_ascii=False)}\n"
        f"请基于母版内容生成定制简历JSON。"
    )
    try:
        return chat_json(TAILOR_SYSTEM, user, model=model, max_tokens=8000)
    except Exception:
        # Retry with shorter prompt
        user_short = f"母版简历:\n{resume[:2000]}\n\n岗位:{title}@{company}\nJD:{jd[:1000]}\n请生成定制简历JSON。"
        return chat_json(TAILOR_SYSTEM, user_short, model=model, max_tokens=8000)


def _rule_tailor(resume: str, jd: str, title: str, company: str, score: dict) -> dict:
    """规则降级：关键词匹配 + 技能排序 + 模板化改写。"""
    resume_lower = resume.lower()
    jd_lower = jd.lower()

    # Extract keywords from JD
    import re
    keywords = list(set(re.findall(r'[A-Za-z+#.]+', jd)))
    keywords = [k for k in keywords if len(k) > 1 and k.lower() not in
                ('the', 'a', 'an', 'is', 'are', 'and', 'or', 'to', 'in', 'of', 'for')]

    matched = [k for k in keywords if k.lower() in resume_lower]
    unmatched = [k for k in keywords if k.lower() not in resume_lower][:10]

    # Simple template
    full = (
        f"# 定制简历\n\n"
        f"## 目标岗位\n{title} @ {company}\n\n"
        f"## 母版简历\n{resume[:3000]}\n\n"
        f"## 匹配关键词\n{', '.join(matched[:20])}\n\n"
        f"## 建议补充\n{', '.join(unmatched[:10])}\n\n"
        f"> 生成方式: 规则匹配。使用LLM可获得更精准的定制。"
    )

    return {
        "tailored_summary": f"针对{title}岗位的定制简历（规则生成）",
        "reordered_skills": matched[:15],
        "experience_bullets": [],
        "matched_keywords": matched,
        "unsupported_requirements": unmatched,
        "hard_blockers": score.get("hard_blockers", []),
        "full_resume_text": full,
        "warnings": ["规则生成版本，建议使用LLM重新生成以获得更好效果"],
    }


def get_versions(application_id: int) -> list:
    session = get_session()
    try:
        rows = session.query(ResumeVersion).filter(
            ResumeVersion.application_id == application_id
        ).order_by(ResumeVersion.created_at.desc()).all()
        return [_version_row(r) for r in rows]
    finally:
        session.close()


def get_version(version_id: int) -> Optional[dict]:
    session = get_session()
    try:
        rv = session.get(ResumeVersion, version_id)
        return _version_row(rv) if rv else None
    finally:
        session.close()


def update_version(version_id: int, data: dict) -> Optional[dict]:
    session = get_session()
    try:
        rv = session.get(ResumeVersion, version_id)
        if not rv:
            return None
        for k, v in data.items():
            if hasattr(rv, k) and k != "id":
                setattr(rv, k, v)
        rv.updated_at = _now()
        session.commit()
        session.refresh(rv)
        return _version_row(rv)
    finally:
        session.close()


def mark_used(version_id: int) -> Optional[dict]:
    session = get_session()
    try:
        rv = session.get(ResumeVersion, version_id)
        if not rv:
            return None
        # Block mark-used for low-context versions
        gap = json.loads(rv.gap_analysis_json or "{}")
        if gap.get("context_quality") == "LOW" or rv.generation_method == "low_context_rule_based":
            return {"error": "Cannot mark USED: low context quality. Add full JD and regenerate.", "status": 400}
        # Demote other USED versions for same application
        session.execute(
            sa_text("UPDATE resume_versions SET status='REVIEWED' "
                    "WHERE application_id=:aid AND status='USED' AND id!=:vid"),
            {"aid": rv.application_id, "vid": version_id},
        )
        rv.status = "USED"
        rv.updated_at = _now()
        session.commit()
        session.refresh(rv)
        return _version_row(rv)
    finally:
        session.close()


def get_profiles() -> list:
    session = get_session()
    try:
        return [_profile_row(r) for r in session.query(ResumeProfile).all()]
    finally:
        session.close()


def upsert_profile(data: dict) -> dict:
    session = get_session()
    try:
        pid = data.get("id")
        if pid:
            rp = session.get(ResumeProfile, pid)
            if rp:
                for k, v in data.items():
                    if hasattr(rp, k) and k != "id":
                        setattr(rp, k, v)
                rp.updated_at = _now()
        else:
            rp = ResumeProfile(
                name=data.get("name", "Untitled"),
                content_text=data.get("content_text", ""),
                is_master=data.get("is_master", 0),
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(rp)
        session.commit()
        session.refresh(rp)
        return _profile_row(rp)
    finally:
        session.close()


def _version_row(rv: ResumeVersion) -> dict:
    return {
        "id": rv.id,
        "application_id": rv.application_id,
        "resume_profile_id": rv.resume_profile_id,
        "version_name": rv.version_name,
        "summary_text": rv.summary_text,
        "skills_json": rv.skills_json,
        "experience_bullets_json": rv.experience_bullets_json,
        "gap_analysis_json": rv.gap_analysis_json,
        "full_text": rv.full_text,
        "generation_method": rv.generation_method,
        "status": rv.status,
        "created_at": rv.created_at,
        "updated_at": rv.updated_at,
    }


def _profile_row(rp: ResumeProfile) -> dict:
    return {
        "id": rp.id,
        "name": rp.name,
        "content_text": rp.content_text,
        "is_master": rp.is_master,
        "created_at": rp.created_at,
        "updated_at": rp.updated_at,
    }


def _parse_json(val: Optional[str]) -> list:
    if not val:
        return []
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return [val] if val else []
