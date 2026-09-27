# 配置格式规范

> 状态：schema 骨架已落地（`server/src/mochi_server/config.py` + `server/config.example.toml`）
> 原则：Zero Config（功能清单 1.5）—— 缺省值必须能跑通全链路；用户不写配置也能用。

## 1. 基本决策

| 项       | 决策                                                                   | 理由                                                                  |
| -------- | ---------------------------------------------------------------------- | --------------------------------------------------------------------- |
| 格式     | **TOML**                                                               | 支持注释、人类可编辑；Python 标准库 `tomllib` 原生读取；Rust 生态成熟 |
| 文件位置 | `<userData>/config.toml`（各 OS 用户数据目录，经 Tauri path API 解析） | 不污染安装目录；macOS/Windows 权限友好                                |
| 事实源   | **sidecar 独占读写**；前端经 RPC 访问，不直接操作文件                  | 避免双写竞争；配置变更事件可由 sidecar 统一广播                       |
| 校验     | pydantic 模型（`config.py`）；前端如需镜像用 zod（M1 评估）            | 边界数据必须过模型（代码规范 §3）                                     |
| 敏感信息 | **API Key 永不落配置文件**，只存 `key_ref`（系统钥匙串条目名）         | 安全红线（功能清单 7.2）                                              |

## 2. 文件结构

```toml
config_version = 2            # schema 版本，迁移依据（§4）

[general]                     # 语言 / 自启 / 遥测 / 省电模式
[character]                   # 当前皮肤等角色偏好
[model]                       # default_profile + connections + profiles
[voice]                       # TTS 引擎 / 音色 / 音量 / 静音
[privacy]                     # local_only 隐私模式
[skills]                      # 已启用技能 id 列表
[tools]                       # dangerous 工具「总是允许」白名单（6.5）
[agent]                       # 情绪推断开关等 Agent 行为
[memory]                      # 记忆自动沉淀开关与上限
```

完整示例与字段注释见 `server/config.example.toml`。

模型配置拆成三个层次：

- `preset_id` 是内置厂商目录项，提供推荐协议、默认 Base URL 和认证方式；
- `[model.connections.<id>]` 表示一个账号或本地服务，持有端点和 `key_ref`；
- `[model.profiles.<id>]` 表示一个可选择的具体模型，引用 connection，并声明
  `protocol`、`model` 与可选 `context_window`。

同一 connection 可以挂多个 profile，共享 Key 和端点；厂商与协议分离，因此同一
厂商可以同时配置 Chat Completions 与 Responses。`context_window` 缺省 8192，
超出预算的历史自动截断并注入省略标记，对用户无感。

## 3. 敏感信息处理

1. `[model.connections.<id>]` 中只允许 `key_ref = "mochi:provider:<id>"`。
2. 真实 Key 存入 OS 钥匙串：macOS Keychain / Windows Credential Manager。
   M0 选型：**Python `keyring` 库（sidecar 侧直连 OS 钥匙串）**——配置事实源在
   sidecar，且 Rust 面保持最小化；候选过的 Rust `keyring` crate /
   tauri-plugin-stronghold 不采用。
3. 日志、遥测、错误上报路径**禁止**序列化 connection 表原文（脱敏规则：只保留 `preset_id`/`protocol`/`model`/`key_ref`）。
4. 「导出配置」（功能清单 7.6）时同样只导出 `key_ref`，导入端需重新授权 Key。

## 4. 版本与迁移

1. 顶层 `config_version` 为 schema 版本号（整数递增，独立于应用 SemVer）。
2. 加载流程：读取 → 版本比对 → 依次执行迁移函数 `migrate_1_to_2`… → pydantic 校验 → 落盘新版本号。
3. 迁移函数必须**幂等**且只增不删（删除字段保留一个版本周期的兼容读取）。
4. 校验失败处理：不覆盖用户文件；将损坏文件备份为 `config.toml.bak-<ts>`，
   以默认配置启动，并在 UI 给出可读提示（功能清单 6.7 同款文案要求）。

## 5. 写入约定

1. **原子写入**：写临时文件 + `os.replace` 落盘，杜绝半截文件。
2. 注释在 TOML 往返后不保留——`config.example.toml` 承担注释文档职责，
   实际文件由程序生成、不鼓励手改（README 文案需引导用户走设置面板）。
3. 写入去抖：UI 连续修改合并为一次落盘（M0 实现时 ≥500ms debounce）。

## 6. 默认配置生成（Zero Config 关键路径）

首次启动且无配置文件时：

1. 探测本地 Ollama（`127.0.0.1:11434/api/tags`）；
2. 探测到 → 生成 Ollama connection + profile 并设为默认（引导向导展示「已发现本地模型」）；
3. 未探测到 → 生成空模型配置，引导向导进入「填 Key / 试用模式」分支（功能清单 1.5）。

v1 的 `[model.providers.*]` 在读取时自动迁移为同名 connection + profile；原有
`key_ref` 不变，所以升级无需重新输入 API Key。

## 7. 前端状态不进入 config.toml

窗口位置、面板开合等纯 UI 状态由 Tauri 壳本地存储（window state 插件），
与用户配置分离——config.toml 只承载「跨会话有意义的用户偏好」。
