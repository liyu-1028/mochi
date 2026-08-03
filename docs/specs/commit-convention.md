# Git 与 Commit 规范（个人开发版）

> 状态：已落地（commitlint 强制） · 规范基准：[Conventional Commits 1.0](https://www.conventionalcommits.org/zh-hans/)

## 1. 分支模型（从简）

- **main 单主干**：所有提交最终进入 main，保持随时可发布状态。
- 超过半天的改动开**短生命周期 feature 分支**（如 `feat/skin-import`），完成后并回 main；
  小改动直接提交 main。
- 不使用 git-flow、不维护 develop/release 分支（个人项目成本大于收益）。
- 发布即打 tag：`v0.1.0`（见 §4）。

## 2. 提交信息格式

```text
<type>(<scope>): <subject>

[body 可选：说明动机与上下文]

[BREAKING CHANGE: <说明>]   ← 可选
```

约束（commitlint 强制项标 ★）：

- ★ `type` 取值：`feat` `fix` `docs` `style` `refactor` `perf` `test` `build` `ci` `chore` `revert`
- `scope` 建议取值（告警级）：`desktop` `protocol` `server` `skin` `voice` `docs` `ci` `repo`
- subject 用祈使句、中英文均可、结尾不加句号、≤ 72 字符
- 一次提交只做一件事；协议双端镜像修改必须在同一提交（见 monorepo 规范 §4）

## 3. 示例

```text
feat(protocol): 定义事件协议 v0.1 信封与握手流程
feat(server): 实现 hello 握手与版本协商
fix(desktop): 修复透明窗口在 Windows 上的白边
docs(specs): 补充 sidecar 端口发现机制说明
build(repo): 升级 vite 至 6.3 并锁定 pnpm 版本
test(server): 为黄金样例补充协议解析测试
chore(repo): 更新 .gitignore 排除 pytest 缓存

BREAKING CHANGE(protocol): state.change 携带原因字段，不兼容 0.1 客户端
```

## 4. 版本与 tag

- tag 格式 `v<major>.<minor>.<patch>`，与 `tauri.conf.json` 的 `version` 一致。
- 应用版本遵循 SemVer；**协议版本与 skin.json 版本独立演进**，
  其变更在提交中以 `BREAKING CHANGE(protocol)` / `BREAKING CHANGE(skin)` 显式标注。
- changelog 手写（个人项目足够），发布时归档至 GitHub Release Notes。

## 5. 卫生约定

- 提交前跑 `pnpm lint`（钩子会兜底，但别依赖它）。
- 禁止提交：密钥/Key（任何形式）、`assets/` 中无许可登记的模型、>5MB 的二进制
  （皮肤资产走皮肤包分发，不直接塞仓库——例外需在此文档登记）。
- 回滚用 `git revert`，不改写已推送历史。
