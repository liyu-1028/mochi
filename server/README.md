# mochi-server

Mochi 的本地 Agent sidecar（Python）。M0 阶段职责：

- 通过 WebSocket 向前端推送标准事件流（协议 v0.1，见 `docs/protocol/agent-events-v0.1.md`）
- 拥有用户配置（`config.toml`）的读写权（规范见 `docs/specs/config-format.md`）
- M0 引入 LangGraph 认知核心与工具调用框架

## 开发

```bash
uv sync          # 安装依赖（含 dev 组）
uv run ruff check . && uv run ruff format .
uv run uvicorn mochi_server.main:app --reload --port 8199
```

## 结构

```
src/mochi_server/
├── main.py       # FastAPI 入口（/health + /ws）
├── events.py     # 协议 v0.1 事件模型（与 packages/protocol 保持镜像一致）
└── config.py     # 配置 schema（pydantic），见 docs/specs/config-format.md
```
