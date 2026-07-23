"""Job-Copilot 命令行入口。

用法:
    python -m job_copilot <命令>

命令按阶段解锁（详见 docs/需求文档.md §6 路线图）:
    P1: collect / clean / market / skills
    P2: score / greet / apply
    P3: inbox / stats / interview / decide
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .config import load_config

# (命令, 阶段, 说明)
COMMANDS = [
    ("status",    "P0", "检查配置与数据状态"),
    ("collect",   "P1", "采集职位数据（Playwright带登录态 / 导入八爪鱼CSV）"),
    ("clean",     "P1", "清洗整合，导出Excel供筛选打标"),
    ("market",    "P1", "市场画像与换行方向候选分析"),
    ("skills",    "P1", "竞争力与技能树诊断"),
    ("match",     "P1", "JD↔简历 本地语义匹配打分（bge向量）"),
    ("dashboard", "P1", "生成可视化仪表盘HTML（薪资/技能/匹配，浏览器打开）"),
    ("evalset",   "P1", "生成评测集标注表（分层抽样，供人工标注该投/不投）"),
    ("eval",      "P1", "评测：用标注算 precision@k，对比粗筛vs精排"),
    ("score",     "P1", "LLM 精排：对粗筛候选做 Block A-G 评估"),
    ("greet",     "P2", "为'感兴趣'岗位生成定制招呼语"),
    ("apply",     "P2", "半自动投递（每条需确认）"),
    ("inbox",     "P3", "回读HR消息，起草回复，收集邀约"),
    ("stats",     "P3", "已读不回/回复/邀约率分组统计"),
    ("interview", "P3", "生成面试准备卡"),
    ("decide",    "P3", "生成个人求职决策报告"),
]

IMPLEMENTED = {"status", "collect", "clean", "market", "skills", "match", "dashboard", "evalset", "score", "eval", "greet", "stats"}


def cmd_status() -> None:
    try:
        cfg = load_config()
    except FileNotFoundError as e:
        print(f"✗ {e}")
        sys.exit(1)
    me = cfg.me
    print(f"Job-Copilot v{__version__}")
    print(f"✓ 配置已加载: LLM={cfg.llm.get('provider')} "
          f"({cfg.llm.get('model_analysis')}/{cfg.llm.get('model_drafting')})")
    print(f"✓ 求职画像: {me.get('keywords')} @ {me.get('cities')} "
          f"薪资 {me.get('salary_expect_min')}~{me.get('salary_expect_max')}")
    print(f"✓ 采集平台: {cfg.collect.get('platforms')} "
          f"(日限 {cfg.collect.get('daily_limit')})")
    print(f"✓ 投递: 日限 {cfg.apply.get('daily_apply_limit')}, "
          f"需确认={cfg.apply.get('require_confirm')}")
    from . import db
    stats = db.job_stats(db.connect())
    print(f"✓ 职位库: {stats['total']} 条 / {stats['companies']} 家公司 {stats['by_platform']}")
    print("\n当前进度: P1 完成；P2 首批分组对照投递已发出（见 data/exports/投递追踪-*.csv）；"
          "P3 stats 已上线，反馈回填后重跑出竞争力结论。")


def cmd_collect(args) -> None:
    from . import collect_boss
    if args.action == "login":
        collect_boss.login()
    elif args.action == "run":
        collect_boss.collect(pages=args.pages, keyword=args.keyword, city=args.city)
    elif args.action == "import":
        collect_boss.import_files(paths=args.paths or None)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="job_copilot",
        description="求职助手：投得准 + 谈得好 > 投得多",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(
            f"  {name:<10} [{phase}] {desc}" for name, phase, desc in COMMANDS
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    for name, phase, desc in COMMANDS:
        if name == "match":
            p_match = sub.add_parser(name, help=desc)
            p_match.add_argument("--top", type=int, default=20, help="输出前 N 个匹配（默认20）")
            p_match.add_argument("--rebuild", action="store_true", help="重建全部向量索引")
        elif name == "score":
            p_score = sub.add_parser(name, help=desc)
            p_score.add_argument("--top", type=int, default=20,
                                 help="精排前 N 个粗筛候选（默认20，每条约十几秒）")
            p_score.add_argument("--skip-scored", action="store_true",
                                 help="跳过已精排的岗，只评接下来 N 个新候选（分批扩投用）")
        elif name == "skills":
            p_skills = sub.add_parser(name, help=desc)
            p_skills.add_argument("--jobs", help="清洗后岗位CSV路径（默认 data/clean/cleaned_jobs.csv）")
            p_skills.add_argument("--profile", help="简历/profile路径（默认 resume/母版简历.md）")
        elif name == "eval":
            p_eval = sub.add_parser(name, help=desc)
            p_eval.add_argument("--file", help="指定标注表路径（默认取最新；留出集评测时指向 holdout 文件）")
        elif name == "greet":
            p_greet = sub.add_parser(name, help=desc)
            p_greet.add_argument("--min-fit", type=int, default=4,
                                 help="最低精排分（默认4；扩投对照可降到3，自动滤掉真实性低/够不着的）")
            p_greet.add_argument("--limit", type=int, default=20,
                                 help="本批最多生成条数（默认20）")
        elif name == "collect":
            p_collect = sub.add_parser(name, help=desc)
            p_collect.add_argument("action", choices=["login", "run", "import"],
                                   help="login=扫码登录保存会话; run=Playwright自动采集; "
                                        "import=导入油猴脚本导出的JSON（推荐，合规）")
            p_collect.add_argument("--pages", type=int, default=3,
                                   help="每个 关键词×城市 组合的翻页数（默认3，约90条）")
            p_collect.add_argument("--keyword", help="只采集该关键词（默认用配置全部）")
            p_collect.add_argument("--city", help="只采集该城市（默认用配置全部）")
            p_collect.add_argument("paths", nargs="*",
                                   help="import 用：待导入的 JSON 文件或目录（默认扫 ~/Downloads）")
        else:
            sub.add_parser(name, help=f"[{phase}] {desc}")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status()
    elif args.command == "collect":
        cmd_collect(args)
    elif args.command == "clean":
        from . import clean
        print(clean.run())
    elif args.command == "skills":
        from . import skills_diagnose
        print(skills_diagnose.run(
            jobs_csv=getattr(args, "jobs", None),
            profile_path=getattr(args, "profile", None),
        ))
    elif args.command == "market":
        from . import analyze
        print(analyze.market_report())
    elif args.command == "match":
        from . import match as match_mod
        if args.rebuild:
            match_mod.build_index(rebuild=True)
        print(match_mod.match(top_k=args.top))
    elif args.command == "dashboard":
        from . import report_html
        path = report_html.write_dashboard()
        print(f"✓ 仪表盘已生成：{path}")
        print(f"  用浏览器打开：open '{path}'")
    elif args.command == "evalset":
        from . import evalset
        print(evalset.make_worksheet())
    elif args.command == "score":
        from . import score
        print(score.score_top(top_k=args.top, skip_scored=args.skip_scored))
    elif args.command == "eval":
        from . import evaluate
        print(evaluate.run(path=getattr(args, "file", None)))
    elif args.command == "greet":
        from . import greet
        print(greet.generate(min_fit=args.min_fit, limit=args.limit))
    elif args.command == "stats":
        from . import stats
        print(stats.report())
    elif args.command not in IMPLEMENTED:
        phase = next(p for n, p, _ in COMMANDS if n == args.command)
        print(f"命令 `{args.command}` 属于 {phase} 阶段，尚未实现。")
        sys.exit(1)


if __name__ == "__main__":
    main()
