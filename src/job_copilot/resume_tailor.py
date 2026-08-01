"""简历定制引擎 —— LLM 生成 + 规则降级。

事实红线：只重组母版简历已有内容，不得生成虚假经历/技能/数字。
"""

from __future__ import annotations

import datetime
import json
import re
from typing import Optional

from .database import get_session
from .models import Application, ApplicationEvent, ResumeProfile, ResumeVersion
from .config import load_config, RESUME_DIR
from .llm_runtime import LLMDryRun, LLMRuntimeError, get_runtime


TAILOR_SYSTEM = """你是高级简历顾问。根据母版简历和岗位JD，定制简历。

红线：只能重组母版已有内容，不得添加不存在的工作经历、项目、技能、学历、公司、时间、量化数字。

输出JSON：
{
  "tailored_summary": "2-3句职业摘要",
  "summary_evidence": [
    {"claim": "摘要中的原句", "source_text": "母版简历中的直接证据"}
  ],
  "reordered_skills": ["按JD匹配度排序的技能列表"],
  "skills_evidence": [
    {"skill": "技能名", "source_text": "母版简历中的直接证据"}
  ],
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


class ResumeWorkflowError(Exception):
    """可安全映射为真实 HTTP 状态码的简历工作流错误。"""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


RESUME_EVENT_TYPES = {"resume_created", "resume_reviewed", "resume_used"}


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
            raise ResumeWorkflowError(404, "Application not found")
        if not app.job:
            raise ResumeWorkflowError(422, "Application has no linked job")

        job = app.job
        master = session.query(ResumeProfile).filter(
            ResumeProfile.is_master == 1
        ).first()
        resume = (master.content_text or "") if master else _resume_text()

        if not resume.strip():
            raise ResumeWorkflowError(422, "Master resume is empty")

        jd_text = (job.jd_text or "").strip()
        title = job.title or ""
        company = job.company or ""

        # JD quality gate: require >= 100 chars for full generation
        has_full_jd = len(jd_text) >= 100
        runtime = get_runtime("resume_tailor")
        if runtime.mode == "dry-run" and not has_full_jd:
            raise ResumeWorkflowError(
                422, "A complete JD is required for LLM dry-run validation"
            )

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
            except LLMDryRun as dry_run:
                preview = dict(dry_run.preview)
                preview["application_id"] = application_id
                return preview
            except LLMRuntimeError as exc:
                raise ResumeWorkflowError(
                    exc.status_code, exc.detail
                ) from exc
            source = result.pop(
                "_llm_source",
                runtime.mode,
            )
            result.pop("_llm_mode", None)
            method = f"llm_{source}"
        else:
            result = _rule_tailor(resume, jd_text, title, company, score_data)
            method = "low_context_rule_based"

        if not master:
            now = _now()
            master = ResumeProfile(
                name="母版简历",
                content_text=resume,
                is_master=1,
                created_at=now,
                updated_at=now,
            )
            session.add(master)
            session.flush()

        # Create version
        version_name = f"{company}-{title}-{datetime.date.today().isoformat()}"
        bullets = result.get("experience_bullets", [])
        # Restore original_text from master for each bullet with source_id
        bullets = _restore_original_texts(bullets, resume)

        # Evidence gate on summary and skills
        unsupported = result.get("unsupported_requirements", [])
        summary_text, summary_evidence = _clean_summary(
            result.get("tailored_summary", ""),
            result.get("summary_evidence", []),
            unsupported,
            resume,
        )
        skills_list, skills_evidence = _clean_skills(
            result.get("reordered_skills", []),
            result.get("skills_evidence", []),
            unsupported,
            resume,
        )
        evidence = {
            "summary": summary_evidence,
            "skills": skills_evidence,
        }
        _validate_generated_evidence(
            summary_text, skills_list, bullets, evidence, resume
        )
        now = _now()

        rv = ResumeVersion(
            application_id=application_id,
            resume_profile_id=master.id,
            version_name=version_name,
            summary_text=summary_text,
            skills_json=json.dumps(skills_list, ensure_ascii=False),
            experience_bullets_json=json.dumps(bullets, ensure_ascii=False),
            gap_analysis_json=json.dumps({
                "matched_keywords": result.get("matched_keywords", []),
                "unsupported": unsupported,
                "hard_blockers": result.get("hard_blockers", []),
                "warnings": result.get("warnings", []),
                "context_quality": "FULL" if has_full_jd else "LOW",
                "evidence": evidence,
            }, ensure_ascii=False),
            full_text=_build_full_text(summary_text, skills_list, bullets),
            generation_method=method,
            status="DRAFT",
            created_at=now,
            updated_at=now,
        )
        session.add(rv)
        session.flush()
        _add_resume_event(
            session, rv, "resume_created", None, "DRAFT", now
        )
        session.commit()
        session.refresh(rv)

        events = _status_events(session, rv.application_id)
        return _version_row(rv, events.get(rv.id, []))
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
            elif not str(b.get("evidence_reference", "")).strip():
                b["evidence_reference"] = orig

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
    return chat_json(
        TAILOR_SYSTEM,
        user,
        model=model,
        max_tokens=8000,
        operation="resume_tailor",
        fake_response=lambda: _fake_tailor_result(
            resume, jd, title, company, score
        ),
    )


def _fake_tailor_result(
    resume: str, jd: str, title: str, company: str, score: dict
) -> dict:
    result = _rule_tailor(resume, jd, title, company, score)
    result["warnings"] = [
        "测试模式确定性结果，不代表真实模型输出"
    ]
    return result


def _rule_tailor(resume: str, jd: str, title: str, company: str, score: dict) -> dict:
    """规则降级：只抽取母版原文和已存在技能，不生成新事实。"""
    resume_lower = resume.lower()

    # Extract keywords from JD
    keywords = list(set(re.findall(r'[A-Za-z+#.]+', jd)))
    keywords = [k for k in keywords if len(k) > 1 and k.lower() not in
                ('the', 'a', 'an', 'is', 'are', 'and', 'or', 'to', 'in', 'of', 'for')]

    matched = [k for k in keywords if k.lower() in resume_lower]
    unmatched = [k for k in keywords if k.lower() not in resume_lower][:10]

    evidence_lines = _master_evidence_lines(resume)
    summary_source = _best_evidence_line(evidence_lines, jd, title)
    summary_evidence = []
    if summary_source:
        summary_evidence.append({
            "claim": summary_source,
            "source_text": summary_source,
        })

    skills_evidence = []
    for skill in matched[:15]:
        source = next(
            (line for line in evidence_lines if skill.lower() in line.lower()),
            skill,
        )
        skills_evidence.append({"skill": skill, "source_text": source})

    return {
        "tailored_summary": summary_source,
        "summary_evidence": summary_evidence,
        "reordered_skills": matched[:15],
        "skills_evidence": skills_evidence,
        "experience_bullets": [],
        "matched_keywords": matched,
        "unsupported_requirements": unmatched,
        "hard_blockers": score.get("hard_blockers", []),
        "full_resume_text": "",
        "warnings": ["规则生成版本仅抽取母版原文，未执行经历改写"],
    }


def get_versions(application_id: int) -> list:
    session = get_session()
    try:
        if not session.get(Application, application_id):
            raise ResumeWorkflowError(404, "Application not found")
        rows = session.query(ResumeVersion).filter(
            ResumeVersion.application_id == application_id
        ).order_by(ResumeVersion.created_at.desc()).all()
        events = _status_events(session, application_id)
        return [_version_row(r, events.get(r.id, [])) for r in rows]
    finally:
        session.close()


def get_version(version_id: int) -> Optional[dict]:
    session = get_session()
    try:
        rv = session.get(ResumeVersion, version_id)
        if not rv:
            return None
        events = _status_events(session, rv.application_id)
        return _version_row(rv, events.get(rv.id, []))
    finally:
        session.close()


def update_version(version_id: int, data: dict) -> Optional[dict]:
    session = get_session()
    try:
        rv = session.get(ResumeVersion, version_id)
        if not rv:
            return None
        protected = {
            "status", "created_at", "updated_at", "application_id",
            "resume_profile_id",
        }
        if protected.intersection(data):
            raise ResumeWorkflowError(
                422, "Resume status and audit fields are read-only"
            )
        if rv.status != "DRAFT":
            raise ResumeWorkflowError(
                409, "Only DRAFT resume versions can be edited"
            )
        allowed = {"version_name", "experience_bullets_json"}
        unknown = set(data) - allowed
        if unknown:
            fields = ", ".join(sorted(unknown))
            raise ResumeWorkflowError(422, f"Unsupported resume fields: {fields}")
        for k, v in data.items():
            setattr(rv, k, v)
        if "experience_bullets_json" in data:
            bullets = _parse_json(data["experience_bullets_json"])
            skills = _parse_json(rv.skills_json)
            rv.full_text = _build_full_text(
                rv.summary_text or "", skills, bullets
            )
        rv.updated_at = _now()
        session.commit()
        session.refresh(rv)
        events = _status_events(session, rv.application_id)
        return _version_row(rv, events.get(rv.id, []))
    finally:
        session.close()


def review_version(version_id: int) -> Optional[dict]:
    session = get_session()
    try:
        rv = session.get(ResumeVersion, version_id)
        if not rv:
            return None
        if rv.status != "DRAFT":
            raise ResumeWorkflowError(
                409, f"Invalid resume transition: {rv.status} -> REVIEWED"
            )
        _validate_review_evidence(session, rv)
        now = _now()
        rv.status = "REVIEWED"
        rv.updated_at = now
        _add_resume_event(
            session, rv, "resume_reviewed", "DRAFT", "REVIEWED", now
        )
        session.commit()
        session.refresh(rv)
        events = _status_events(session, rv.application_id)
        return _version_row(rv, events.get(rv.id, []))
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def use_version(version_id: int) -> Optional[dict]:
    session = get_session()
    try:
        rv = session.get(ResumeVersion, version_id)
        if not rv:
            return None
        if rv.status != "REVIEWED":
            raise ResumeWorkflowError(
                409, f"Invalid resume transition: {rv.status} -> USED"
            )
        _validate_review_evidence(session, rv)
        now = _now()
        rv.status = "USED"
        rv.updated_at = now
        _add_resume_event(
            session, rv, "resume_used", "REVIEWED", "USED", now
        )
        session.commit()
        session.refresh(rv)
        events = _status_events(session, rv.application_id)
        return _version_row(rv, events.get(rv.id, []))
    except Exception:
        session.rollback()
        raise
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


def _version_row(rv: ResumeVersion, status_events: Optional[list] = None) -> dict:
    events = status_events or []
    reviewed_at = next(
        (e["timestamp"] for e in events
         if e["event_type"] == "resume_reviewed"),
        None,
    )
    used_at = next(
        (e["timestamp"] for e in events
         if e["event_type"] == "resume_used"),
        None,
    )
    if rv.generation_method == "llm_fake":
        source = "fake"
    elif rv.generation_method == "llm_live":
        source = "live"
    elif rv.generation_method == "llm":
        source = "legacy"
    else:
        source = "rule"
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
        "source": source,
        "status": rv.status,
        "created_at": rv.created_at,
        "reviewed_at": reviewed_at,
        "used_at": used_at,
        "updated_at": rv.updated_at,
        "status_events": events,
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


def _build_full_text(summary: str, skills: list, bullets: list) -> str:
    """Assemble full resume text from accepted bullets only."""
    accepted = [b for b in bullets if b.get("risk_level") != "BLOCKED"]
    L = ["# 定制简历", "", "## 职业摘要", summary, "", "## 技能"]
    for s in skills:
        L.append(f"- {s}")
    L.append("")
    L.append("## 相关经历")
    for i, b in enumerate(accepted):
        L.append(f"### {i+1}. {b.get('tailored_text','')[:80]}")
        L.append(b.get("tailored_text", ""))
        L.append("")
    return "\n".join(L)


def _clean_summary(
    summary: str, evidence: list, unsupported: list, master: str
) -> tuple[str, list]:
    """只保留带有母版原文证据的 Summary claim；无安全回退。"""
    unsup_lower = {u.lower()[:20] for u in unsupported}
    summary_norm = _normalize_text(summary)
    verified = []
    claims = []
    for item in evidence if isinstance(evidence, list) else []:
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim", "")).strip()
        source = str(item.get("source_text", "")).strip()
        if not claim or not _source_in_master(source, master):
            continue
        if _normalize_text(claim) not in summary_norm:
            continue
        if any(u[:10] and u[:10] in claim.lower() for u in unsup_lower):
            continue
        if not _numbers_supported(claim, source):
            continue
        claims.append(claim)
        verified.append({"claim": claim, "source_text": source})
    return " ".join(claims).strip(), verified


def _clean_skills(
    skills: list, evidence: list, unsupported: list, master: str
) -> tuple[list, list]:
    """Filter skills against unsupported requirements and master evidence."""
    unsup_keywords = set()
    for u in unsupported:
        for w in u.lower().split():
            if len(w) > 3 and w not in ('的','和','与','或','有','等','及'):
                unsup_keywords.add(w)
    # Also check for frameworks/tools not in master
    master_lower = master.lower()
    clean = []
    verified_evidence = []
    evidence_by_skill = {
        str(item.get("skill", "")).strip().lower(): item
        for item in evidence
        if isinstance(item, dict) and item.get("skill")
    }
    for s in skills:
        if not isinstance(s, str) or not s.strip():
            continue
        s = s.strip()
        s_lower = s.lower()
        # Block if keyword matches unsupported
        if any(kw in s_lower for kw in unsup_keywords):
            continue
        # Block framework claims not in master
        for fw in ['langchain','langgraph','fastapi','flask','django','tensorflow','pytorch']:
            if fw in s_lower and fw not in master_lower:
                break
        else:
            item = evidence_by_skill.get(s_lower)
            source = str(item.get("source_text", "")).strip() if item else ""
            if s_lower not in master_lower or not _source_in_master(source, master):
                continue
            clean.append(s)
            verified_evidence.append({"skill": s, "source_text": source})
    return clean, verified_evidence


def _normalize_text(value: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKC", value or "").lower()
    return re.sub(r"\s+", " ", normalized).strip()


def _source_in_master(source: str, master: str) -> bool:
    source_norm = _normalize_text(source)
    return bool(source_norm) and source_norm in _normalize_text(master)


def _numbers_supported(claim: str, source: str) -> bool:
    claim_numbers = set(re.findall(r"\d+(?:\.\d+)?%?", claim or ""))
    source_numbers = set(re.findall(r"\d+(?:\.\d+)?%?", source or ""))
    return claim_numbers.issubset(source_numbers)


def _master_evidence_lines(master: str) -> list[str]:
    lines = []
    for raw in master.splitlines():
        line = raw.strip().lstrip("-* ").strip()
        if len(line) < 12 or line.startswith("#") or line.startswith(">"):
            continue
        if "@" in line or re.search(r"\b1\d{10}\b", line):
            continue
        lines.append(line)
    return lines


def _best_evidence_line(lines: list[str], jd: str, title: str) -> str:
    if not lines:
        return ""
    target_tokens = {
        token.lower()
        for token in re.findall(r"[A-Za-z+#.]{2,}|[\u4e00-\u9fff]{2,}", f"{title} {jd}")
    }

    def score(line: str) -> tuple[int, int]:
        line_lower = line.lower()
        overlap = sum(1 for token in target_tokens if token in line_lower)
        return overlap, min(len(line), 160)

    return max(lines, key=score)


def _validate_generated_evidence(
    summary: str, skills: list, bullets: list, evidence: dict, master: str
) -> None:
    if not summary.strip() or not evidence.get("summary"):
        raise ResumeWorkflowError(
            422, "No evidence-backed Summary could be generated"
        )

    summary_items = [
        item for item in evidence.get("summary", [])
        if isinstance(item, dict)
    ]
    for item in summary_items:
        claim = str(item.get("claim", "")).strip()
        source = str(item.get("source_text", "")).strip()
        if not _source_in_master(source, master):
            raise ResumeWorkflowError(422, "Summary source is not in master resume")
        if not _numbers_supported(claim, source):
            raise ResumeWorkflowError(422, "Summary introduces unsupported numbers")
    summary_claims = " ".join(
        str(item.get("claim", "")).strip() for item in summary_items
    ).strip()
    if _normalize_text(summary_claims) != _normalize_text(summary):
        raise ResumeWorkflowError(422, "Summary evidence does not match content")

    skill_refs = {
        str(item.get("skill", "")).strip().lower(): item
        for item in evidence.get("skills", [])
        if isinstance(item, dict)
    }
    for skill in skills:
        item = skill_refs.get(str(skill).strip().lower())
        source = str(item.get("source_text", "")).strip() if item else ""
        if not item or not _source_in_master(source, master):
            raise ResumeWorkflowError(
                422, f"Skill lacks master-resume evidence: {skill}"
            )

    for bullet in bullets:
        if not isinstance(bullet, dict) or bullet.get("risk_level") == "BLOCKED":
            continue
        original = str(bullet.get("original_text", "")).strip()
        tailored = str(bullet.get("tailored_text", "")).strip()
        reference = str(bullet.get("evidence_reference", "")).strip()
        if not original or not tailored or not reference:
            raise ResumeWorkflowError(422, "Experience bullet lacks evidence")
        if not _source_in_master(original, master):
            raise ResumeWorkflowError(422, "Experience evidence is not in master resume")
        if not _numbers_supported(tailored, original):
            raise ResumeWorkflowError(422, "Experience bullet introduces unsupported numbers")


def _validate_review_evidence(session, rv: ResumeVersion) -> None:
    app = session.get(Application, rv.application_id)
    if not app or not app.job:
        raise ResumeWorkflowError(422, "Resume version has no linked job")
    jd_text = (app.job.jd_text or "").strip()
    if len(jd_text) < 100:
        raise ResumeWorkflowError(
            422, "A complete JD is required before review"
        )

    gap = _parse_json_object(rv.gap_analysis_json)
    if (gap.get("context_quality") != "FULL" or
            rv.generation_method == "low_context_rule_based"):
        raise ResumeWorkflowError(
            422, "Low-context resume versions cannot be reviewed"
        )

    profile = session.get(ResumeProfile, rv.resume_profile_id)
    master = profile.content_text or "" if profile else ""
    if not master.strip():
        raise ResumeWorkflowError(422, "Master resume evidence is unavailable")

    skills = _parse_json(rv.skills_json)
    bullets = _parse_json(rv.experience_bullets_json)
    evidence = gap.get("evidence", {})
    _validate_generated_evidence(
        rv.summary_text or "", skills, bullets, evidence, master
    )

    unsafe_bullets = [
        bullet for bullet in bullets
        if isinstance(bullet, dict) and bullet.get("risk_level") == "REVIEW"
    ]
    safe_bullets = [
        bullet for bullet in bullets
        if isinstance(bullet, dict) and bullet.get("risk_level") == "SAFE"
    ]
    if unsafe_bullets:
        raise ResumeWorkflowError(
            422, "All REVIEW experience bullets must be accepted or rejected"
        )
    if not skills and not safe_bullets:
        raise ResumeWorkflowError(
            422, "Resume evidence is insufficient for review"
        )


def _add_resume_event(
    session, rv: ResumeVersion, event_type: str,
    from_status: Optional[str], to_status: str, occurred_at: str,
) -> None:
    content = json.dumps(
        {
            "resume_version_id": rv.id,
            "application_id": rv.application_id,
            "from_status": from_status,
            "to_status": to_status,
            "timestamp": occurred_at,
            "version_name": rv.version_name,
        },
        ensure_ascii=False,
    )
    session.add(ApplicationEvent(
        application_id=rv.application_id,
        event_type=event_type,
        from_stage=from_status,
        to_stage=to_status,
        content=content,
        occurred_at=occurred_at,
    ))


def _status_events(session, application_id: int) -> dict[int, list[dict]]:
    rows = session.query(ApplicationEvent).filter(
        ApplicationEvent.application_id == application_id,
        ApplicationEvent.event_type.in_(RESUME_EVENT_TYPES),
    ).order_by(ApplicationEvent.id).all()
    grouped: dict[int, list[dict]] = {}
    for event in rows:
        payload = _parse_json_object(event.content)
        version_id = payload.get("resume_version_id")
        if not isinstance(version_id, int):
            continue
        grouped.setdefault(version_id, []).append({
            "id": event.id,
            "event_type": event.event_type,
            "resume_version_id": version_id,
            "application_id": event.application_id,
            "from_status": event.from_stage,
            "to_status": event.to_stage,
            "timestamp": event.occurred_at,
        })
    return grouped


def _parse_json_object(val: Optional[str]) -> dict:
    if not val:
        return {}
    try:
        parsed = json.loads(val)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _parse_json(val: Optional[str]) -> list:
    if not val:
        return []
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return [val] if val else []
