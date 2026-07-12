"""可视化仪表盘生成器（M3/M6 的可视层）。

从 SQLite 实时聚合，生成单个自包含 HTML（无外部依赖，本地双击即看，
明暗主题自适应）。图表用纯 CSS 条形，配色遵循数据可视化规范（单色蓝序列 +
文本墨色 + 明暗双 surface）。数据：薪资分位、技能词频（应用岗子集）、匹配 Top-N。
"""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from datetime import date

from .config import REPORTS_DIR
from . import db, match


def _percentiles(vals, ps):
    vals = sorted(vals)
    out = {}
    if not vals:
        return {p: None for p in ps}
    for p in ps:
        k = (len(vals) - 1) * p / 100
        lo = int(k); hi = min(lo + 1, len(vals) - 1)
        out[p] = vals[lo] + (vals[hi] - vals[lo]) * (k - lo)
    return out


def _gather():
    conn = db.connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM jobs")]
    n = len(rows)
    companies = len({r.get("company") for r in rows})

    mids = [(r["salary_min"] + r["salary_max"]) / 2
            for r in rows if r.get("salary_min") and r.get("salary_max")]
    pcts = _percentiles(mids, [10, 25, 50, 75, 90])

    # 技能词频：应用岗子集（剔算法研究岗），剔经验/学历噪声
    EXP = re.compile(r"^\d+[-\d]*年$|经验不限|应届|在校|不限")
    DEG = {"本科", "大专", "硕士", "博士", "学历不限", "中专", "高中"}
    skill_cnt: Counter = Counter()
    disp = {}
    app_rows = [r for r in rows if not match._is_algorithm_role(r)]
    for r in app_rows:
        seen = set()
        for t in match._tags_of(r):
            if not t or t in DEG or EXP.search(t):
                continue
            k = t.lower()
            if k in seen:
                continue
            seen.add(k); skill_cnt[k] += 1; disp.setdefault(k, t)
    top_skills = [(disp[k], c) for k, c in skill_cnt.most_common(15)]

    exp_cnt = Counter(r.get("experience") for r in rows if r.get("experience"))

    matches = match.ranked_matches(top_k=30, filtered=True)
    return {
        "n": n, "companies": companies, "n_app": len(app_rows),
        "pcts": pcts, "top_skills": top_skills, "exp": exp_cnt,
        "matches": matches,
    }


def _bar_v(pcts):
    """薪资分位垂直条。"""
    items = [(f"P{p}", pcts.get(p)) for p in [10, 25, 50, 75, 90]]
    mx = max((v for _, v in items if v), default=1)
    cells = []
    for label, v in items:
        h = int((v or 0) / mx * 150) if v else 0
        val = f"{v/1000:.1f}K" if v else "—"
        emph = " emph" if label == "P50" else ""
        cells.append(
            f'<div class="vbar-col"><div class="vbar-val">{val}</div>'
            f'<div class="vbar{emph}" style="height:{h}px" title="{label} {val}"></div>'
            f'<div class="vbar-lab">{label}</div></div>')
    return '<div class="vbar-wrap">' + "".join(cells) + "</div>"


def _bar_h(skills):
    """技能词频水平条。"""
    mx = max((c for _, c in skills), default=1)
    rows = []
    for name, c in skills:
        w = int(c / mx * 100)
        rows.append(
            f'<div class="hbar-row" title="{html.escape(name)}：{c} 条">'
            f'<div class="hbar-lab">{html.escape(name)}</div>'
            f'<div class="hbar-track"><div class="hbar" style="width:{w}%"></div></div>'
            f'<div class="hbar-val">{c}</div></div>')
    return '<div class="hbar-wrap">' + "".join(rows) + "</div>"


def _table(matches):
    mx = max((s for s, _ in matches), default=1) or 1
    trs = []
    for i, (score, r) in enumerate(matches, 1):
        tags = [t for t in match._tags_of(r)
                if not re.search(r"^\d+[-\d]*年$|本科|大专|硕士|博士", t)][:5]
        url = r.get("url") or ""
        title = html.escape(r.get("title") or "")
        title_cell = f'<a href="{html.escape(url)}" target="_blank">{title}</a>' if url else title
        w = int(score / mx * 100)
        search = html.escape(" ".join([
            r.get("title") or "", r.get("company") or "", "、".join(tags)]).lower(), quote=True)
        smax = int(r.get("salary_max") or 0)
        trs.append(
            f'<tr data-smax="{smax}" data-text="{search}">'
            f'<td class="num">{i}</td>'
            f'<td class="num" data-sort="{score:.4f}">'
            f'<div class="score"><div class="score-bar" style="width:{w}%"></div>'
            f'<span>{score:.3f}</span></div></td>'
            f'<td>{title_cell}</td>'
            f'<td>{html.escape(r.get("company") or "")}</td>'
            f'<td class="num" data-sort="{r.get("salary_max") or 0}">{html.escape(r.get("salary_text") or "")}</td>'
            f'<td>{html.escape(r.get("experience") or "")}</td>'
            f'<td class="muted">{html.escape("、".join(tags))}</td>'
            f'</tr>')
    return "".join(trs)


def build_dashboard() -> str:
    d = _gather()
    p = d["pcts"]
    med = f"{p[50]/1000:.1f}K" if p.get(50) else "—"
    generated = date.today().isoformat()

    tiles = [
        ("职位总数", str(d["n"])),
        ("公司数", str(d["companies"])),
        ("应用/工程岗", str(d["n_app"])),
        ("薪资中位(P50)", med),
        ("匹配候选", str(len(d["matches"]))),
    ]
    tiles_html = "".join(
        f'<div class="tile"><div class="tile-v">{v}</div><div class="tile-l">{l}</div></div>'
        for l, v in tiles)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job-Copilot 求职仪表盘 · 深圳 AI Agent</title>
<style>
:root {{
  --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e;
  --muted:#898781; --grid:#e1e0d9; --series:#2a78d6; --series-soft:#cde2fb;
  --border:rgba(11,11,11,0.10);
}}
:root[data-theme="dark"], html[data-theme="dark"] {{
  --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7;
  --muted:#898781; --grid:#2c2c2a; --series:#3987e5; --series-soft:#184f95;
  --border:rgba(255,255,255,0.10);
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7;
    --muted:#898781; --grid:#2c2c2a; --series:#3987e5; --series-soft:#184f95;
    --border:rgba(255,255,255,0.10);
  }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--plane); color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif; line-height:1.5; }}
.wrap {{ max-width:1080px; margin:0 auto; padding:28px 20px 60px; }}
header {{ display:flex; justify-content:space-between; align-items:flex-start; gap:16px; flex-wrap:wrap; }}
h1 {{ font-size:22px; margin:0 0 4px; }}
.sub {{ color:var(--ink2); font-size:13px; }}
.theme-btn {{ border:1px solid var(--border); background:var(--surface); color:var(--ink2);
  border-radius:8px; padding:6px 12px; font-size:13px; cursor:pointer; }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:12px; margin:22px 0 8px; }}
.tile {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:14px 16px; }}
.tile-v {{ font-size:26px; font-weight:650; }}
.tile-l {{ color:var(--ink2); font-size:12px; margin-top:2px; }}
section {{ background:var(--surface); border:1px solid var(--border); border-radius:14px;
  padding:18px 20px; margin-top:18px; }}
h2 {{ font-size:15px; margin:0 0 4px; }}
.hint {{ color:var(--muted); font-size:12px; margin:0 0 16px; }}
.grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
@media (max-width:760px) {{ .grid2 {{ grid-template-columns:1fr; }} }}
/* 垂直条 */
.vbar-wrap {{ display:flex; align-items:flex-end; gap:14px; height:190px; padding-top:8px; }}
.vbar-col {{ flex:1; display:flex; flex-direction:column; align-items:center; justify-content:flex-end; height:100%; }}
.vbar {{ width:70%; max-width:56px; background:var(--series-soft); border-radius:4px 4px 0 0; }}
.vbar.emph {{ background:var(--series); }}
.vbar-val {{ font-size:12px; color:var(--ink2); margin-bottom:6px; font-variant-numeric:tabular-nums; }}
.vbar-lab {{ font-size:12px; color:var(--muted); margin-top:8px; }}
/* 水平条 */
.hbar-row {{ display:grid; grid-template-columns:96px 1fr 34px; align-items:center; gap:10px; margin:7px 0; }}
.hbar-lab {{ font-size:12.5px; color:var(--ink2); text-align:right; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.hbar-track {{ background:var(--grid); border-radius:4px; height:14px; }}
.hbar {{ height:100%; background:var(--series); border-radius:4px; min-width:3px; }}
.hbar-val {{ font-size:12px; color:var(--ink2); font-variant-numeric:tabular-nums; }}
/* 表格 */
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--grid); vertical-align:middle; }}
th {{ color:var(--ink2); font-weight:600; cursor:pointer; user-select:none; white-space:nowrap; position:sticky; top:0; background:var(--surface); }}
th:hover {{ color:var(--ink); }}
td.num {{ font-variant-numeric:tabular-nums; }}
td.muted {{ color:var(--muted); font-size:12px; }}
a {{ color:var(--series); text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
.score {{ position:relative; display:flex; align-items:center; gap:8px; min-width:96px; }}
.score-bar {{ height:8px; background:var(--series); border-radius:4px; min-width:4px; }}
.score span {{ font-size:12px; color:var(--ink2); }}
tbody tr:hover {{ background:color-mix(in srgb, var(--series) 7%, transparent); }}
.filters {{ display:flex; gap:16px; align-items:center; flex-wrap:wrap; margin:0 0 14px; }}
.filters input[type=search] {{ flex:1; min-width:200px; padding:8px 12px; font-size:13px;
  border:1px solid var(--border); border-radius:8px; background:var(--plane); color:var(--ink); }}
.slider-lab {{ font-size:12.5px; color:var(--ink2); display:flex; align-items:center; gap:8px; white-space:nowrap; }}
.slider-lab input[type=range] {{ accent-color:var(--series); width:140px; }}
.slider-lab b {{ color:var(--ink); font-variant-numeric:tabular-nums; min-width:34px; display:inline-block; }}
.count {{ font-size:12px; color:var(--muted); white-space:nowrap; }}
.foot {{ color:var(--muted); font-size:12px; margin-top:26px; text-align:center; }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div>
    <h1>求职仪表盘 · 深圳 AI Agent 岗</h1>
    <div class="sub">数据源 Boss直聘 · 本地生成 {generated} · 求职画像匹配基于 bge-small-zh 语义模型</div>
  </div>
  <button class="theme-btn" onclick="toggleTheme()">◐ 明/暗</button>
</header>

<div class="tiles">{tiles_html}</div>

<div class="grid2">
  <section>
    <h2>月薪分布（分位）</h2>
    <p class="hint">按 min/max 中点 · P50 为中位数</p>
    {_bar_v(p)}
  </section>
  <section>
    <h2>技能词频 Top 15</h2>
    <p class="hint">应用/工程岗子集 · 出现在多少条职位中</p>
    {_bar_h(d["top_skills"])}
  </section>
</div>

<section>
  <h2>匹配职位 Top {len(d["matches"])}（过滤后 · 点表头可排序）</h2>
  <p class="hint">已过滤：算法研究岗 / 非开发岗 / 薪资低于地板 / 资历过高。分数=与你简历的语义相似度（粗筛，精评待 LLM Block A-G）</p>
  <div class="filters">
    <input id="kw" type="search" placeholder="🔍 搜索职位/公司/技能（如 LangChain、双休）" oninput="applyFilters()">
    <label class="slider-lab">最低月薪 <b id="salval">0K</b>
      <input id="sal" type="range" min="0" max="60" step="1" value="0" oninput="applyFilters()">
    </label>
    <span class="count" id="cnt"></span>
  </div>
  <div style="overflow-x:auto">
  <table id="mt">
    <thead><tr>
      <th data-c="0" data-t="n">#</th>
      <th data-c="1" data-t="n">分数</th>
      <th data-c="2" data-t="s">职位</th>
      <th data-c="3" data-t="s">公司</th>
      <th data-c="4" data-t="n">薪资</th>
      <th data-c="5" data-t="s">经验</th>
      <th data-c="6" data-t="s">技能标签</th>
    </tr></thead>
    <tbody>{_table(d["matches"])}</tbody>
  </table>
  </div>
</section>

<div class="foot">Job-Copilot · 本地运行，数据不出本机 · 重新生成：<code>python -m job_copilot dashboard</code></div>
</div>
<script>
function toggleTheme() {{
  var el = document.documentElement;
  var cur = el.getAttribute('data-theme');
  var dark = cur ? cur === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  el.setAttribute('data-theme', dark ? 'light' : 'dark');
}}
// 筛选：关键词 + 最低薪资（薪资未知的行始终显示）
function applyFilters() {{
  var kw = (document.getElementById('kw').value || '').trim().toLowerCase();
  var sal = +document.getElementById('sal').value;
  document.getElementById('salval').textContent = sal + 'K';
  var tb = document.querySelector('#mt tbody'), shown = 0, total = 0;
  Array.from(tb.rows).forEach(function(r) {{
    total++;
    var smax = +r.dataset.smax;
    var okKw = !kw || (r.dataset.text || '').indexOf(kw) !== -1;
    var okSal = sal === 0 || smax === 0 || smax >= sal * 1000;
    var vis = okKw && okSal;
    r.style.display = vis ? '' : 'none';
    if (vis) shown++;
  }});
  document.getElementById('cnt').textContent = '显示 ' + shown + ' / ' + total;
}}
// 点表头排序
document.querySelectorAll('#mt th').forEach(function(th) {{
  th.addEventListener('click', function() {{
    var tb = document.querySelector('#mt tbody');
    var c = +th.dataset.c, numeric = th.dataset.t === 'n';
    var asc = th._asc = !th._asc;
    var rows = Array.from(tb.rows);
    rows.sort(function(a, b) {{
      var x = a.cells[c].dataset.sort || a.cells[c].innerText;
      var y = b.cells[c].dataset.sort || b.cells[c].innerText;
      if (numeric) {{ x = parseFloat(x)||0; y = parseFloat(y)||0; return asc ? x-y : y-x; }}
      return asc ? String(x).localeCompare(y,'zh') : String(y).localeCompare(x,'zh');
    }});
    rows.forEach(function(r) {{ tb.appendChild(r); }});
  }});
}});
applyFilters();  // 初始化显示计数
</script>
</body>
</html>"""


def write_dashboard() -> str:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / "仪表盘.html"
    path.write_text(build_dashboard(), encoding="utf-8")
    return str(path)
