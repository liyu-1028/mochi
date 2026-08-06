# skin.json 清单规范 v1（功能清单 3.1）

> 状态：v1（2026-08-06，M1-S1）
> 关联：功能清单 3.1–3.5、docs/internal/adr/0006-skin-manifest.md（本地）
> 服务端模型：`server/src/mochi_server/skin_manifest.py`；前端类型：`apps/desktop/src/api/skinsClient.ts`

皮肤包 = 一个目录，内含 `skin.json` 清单 + 资源文件。内置皮肤随前端资产分发
（`assets/skins/<id>/` → `dist/skins/<id>/`），用户皮肤位于 `<userData>/skins/<id>/`。

## 目录与 id

- 皮肤 id：`^[a-z0-9][a-z0-9-]{0,31}$`（目录名安全）；
- 内置 id 由服务端常量表登记（`skin/builtin.py`），新增内置皮肤 = 改表 + 加资源目录；
- 用户皮肤经 `POST /skins/import`（PNG / zip）或手动放置目录（读时扫描即时可见）。

## 字段（camelCase；缺字段给默认值，向后兼容 M0-S3 最小清单）

| 字段             | 类型                   | 必填           | 说明                                                                         |
| ---------------- | ---------------------- | -------------- | ---------------------------------------------------------------------------- |
| `id`             | string                 | ✅             | 皮肤 id（pattern 见上）                                                      |
| `name`           | string                 | ✅             | 展示名                                                                       |
| `version`        | string                 | 默认 `"1.0.0"` | SemVer                                                                       |
| `resourceType`   | `"live2d" \| "static"` | ✅             | 资源类型二选一                                                               |
| `license`        | string                 | 默认 `""`      | 授权说明（版权干净是内置皮肤红线）                                           |
| `cubismVersion`  | int                    | live2d         | Cubism 主版本（当前 3）                                                      |
| `modelFile`      | string                 | live2d         | 模型入口（相对皮肤目录）                                                     |
| `imageFile`      | string                 | static         | 图片文件（相对皮肤目录，建议透明底 PNG）                                     |
| `capabilities`   | object                 | 默认空         | `{motionGroups: string[], expressions: string[]}`，前端状态机据此选动作/表情 |
| `animation`      | object                 | 默认空         | static 逐状态动画开关，键为 6 状态（见下）                                   |
| `emotionMapping` | object                 | 默认空         | static 情绪表达：`{<emotion>: {scale: 0.5–2.0, tint: "#RRGGBB"\|null}}`      |
| `credits`        | object                 | 默认空         | 致谢（`illustration` / `model` 等自由键）                                    |

### `animation` 逐状态开关（static）

键：`idle / talking / thinking / working / error / sleeping`；
值：`{float, breathe, sway}` 布尔（漂浮 / 呼吸缩放 / 微旋摇摆）。
推荐基线（与导入静态皮肤默认表一致）：idle/talking 漂浮+呼吸、thinking 漂浮、
working 呼吸+摇摆、error 全关、sleeping 呼吸。

### `capabilities`（live2d）

`motionGroups` 须与 model3.json 实际动作组一致（状态机按偏好表挑选，缺失回退
首个可用组）；`expressions` 列出 exp3 表情名（情绪命中时优先表情文件，否则
参数预设）。

## 模板：静态皮肤

```json
{
  "id": "my-cat",
  "name": "我的猫",
  "version": "1.0.0",
  "resourceType": "static",
  "license": "CC0 / 自有版权 / …",
  "imageFile": "avatar.png",
  "animation": {
    "idle": { "float": true, "breathe": true, "sway": false },
    "talking": { "float": true, "breathe": true, "sway": false },
    "thinking": { "float": true, "breathe": false, "sway": false },
    "working": { "float": false, "breathe": true, "sway": true },
    "error": { "float": false, "breathe": false, "sway": false },
    "sleeping": { "float": false, "breathe": true, "sway": false }
  },
  "credits": { "illustration": "…" }
}
```

## 导入校验（3.5）

- PNG：magic + IHDR 尺寸 64–4096、≤10MB；落盘为 `avatar.png` 并生成静态清单；
- zip：`skin.json` 须在根或单层子目录内；清单 pydantic 校验；`modelFile`/
  `imageFile` 资源存在性；逐成员防 zip-slip；≤50MB、≤500 条目；
- 错误一律可读文案（422/409），前端直接展示。

## 制作建议与尺寸归一化

- 静态皮肤用**透明底 PNG**（带底图会以卡片形态原样展示）；
- 角色主体尽量占满画布、脚底贴下边（布局按包围盒底边对齐）；
- 推荐长边 **512–2048**；尺寸处理三层防线：
  - **导入侧**：长边 >2048 自动 canvas 降采样到 2048 再上传（PNG 无损保 alpha）；
    max 边 <256 软提示「分辨率较低」但不阻断；
  - **服务端**：IHDR 尺寸 64–4096 硬拒绝（zip/手动放置漏网图的第一道闸）；
  - **渲染侧**：放大上限 2x（`MAX_STATIC_UPSCALE`）——小图封顶 2 倍放大，
    宁矮不糊；窗口随 capped 包围盒贴合，无空窗；
- 横版/超宽图受角色宽上限（360px）约束，角色会偏矮（既有布局行为）。
