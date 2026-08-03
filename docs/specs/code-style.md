# 代码规范与 Lint/Format（含提交钩子）

> 状态：已落地 · 工具链：ESLint 9 + Prettier（TS/JS）· Ruff（Python）· husky + lint-staged + commitlint

## 1. 总原则

1. **机器能管的一律交给机器**：格式问题零讨论，review 只谈设计与正确性。
2. **钩子报错就修，不要 `--no-verify` 绕过**。确属钩子误报，改配置并记录理由。
3. 个人项目从简：规则集只用「recommended」档位，新增规则必须伴随真实痛点。

## 2. TypeScript / React

| 项     | 配置                                                                             | 文件                 |
| ------ | -------------------------------------------------------------------------------- | -------------------- |
| Lint   | ESLint 9 flat config：`@eslint/js` recommended + `typescript-eslint` recommended | `eslint.config.js`   |
| Format | Prettier：printWidth 100 / 双引号 / 分号 / 尾逗号 all                            | `.prettierrc.json`   |
| 严格度 | `strict: true` + `noUnusedLocals` + `noUnusedParameters`                         | 各包 `tsconfig.json` |

约定：

- 命名：变量/函数 camelCase，类型/组件 PascalCase，常量枚举对象大写蛇形（见 protocol 包）。
- 事件协议常量必须从 `@mochi/protocol` 导入。
- React 组件一律函数式 + hooks；样式方案 M0 再定（骨架用纯 CSS）。
- ESLint 不管格式（无 stylistic 规则），格式分歧以 Prettier 输出为准。

## 3. Python

| 项       | 配置                                                                                                 | 位置                                |
| -------- | ---------------------------------------------------------------------------------------------------- | ----------------------------------- |
| Lint     | Ruff：E/W/F/I/UP/B/SIM/RUF，line-length 100，target py311；豁免 RUF001–003（中文注释天然含全角标点） | `server/pyproject.toml [tool.ruff]` |
| Format   | Ruff format（双引号、空格缩进）                                                                      | 同上                                |
| 导入排序 | isort 规则内置于 Ruff，`mochi_server` 为 first-party                                                 | 同上                                |

约定：

- 全量类型标注（公共函数必须；pydantic 模型字段必须）。
- 边界数据（协议帧、配置、工具入参）一律 pydantic 模型，不用裸 dict 传递。
- `raise NotImplementedError("M0 实现")` 是骨架占位的标准写法，附 TODO 说明。
- 异步优先：sidecar I/O 路径一律 async。

## 4. 提交钩子（husky + lint-staged）

| 钩子         | 动作                                                | 涉及文件                             |
| ------------ | --------------------------------------------------- | ------------------------------------ |
| `pre-commit` | lint-staged：Prettier 格式化 → ESLint 修复          | `*.{ts,tsx,js,mjs,json,md,yaml,yml}` |
| `pre-commit` | lint-staged：`uvx ruff check --fix` + `ruff format` | `server/**/*.py`                     |
| `commit-msg` | commitlint 校验 Conventional Commits                | 提交信息                             |

首次生效前提：`pnpm install`（自动执行 `prepare: husky`）。
Python 侧钩子依赖 `uvx`（随 uv 安装），无需全局安装 ruff。

## 5. 其他语言

- **Rust**：`cargo fmt` + `cargo clippy`（M0 接入 CI），不另行约定。
- **TOML / JSON / Markdown**：交给 Prettier；`assets/` 与 LICENSE 文件已排除。

## 6. CI 预告（M0 落地）

GitHub Actions 每 PR 执行：`pnpm lint` + `pnpm typecheck` + `uv run ruff check` + `cargo clippy`。
发布流水线见 docs/specs/monorepo-structure.md §7（M1 专项调研）。
