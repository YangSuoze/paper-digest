# Frontend (React + TypeScript)

## 安装依赖

```bash
npm install
```

## 本地开发

```bash
npm run dev
```

开发模式下已配置代理：`/api/* -> http://127.0.0.1:8000`

因此请确保后端先启动在 `8000` 端口。

## 生产构建

```bash
npm run build
```

构建产物输出到 `dist/`，后端会挂载 `dist/index.html` 和 `dist/assets/`。

说明：前端仅维护用户级的目标邮箱、关键词、定时设置；SMTP 由后端环境变量统一配置。

控制台支持查看：

- 最近执行日志
- 最近入库论文记录（来自 `/api/v1/push/papers`）
