"""数据清洗与导出（M2）。

职责：
- 字段标准化：去空白、统一经验/学历表达、清理技能标签噪声
- 去重：同 公司 + 岗位名 + 城市 保留信息最完整的一条，合并标签
- 导出：Excel（openpyxl）供用户在表格中筛选打标，CSV 兜底

只读 SQLite → 写 Excel/CSV，不修改 jobs 表（幂等、可反复跑）。
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Optional

from .config import DATA_DIR
from . import db

CLEAN_DIR = DATA_DIR / "clean"
OUTPUT_EXCEL = CLEAN_DIR / "cleaned_jobs.xlsx"
OUTPUT_CSV = CLEAN_DIR / "cleaned_jobs.csv"

# ---- 经验表达归一化 ----
_EXP_NORM = {
    "在校/应届": "应届",
    "应届生": "应届",
    "1年以内": "1年以内",
    "1-3年": "1-3年",
    "3-5年": "3-5年",
    "5-10年": "5-10年",
    "10年以上": "10年以上",
    "经验不限": "经验不限",
}

# ---- 学历归一化 ----
_DEGREE_NORM = {
    "大专": "大专",
    "本科": "本科",
    "硕士": "硕士",
    "硕士及以上": "硕士及以上",
    "博士": "博士",
    "学历不限": "学历不限",
    "中专": "中专",
    "高中": "高中",
    "MBA": "MBA",
}

# ---- tags 里混入的非技能标签（经验/学历） ----
_EXP_TAG_RE = re.compile(r"^\d+[-\d]*年$|经验不限|应届|在校|不限$")
_DEGREE_TAGS = {"本科", "大专", "硕士", "硕士及以上", "博士", "学历不限", "中专", "高中", "MBA", "初中及以下"}
_STOP_TAGS = {"经验", "开发经验", "相关经验"}


def _load_jobs():
    """从 SQLite 读取全部职位为 dict 列表。"""
    conn = db.connect()
    return [dict(r) for r in conn.execute("SELECT * FROM jobs ORDER BY id")]


def _norm_title(t: Optional[str]) -> str:
    """清理职位名：去首尾空白、去换行、合并多空格。"""
    if not t:
        return ""
    return re.sub(r"\s+", " ", t.strip())


def _norm_company(c: Optional[str]) -> str:
    """清理公司名：去首尾空白。不过度修改（不猜测简称/全称，容易出错）。"""
    if not c:
        return ""
    return c.strip()


def _norm_experience(e: Optional[str]) -> str:
    """统一经验表达。"""
    if not e:
        return ""
    e = e.strip()
    return _EXP_NORM.get(e, e)


def _norm_degree(d: Optional[str]) -> str:
    """统一学历表达。"""
    if not d:
        return ""
    d = d.strip()
    return _DEGREE_NORM.get(d, d)


def _clean_tags(tags_json: Optional[str]) -> list[str]:
    """解析 tags JSON，去经验/学历噪声，去重（大小写不敏感），保留原始大小写。"""
    if not tags_json:
        return []
    try:
        raw = json.loads(tags_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(raw, list):
        return []
    seen = set()
    out = []
    display = {}
    for t in raw:
        t = (t or "").strip()
        if not t:
            continue
        if t in _DEGREE_TAGS or t in _STOP_TAGS or _EXP_TAG_RE.search(t):
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        display.setdefault(key, t)
        out.append(display[key])
    return out


def _field_richness(r: dict, fields: list[str]) -> int:
    """计算记录的信息完整度 = 非空字段数。"""
    return sum(1 for f in fields if r.get(f))


def _dedup_key(r: dict) -> str:
    """去重键：公司 + 标准化岗位名（小写去空格）+ 城市。"""
    title = re.sub(r"\s+", "", _norm_title(r.get("title")).lower())
    company = _norm_company(r.get("company")).lower()
    city = (r.get("city") or "").strip()
    return f"{company}|{title}|{city}"


def clean_and_export() -> tuple[int, int, int, Path, Path]:
    """主流程：加载 → 清洗 → 去重 → 导出。返回 (原始数, 清洗后, 去重数, excel, csv)。"""
    rows = _load_jobs()
    raw_n = len(rows)

    # ---- 1. 字段标准化 ----
    for r in rows:
        r["title"] = _norm_title(r.get("title"))
        r["company"] = _norm_company(r.get("company"))
        r["experience"] = _norm_experience(r.get("experience"))
        r["degree"] = _norm_degree(r.get("degree"))
        r["clean_tags"] = _clean_tags(r.get("tags"))

    # ---- 2. 去重 ----
    # 分组；每组保留信息最完整的一条（非空字段数），合并标签
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(_dedup_key(r), []).append(r)

    dedup_n = raw_n - len(groups)

    critical_fields = [
        "platform", "job_id", "url", "title", "company", "salary_text",
        "salary_min", "salary_max", "city", "experience", "degree",
        "jd_text", "industry",
    ]

    kept = []
    for key, g in groups.items():
        g.sort(key=lambda r: _field_richness(r, critical_fields), reverse=True)
        best = g[0]
        # 合并同组所有标签
        all_tags: set = set()
        for r in g:
            for t in _clean_tags(r.get("tags")):
                all_tags.add(t.lower())
        # 重建标签列表（用 best 的 display 名优先，追加其他）
        best_display = {t.lower(): t for t in _clean_tags(best.get("tags"))}
        merged = []
        for t_lower in sorted(all_tags):
            merged.append(best_display.get(t_lower, t_lower))
        best["clean_tags"] = merged
        best["_dedup_group_size"] = len(g)
        kept.append(best)

    # ---- 3. 导出 Excel ----
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)

    # 排除内部的 clean_tags（一会展开写）
    FIELDS = [
        "platform", "job_id", "url", "title", "company", "company_size",
        "industry", "salary_text", "salary_min", "salary_max", "salary_months",
        "city", "district", "experience", "degree",
        "tags_clean",  # 展开后的 clean_tags
        "hr_name", "hr_title", "hr_active",
        "search_keyword", "search_city", "collected_at",
    ]
    HEADERS = [
        "平台", "职位ID", "链接", "职位", "公司", "公司规模",
        "行业", "薪资文本", "薪资下限", "薪资上限", "薪月数",
        "城市", "区", "经验要求", "学历要求",
        "技能标签(已清理)",
        "HR名", "HR职位", "HR活跃",
        "搜索关键词", "搜索城市", "采集时间",
    ]

    excel_rows = []
    for r in kept:
        row_data = {}
        for f, h in zip(FIELDS, HEADERS):
            if f == "tags_clean":
                row_data[h] = "、".join(r.get("clean_tags", []))
            else:
                val = r.get(f)
                row_data[h] = val
        excel_rows.append(row_data)

    _write_excel(excel_rows, HEADERS)
    _write_csv(excel_rows, HEADERS)

    clean_n = len(kept)
    return raw_n, clean_n, dedup_n, OUTPUT_EXCEL, OUTPUT_CSV


def _write_excel(rows: list[dict], headers: list[str]) -> None:
    """写 Excel，带筛选器和冻结首行。"""
    import openpyxl
    from openpyxl.utils import get_column_letter
    from openpyxl.styles import Font, PatternFill, Alignment

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "岗位数据"

    # 表头
    header_font = Font(bold=True, size=11)
    header_fill = PatternFill(start_color="D9E2F3", end_color="D9E2F3", fill_type="solid")
    for ci, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=ci, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # 数据行
    for ri, row in enumerate(rows, 2):
        for ci, h in enumerate(headers, 1):
            val = row.get(h, "")
            # 数值列
            if h in ("薪资下限", "薪资上限", "薪月数"):
                val = val if val is not None else ""
            ws.cell(row=ri, column=ci, value=val)

    # 列宽自适应
    col_widths = {
        "平台": 8, "职位ID": 10, "链接": 36, "职位": 28, "公司": 20,
        "公司规模": 10, "行业": 14, "薪资文本": 10, "薪资下限": 9, "薪资上限": 9,
        "薪月数": 7, "城市": 6, "区": 8, "经验要求": 10, "学历要求": 8,
        "技能标签(已清理)": 42, "HR名": 8, "HR职位": 10, "HR活跃": 10,
        "搜索关键词": 16, "搜索城市": 8, "采集时间": 18,
    }
    for ci, h in enumerate(headers, 1):
        ws.column_dimensions[get_column_letter(ci)].width = col_widths.get(h, 12)

    # 筛选器 + 冻结首行
    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = "A2"

    # 薪资数值列设置数字格式
    for ri in range(2, len(rows) + 2):
        for ci, h in enumerate(headers, 1):
            if h in ("薪资下限", "薪资上限"):
                ws.cell(row=ri, column=ci).number_format = "#,##0"

    wb.save(OUTPUT_EXCEL)


def _write_csv(rows: list[dict], headers: list[str]) -> None:
    """兜底 CSV（UTF-8 BOM，Excel 可双击打开不乱码）。"""
    with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        w.writerows(rows)


# ---- CLI 入口 ----

def run() -> str:
    raw_n, clean_n, dedup_n, xlsx, csv_path = clean_and_export()

    # 统计额外信息
    conn = db.connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM jobs")]
    no_salary = sum(1 for r in rows if r.get("salary_min") is None)
    no_exp = sum(1 for r in rows if not (r.get("experience") or "").strip())
    no_url = sum(1 for r in rows if not (r.get("url") or "").strip())
    no_company = sum(1 for r in rows if not (r.get("company") or "").strip())

    lines = [
        "=" * 50,
        "  数据清洗完成",
        "=" * 50,
        f"  原始岗位数   : {raw_n}",
        f"  清洗后岗位数 : {clean_n}",
        f"  去重删除     : {dedup_n}",
        "",
        f"  缺失公司     : {no_company}",
        f"  缺失薪资     : {no_salary}",
        f"  缺失经验     : {no_exp}",
        f"  缺失URL      : {no_url}",
        "",
        f"  去重规则     : 公司 + 标准化岗位名 + 城市（同组保留信息最完整一条，合并标签）",
        f"  标签清理     : 剔除经验/学历噪声标签（如 \"3-5年\"\"本科\"等），去重",
        "",
        f"  Excel        : {xlsx}",
        f"  CSV          : {csv_path}",
        "=" * 50,
    ]
    return "\n".join(lines)
