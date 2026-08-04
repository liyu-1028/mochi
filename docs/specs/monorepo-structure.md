# Monorepo 结构规范

> 状态：已落地骨架 · 最后更新 2026-08-03
> 参照项目：同类项目 AIRI（moeru-ai/airi）的 Monorepo 实践；Turborepo 的 Python 支持
> 目前仍为实验特性（不自动维护 uv.lock、仅支持根级 workspace），故暂不引入。

## 1. 技术栈基线

| 层            | 选型                                                             | 版本基线                                                     |
| ------------- | ---------------------------------------------------------------- | ------------------------------------------------------------ |
| 桌面壳        | Tauri v2（Rust）                                                 | tauri ^2 · Rust 1.97.1（rust-toolchain.toml 固定）           |
| 前端          | React + TypeScript + Vite                                        | react ^19 / vite ^6 · Node 20.x（.nvmrc 固定）               |
| 后端 sidecar  | Python + FastAPI（M0 引入 LangGraph）                            | Python 3.12（server/.python-version 固定；允许 ≥3.11,<3.14） |
| JS 包管理     | pnpm workspaces                                                  | pnpm 10.8.1（packageManager 字段固定）                       |
| Python 包管理 | uv                                                               | ≥0.12（CI 固定 0.12.1）                                      |
| 构建编排      | 暂不引入 Turborepo（其 Python 支持为实验性，见调研报告 §风险 2） | —                                                            |

## 2. 目录结构

```text
mochi/
├── apps/
│   └── desktop/                # @mochi/desktop —— Tauri 桌面壳（唯一 app）
│       ├── src/                # React 前端源码（角色渲染、对话面板、设置）
│       ├── src-tauri/          # Rust 壳（托盘、窗口、sidecar 生命周期）
│       ├── index.html
│       ├── vite.config.ts
│       └── package.json
├── packages/
│   └── protocol/               # @mochi/protocol —— 事件协议 TS 事实源 + 黄金样例
├── server/                     # mochi-server —— Python sidecar（uv 工程，独立于 pnpm）
│   ├── src/mochi_server/
│   ├── config.example.toml
│   └── pyproject.toml
├── assets/                     # 角色资产（许可与代码隔离，见 LICENSE-Live2D.md）
│   └── skins/                  # 内置皮肤包（每个皮肤一个目录 + skin.json）
├── docs/                       # 全部规范与文档
│   ├── adr/                    # 架构决策记录
│   ├── protocol/               # 协议规范
│   ├── research/               # 调研报告
│   └── specs/                  # 工程规范（本目录）
├── .husky/                     # Git 钩子（commit-msg / pre-commit）
├── eslint.config.js            # 根级 ESLint flat config
├── commitlint.config.js
├── pnpm-workspace.yaml
└── package.json                # 根脚本 + lint-staged 配置
```

## 3. 工作区职责与依赖规则

1. `packages/protocol` 是**前端侧协议唯一事实源**，只能被依赖、不得依赖任何内部包。
2. `apps/desktop` 通过 `workspace:*` 依赖 `@mochi/protocol`；事件类型一律从协议包导入，
   禁止在业务代码中散落事件名字符串字面量（review 红线）。
3. `server/` 与 pnpm workspace **互相独立**（两套工具链并行，CI 中分别执行）。
4. 新增 workspace：前端包放 `packages/`，命名 `@mochi/<name>`；
   Python 包纳入 `server/` 的 uv workspace（如未来拆分 `server/packages/*`）。
5. `assets/` 只能被打包脚本引用，源码不得硬编码资产绝对路径。

## 4. 协议双端一致性规则

`packages/protocol/src/index.ts`（TS）与 `server/src/mochi_server/events.py`（Python）
为人工镜像。约束：

- 任何协议变更必须**同一提交**内同时修改两侧 + 协议文档（commit scope 用 `protocol`）。
- 黄金样例 `packages/protocol/testdata/*.jsonl` 作为双端解析测试的共享夹具
  （M0 落地：Python 侧 pytest 逐行解析、TS 侧 vitest 类型校验）——这是「改了协议不提心吊胆」的保险丝。

## 5. 常用命令

| 命令                   | 说明                                               |
| ---------------------- | -------------------------------------------------- |
| `pnpm install`         | 安装 JS 依赖并激活 husky 钩子                      |
| `pnpm dev`             | 启动 Tauri 桌面应用（开发模式）                    |
| `pnpm dev:web`         | 仅启动前端 Vite（浏览器调试 UI）                   |
| `pnpm dev:server`      | 启动 Python sidecar（uvicorn --reload，端口 8199） |
| `pnpm lint`            | ESLint + Ruff 检查                                 |
| `pnpm format`          | Prettier + Ruff format                             |
| `pnpm typecheck`       | 全工作区 tsc --noEmit                              |
| `cd server && uv sync` | 安装 Python 依赖                                   |

## 6. Rust/桌面壳约定

- Rust 代码风格交给 `cargo fmt`（rustfmt 默认），不另设规则；CI 加 `cargo clippy`（M0）。
- Release profile 已配置体积优化（`lto`、`opt-level="s"`、`strip`），勿随意回退。
- Tauri capabilities 遵循最小权限：新增插件必须在 `capabilities/default.json`
  显式授权并在此文档登记理由。

## 7. sidecar 分发策略（M0-S4 定案）

- 开发模式：`uv run` 直接跑源码（lib.rs dev 分支自动拉起）。
- 发布模式：**PyInstaller onedir + noarchive**（冷启动达标，选型对比见
  ADR-0004），由 `scripts/package-sidecar.sh` 构建并经 `bundle.resources`
  打进安装包（`$RESOURCE/sidecar/`），Rust 侧 `sidecar.rs` release 分支
  spawn + 监督重启 + 状态事件。
- 发布链路约束：PyInstaller 不支持交叉编译 → 各平台在对应 CI runner 现机构建
  （.github/workflows/release.yml 矩阵）。
- 待办（M1）：macOS 签名 + 公证、Windows 代码签名、runtime.json 端口发现。

## 8. 版本政策

- 应用版本（`tauri.conf.json` + 各 package.json 的 `version`）遵循 SemVer，发布前统一对齐。
- **协议版本**（`PROTOCOL_VERSION`）与 **skin.json manifest 版本**独立演进，
  不与应用版本绑定（见 docs/protocol/agent-events-v0.1.md §9）。
- **依赖可复现**：三端锁文件（`pnpm-lock.yaml` / `server/uv.lock` /
  `Cargo.lock`）必须入库；CI 一律 frozen 安装（`--frozen-lockfile` /
  `uv sync --frozen` / `cargo --locked`）。manifest（package.json /
  pyproject.toml / Cargo.toml）保留语义化区间以便升级，精确版本以锁文件为准。
- **工具链固定**：Node 由 `.nvmrc`、pnpm 由 `packageManager` 字段、Rust 由
  `rust-toolchain.toml`（CI 的 dtolnay/rust-toolchain 引用需同步）、Python 由
  `server/.python-version`、uv 由 CI `setup-uv.version` 固定。升级任一项时
  同步更新对应文件、CI 工作流与 README「开发环境准备」表，并全量跑一次测试。
