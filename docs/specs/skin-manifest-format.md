# skin.json 清单规范 v2（功能清单 3.1）

> 状态：v2（M-A：新增 `actions` 语义动作注册表）；v1（2026-08-06，M1-S1）
> **2026-09-28：`static`（单张图片）资源类型下线移除**——产品决策只保留
> Live2D 及未来扩展的动态类型；内置静态皮肤（pokesprite 三只）与 PNG
> 「图片即皮肤」导入一并移除，应用不再分发任何静态装扮。
> 关联：功能清单 3.1–3.5、docs/internal/adr/0006-skin-manifest.md（本地）、
> docs/protocol/agent-events-v0.1.md §11（语义词表）、
> docs/internal/companion-behavior-rollout-plan.md（M-A）
> 服务端模型：`server/src/mochi_server/skin_manifest.py`；前端类型：`apps/desktop/src/api/skinsClient.ts`；
> 前端解析：`apps/desktop/src/live2d/actionRegistry.ts`

皮肤包 = 一个目录，内含 `skin.json` 清单 + 资源文件。用户皮肤位于
`<userData>/skins/<id>/`，经 `POST /skins/import`（zip）或手动放置目录
（读时扫描即时可见）进入。应用不内置任何皮肤：fresh install 无装扮，
需导入 Live2D 皮肤包后才可渲染（加载失败/未设置降级为占位形象）。

## 目录与 id

- 皮肤 id：`^[a-z0-9][a-z0-9-]{0,31}$`（目录名安全）；
- 用户皮肤经 `POST /skins/import`（仅 zip 皮肤包）或手动放置目录。

## 字段（camelCase；缺字段给默认值，向后兼容 M0-S3 最小清单）

| 字段            | 类型         | 必填           | 说明                                                                         |
| --------------- | ------------ | -------------- | ---------------------------------------------------------------------------- |
| `id`            | string       | ✅             | 皮肤 id（pattern 见上）                                                      |
| `name`          | string       | ✅             | 展示名                                                                       |
| `version`       | string       | 默认 `"1.0.0"` | SemVer                                                                       |
| `resourceType`  | `"live2d"`   | ✅             | 资源类型（`"static"` 已下线，导入时给出可读拒绝文案）                        |
| `license`       | string       | 默认 `""`      | 授权说明                                                                     |
| `cubismVersion` | int          | 可选           | Cubism 主版本（当前 3）                                                      |
| `modelFile`     | string       | ✅             | 模型入口（相对皮肤目录）                                                     |
| `capabilities`  | object       | 默认空         | `{motionGroups: string[], expressions: string[]}`，前端状态机据此选动作/表情 |
| `actions`       | SkinAction[] | 默认空（v2）   | 语义动作注册表，见下节；缺字段 = v1 行为，完全向后兼容                       |
| `credits`       | object       | 默认空         | 致谢（`model` 等自由键）                                                     |

### `actions` 语义动作注册表（v2，M-A）

皮肤声明自己支持的语义动作与实现绑定；前端 ActionRegistry 据此解析，未实现的沿
`fallback` 链降级到 `idle_neutral`（全链路兜底终点，协议规范 §11）。动作 id 从
语义词表 `SEMANTIC_ACTIONS`（12 项）取，或自定义 snake_case id（自定义 id 不可被
LLM 选择，除非 `agentSelectable: true`——白名单铁律在服务端 cue 生成处强制）。

| 字段              | 类型                     | 默认      | 说明                                                                                 |
| ----------------- | ------------------------ | --------- | ------------------------------------------------------------------------------------ |
| `id`              | string                   | ✅        | snake_case：`^[a-z][a-z0-9_]{0,47}$`；清单内唯一                                     |
| `kind`            | `"oneshot" \| "loop"`    | `oneshot` | loop 动作持续到被打断                                                                |
| `channels`        | string[]                 | `[]`      | ⊆ `face/body/locomotion/voice/effect`（协议 §11 `ACTION_CHANNELS`）；空 = 由绑定推断 |
| `live2d`          | object                   | ✅        | `{motionGroups: string[], expression?: string}`；按偏好取首个模型实际拥有的组        |
| `priority`        | int 0–100                | 50        | 越高越优先（调度语义 M-B 生效）                                                      |
| `interruptPolicy` | `replace\|queue\|ignore` | `replace` | 冲突策略（M-B 生效）                                                                 |
| `cooldownMs`      | int ≥0                   | 0         | 动作冷却                                                                             |
| `agentSelectable` | bool                     | **false** | 白名单铁律：仅 true 可被 LLM 选择                                                    |
| `fallback`        | string                   | null      | 降级目标：同清单其他动作 id 或语义词表内动作；`idle_neutral` 自身不得声明 fallback   |

约束（服务端校验，422 可读文案）：

- 每个动作必须有 `live2d` 实现绑定；
- `channels` 不得含未知通道；
- `fallback` 引用必须可解析（同清单 id 或 `SEMANTIC_ACTIONS` 成员），且不得成环；
- `live2d.motionGroups` 是否真实存在于模型由**前端加载时判**（服务端不解析 model3.json）；
  全缺时该动作视为未命中，沿 fallback 继续；`expression` 不在模型档案时静默置空。

清单无 `actions` 字段的旧版导入皮肤：前端按模型通用动作组
（Tap/Flick 系列，`actionRegistry.DEFAULT_LIVE2D_ACTIONS`）给全词表可解析的
默认映射；`stretch`/`doze` 无通用诚实实现 → 直接降级 `idle_neutral`。

### `capabilities`（live2d）

`motionGroups` 须与 model3.json 实际动作组一致（状态机按偏好表挑选，缺失回退
首个可用组）；`expressions` 列出 exp3 表情名（情绪命中时优先表情文件，否则
参数预设）。

## 模板：Live2D 皮肤

```json
{
  "id": "my-model",
  "name": "我的模型",
  "version": "1.0.0",
  "resourceType": "live2d",
  "license": "Live2D 示例数据 / 自有版权 / …",
  "cubismVersion": 3,
  "modelFile": "model.model3.json",
  "capabilities": { "motionGroups": ["Idle", "Tap", "Flick"], "expressions": [] },
  "credits": { "model": "…" }
}
```

## 导入校验（3.5）

- 仅接受 zip 皮肤包：`skin.json` 须在根或单层子目录内；清单 pydantic 校验
  （`resourceType: "static"` 给出「静态皮肤类型已下线」可读文案）；
  `modelFile` 资源存在性；逐成员防 zip-slip；≤50MB、≤500 条目；
- `skin_id` 表单覆盖时清单 id 改写为与目录名一致（注册表按清单 id 登记）；
- 错误一律可读文案（422/409），前端直接展示。

## 制作建议

- 角色主体尽量占满画布、脚底贴下边（布局按包围盒底边对齐）；
- 授权红线：Live2D 模型的再分发许可须在 `license` 字段与
  `LICENSE-Live2D.md` 登记表说明清楚；
- 横版/超宽模型受角色宽上限（360px）约束，角色会偏矮（既有布局行为）。
