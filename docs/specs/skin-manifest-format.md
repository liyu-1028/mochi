> 2026-10-09：默认角色仅 Mochi。装扮管理支持直接导入 VRM 0.x/1.0 文件，自动从模型元数据生成本地清单，原始 VRM 保持不变；ZIP 皮肤包导入继续可用。

# skin.json 清单规范（v2 基线；v3 增 paramEnvelope/durationMs，G3）

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

### `actions` 语义动作注册表（v2，M-A；v3 增补 G3）

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
| `durationMs`      | int 1–10000              | null      | **v3**：动作占位窗口（ms）；缺省用前端默认窗口                                       |

`live2d` 绑定字段：

| 字段            | 类型     | 默认 | 说明                                                         |
| --------------- | -------- | ---- | ------------------------------------------------------------ |
| `motionGroups`  | string[] | `[]` | 偏好有序；取首个模型实际拥有的组                             |
| `expression`    | string   | null | 模型档案含此 exp3 时叠加表情                                 |
| `paramEnvelope` | object   | null | **v3**：声明式参数包络（见下节）；声明后任何 Cubism 模型可演 |

#### `live2d.paramEnvelope` 声明式参数包络（v3，G3）

皮肤作者免 Live2D Editor，用参数关键帧定义动作；前端逐帧插值应用到模型。
播放优先级：`motionGroups` 命中 > `paramEnvelope` > 内置兜底（`actionRegistry`
默认映射的参数包络，如 wink）；畸形声明前端静默回落内置兜底，绝不阻塞渲染。

```json
{
  "id": "custom_wink",
  "channels": ["body"],
  "agentSelectable": true,
  "durationMs": 700,
  "live2d": {
    "paramEnvelope": {
      "durationMs": 700,
      "easing": "smoothstep",
      "keyframes": [
        {
          "param": "ParamEyeLOpen",
          "points": [
            [0, 1],
            [350, 0],
            [700, 1]
          ]
        },
        {
          "param": "ParamMouthForm",
          "points": [
            [0, 0],
            [200, 0.6],
            [700, 0]
          ]
        }
      ]
    }
  }
}
```

| 字段                 | 类型                 | 默认     | 说明                                                       |
| -------------------- | -------------------- | -------- | ---------------------------------------------------------- |
| `durationMs`         | int 1–10000          | ✅       | 包络总时长（ms）                                           |
| `easing`             | `linear\|smoothstep` | `linear` | 段内插值缓动（逐段应用）                                   |
| `keyframes`          | object[]             | ✅ ≥1 项 | 单参数关键帧：`{param, points}`                            |
| `keyframes[].param`  | string               | ✅       | Cubism 参数 id：`^[A-Za-z][A-Za-z0-9_]{0,63}$`，包络内唯一 |
| `keyframes[].points` | `[t, value][]`       | ✅ ≥2 点 | `t` 为 ms 且严格递增、首点 t=0、末点 t=`durationMs`        |

约束（服务端强校验，422 可读文案）：

- 末点时间必须等于 `durationMs`；关键帧时间戳严格递增；
- 值域 ±10000（防数值爆炸；真实物理范围由前端按模型钳制）；
- 参数缺失的模型运行时静默跳过该参数（`getParameterIndex < 0`），
  因此包络声明不参与「动作命中判定」——仅声明包络也视为可演；
- 播放端不信任运行时数据：前端 `compileParamEnvelope` 对畸形声明防御性
  返回 null 并回落内置兜底（服务端校验是第一道门，这是第二道）。

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

## 动作扩展包（G4：给已导入的皮肤追加 motion 动作）

免重新打包整个皮肤，直接向**用户导入的皮肤**追加原创 `motion3.json`
动作（动作扩展方案 M-G 的 L3 层）：`POST /skins/import-motion-pack`
（zip 内含 `pack.json`，根或单层子目录，与 skin.json 同惯例）。

```json
{
  "targetSkin": "live2d-hiyori",
  "name": "hiyori-extra-motions",
  "license": "CC0（原创动作，作者：…）",
  "motions": [{ "group": "MochiWave", "file": "motions/wave.motion3.json" }],
  "actions": [
    {
      "id": "wave_hand",
      "channels": ["body"],
      "agentSelectable": true,
      "live2d": { "motionGroups": ["MochiWave"] }
    }
  ]
}
```

校验与合并规则：

- **仅用户皮肤可扩展**（内置皮肤不可写）；`targetSkin` 不存在即 422；
- **授权红线**：`license` 必填，登记进皮肤 `credits`（键
  `motionPack:<name>`）；动作须为原创资产，不得转载官方/第三方动作；
- motion3.json 结构校验（Cubism 3）：`Version: 3`、`Meta.Duration > 0`、
  `Curves[].Target === "Parameter"`、`Id` 非空、`Segments` 段类型标记合法
  （0/1/2/3）且曲线末点 ≤ Duration。与仓库脚本同口径：
  `node scripts/validate-motion3.mjs <file...>`（资产仓库 CI 用）；
- 组名 / 动作 id 冲突一律 **409 拒绝**（不静默覆盖）；`actions[].live2d.`
  `motionGroups` 引用的组必须在包内声明（包络-only 动作除外）；
- 合并前备份原 `model3.json` / `skin.json`（`*.orig.json`，仅首次保留
  原始状态，可回滚）；合并 `FileReferences.Motions`（新组各挂一条
  `{File}`）、`capabilities.motionGroups` 追加、`actions` 合并；
- zip 大小/条目/zip-slip 防护与皮肤包导入同一套；
- 前端：目标是当前装扮时经 `EVENT_SKIN_CHANGED` 热更；motion 组集合
  变化触发舞台重建后即可播新动作，无需重启。

## 制作建议

- 角色主体尽量占满画布、脚底贴下边（布局按包围盒底边对齐）；
- 授权红线：Live2D 模型的再分发许可须在 `license` 字段与
  `LICENSE-Live2D.md` 登记表说明清楚；
- 横版/超宽模型受角色宽上限（360px）约束，角色会偏矮（既有布局行为）。
