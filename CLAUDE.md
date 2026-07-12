# Job-Copilot 项目指引

单用户本地求职助手。PRD 见 `docs/需求文档.md`（含设计红线，改动前必读）。

## 求职者画像（个人数据，全部不入库，见 .gitignore）
- 意向/城市/薪资：`config/config.toml` 的 `[me]` 段（模板 `config.example.toml`）
- 母版简历：`resume/` 目录（所有真实经历的完整版，是一切生成的唯一事实来源）
- 个性化策略：`config/profile.md`（求职叙事、画像偏好、谈判底线；模板 `profile.example.md`）
- 严禁在代码、技能、文档中硬编码候选人姓名/东家/经历——一律从上述文件动态读取

## 复用的 career-ops 方法论（vendor/career-ops-src/，MIT）
本项目复用了开源项目 [career-ops](https://github.com/santifer/career-ops)（作者 Santiago Fernández de Valderrama，MIT License）的技能方法论。
- **正式技能**（中国市场改编版，自包含）：`skills/`（`.claude/skills` 是它的软链，Claude Code 会话可直接调用）：job-eval / interview-prep / interview-redflag / offer-prep / company-research / followup + `shared/求职共享上下文.md`
- **上游原文**（30个mode完整副本，深挖方法论时查阅）：`vendor/career-ops-src/modes/`（含 `zh/` 中文模式5件）
- 整合记录（搬了什么/改了什么/不搬什么）：`docs/借鉴-career-ops.md`

**路径映射**（读 vendor 技能文件时按此翻译，它引用的 node 脚本一律跳过）：

| career-ops 引用 | 本项目对应 |
|---|---|
| `cv.md` | `resume/` 下的母版简历 |
| `config/profile.yml` | `config/config.toml` 的 `[me]` |
| `modes/_profile.md` | `config/profile.md` |
| `article-digest.md` / `writing-samples/` | 暂无，跳过 |
| tracker (`data/applications.md` + TSV) | `data/exports/tracker.md`（P3 后迁 SQLite） |
| `node cv-sync-check.mjs` 等脚本 | 不使用，跳过 |
| 报告输出 | `reports/` 目录 |

## 设计红线（压缩版，全文见 PRD §2）
1. 不伪造经历——简历/招呼语/回复只重组润色 `resume/` 里的真实内容。
2. 不代发——任何投递、消息发送必须用户确认；工具只起草。
3. 采集个人规模+公开信息，单账号节流，不破解反爬。
4. 竞争力用"分组对照投递+已读不回率"实证，不搞海投。

## 运行
```bash
PYTHONPATH=src .venv/bin/python -m job_copilot status   # Python 3.9
```
