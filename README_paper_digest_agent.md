# 每日论文推送 Agent

这个 Agent 会每天自动检索并邮件推送论文，支持 arXiv / Crossref / PubMed / IEEE Xplore，并可选调用 LLM 生成中文解读。

## 1) 当前默认策略（已生效）

- 每天最多推送 `5` 篇（`search.max_total_papers`）。
- 每天只允许正式发送 `1` 次（`state.single_push_per_day=true`）。
- 如果当天已经成功发送，再次触发任务会直接跳过，避免重复推送和误消耗去重配额。
- 定时任务时间：每天 `09:30`（任务名 `PaperDigestDaily`）。
- 任务要求联网才执行：`RunOnlyIfNetworkAvailable=True`。
- 若错过计划时点，条件满足后会补跑：`StartWhenAvailable=True`。

## 2) 配置文件

主配置文件：`paper_digest_config.json`

重点字段：

- `search.max_total_papers`: 每次推送篇数上限（当前 5）。
- `search.keywords`: 检索关键词列表。
- `llm.max_summaries`: LLM 解读数量上限（当前 5）。
- `state.dedupe_start_date`: 去重生效日期。
- `state.single_push_per_day`: 每天仅发送一次开关（建议保持 true）。

## 3) 常用命令

进入项目目录：

```powershell
cd "D:\OneDrive - The Hong Kong Polytechnic University\python_project"
```

手动正式执行（会发邮件）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_paper_digest.ps1
```

手动测试（不发邮件）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_paper_digest.ps1 -DryRun
```

重新设置自动任务时间（会覆盖同名任务）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_daily_digest_task.ps1 -StartDate 2026/03/01 -StartTime 09:30
```

## 4) 自动任务行为说明

当前任务配置（`PaperDigestDaily`）：

- `Trigger`: Daily `09:30`
- `RunOnlyIfNetworkAvailable=True`
- `StartWhenAvailable=True`
- `MultipleInstances=IgnoreNew`
- `RestartCount=3`，`RestartInterval=30min`

实际行为：

- 到点时已开机、已登录、已联网：按时运行。
- 到点未开机或未联网：满足条件后会补跑。
- 同一天多次开关机：不会并发重复跑；且脚本层面也会阻止当天第二次正式发送。
- 自动任务不需要打开 VS Code；只要 Windows 登录该用户会话即可。

## 5) 双击运行说明

- `.ps1` 不建议直接双击（可能打开编辑器或窗口闪退）。
- 鼠标双击推荐用：`run_paper_digest.cmd`。
- 命令行执行推荐用：`run_paper_digest.ps1`（便于看日志输出）。

## 6) 日志位置

- `logs\paper_digest_YYYY-MM-DD.log`
