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
