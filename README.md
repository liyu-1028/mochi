# Mochi 🍡

**会成长的桌面智能伙伴** —— 捏出你的专属 AI 伙伴，让智能体拥有温暖的模样。

Mochi 将冰冷的命令行和对话框，升级为有温度、有形象、可陪伴的桌面存在：
前端是灵动鲜活的 Live2D 角色，后端是 LangGraph 驱动的强大认知核心。

> 🚧 当前阶段：规范与骨架已就绪，M0 垂直原型开发即将开始。
> 产品全貌见 [docs/feature-list.md](docs/feature-list.md)。

## 技术栈

| 层         | 选型                                                                 |
| ---------- | -------------------------------------------------------------------- |
| 桌面壳     | Tauri v2（Rust）                                                     |
| 前端       | React 19 + TypeScript + Vite                                         |
| Agent 后端 | Python sidecar（FastAPI + LangGraph）                                |
| 前后端通信 | 本地 WebSocket · [事件协议 v0.1](docs/protocol/agent-events-v0.1.md) |

## 开发环境准备

| 工具    | 要求   | 安装                                                                                                                                |
| ------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| Node.js | ≥20    | `nvm use`（仓库含 .nvmrc）                                                                                                          |
| pnpm    | 10.x   | `npm i -g pnpm`                                                                                                                     |
| Rust    | stable | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh`，另需 [Tauri 平台依赖](https://v2.tauri.app/start/prerequisites/) |
| uv      | 最新   | `curl -LsSf https://astral.sh/uv/install.sh \| sh`                                                                                  |

## 快速开始

```bash
pnpm install                 # JS 依赖 + husky 钩子（postinstall 自动下载 Live2D Core）
cd server && uv sync && cd .. # Python 依赖

./scripts/start.sh            # 一键启动桌面端：Tauri 窗口 + vite + sidecar
./scripts/stop.sh             # 一键停止桌面端（--all 连同 Ollama）
./scripts/start.sh --web-only # 仅启动浏览器侧：vite（1420）+ sidecar（不开窗口）
```

> Live2D Cubism Core 为专有代码不入库，由 `scripts/download-live2d-core.mjs`
> 下载（SHA256 校验）。缺失时角色降级为 emoji 占位，不影响对话功能。

或按需单独启动：

```bash
pnpm dev:server              # sidecar（http://127.0.0.1:8199/health）
pnpm dev:web                 # 前端（http://localhost:1420）
pnpm dev                     # Tauri 桌面应用（开发模式，需 Rust 环境）
```

代码检查：`pnpm lint` · `pnpm typecheck` · `pnpm format`

## 文档索引

| 文档                                                                     | 内容                                 |
| ------------------------------------------------------------------------ | ------------------------------------ |
| [docs/feature-list.md](docs/feature-list.md)                             | 功能清单（模块 × 优先级 × 验收标准） |
| [docs/protocol/agent-events-v0.1.md](docs/protocol/agent-events-v0.1.md) | Agent 事件协议 v0.1                  |
| [docs/specs/monorepo-structure.md](docs/specs/monorepo-structure.md)     | 仓库结构与工作区规则                 |
| [docs/specs/code-style.md](docs/specs/code-style.md)                     | 代码规范与提交钩子                   |
| [docs/specs/commit-convention.md](docs/specs/commit-convention.md)       | Git 与 Commit 规范                   |
| [docs/specs/config-format.md](docs/specs/config-format.md)               | 用户配置格式规范                     |

## 许可证

- **源代码**：[MIT](LICENSE)
- **角色资产**（`assets/`）：独立许可，见 [LICENSE-Live2D.md](LICENSE-Live2D.md) ——
  Live2D 相关资产遵循 Live2D Inc. 的授权条款，不在 MIT 覆盖范围内。
