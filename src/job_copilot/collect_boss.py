"""Boss直聘采集器（M1）。

策略：Playwright 有头浏览器 + 登录态复用 + XHR 响应拦截。
Boss直聘 Web 端是 SPA，列表数据由 wapi/zpgeek/search/joblist.json 返回，
拦截该响应拿结构化 JSON，比解析 DOM 稳健（改版不影响字段）。

红线约束（PRD §2.3）：
- 有头模式运行，登录/安全验证一律人工完成，工具只等待，不破解；
- 单账号节流：请求间隔 config [collect] min/max_interval_sec，日限 daily_limit；
- 原始响应留档 data/raw/，便于字段变更时回溯。
"""

from __future__ import annotations

import json
import random
import time
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Optional

from .config import DATA_DIR, load_config
from . import db

SESSION_DIR = DATA_DIR / "sessions"
RAW_DIR = DATA_DIR / "raw"
IMPORT_DIR = DATA_DIR / "imports"
BOSS_HOME = "https://www.zhipin.com/"
SEARCH_URL = "https://www.zhipin.com/web/geek/jobs?query={query}&city={city}"
JOBLIST_API = "zpgeek/search/joblist.json"

# 城市名 → Boss直聘城市码（覆盖配置常用城市，缺的运行时报错提示补充）
CITY_CODES = {
    "深圳": "101280600",
    "广州": "101280100",
    "北京": "101010100",
    "上海": "101020100",
    "杭州": "101210100",
    "成都": "101270100",
}

CITY_NAMES = {code: name for name, code in CITY_CODES.items()}  # 城市码 → 城市名

SECURITY_MARKERS = ("安全验证", "security-check", "请稍候", "verify-slider")

# 登录成功后 Boss直聘 会种下的会话 cookie（任一存在即视为已登录）
LOGIN_COOKIE_NAMES = {"bst", "wt2", "zp_at", "geek_zp_token"}


def _session_path(platform: str = "boss") -> Path:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_DIR / f"{platform}.json"


# 反自动化检测的浏览器启动参数（防止 Boss 直聘等网站白屏拦截）
_ANTI_DETECT_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-sandbox",
    "--disable-setuid-sandbox",
]


def _launch(playwright, storage_state: Optional[Path], headless: bool = False):
    browser = playwright.chromium.launch(headless=headless, args=_ANTI_DETECT_ARGS)
    context = browser.new_context(
        storage_state=str(storage_state) if storage_state and storage_state.exists() else None,
        viewport={"width": 1440, "height": 900},
        locale="zh-CN",
    )
    # 反检测启动参数已足够，不再篡改 navigator（Boss 直聘会检测 webdriver 被篡改并白屏）
    return browser, context


def _is_logged_in(context) -> bool:
    try:
        cookies = context.cookies()
    except Exception:
        return False
    return any(c.get("name") in LOGIN_COOKIE_NAMES and c.get("value") for c in cookies)


def login(timeout_sec: int = 300) -> None:
    """打开浏览器让用户扫码登录，自动检测登录成功并保存登录态。

    终端可能没有交互输入通道（如经 Claude Code 的 `!` 执行），
    因此不等待键盘，改为轮询登录 cookie，检测到即保存并退出。
    """
    from playwright.sync_api import sync_playwright

    state = _session_path()
    with sync_playwright() as p:
        browser, context = _launch(p, state)
        page = context.new_page()
        page.goto(BOSS_HOME, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        if _is_logged_in(context):
            context.storage_state(path=str(state))
            browser.close()
            print(f"✓ 已处于登录状态，登录态已刷新: {state}")
            return

        print("浏览器已打开。请在页面中完成扫码登录。")
        print(f"登录成功后会自动检测并保存，无需回终端操作（限时 {timeout_sec // 60} 分钟，期间请勿关闭浏览器）…")
        deadline = time.time() + timeout_sec
        ok = False
        last_cookie_dump = 0.0
        while time.time() < deadline:
            time.sleep(2)
            try:
                if page.is_closed():
                    print("⚠ 浏览器窗口已被关闭")
                    break
            except Exception:
                break

            # 每 10 秒输出一次调试信息
            now = time.time()
            if now - last_cookie_dump >= 10:
                last_cookie_dump = now
                try:
                    cookies = context.cookies()
                    cookie_names = [c.get("name") for c in cookies if c.get("value")]
                    print(f"  [调试] 当前页面: {page.url[:80]}")
                    print(f"  [调试] 当前 cookie: {cookie_names}")
                except Exception:
                    pass

            if _is_logged_in(context):
                ok = True
                break

        if ok:
            context.storage_state(path=str(state))
            print(f"✓ 检测到登录成功，登录态已保存: {state}")
            print("  后续运行 `collect run` 将复用此登录态；失效时重新执行 `collect login`。")
        else:
            print("✗ 未检测到登录（超时或浏览器被关闭），登录态未保存。请重新执行 collect login。")
        try:
            browser.close()
        except Exception:
            pass


def _hit_security_check(page) -> bool:
    try:
        title = page.title()
    except Exception:
        return False
    return any(m in (title or "") for m in SECURITY_MARKERS) or any(
        m in page.url for m in ("security-check", "safe/verify")
    )


def _wait_if_security_check(page, timeout_sec: int = 180) -> None:
    """检测到安全验证页时暂停，轮询等用户人工完成后继续（不做任何绕过）。"""
    if not _hit_security_check(page):
        return
    print(f"⚠ 遇到安全验证页。请在浏览器中人工完成验证，完成后会自动继续（限时 {timeout_sec // 60} 分钟）…")
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        time.sleep(2)
        if not _hit_security_check(page):
            print("✓ 验证已通过，继续采集。")
            page.wait_for_timeout(2000)
            return
    print("✗ 验证等待超时，本组采集可能失败；稍后可重跑 collect run。")


def collect(pages: int = 3, keyword: Optional[str] = None, city: Optional[str] = None) -> None:
    """按配置的意向关键词×城市采集职位列表。

    pages: 每个 关键词×城市 组合翻页数（每页约30条）。
    """
    from playwright.sync_api import sync_playwright

    cfg = load_config()
    keywords = [keyword] if keyword else list(cfg.me.get("keywords", []))
    cities = [city] if city else list(cfg.me.get("cities", []))
    daily_limit = int(cfg.collect.get("daily_limit", 300))
    lo = float(cfg.collect.get("min_interval_sec", 3))
    hi = float(cfg.collect.get("max_interval_sec", 8))

    state = _session_path()
    if not state.exists():
        print("✗ 未找到登录态。请先执行: python -m job_copilot collect login")
        return

    conn = db.connect()
    collected_today = db.count_today(conn, "boss")
    if collected_today >= daily_limit:
        print(f"✗ 今日已采集 {collected_today} 条，达到日限 {daily_limit}（红线：单账号节流）。明天再来。")
        return

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_file = RAW_DIR / f"boss-{date.today().isoformat()}.jsonl"
    new_count, dup_count = 0, 0
    captured: list = []

    def on_response(resp):
        if JOBLIST_API in resp.url and resp.status == 200:
            try:
                payload = resp.json()
            except Exception:
                return
            jobs = (payload.get("zpData") or {}).get("jobList") or []
            if jobs:
                captured.append(jobs)

    with sync_playwright() as p:
        browser, context = _launch(p, state)
        page = context.new_page()
        page.on("response", on_response)

        with open(raw_file, "a", encoding="utf-8") as raw_out:
            for kw in keywords:
                for ct in cities:
                    code = CITY_CODES.get(ct)
                    if not code:
                        print(f"⚠ 城市 `{ct}` 无城市码映射，跳过（在 collect_boss.CITY_CODES 中补充）")
                        continue
                    url = SEARCH_URL.format(query=urllib.parse.quote(kw), city=code)
                    print(f"→ 采集: {kw} @ {ct}")
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)
                    _wait_if_security_check(page)

                    for page_no in range(pages):
                        if db.count_today(conn, "boss") >= daily_limit:
                            print(f"⚠ 达到日限 {daily_limit}，停止。")
                            break
                        # 等待本页 joblist 响应被拦截
                        deadline = time.time() + 15
                        while not captured and time.time() < deadline:
                            page.wait_for_timeout(500)
                        if not captured:
                            print(f"  第{page_no + 1}页未捕获到数据（可能需登录/验证或已到末页）")
                            _wait_if_security_check(page)
                            break
                        for jobs in captured:
                            for j in jobs:
                                raw_out.write(json.dumps(j, ensure_ascii=False) + "\n")
                                rec = _normalize(j, kw, ct)
                                if db.upsert_job(conn, rec):
                                    new_count += 1
                                else:
                                    dup_count += 1
                        captured.clear()
                        # 翻页：滚到底部触发下一页加载（Boss直聘 Web 为滚动加载）
                        if page_no < pages - 1:
                            time.sleep(random.uniform(lo, hi))
                            page.mouse.wheel(0, 4000)
                            page.wait_for_timeout(2000)
                    time.sleep(random.uniform(lo, hi))

        context.storage_state(path=str(state))  # 回写刷新过的 cookie
        browser.close()

    stats = db.job_stats(conn)
    print(f"\n✓ 本次新增 {new_count} 条，重复 {dup_count} 条（已去重更新）")
    print(f"✓ 原始数据: {raw_file}")
    print(f"✓ 库内累计: {stats['total']} 条 / {stats['companies']} 家公司 {stats['by_platform']}")


def import_files(paths: Optional[list] = None) -> None:
    """导入油猴脚本导出的 boss-jobs-*.json 文件入库。

    数据来源：用户本人正常浏览 Boss直聘 搜索页时，tools/boss-collector.user.js
    把页面自己加载的公开职位数据存成 JSON。这里读文件、规整、去重入库。
    不驱动浏览器、不发请求——纯本地文件处理。

    paths: 文件或目录列表；缺省时扫描 ~/Downloads 与 data/imports/。
    """
    import glob

    if paths:
        files: list[Path] = []
        for p in paths:
            pp = Path(p).expanduser()
            if pp.is_dir():
                files += [Path(x) for x in glob.glob(str(pp / "boss-jobs-*.json"))]
            elif pp.exists():
                files.append(pp)
            else:
                files += [Path(x) for x in glob.glob(str(pp))]
    else:
        search_dirs = [Path.home() / "Downloads", IMPORT_DIR]
        files = []
        for d in search_dirs:
            files += [Path(x) for x in glob.glob(str(d / "boss-jobs-*.json"))]

    files = sorted(set(files))
    if not files:
        print("✗ 未找到待导入文件。")
        print("  用法：先用 tools/boss-collector.user.js 在 Boss直聘 浏览并「导出JSON」，")
        print("  文件默认落在 ~/Downloads，然后运行： collect import")
        print("  或指定路径： collect import <文件或目录>")
        return

    conn = db.connect()
    new_count, dup_count, bad = 0, 0, 0
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    processed_dir = IMPORT_DIR / "processed"
    processed_dir.mkdir(exist_ok=True)

    for f in files:
        try:
            records = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"⚠ 跳过无法解析的文件 {f.name}: {e}")
            bad += 1
            continue
        if not isinstance(records, list):
            print(f"⚠ 跳过格式异常的文件 {f.name}（顶层应为数组）")
            bad += 1
            continue
        file_new = 0
        for j in records:
            kw = j.get("_kw") or ""
            city_code = j.get("_cityCode") or ""
            city = CITY_NAMES.get(city_code) or j.get("cityName") or ""
            rec = _normalize(j, kw, city)
            if not rec.get("job_id"):
                continue
            if db.upsert_job(conn, rec):
                new_count += 1
                file_new += 1
            else:
                dup_count += 1
        print(f"  ✓ {f.name}: {len(records)} 条，新增 {file_new}")
        # 处理过的文件归档，避免重复扫描（去重本就幂等，归档只是清爽）
        try:
            f.replace(processed_dir / f.name)
        except Exception:
            pass  # 跨盘/权限问题时保留原文件，不影响入库

    stats = db.job_stats(conn)
    print(f"\n✓ 导入完成：新增 {new_count} 条，重复 {dup_count} 条"
          + (f"，{bad} 个文件异常" if bad else ""))
    print(f"✓ 库内累计: {stats['total']} 条 / {stats['companies']} 家公司 {stats['by_platform']}")
    if new_count:
        print("下一步：运行 clean 清洗导出，或让我直接做市场画像。")


def _normalize(j: dict, keyword: str, city: str) -> dict:
    """joblist.json 单条 → jobs 表记录。字段名以 2025-2026 Web 端为准，缺失容错。"""
    salary_text = j.get("salaryDesc") or ""
    lo, hi, months = db.parse_salary(salary_text)
    job_id = j.get("encryptJobId") or j.get("jobId") or ""
    return {
        "platform": "boss",
        "job_id": str(job_id),
        "url": f"https://www.zhipin.com/job_detail/{job_id}.html" if job_id else None,
        "title": j.get("jobName"),
        "company": j.get("brandName"),
        "company_size": j.get("brandScaleName"),
        "industry": j.get("brandIndustry"),
        "salary_text": salary_text,
        "salary_min": lo,
        "salary_max": hi,
        "salary_months": months,
        "city": j.get("cityName") or city,
        "district": j.get("areaDistrict"),
        "experience": j.get("jobExperience"),
        "degree": j.get("jobDegree"),
        "tags": (j.get("skills") or []) + (j.get("jobLabels") or []),
        "hr_name": j.get("bossName"),
        "hr_title": j.get("bossTitle"),
        "hr_active": j.get("activeTimeDesc"),
        "jd_text": "",  # 列表页无全文；详情采集在 P2 score 前按需补
        "search_keyword": keyword,
        "search_city": city,
    }
