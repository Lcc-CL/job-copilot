"""Job-Copilot: 单用户本地求职助手。

模块规划（详见 docs/需求文档.md §3）:
  collect    M1 数据采集（Playwright带登录态 + 八爪鱼导入）
  clean      M2 数据清洗与整合
  market     M3 行业/市场分析
  skills     M4 竞争力与技能树诊断
  experiment M5 分组对照投递与已读不回统计
  apply      M6 简历定制与半自动投递
  greeting   M7 招呼语生成
  inbox      M8 HR回复与面试邀约管理
  interview  M9 面试方向与指导
  decision   M10 决策支持报告
"""

__version__ = "0.1.0"
