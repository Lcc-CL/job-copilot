# Boss直聘 油猴采集器 — 使用说明

**为什么用这个而不是自动爬**：Boss直聘 对自动化浏览器有主动反爬。这个脚本不驱动浏览器、不发任何请求——是**你本人**正常浏览搜索页，脚本把页面自己加载的公开职位数据顺手存到本地。采集的就是你眼睛看到的东西，合规、稳定、不会被封号。

## 一次性安装（约2分钟）

1. 浏览器装 **Tampermonkey（油猴）** 扩展：
   - Chrome/Edge：应用商店搜 "Tampermonkey" 安装
2. 点油猴图标 → **添加新脚本** → 清空模板，把 `boss-collector.user.js` 全文粘进去 → **Ctrl/Cmd+S 保存**
3. 确认油猴里该脚本是「已启用」状态

## 每次采集（你只需正常刷职位）

1. 打开 Boss直聘，登录，正常搜索你的意向岗（如「AI Agent工程师 深圳」）
2. 右下角会出现青色悬浮条「已抓 N 个职位」——你**往下滚、翻页**，数字自动涨
3. 想采几个关键词就换关键词继续搜，数字持续累加、自动去重
4. 采够了点悬浮条上的 **「导出JSON」** → 文件存到 `~/Downloads/boss-jobs-<时间>.json`

## 入库（交给工具）

```bash
cd /Users/lcc/job-copilot
PYTHONPATH=src .venv/bin/python -m job_copilot collect import
```

默认自动扫 `~/Downloads` 里所有 `boss-jobs-*.json`，规整、去重、入库，处理完归档到 `data/imports/processed/`。
也可指定路径：`collect import ~/Downloads/boss-jobs-xxx.json`

入库后告诉我「导入完了」，我接着做清洗和深圳 AI Agent 岗市场画像。

## 建议采集量

首轮市场画像，建议每个意向关键词翻 5-10 页（合计 200-400 条），就足够算薪资分布（P10/P50/P90）和技能词频了。不用贪多。
