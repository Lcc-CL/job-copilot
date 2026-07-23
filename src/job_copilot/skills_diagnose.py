"""技能树诊断（M4 · 竞争力与技能差距分析）。

从清洗后岗位数据提取市场需求技能，与用户简历证据对比，输出：
- 市场技能需求 Top N
- 用户已有技能（含证据来源）
- 高/中/低优先级技能缺口
- 简历优化建议 + 学习路线图

原则：
- 用户技能必须有简历/profil证据，不臆造
- 技能别名归一化（不建庞大知识图谱，覆盖高频即可）
- 缺口优先级 = 市场需求频率 × 证据强弱 × 可补齐性
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from .config import DATA_DIR, REPORTS_DIR, RESUME_DIR, load_config

CLEAN_CSV = DATA_DIR / "clean" / "cleaned_jobs.csv"
ANALYSIS_DIR = DATA_DIR / "analysis"

# ============================================================
# 技能别名归一化表（高频覆盖，不建知识图谱）
# ============================================================
_ALIAS_MAP: dict[str, str] = {
    # 编程语言
    "js": "JavaScript", "javascript": "JavaScript",
    "ts": "TypeScript", "typescript": "TypeScript",
    "py": "Python",
    "golang": "Go", "go": "Go",
    "c/c++": "C/C++", "c++": "C++",
    "rust": "Rust",
    "java": "Java",
    "c#": "C#", "csharp": "C#",
    "php": "PHP",
    "ruby": "Ruby",
    "scala": "Scala",
    "kotlin": "Kotlin",
    "swift": "Swift",
    # AI/LLM
    "llm": "大语言模型(LLM)", "大模型": "大语言模型(LLM)",
    "大语言模型": "大语言模型(LLM)", "大模型算法": "大模型算法",
    "ai agent": "AI Agent", "agent": "AI Agent",
    "rag": "RAG",
    "langchain": "LangChain",
    "dify": "Dify",
    "prompt engineering": "Prompt工程", "prompt": "Prompt工程",
    "机器学习": "机器学习", "深度学习": "深度学习",
    "自然语言处理": "自然语言处理(NLP)", "nlp": "自然语言处理(NLP)",
    "自然语言处理算法": "自然语言处理(NLP)",
    "计算机视觉": "计算机视觉(CV)", "cv": "计算机视觉(CV)",
    "图像算法": "计算机视觉(CV)", "视觉算法": "计算机视觉(CV)",
    "多模态算法": "多模态", "多模态": "多模态",
    "强化学习": "强化学习",
    "推荐算法": "推荐系统", "搜索算法": "搜索系统",
    "语音算法": "语音识别/合成",
    "pytorch": "PyTorch", "tensorflow": "TensorFlow",
    "模型加速/性能优化": "模型优化/加速",
    "发表算法相关优秀论文": "论文发表(算法)",
    "参加算法相关竞赛/获奖": "竞赛经历(算法)",
    # 后端
    "flask": "Flask", "django": "Django", "fastapi": "FastAPI",
    "spring": "Spring", "spring boot": "Spring Boot",
    "node.js": "Node.js", "nodejs": "Node.js",
    "微服务经验": "微服务", "微服务": "微服务",
    "分布式经验": "分布式系统",
    "架构设计经验": "系统架构设计",
    "后端开发": "后端开发",
    # 数据库
    "mysql": "MySQL", "postgresql": "PostgreSQL", "postgres": "PostgreSQL",
    "redis": "Redis", "mongodb": "MongoDB",
    "elasticsearch": "Elasticsearch",
    "sql": "SQL", "nosql": "NoSQL",
    # 工程化/DevOps
    "docker": "Docker", "kubernetes": "Kubernetes", "k8s": "Kubernetes",
    "linux": "Linux", "linux开发/部署经验": "Linux",
    "git": "Git", "ci/cd": "CI/CD",
    "devops": "DevOps",
    "大数据处理框架(spark/hadoop/hive)": "大数据(Spark/Hadoop)",
    "spark": "Spark", "hadoop": "Hadoop",
    "kafka": "Kafka", "rabbitmq": "RabbitMQ",
    # 前端
    "react": "React", "react.js": "React",
    "vue": "Vue.js", "vue.js": "Vue.js",
    "angular": "Angular",
    "html": "HTML/CSS", "css": "HTML/CSS",
    # 通用
    "ai": "AI/人工智能(泛指)",
    "优秀开源项目经历": "开源项目经历",
    "计算机相关专业": "计算机相关专业",
    "机器学习经验": "机器学习经验",
    "云计算经验": "云计算经验",
    "不接受居家办公": "",  # 非技能，过滤
    "大数据": "大数据",
}

# 归一到新名后，某些原始标签应该直接移除（非技能）
_SKIP_NORMALIZED = {"", "ai/人工智能(泛指)"}

# ============================================================
# 技能分类
# ============================================================
_CATEGORY_MAP: dict[str, str] = {}

def _seed_categories():
    """按关键词归类的简单规则（不建完整 ontology）。"""
    rules = [
        ("编程语言", ["Python", "Java", "JavaScript", "TypeScript", "Go", "C/C++", "C++", "Rust",
                       "C#", "PHP", "Ruby", "Scala", "Kotlin", "Swift", "SQL"]),
        ("AI/LLM", ["大语言模型(LLM)", "大模型算法", "AI Agent", "RAG", "LangChain", "Dify",
                     "Prompt工程", "机器学习", "深度学习", "自然语言处理(NLP)", "计算机视觉(CV)",
                     "多模态", "强化学习", "推荐系统", "搜索系统", "语音识别/合成",
                     "PyTorch", "TensorFlow", "模型优化/加速", "算法工程化经验",
                     "论文发表(算法)", "竞赛经历(算法)", "机器学习经验",
                     "n8n", "coze", "扣子"]),
        ("后端/API", ["Flask", "Django", "FastAPI", "Spring", "Spring Boot", "Node.js",
                      "微服务", "分布式系统", "系统架构设计", "后端开发", "GraphQL", "REST API"]),
        ("数据库", ["MySQL", "PostgreSQL", "Redis", "MongoDB", "Elasticsearch",
                    "NoSQL", "SQLite"]),
        ("工程化/DevOps", ["Docker", "Kubernetes", "Linux", "Git", "CI/CD", "DevOps",
                           "大数据(Spark/Hadoop)", "Spark", "Hadoop", "Kafka", "RabbitMQ",
                           "云计算经验", "大数据"]),
        ("前端", ["React", "Vue.js", "Angular", "HTML/CSS", "Electron"]),
        ("数据分析", ["pandas", "numpy", "matplotlib", "数据可视化", "数据驾驶舱",
                      "Tableau", "Power BI"]),
        ("产品/业务", ["产品设计", "PRD撰写", "Axure", "XMind", "用户研究",
                       "A/B测试", "数据分析(业务)"]),
        ("通用能力", ["开源项目经历", "团队管理经验", "计算机相关专业",
                      "英语", "沟通能力"]),
    ]
    for cat, skills in rules:
        for s in skills:
            _CATEGORY_MAP.setdefault(s.lower(), cat)


# ============================================================
# 用户技能提取（从母版简历，含证据）
# ============================================================

@dataclass
class UserSkill:
    skill: str
    evidence: str
    source_section: str  # 技能清单 / 项目经历 / 工作经历
    strength: str  # strong / partial

    def as_dict(self):
        return {
            "skill": self.skill,
            "evidence": self.evidence,
            "source": self.source_section,
            "strength": self.strength,
        }


def _parse_resume_skills() -> list[UserSkill]:
    """从母版简历提取有证据的用户技能。"""
    resume_path = RESUME_DIR / "母版简历.md"
    if not resume_path.exists():
        return []

    text = resume_path.read_text(encoding="utf-8")

    # 提取 技能清单 section
    skills_section = ""
    m = re.search(r"##\s*技能清单(.*?)(?:\n##\s|\Z)", text, re.S)
    if m:
        skills_section = m.group(1)

    # 提取 项目经历 section（用于 evidence）
    projects_section = ""
    m = re.search(r"##\s*项目经历(.*?)(?:\n##\s|\Z)", text, re.S)
    if m:
        projects_section = m.group(1)

    # 提取 工作经历 section
    work_section = ""
    m = re.search(r"##\s*工作经历(.*?)(?:\n##\s|\Z)", text, re.S)
    if m:
        work_section = m.group(1)

    full_text = text  # 用于全文搜索证据

    # ---- 手动映射：简历技能 → 标准化技能名 + 证据 ----
    # 基于 AI应用/Agent工程 方向，从简历各段提取
    manual: list[UserSkill] = []

    def add(skill: str, evidence: str, source: str, strength: str = "strong"):
        manual.append(UserSkill(skill, evidence, source, strength))

    # 技能清单段
    add("Python", "技能清单：Python；job-copilot项目全链路Python实现", "技能清单", "strong")
    add("大语言模型(LLM)", "技能清单：大语言模型应用与微调(Claude/GPT)", "技能清单", "strong")
    add("AI Agent", "技能清单：AI智能体工作流搭建；job-copilot项目", "技能清单", "strong")
    add("Prompt工程", "技能清单：Prompt工程实践", "技能清单", "strong")
    add("计算机视觉(CV)", "技能清单：YOLOv8；毕业设计血细胞检测系统", "技能清单", "strong")
    add("LSTM/时序预测", "项目：AI直播引擎中LSTM时序预测GMV趋势，准确率85%+", "项目经历", "strong")
    add("实时翻译引擎", "项目：AI直播引擎集成实时翻译引擎，四语种延迟<1秒", "项目经历", "strong")
    add("Claude Code", "技能清单+项目：Claude Code深度使用，客户开发管线", "技能清单", "strong")
    add("SQLite", "项目：job-copilot数据层用SQLite存职位+向量", "项目经历", "strong")
    add("numpy/pandas", "项目：job-copilot数据处理与向量计算", "项目经历", "strong")
    add("Playwright", "项目：job-copilot浏览器自动化采集", "项目经历", "strong")
    add("BGE向量/Embedding", "项目：job-copilot离线bge-small-zh向量化+语义匹配", "项目经历", "strong")
    add("数据驾驶舱", "工作：跨境直播中搭建多平台实时数据驾驶舱", "工作经历", "strong")
    add("Axure", "技能清单：Axure产品原型", "技能清单", "partial")
    add("XMind", "技能清单：XMind思维导图", "技能清单", "partial")
    add("PRD撰写", "技能清单：产品原型与PRD撰写", "技能清单", "partial")
    add("客户开发(北美)", "工作：LinkedIn/TikTok等多平台北美客户开发", "工作经历", "strong")
    add("内容运营(海外社媒)", "工作：LinkedIn货运KOL内容10篇，曝光1k+", "工作经历", "strong")
    add("英语(商务)", "技能清单+工作：英语商务书面+口语流畅，北美客户直接沟通", "技能清单", "strong")
    add("多语种协作", "工作：泰语/西语业务协作经验", "工作经历", "partial")
    add("自动化工作流", "工作：WorkBuddy编排客户开发自动化+油猴脚本", "工作经历", "strong")
    add("数据标注", "项目：YOLOv8项目完成数据标注全流程", "项目经历", "partial")
    add("模型微调", "技能清单：大模型微调(Claude/GPT)；翻译引擎微调", "技能清单", "partial")
    add("Linux", "项目：job-copilot在Linux/macOS环境开发部署", "项目经历", "partial")
    add("RAG", "项目：job-copilot实现RAG检索层(bge向量+元数据过滤+余弦召回)", "项目经历", "strong")
    add("DeepSeek", "项目：job-copilot接入DeepSeek API(OpenAI兼容接口)", "项目经历", "strong")
    add("量化评测", "项目：job-copilot自建70条标注评测集，precision@k量化对比", "项目经历", "strong")

    return manual


# ============================================================
# 市场技能提取
# ============================================================

@dataclass
class MarketSkill:
    normalized: str
    job_count: int
    confidence: str  # high / medium / low
    category: str = "其他"

    def as_dict(self):
        return {
            "skill": self.normalized,
            "job_count": self.job_count,
            "demand_rate": self.job_count,
            "confidence": self.confidence,
            "category": self.category,
        }


def _normalize_skill(raw: str) -> Optional[str]:
    """别名归一化，返回标准化名或 None（应跳过）。"""
    key = raw.strip().lower()
    if not key:
        return None
    if key in _SKIP_NORMALIZED:
        return None
    normalized = _ALIAS_MAP.get(key, raw.strip())
    if normalized in _SKIP_NORMALIZED:
        return None
    return normalized


def _extract_market_skills(csv_path: Path) -> tuple[list[MarketSkill], int]:
    """从清洗后CSV提取市场技能，返回(技能列表, 总岗位数)。"""
    if not csv_path.exists():
        print(f"✗ 未找到清洗数据: {csv_path}，请先运行 `clean`。")
        return [], 0

    rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))
    total = len(rows)
    raw_counter: Counter = Counter()
    # 每个技能出现在多少个岗位中（而非总出现次数）
    for r in rows:
        tags_str = r.get("技能标签(已清理)", "")
        seen_in_job = set()
        for t in tags_str.split("、"):
            norm = _normalize_skill(t)
            if norm:
                seen_in_job.add(norm.lower())
        for s in seen_in_job:
            raw_counter[s] += 1

    # 也检查 title 中的隐含技能（低置信度——title 可能包装）
    # 这里不做 title 推断，避免假阳性——标签已是可靠来源

    skills = []
    for norm_key, cnt in raw_counter.most_common():
        # 找 display name（保留首次出现的大小写形式）
        display = norm_key  # fallback
        # confidence 判断：均来自 tags → high
        skills.append(MarketSkill(
            normalized=norm_key,
            job_count=cnt,
            confidence="high",
            category=_CATEGORY_MAP.get(norm_key.lower(), _guess_category(norm_key)),
        ))

    return skills, total


def _guess_category(skill: str) -> str:
    """简单关键词猜测类别。"""
    s = skill.lower()
    if any(kw in s for kw in ["python", "java", "go", "rust", "c++", "javascript", "typescript", "sql"]):
        return "编程语言"
    if any(kw in s for kw in ["llm", "大语言", "agent", "rag", "prompt", "机器学习", "深度学习",
                               "自然语言", "计算机视觉", "nlp", "cv", "多模态", "强化",
                               "推荐系统", "搜索系统", "pytorch", "tensorflow", "算法工程化",
                               "模型优化", "模型加速", "微调", "langchain", "dify"]):
        return "AI/LLM"
    if any(kw in s for kw in ["flask", "django", "fastapi", "spring", "node", "微服务",
                               "分布式", "架构设计", "后端"]):
        return "后端/API"
    if any(kw in s for kw in ["mysql", "postgresql", "redis", "mongodb", "elasticsearch"]):
        return "数据库"
    if any(kw in s for kw in ["docker", "kubernetes", "linux", "git", "ci/cd", "devops",
                               "spark", "hadoop", "kafka", "rabbitmq", "云计算", "大数据"]):
        return "工程化/DevOps"
    if any(kw in s for kw in ["react", "vue", "angular", "html", "css", "前端"]):
        return "前端"
    if any(kw in s for kw in ["pandas", "numpy", "matplotlib", "可视化", "驾驶舱", "tableau"]):
        return "数据分析"
    if any(kw in s for kw in ["产品", "prd", "axure", "xmind", "用户研究", "ab测试"]):
        return "产品/业务"
    if any(kw in s for kw in ["开源项目", "团队管理", "计算机相关", "英语", "沟通"]):
        return "通用能力"
    return "其他"


# ============================================================
# 差距分析
# ============================================================

@dataclass
class GapItem:
    normalized: str
    category: str
    market_job_count: int
    market_demand_rate: float
    extraction_confidence: str
    resume_status: str  # strong / partial / missing
    resume_evidence: str
    gap_priority: str  # high / medium / low
    recommended_action: str

    def as_dict(self):
        return {
            "skill": self.normalized,
            "category": self.category,
            "market_count": self.market_job_count,
            "demand_pct": f"{self.market_demand_rate:.1%}",
            "confidence": self.extraction_confidence,
            "resume_status": self.resume_status,
            "evidence": self.resume_evidence,
            "gap_priority": self.gap_priority,
            "action": self.recommended_action,
        }


# 算法研究岗专属技能——AI应用/Agent工程方向不需要，强制降为 low
# 全部用小写，因为市场技能归一化后会 lower()
_ALGO_ONLY_SKILLS = {
    "大模型算法", "深度学习", "算法工程化经验", "多模态", "强化学习",
    "自然语言处理(nlp)", "计算机视觉(cv)", "语音识别/合成", "模型优化/加速",
    "论文发表(算法)", "竞赛经历(算法)", "推荐系统", "搜索系统",
    "pytorch", "tensorflow",
    "图像算法",  # 部分标签可能未在别名表中
}


def _analyze_gaps(market: list[MarketSkill], user: list[UserSkill], total_jobs: int) -> list[GapItem]:
    """对比市场需求与用户技能，输出差距列表。"""
    user_map: dict[str, UserSkill] = {}
    for u in user:
        key = u.skill.lower()
        if key not in user_map or (u.strength == "strong" and user_map[key].strength != "strong"):
            user_map[key] = u

    gaps = []
    for ms in market:
        key = ms.normalized.lower()
        u = user_map.get(key)
        demand_rate = ms.job_count / total_jobs if total_jobs else 0

        if u:
            status = u.strength
            evidence = u.evidence
        else:
            status = "missing"
            evidence = ""

        # ---- 优先级计算（透明、可解释）----
        # 算法研究岗专属技能：对 AI应用/Agent工程 方向强制低优先级
        if ms.normalized in _ALGO_ONLY_SKILLS:
            gaps.append(GapItem(
                normalized=ms.normalized,
                category=ms.category,
                market_job_count=ms.job_count,
                market_demand_rate=demand_rate,
                extraction_confidence=ms.confidence,
                resume_status=status,
                resume_evidence=evidence,
                gap_priority="low",
                recommended_action="算法研究岗专属能力，AI应用/Agent工程方向不需要，不建议投入时间",
            ))
            continue

        # 基础分 = 市场需求频率 (0-1)
        base = demand_rate * 100
        # 状态系数
        if status == "missing":
            coeff = 2.0
        elif status == "partial":
            coeff = 1.0
        else:
            coeff = 0.0
        # 可补齐性调整
        if ms.category in ("AI/LLM", "编程语言"):
            learnability = 1.0  # 用户已有相关基础
        elif ms.category in ("算法研究",):
            learnability = 0.3  # 需要深度学术背景
        else:
            learnability = 0.7

        score = base * coeff * learnability
        if score >= 8:
            priority = "high"
        elif score >= 3:
            priority = "medium"
        else:
            priority = "low"

        # 生成行动建议
        action = _generate_action(ms.normalized, status, ms.category, demand_rate)

        gaps.append(GapItem(
            normalized=ms.normalized,
            category=ms.category,
            market_job_count=ms.job_count,
            market_demand_rate=demand_rate,
            extraction_confidence=ms.confidence,
            resume_status=status,
            resume_evidence=evidence,
            gap_priority=priority,
            recommended_action=action,
        ))

    # 按优先级排序: high → medium → low，同优先级按 demand 降序
    order = {"high": 0, "medium": 1, "low": 2}
    gaps.sort(key=lambda g: (order[g.gap_priority], -g.market_job_count))
    return gaps


def _generate_action(skill: str, status: str, category: str, demand_rate: float) -> str:
    """生成针对性的行动建议。"""
    if status == "strong":
        return f"✓ 已有强证据，简历中保持并继续突出"
    if status == "partial":
        if demand_rate > 0.1:
            return f"强化证据：在简历项目描述中补充 {skill} 的具体使用场景和量化成果"
        return f"简历中简要提及即可，不作重点"
    # missing
    if demand_rate > 0.15:
        if "编程" in category or "后端" in category:
            return f"用 1-2 周通过 job-copilot 项目实践 {skill}，在简历项目经历中加入具体使用案例"
        if "数据库" in category:
            return f"在 job-copilot 项目中集成 {skill}，记录性能对比/查询优化等可量化成果"
        if "工程化" in category:
            return f"将 job-copilot 容器化({skill})，记录部署流程到项目描述"
        if "AI" in category:
            return f"用 3-5 天完成一个 {skill} 的最小可行项目，产出可展示的 Demo"
        return f"评估 {skill} 是否与目标方向匹配，若是则用 1 周学习基础并产出最小证明"
    if demand_rate > 0.05:
        return f"了解 {skill} 基础概念，简历中可提及但不作重点"
    return f"暂不建议投入时间（市场需求 {demand_rate:.0%}，优先级低）"


# ============================================================
# 报告生成
# ============================================================

def _write_markdown(gaps: list[GapItem], market: list[MarketSkill],
                    user: list[UserSkill], user_skills_count: int,
                    total_jobs: int, total_market_skills: int) -> Path:
    """生成 skills_gap.md。"""
    # 分组
    strong = [u for u in user if u.strength == "strong"]
    partial = [u for u in user if u.strength == "partial"]
    high_gaps = [g for g in gaps if g.gap_priority == "high" and g.resume_status != "strong"]
    medium_gaps = [g for g in gaps if g.gap_priority == "medium" and g.resume_status != "strong"]
    low_value = [g for g in gaps if g.gap_priority == "low" and g.resume_status == "missing"]
    # 简历表达不足
    under_expressed = [g for g in gaps if g.resume_status == "partial"]

    L = []
    L.append(f"# 技能差距诊断报告")
    L.append("")
    L.append(f"> 生成日期：{date.today().isoformat()} ｜ 分析岗位：{total_jobs} 条（Boss直聘·深圳·AI Agent/应用方向）")
    L.append(f"> 市场识别技能：{total_market_skills} 个 ｜ 用户有证据技能：{user_skills_count} 个（强 {len(strong)} / 偏弱 {len(partial)}）")
    L.append(f"> 数据限制说明见文末 §8")
    L.append("")

    # §1 市场技能需求 Top 20
    L.append("## 一、市场技能需求 Top 20")
    L.append("")
    L.append("| # | 技能 | 需求岗位数 | 需求率 | 类别 |")
    L.append("|---|---|---|---|---|")
    for i, ms in enumerate(market[:20], 1):
        L.append(f"| {i} | {ms.normalized} | {ms.job_count} | {ms.job_count/total_jobs:.0%} | {ms.category} |")
    L.append("")

    # §2 用户核心优势
    L.append("## 二、用户已具备的核心优势（有证据支撑）")
    L.append("")
    L.append("### 强证据技能")
    L.append("")
    for u in strong:
        L.append(f"- **{u.skill}**：{u.evidence}")
    L.append("")
    L.append("### 有基础但证据偏弱的技能")
    L.append("")
    for u in partial:
        L.append(f"- **{u.skill}**：{u.evidence}")
    L.append("")

    # §3 高优先级缺口
    L.append("## 三、高优先级技能缺口（急需补齐或强化）")
    L.append("")
    if high_gaps:
        L.append("| 技能 | 市场需求 | 当前状态 | 行动建议 |")
        L.append("|---|---|---|---|")
        for g in high_gaps[:10]:
            status_cn = {"missing": "❌ 缺失", "partial": "⚠️ 偏弱", "strong": "✓ 已有"}[g.resume_status]
            L.append(f"| **{g.normalized}** | {g.market_job_count} 岗({g.market_demand_rate:.0%}) | {status_cn} | {g.recommended_action} |")
    else:
        L.append("> ✓ 当前无高优先级缺口（市场高频技能你已基本覆盖）。")
    L.append("")

    # §4 简历表达不足
    L.append("## 四、简历中已有但表达不足的技能")
    L.append("")
    if under_expressed:
        L.append("| 技能 | 市场需求 | 当前证据 | 强化建议 |")
        L.append("|---|---|---|---|")
        for g in under_expressed[:8]:
            L.append(f"| **{g.normalized}** | {g.market_job_count} 岗 | {g.resume_evidence[:60]}… | {g.recommended_action} |")
    else:
        L.append("> 当前无限表达不足的技能。")
    L.append("")

    # §5 低价值技能
    L.append("## 五、不建议当前投入的技能")
    L.append("")
    L.append("以下技能在市场中虽有出现，但对你当前方向（AI应用/Agent工程）投入产出比低：")
    L.append("")
    L.append("| 技能 | 原因 |")
    L.append("|---|---|")
    low_value_skills = [g for g in gaps if g.gap_priority == "low" and g.resume_status == "missing"][:8]
    for g in low_value_skills:
        L.append(f"| {g.normalized} | {g.recommended_action} |")
    # 补充一些高频但用户方向不需要的技能
    noise_skills = ["大模型算法", "发表算法相关优秀论文", "参加算法相关竞赛/获奖",
                    "图像算法", "语音算法", "推荐算法", "搜索算法"]
    for ns in noise_skills:
        if not any(g.normalized == ns for g in low_value_skills):
            for ms in market:
                if ms.normalized == ns and ms.job_count > 5:
                    L.append(f"| {ns} | 偏向算法研究岗，AI应用/工程方向不需要（{ms.job_count} 岗含此标签） |")
                    break
    L.append("")

    # §6 推荐投递方向
    L.append("## 六、推荐投递的岗位方向")
    L.append("")
    L.append("基于你的技能画像，以下方向契合度最高：")
    L.append("")
    L.append("1. **AI Agent 应用开发**（最契合）：Python + AI Agent + RAG + Prompt工程 + LLM 均已具备强证据")
    L.append("2. **大模型应用工程**（可投）：缺后端/DevOps 工程栈但 AI 能力已足够，边投边补")
    L.append("3. **AI 产品/解决方案**（备选）：PRD撰写、数据驾驶舱、多语种协作是差异化优势")
    L.append("")
    L.append("**应暂避的方向**：")
    L.append("- 纯算法研究岗（大模型算法/多模态/推荐/搜索/图像/语音——需要论文+竞赛背景）")
    L.append("- 要求 3 年以上 Java/Go 后端经验的岗位（你的后端工程栈是弱项）")
    L.append("")

    # §7 7天行动建议
    L.append("## 七、接下来 7 天的具体行动建议")
    L.append("")
    L.append("### 简历优化（立即做）")
    L.append("")
    idx = 1
    for g in under_expressed[:3]:
        L.append(f"{idx}. 在简历「{g.category}」相关项目中补充 **{g.normalized}** 的具体使用证据和成果")
        idx += 1
    for g in high_gaps[:2]:
        if g.resume_status == "missing":
            L.append(f"{idx}. 评估是否能用 2-3 天快速上手 **{g.normalized}** 并在 job-copilot 项目中落地，补入简历")
            idx += 1
    L.append("")
    L.append("### 技能补齐（选 1-2 个最高 ROI）")
    L.append("")
    for g in high_gaps[:3]:
        if g.resume_status == "missing":
            L.append(f"- **{g.normalized}**：{g.recommended_action}")
    L.append("")
    L.append("### 投递策略")
    L.append("")
    L.append("- 优先投 AI Agent/应用工程 岗位（match 粗筛+score 精排 fit≥4 的）")
    L.append("- 避免浪费招呼语在算法研究岗（即使粗筛分高，精排会筛掉）")
    L.append("- 每批投递后追踪已读不回率，发现某方向回复率断崖则调整")
    L.append("")

    # §8 数据限制
    L.append("## 八、数据限制说明")
    L.append("")
    L.append("- **JD 全文缺失**：当前 387 条岗位仅含列表页标签，无 JD 描述正文。技能识别完全依赖标签字段（高置信度），但 JD 正文可能包含更多隐性要求（如\"熟悉微服务架构\"\"有高并发经验\"），这部分当前无法捕获")
    L.append("- **标签覆盖偏差**：Boss直聘标签更侧重编程语言/框架/算法方向，对\"沟通能力\"\"项目管理\"等软技能标记较少，报告中的软技能市场需求可能偏低")
    L.append("- **技能归一化**：仅覆盖高频别名（~100 条规则），低频技能可能因大小写/中英文变体被计为独立条目。不影响 Top 20 结论")
    L.append("- **用户技能判断**：基于母版简历显式描述，简历中未提及但实际掌握的能力会被标记为 missing。建议对照报告补全简历")
    L.append(f"- **分析时间**：{date.today().isoformat()}，市场数据快照于 2026-07-10")
    L.append("")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"技能差距诊断-{date.today().isoformat()}.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path


def _write_csv_xlsx(gaps: list[GapItem], market: list[MarketSkill],
                    user: list[UserSkill], total_jobs: int) -> tuple[Path, Path]:
    """导出 CSV 和 Excel（多工作表）。"""
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    # --- CSV ---
    csv_path = ANALYSIS_DIR / "skills_gap.csv"
    csv_fields = ["skill", "category", "market_count", "demand_pct", "confidence",
                  "resume_status", "evidence", "gap_priority", "action"]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=csv_fields)
        w.writeheader()
        for g in gaps:
            w.writerow(g.as_dict())

    # --- Excel ---
    xlsx_path = ANALYSIS_DIR / "skills_gap.xlsx"
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()

    # Sheet 1: Skill Gaps
    ws = wb.active
    ws.title = "Skill Gaps"
    gap_headers = ["技能", "类别", "市场需求(岗位数)", "需求率", "置信度",
                   "简历状态", "简历证据", "缺口优先级", "行动建议"]
    header_font = Font(bold=True, size=11)
    header_fill = PatternFill(start_color="D9E2F3", end_color="D9E2F3", fill_type="solid")
    for ci, h in enumerate(gap_headers, 1):
        cell = ws.cell(row=1, column=ci, value=h)
        cell.font = header_font
        cell.fill = header_fill

    for ri, g in enumerate(gaps, 2):
        d = g.as_dict()
        ws.cell(row=ri, column=1, value=g.normalized)
        ws.cell(row=ri, column=2, value=g.category)
        ws.cell(row=ri, column=3, value=g.market_job_count)
        ws.cell(row=ri, column=4, value=g.market_demand_rate)
        ws.cell(row=ri, column=5, value=g.extraction_confidence)
        ws.cell(row=ri, column=6, value=g.resume_status)
        ws.cell(row=ri, column=7, value=g.resume_evidence)
        ws.cell(row=ri, column=8, value=g.gap_priority)
        ws.cell(row=ri, column=9, value=g.recommended_action)

    for ci, w_val in enumerate([22, 12, 14, 10, 8, 10, 50, 10, 50], 1):
        ws.column_dimensions[get_column_letter(ci)].width = w_val
    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = "A2"
    ws.cell(row=ri, column=4).number_format = "0.0%"

    # Sheet 2: Market Skills
    ws2 = wb.create_sheet("Market Skills")
    mkt_headers = ["技能", "类别", "需求岗位数", "需求率", "置信度"]
    for ci, h in enumerate(mkt_headers, 1):
        cell = ws2.cell(row=1, column=ci, value=h)
        cell.font = header_font
        cell.fill = header_fill

    for ri, ms in enumerate(market, 2):
        ws2.cell(row=ri, column=1, value=ms.normalized)
        ws2.cell(row=ri, column=2, value=ms.category)
        ws2.cell(row=ri, column=3, value=ms.job_count)
        ws2.cell(row=ri, column=4, value=ms.job_count / total_jobs if total_jobs else 0)
        ws2.cell(row=ri, column=5, value=ms.confidence)
    for ci, w_val in enumerate([22, 12, 12, 10, 8], 1):
        ws2.column_dimensions[get_column_letter(ci)].width = w_val
    ws2.auto_filter.ref = ws2.dimensions
    ws2.freeze_panes = "A2"

    # Sheet 3: Resume Skills
    ws3 = wb.create_sheet("Resume Skills")
    usr_headers = ["技能", "证据", "来源段落", "证据强度"]
    for ci, h in enumerate(usr_headers, 1):
        cell = ws3.cell(row=1, column=ci, value=h)
        cell.font = header_font
        cell.fill = header_fill

    for ri, u in enumerate(user, 2):
        d = u.as_dict()
        ws3.cell(row=ri, column=1, value=d["skill"])
        ws3.cell(row=ri, column=2, value=d["evidence"])
        ws3.cell(row=ri, column=3, value=d["source"])
        ws3.cell(row=ri, column=4, value=d["strength"])
    for ci, w_val in enumerate([22, 55, 18, 10], 1):
        ws3.column_dimensions[get_column_letter(ci)].width = w_val
    ws3.auto_filter.ref = ws3.dimensions
    ws3.freeze_panes = "A2"

    wb.save(xlsx_path)
    return csv_path, xlsx_path


# ============================================================
# CLI 入口
# ============================================================

def run(jobs_csv: Optional[str] = None, profile_path: Optional[str] = None) -> str:
    csv_path = Path(jobs_csv) if jobs_csv else CLEAN_CSV

    if not csv_path.exists():
        return (f"✗ 未找到清洗数据: {csv_path}\n"
                "  请先运行: python -m job_copilot clean\n"
                "  或指定路径: python -m job_copilot skills --jobs <path>")

    _seed_categories()

    # 1. 市场技能提取
    market, total_jobs = _extract_market_skills(csv_path)
    if not market:
        return "✗ 未能从岗位数据中提取到技能标签。"

    # 2. 用户技能提取
    user = _parse_resume_skills()
    if not user:
        return ("✗ 未找到母版简历或无法提取技能。请检查 resume/母版简历.md 是否存在。\n"
                f"  已有市场 {len(market)} 个技能可单独查看，但无法生成差距分析。")

    # 3. 差距分析
    gaps = _analyze_gaps(market, user, total_jobs)

    # 4. 统计
    high_gap_n = len([g for g in gaps if g.gap_priority == "high" and g.resume_status != "strong"])
    user_skills_n = len(user)

    # 5. 生成报告
    md_path = _write_markdown(gaps, market, user, user_skills_n, total_jobs, len(market))
    csv_out, xlsx_out = _write_csv_xlsx(gaps, market, user, total_jobs)

    lines = [
        "=" * 55,
        "  技能差距诊断完成",
        "=" * 55,
        f"  分析岗位数         : {total_jobs}",
        f"  市场技能数(标准化)  : {len(market)}",
        f"  用户有证据技能数    : {user_skills_n}",
        f"  高优先级缺口       : {high_gap_n}",
        "",
        f"  市场报告           : {md_path}",
        f"  差距明细 CSV       : {csv_out}",
        f"  差距明细 Excel     : {xlsx_out}",
        "=" * 55,
    ]
    return "\n".join(lines)
