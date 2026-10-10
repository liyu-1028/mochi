# vrm-dance 舞蹈评估原型资源

本目录资产仅用于 `?prototype=vrm-dance` 本地观感评估（ADR-0011 预验收），
由 `scripts/download-dance-assets.mjs` 按固定来源与 SHA256 下载，不入库。

| 文件 | 来源 | 许可 |
| --- | --- | --- |
| `sample.vrm` | pixiv/three-vrm `VRM1_Constraint_Twist_Sample.vrm`（固定 commit 1b4fc0c） | VRM Public License 1.0 与模型内许可设置 |
| `samba.fbx` | mrdoob/three.js r180 `Samba Dancing.fbx`（Mixamo 导出） | Mixamo 使用条款 |

`retargetDance.ts`（apps/desktop/src/components/prototypes/）改编自
pixiv/three-vrm `humanoidAnimation` 示例（MIT，Copyright (c) 2019 pixiv Inc.）。

默认角色的正式分发位为 `assets/skins/mochi-vrm/`，通过
`scripts/download-vrm-assets.mjs` 下载。舞蹈评估文件不随发行版提供；
产品动作由用户在「动作管理」中导入 VRMA。
