> 当前 VRM 实现（2026-10-09）：仅播放原始 VRMA 文件。Mochi 本机版本已将用户选定的六个文件纳入角色内置动作包，用户继续导入到「我的动作」。内置条目带角色 id，与旧导入记录合并；署名和原始素材保留。具体使用流程见 [vrma-import-workflow.md](vrma-import-workflow.md)。以下为早期格式草案。

# motion-pack 动作包规范（v2 草案，P2 实施）

> 状态：**草案**——随 vrm-rendering-rollout-plan P2.3 实现定稿；定稿前字段可能调整，
> 调整时升版本号并在变更记录登记。
> 关联：ADR-0011（crafted 动作资产管线）、ADR-0006（皮肤系统——本规范复用其
> manifest/校验/导入模式）、docs/specs/skin-manifest-format.md（skin.json；
> v4 将增 `resourceType: "vrm"`）、docs/protocol/agent-events-v0.1.md §11（语义词表）、
> docs/internal/vrm-rendering-rollout-plan.md（P2/P4 批次）
> 服务端模型（实施时落）：`server/src/mochi_server/skin/motion_pack.py`；
> 前端解析（实施时落）：`apps/desktop/src/character/`（motionPackRegistry）

动作包 = 一个目录，内含 `pack.json` 清单 + 动画资产文件。**动作包独立于皮肤分发**：
一个包内的动作服务所有 VRM 模型（骨骼经 VRM normalized 人形骨架归一化，与具体
模型无关）；皮肤亦可自带动作（skin.json `actions` 引用，见 §5）。

设计原则（ADR-0011 D1/D5）：

1. 骨骼大动作唯一来源是 crafted 资产（VRMA / glb），程序化只做微动作层；
2. `agentSelectable` 白名单铁律：仅显式声明 true 的动作可被 LLM 选择，
   服务端 cue 生成处强校验；
3. 动作 id 双命名空间：官方语义词表 id（进协议，可被 LLM 选）与 `ext.*`
   社区扩展 id（不进协议，皮肤/用户显式引用）。

## 目录与 id

- 动作包 id：`^[a-z0-9][a-z0-9-]{0,31}$`（与皮肤 id 同 pattern，目录名安全）；
- 用户动作包位于 `<userData>/motion-packs/<id>/`，经 `POST /skins/import-motion-pack`
  （zip）导入（端点沿用 G4 动作扩展包先例，扩展包格式升级为本规范）；
- 动作 id：官方词表 id（snake_case，`SEMANTIC_ACTIONS` ∪ `LOCOMOTION_ACTIONS`）或
  `ext.<namespace>.<name>`（namespace 2–16 位 `[a-z0-9-]`，name 同动作 id pattern）；
  清单内唯一，跨包冲突以导入顺序后者拒绝（409）。

## 资产格式（motions/ 目录）

| 格式       | 扩展名  | 说明                                                                                                               |
| ---------- | ------- | ------------------------------------------------------------------------------------------------------------------ |
| VRMA       | `.vrma` | **唯一收包格式**（VRM Animation 标准，glb 容器）。Blender VRM Add-on 可直接导出；加载层为自研薄解析（ADR-0011 D4） |
| Mixamo FBX | `.fbx`  | **不直接进包**——经官方转换工具 `mochi:motion-convert`（retarget 管线 CLI，P2.2）重定向导出为 `.vrma` 后入包        |
| glb 直导   | `.glb`  | 接受轨道名 = VRM humanoid bone name 的直导 glb（与 VRMA 轨道约定同构）                                             |

资产要求（导入校验 + `mochi:motion-lint` CLI 双重把关）：

- **骨骼覆盖**：必需骨骼（VRM `VRMRequiredHumanBoneName` 集合）轨道存在才可注册为
  `kind: "oneshot"` 全身动作；仅上半身轨道的动作须声明 `upperBodyOnly: true`
  （调度时与 locomotion 共存的依据）；
- **首尾帧对齐**：one-shot 动作首尾帧与 stance 姿态偏差在阈值内（lint 报 warning，
  超限 error——防 crossfade 跳变；达不到时提供 `entryAlignMs`/`exitAlignMs` 淡入
  淡出参数补偿）；
- **时长一致**：`durationMs` 与 clip 实际时长偏差 ≤10%（调度窗口准确性）。

## pack.json 字段（camelCase）

### 包级

| 字段         | 类型                   | 必填           | 说明                                                               |
| ------------ | ---------------------- | -------------- | ------------------------------------------------------------------ |
| `format`     | `"vrm-motion-pack/v2"` | ✅             | 格式版本                                                           |
| `id`         | string                 | ✅             | 包 id（pattern 见上）                                              |
| `name`       | string                 | ✅             | 展示名                                                             |
| `version`    | string                 | 默认 `"1.0.0"` | SemVer                                                             |
| `author`     | string                 | ✅             | 作者（生态署名）                                                   |
| `license`    | string                 | ✅             | 资产授权（SPDX 标识或 URL；含 Mixamo 来源的标注 `mixamo-convert`） |
| `targetSkin` | string \| null         | 默认 null      | null = 通用包；指定则仅对该皮肤生效（G4 兼容字段）                 |
| `motions`    | MotionEntry[]          | ✅             | 动作清单，≥1 项                                                    |

### MotionEntry（动作级）

| 字段                           | 类型                     | 默认       | 说明                                                                                                                                                                |
| ------------------------------ | ------------------------ | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                           | string                   | ✅         | 官方词表 id 或 `ext.*`（pattern 见上）；包内唯一                                                                                                                    |
| `asset`                        | string                   | ✅         | 资产文件相对包目录路径（motions/ 下）                                                                                                                               |
| `kind`                         | `"oneshot" \| "loop"`    | `oneshot`  | loop 持续到被打断（idle/walk 类）                                                                                                                                   |
| `channels`                     | string[]                 | `["body"]` | ⊆ `face/body/locomotion/voice/effect`（协议 §11 `ACTION_CHANNELS`）                                                                                                 |
| `upperBodyOnly`                | bool                     | false      | 仅上半身轨道（可与 locomotion 叠加）                                                                                                                                |
| `priority`                     | int 0–100                | 50         | 沿用 actionDirector 调度语义                                                                                                                                        |
| `interruptPolicy`              | `replace\|queue\|ignore` | `replace`  | 冲突策略                                                                                                                                                            |
| `cooldownMs`                   | int ≥0                   | 0          | 动作冷却                                                                                                                                                            |
| `durationMs`                   | int 1–30000              | null       | 动作占位窗口；缺省用 clip 实际时长                                                                                                                                  |
| `entryAlignMs` / `exitAlignMs` | int 0–1000               | 200        | 进/出 stance 的 crossfade 时长                                                                                                                                      |
| `agentSelectable`              | bool                     | **false**  | 白名单铁律：仅 true 可被 LLM 选择                                                                                                                                   |
| `fallback`                     | string                   | null       | 降级目标：词表内动作或其他已注册动作 id；官方词表内动作不得以 `ext.*` 为 fallback                                                                                   |
| `tags`                         | string[]                 | `[]`       | 行为池标签：`idle`（闲置轮换池）/ `reminder`（久坐提醒池）/ `greeting` 等；官方标签集随 P3 扩展                                                                     |
| `expression`                   | object                   | null       | 同步表情：`{preset: string, intensity: 0–1, startMs?, endMs?}`；preset 须为目标模型表情预设或 VRM 标准预设（happy/sad/angry/relaxed/surprised），非标准模型自动跳过 |
| `voice`                        | object                   | null       | 同步音效（effect 通道）：`{file, volume, startMs}`                                                                                                                  |

## 校验规则（服务端 pydantic + 前端导入双重）

1. 结构：上表字段类型/pattern/枚举值；`agentSelectable: true` 且 id 为 `ext.*` 的
   动作**禁止**（ext 动作不可被 LLM 选择——命名空间与白名单双闸）；
2. 引用完整性：`asset` 文件存在、`fallback` 可解析（同包 / 词表 / 已注册集合）；
3. 骨骼覆盖与首尾对齐：见「资产要求」——服务端只验结构，资产内容校验在导入时
   前端跑（服务端不解析动画二进制，与 skin.json「服务端只验结构」口径一致）；
4. 冲突：动作 id 与既有注册集合冲突时整包拒绝（409），提示改名；
5. 畸形包：给可读拒绝文案，不抛裸异常（与 static 皮肤类型下线先例同 UX）。

## 与 skin.json 的关系

- VRM 皮肤：skin.json v4 增 `resourceType: "vrm"`（`modelFile` 指 .vrm），`actions`
  字段复用 G3 结构但绑定字段换为 `{motionPack: "<packId>#<motionId>"}` 或
  `expression`（表情直配）；缺 `actions` = 该皮肤仅默认动作集；
- 能力聚合：cue 提示词能力注入 = 皮肤自带动作 ∪ 已启用动作包中
  `agentSelectable: true` 的动作（P4.4）；`cue_prompt_section` 机制不变；
- 官方词表动作的多来源解析顺序：皮肤声明 > 动作包（后导入优先）> 内置默认
  （P2 官方包）> fallback 链收敛 `idle_neutral`。

## 许可与登记

- 入库资产（官方包/默认皮肤模型）在资产许可登记文件登记来源与许可
  （commit-convention §5 例外流程）；
- 社区包分发不经过本仓库，`license` 字段必填即合规底线；
- Mixamo 转换资产：`license` 标 `mixamo-convert`，导出工具自动写入来源标注。

## 示例

```jsonc
{
  "format": "vrm-motion-pack/v2",
  "id": "mochi-official-gestures",
  "name": "Mochi 官方手势动作包",
  "version": "1.0.0",
  "author": "mochi",
  "license": "CC0-1.0",
  "targetSkin": null,
  "motions": [
    {
      "id": "wave",
      "asset": "motions/wave.vrma",
      "kind": "oneshot",
      "channels": ["body"],
      "priority": 40,
      "cooldownMs": 4000,
      "durationMs": 2200,
      "entryAlignMs": 200,
      "exitAlignMs": 300,
      "agentSelectable": true,
      "tags": ["greeting"],
      "expression": { "preset": "happy", "intensity": 0.6 },
    },
    {
      "id": "ext.demo.stretch_desk",
      "asset": "motions/stretch_desk.vrma",
      "kind": "oneshot",
      "upperBodyOnly": true,
      "agentSelectable": false,
      "tags": ["idle"],
    },
  ],
}
```

## 变更记录

| 版本    | 日期       | 变更                                                    |
| ------- | ---------- | ------------------------------------------------------- |
| v2 草案 | 2026-10-04 | 首稿（ADR-0011 立项时落；G4 动作扩展包格式的 VRM 后继） |
