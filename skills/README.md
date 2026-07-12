# 求职 Skills（Claude Code 技能库）

7 个可复用技能 + 1 个共享上下文，覆盖「评估 → 投递 → 面试 → offer」全程。
改编自 [career-ops](https://github.com/santifer/career-ops)（MIT），已针对中国大陆市场本土化（信息源、薪酬结构、合同条款）。
`.claude/skills` 是本目录的软链，Claude Code 会话中直接以 `/技能名` 调用。

## 技能索引（按求职阶段）

| 阶段 | 技能 | 做什么 |
|---|---|---|
| 投前 | `job-eval` | 单个 JD 的 Block A-G 七维评估：匹配打分、薪酬拆解、简历定制清单、幽灵职位鉴别 |
| 投前 | `company-research` | 公司六维深研：AI战略/近期动态/工程文化/挑战/竞争格局/切入角度（脉脉/看准/天眼查） |
| 投前 | `resume-design` | 中文单页简历排版：HTML+CSS 生成、Playwright 渲染 PDF，内容只来自母版简历 |
| 投后 | `followup` | 跟进节奏管理：按状态分级的跟进时机、递进式消息起草、冷却止损判定 |
| 面试 | `interview-prep` | 面试准备包：按面试官类型（HR/业务/技术/群面）分轨、STAR 故事库映射与缺口检测 |
| 面试 | `interview-redflag` | 面试后红旗复盘：四类信号跨轮次累积计分，输出进/澄清/重新考虑预警 |
| Offer | `offer-prep` | 合同逐条款走查、口头承诺一致性核对、律师清单与雇主沟通清单分流（只准备不代决） |
| — | `shared/求职共享上下文.md` | 所有技能必读：数据路径、评分系统、红线约束 |

## 可复用性设计（换人即用）

技能层零硬编码个人信息（`shared` 里是强制规则）。迁移给新用户只需三步：
1. `resume/` 放入自己的母版简历（所有真实经历的完整版）
2. `config/config.toml` 填意向岗位/城市/薪资（模板 `config.example.toml`）
3. `config/profile.md` 写求职叙事与谈判底线（模板 `profile.example.md`）

## 红线（对所有技能生效）

不伪造经历、不代发消息（只起草，发送必须本人确认）、offer 条款不凭记忆讲法律。
深挖方法论可查上游 30 个 mode 原文：`vendor/career-ops-src/modes/`。
