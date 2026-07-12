# career-ops 借鉴与整合记录

> 来源：github.com/santifer/career-ops（MIT License，作者 Santiago/santifer.io）
> 整合日期：2026-07-10。本机直连 GitHub 超时，素材经服务端逐文件提取，未保留完整克隆。

## 一、项目定性

career-ops 是一套 **Claude Code 原生的"求职方法论技能包"**：核心是 30+ 个 Markdown 技能（modes/），配 80+ 西方招聘平台 JS 爬虫（providers/）和 Go TUI 仪表板。作者用它评估 740+ 职位、生成 100+ 定制简历、拿到 Head of AI 职位。其全局规则（永不编造经历、永不代为提交、AI 输出必须人审）与本项目三条红线完全一致——验证了我们的设计方向。

## 二、已整合内容（→ `skills/` 目录）

| 本项目文件 | 来源 | 对应模块 | 核心能力 |
|---|---|---|---|
| `skills/shared/求职共享上下文.md` | `modes/zh/_shared.md` | 全局 | A-F 评分系统+决策阈值、AI岗位画像检测、公司类型/薪资可信度分级、**中国市场特性表**（五险一金/年终奖/试用期/竞业/个税/落户）、写作风格与ATS规则 |
| `skills/job-eval/` | `modes/zh/oferta.md` | M6.1 | Block A-G 七维评估；**Block G 幽灵职位鉴别**（新鲜度/描述红旗/公司外部信号/历史去重） |
| `skills/interview-prep/` | `modes/interview-prep.md` | M9 | 按面试官类型分轨准备、STAR+R 故事库累积、缺口检测、面经引用不编造 |
| `skills/offer-prep/` | `modes/offer-prep.md` | M10（补缺口） | 条款走查+标签、口头承诺一致性核对、律师清单/雇主沟通清单分流、合同不联网 |
| `skills/company-research/` | `modes/deep.md` | M9前置（补缺口） | 六维公司研究，信息源本土化（天眼查/脉脉/看准/36氪） |
| `skills/interview-redflag/` | `modes/interview-redflag.md` | M9 | 四类信号跨轮累积计分（0-8分）→ 三档预警 |
| `skills/followup/` | `modes/followup.md` | M5/M8 | 状态分级跟进节奏、递进式消息、冷却止损；适配站内信节奏 |

**本土化改造点**：文件路径对齐本项目结构（resume/、config.toml、SQLite tracker）；信息源换成国内平台；跟进节奏按站内信缩短；补 Boss直聘 特有信号（HR活跃度、认证状态）；补中国面试高频题与红旗信号；西式 cover letter 语境改为招呼语/站内信。

**启用方式**：`.claude/skills → ../skills` 软链**已建好**，在 job-copilot 目录启动 Claude Code 即可直接调用这些技能，无需任何手动操作。

## 三、只借方法论、不搬实现

- **batch 并行评估流程**：理念并入 P2 的批量打分管道（Python 实现）
- **ATS 简历模板**：中文简历格式差异大，只保留"关键词映射"方法论（已入共享上下文）
- **tracker 单一数据源理念**：与我们 SQLite applications 表设计吻合，字段口径已参考

## 四、明确不采用

- **providers/ 80+ 爬虫**：全是 Greenhouse/Workday/LinkedIn 系西方平台，无 Boss直聘/智联/猎聘——M1 采集层仍自建（Playwright+登录态）
- **西式投递模型**（表单+邮件）：与国内"打招呼聊天"文化不符，M7 招呼语生成自研
- **Go TUI 仪表板**：维持"表格+CLI"形态，不膨胀技术栈

## 五、它没有而我们独有的

M5 **分组对照投递 + 已读不回率统计**（竞争力实证）——career-ops 无此能力，仍是本项目差异化核心，按原计划自研。

## 六、许可与署名

MIT 允许自由使用、修改、分发；各改编文件头部已注明来源。其 Trademark Policy 仅限品牌名——我们不使用 "career-ops" 品牌，无冲突。

## 七、上游原文副本（后补）

GitHub 直连不通，但最终经 **npmmirror + jsDelivr CDN** 拿到了上游完整原文，存放在 `vendor/career-ops-src/`：
- `modes/` 30 个技能原文（含 `zh/` 中文模式 5 件：_shared / oferta / apply / pipeline / README，以及 offer-prep、interview-redflag、reply-watch 等新增件）
- `templates/`（ATS 简历 HTML/LaTeX 模板、门户配置样例）、`config/profile.example.yml`
- `LICENSE`（MIT，署名保留）、`AGENTS.md`、`README.md`、`TRADEMARK.md`

`skills/` 下的改编版是日常使用的正式版本；深挖某个方法论细节时查 vendor 原文。providers/ 爬虫与 Go 仪表板确认无复用价值，未下载。
