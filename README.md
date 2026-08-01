# Job-Copilot 求职助手

单用户、本地、隐私可控的求职助手。核心理念：**投得准 + 谈得好 > 投得多**。

- 数据与匹配管线：Python CLI（采集导入 → 向量粗筛 → LLM 精排 → 标注评测 → 分组投递统计）
- 判断与方法论：7 个 Claude Code 技能（岗位评估 / 公司研究 / 简历排版 / 跟进 / 面试准备 / 红旗复盘 / offer 谈判），见 [`skills/README.md`](skills/README.md)
- 完整需求与设计红线见 [`docs/需求文档.md`](docs/需求文档.md)

## 它能做什么（分阶段）
- **P1 探索+分析**：采集行业数据 → 清洗 → 市场画像 → 帮你找方向 → 技能树诊断
- **P2 半自动投递**：匹配打分 → 定制招呼语 → 分组对照实验 → 你确认后手动发送
- **P3 追踪+决策**：已读不回统计 → 分组对照 → HR回复起草 → 面试邀约管理 → 决策报告

## 快速开始
```bash
git clone <本仓库> job-copilot && cd job-copilot
python3 -m venv .venv && source .venv/bin/activate   # Python 3.9+
pip install -r requirements.txt

bash tools/download-model.sh                          # 本地向量模型（~90MB，一次性）
cp config/config.example.toml config/config.toml      # 填 DeepSeek API Key + 你的意向
cp config/profile.example.md config/profile.md        # 填你的求职叙事与底线
# resume/ 目录放入你的母版简历（所有真实经历的完整版，是一切生成的唯一事实来源）

PYTHONPATH=src python -m job_copilot status           # 检查配置
```

**采集**：推荐油猴脚本路线（合规、稳定），安装与用法见 [`tools/README-油猴采集.md`](tools/README-油猴采集.md)；
导出 JSON 后 `python -m job_copilot collect import` 入库。

**典型一轮**：`collect import` → `match`（向量粗筛）→ `score`（LLM 精排）→ `greet`（分组招呼语）→
本人在平台手动发送 → 回填 `data/exports/投递追踪-*.csv` → `stats`（竞争力分组对照报告）。

## Web 前端（投递管理面板）

```bash
# 首次使用：交互式创建本地单用户账号（密码不会回显）
PYTHONPATH=src .venv/bin/python -m job_copilot web reset-password --username <本地用户名>

# 终端 1：启动 API
PYTHONPATH=src python -m job_copilot web serve

# 终端 2：启动前端
cd frontend
npm install
npm run dev          # → http://localhost:5173
```

- 登录页：开发服务器使用 `http://localhost:5173/login`；production build 由后端托管时使用 `http://127.0.0.1:8000/login`。
- 账号来源优先级：本地数据库账号 → `APP_USERNAME` / `APP_PASSWORD_HASH` → 显式开发兼容模式。环境变量名称见 `.env.example`，请通过 shell 或启动器注入；项目不会自动读取 `.env` 文件。
- 项目不会自动启用 `admin/admin`。如确需兼容旧开发环境，必须设置 `APP_ALLOW_DEV_DEFAULTS=true`，且 production 中始终禁用。
- 忘记密码时运行 `PYTHONPATH=src .venv/bin/python -m job_copilot web reset-password`；命令会交互式读取新密码，使旧 Session 全部失效，且不会输出密码或 Hash。
- 登录后可在“设置 → 账号与安全”修改用户名、密码或明确退出登录。

## 目录结构
```
job-copilot/
├── docs/             需求文档（PRD，含设计红线）
├── src/job_copilot/  Python 引擎（CLI + FastAPI）
├── frontend/         React 投递管理面板
├── skills/           Claude Code 求职技能库（.claude/skills 软链于此）
├── tools/            油猴采集脚本 + 模型下载脚本
├── vendor/           career-ops 上游原文（MIT，方法论溯源）
├── data/             本地数据（SQLite/原始/导出，全部不入库）
├── resume/           你的母版简历（不入库）
├── reports/          生成的分析报告（不入库）
└── config/           配置与个人策略（模板入库，实际文件不入库）
```

## 隐私设计
- 全部数据本地：简历、采集数据、报告、登录态、API Key 均在 `.gitignore` 中，仓库只含工具与方法论
- 唯一的外发：调用你自己配置的 LLM API（OpenAI 兼容接口，可换任意服务商）；向量化全程本地离线
- 换人即用：替换 `resume/`、`config/config.toml`、`config/profile.md` 三处即可，代码与技能零个人硬编码

## 状态（2026-07-12，原作者实例）
- [x] P0 骨架 + 需求文档
- [x] P1 探索+分析：401条职位入库 · 市场画像 · 技能树诊断 · 向量粗筛+LLM精排+标注评测闭环 · 仪表盘（`clean`/`skills` 命令未单独实现，已由报告覆盖）
- [x] P2 半自动投递：精排50条 → 15条分组对照招呼语（冲刺5/稳妥6/保底4）已于 07-12 手动发出（`apply` 辅助命令未实现，按红线人工发送）
- [ ] P3 追踪+决策：`stats` 已上线、等待首批已读/回复反馈回填；`inbox`/`interview`/`decide` 未实现

## 红线（务必知晓）
不伪造经历、不代发（发送必须本人确认）、不大规模爬取、不破解反爬、不多账号刷量、不采集他人隐私。
详见需求文档 §2。

## 致谢与许可
技能方法论改编自 [career-ops](https://github.com/santifer/career-ops)（Santiago Fernández de Valderrama，MIT），
整合记录见 [`docs/借鉴-career-ops.md`](docs/借鉴-career-ops.md)。本项目同样采用 [MIT License](LICENSE)。
