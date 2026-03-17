# Paper Digest Platform

这是基于当前 `paper_digest_agent.py` 扩展的前后端项目。

## 功能覆盖

- 注册：邮箱验证码校验后完成注册
- 登录/退出登录
- 忘记密码：邮箱验证码重置
- 修改每日定时发送时间
- 修改论文关键词
- 修改目标邮箱（SMTP 由系统统一配置）
- 手动测试 SMTP 发信
- 手动触发一次论文推送
- 多用户并发定时推送
- SQLite 持久化用户与配置
- 手动/定时推送新增论文自动入库

## 代码结构

```
paper_digest_platform/
  backend/                # FastAPI + SQLite + Scheduler
  frontend/               # React + TypeScript + Vite
```

详细启动方式见：`paper_digest_platform/backend/README.md`

## 前端技术栈

- React 18
- TypeScript
- Vite
