# Paper Digest Platform (Backend)

基于 `paper_digest_agent.py` 的多用户推送后端，提供：

- 邮箱验证码注册 + 登录 + 忘记密码
- 每用户目标邮箱/关键词/定时配置
- 手动测试邮件发送
- 手动触发论文推送
- SQLite 持久化配置与执行日志
- APScheduler 多用户并发调度

## 目录

```
backend/
  paper_digest_agent.py      # 兼容入口（薄封装）
  app/
    main.py
    paper_digest/            # 论文推送领域模块
      core_utils.py          # 通用工具与状态处理
      sources_and_llm.py     # 多源检索与 LLM 处理
      rendering.py           # 日报/周报内容渲染与邮件发送
      workflow.py            # run_once / CLI 流程入口
      legacy_agent.py        # 兼容聚合入口（保留旧导入路径）
      runner.py              # 平台统一调用入口
    api/
    core/
    db/
    schemas/
    services/
```

## 快速启动

1. 创建并激活虚拟环境

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

2. 安装依赖

```bash
pip install -r requirements.txt
```

3. 配置环境变量

```bash
cp .env.example .env
```

请至少配置系统 SMTP（同时用于验证码与论文推送）：

- `VERIFY_SMTP_HOST`
- `VERIFY_SMTP_PORT`
- `VERIFY_SMTP_USERNAME`
- `VERIFY_SMTP_PASSWORD`
- `VERIFY_SMTP_FROM_EMAIL`

4. 构建前端（React + TypeScript）

```bash
cd ../frontend
npm install
npm run build
cd ../backend
```

5. 启动服务（在 `paper_digest_platform/backend` 下执行）

```bash
lsof -i:8000 | grep LISTEN | awk '{print $2}' | xargs kill -9
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
nohup uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
nohup gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --timeout 300 --bind 0.0.0.0:8000 > backend.log 2>&1 &
```

访问：`http://127.0.0.1:8000/`

如果提示 `frontend build not found`，请确认已在 `paper_digest_platform/frontend` 执行 `npm run build`。

## 前端开发模式

如需独立调试前端：

```bash
cd paper_digest_platform/frontend
npm install
npm run dev
```

Vite 默认地址：`http://127.0.0.1:5173/`

## 与原脚本集成

后端会按用户配置在内存中动态构造运行参数，并写入临时配置文件调用
`app.paper_digest.runner.run_once(...)` 完成真实推送。

说明：`backend/paper_digest_agent.py` 仅保留兼容入口；核心实现已迁移到
`app/paper_digest/` 多模块，`legacy_agent.py` 仅作为聚合兼容层。

说明：手动“立即执行一次推送”不再依赖固定的 `paper_digest_config.json`；
关键词优先使用前端传入配置，去重状态与推送历史持久化在 SQLite（`user_digest_state` 表）中。

补充：`POST /api/v1/push/run-now` 支持在请求体中传入 `keywords`，本次手动执行会优先使用该关键词列表。

## 论文检索可靠性

论文推送现在使用来源隔离的检索流水线，按用户关键词同时查询 arXiv、Crossref、PubMed、OpenAlex 和 Semantic Scholar。单个来源失败、超时或返回空结果不会阻断其他来源；每次运行都会记录原始候选数、关键词过滤后数量、本轮去重后数量、历史去重后数量、相关性过滤后数量和最终投递数量。

定时任务不再只依赖固定回溯天数。系统会根据 `user_digest_state` 中的上次成功检索窗口和失败标记计算有上限的补偿窗口，用于覆盖漏跑或失败后的时间段，同时继续用 DOI、PMID、arXiv ID 和归一化标题指纹抑制重复论文。

诊断信息会写入 `dispatch_logs.diagnostics_json`，最近一次运行诊断会保存在 `user_digest_state.last_search_diagnostics`。前端的手动任务状态、执行日志和论文记录会展示来源状态、过滤计数、零结果解释和论文来源 provenance。

## 并发推送

- 每个用户有独立定时任务（APScheduler）
- 同时触发时由 `DISPATCH_MAX_CONCURRENCY` 控制并发度
- 执行结果写入 `dispatch_logs` 表，并可前端查询

## 日志

- 控制台输出 + 文件滚动日志同时开启
- 默认日志文件：`paper_digest_platform/runtime/logs/backend.log`
- 可通过环境变量调整：`LOG_LEVEL`、`LOG_FILE`、`LOG_MAX_BYTES`、`LOG_BACKUP_COUNT`

## 数据库存储

SQLite 表：

- `users`
- `email_codes`
- `user_settings`
- `user_sessions`
- `dispatch_logs`
- `paper_records`（保存每次推送新增论文记录）
- `user_digest_state`（保存去重状态与推送历史）

数据库路径默认：`paper_digest_platform/runtime/paper_digest_platform.db`

新增字段通过启动时的兼容迁移补齐：

- `dispatch_logs.diagnostics_json`：保存本次检索诊断
- `paper_records.source_provenance_json`：保存论文命中的全部来源

现有用户配置、论文记录和摘要状态不会被清空；设置保存只更新用户配置字段，论文入库使用 `INSERT OR IGNORE`，摘要状态保存会合并为同一用户的一条 JSON 状态记录。
