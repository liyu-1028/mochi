# Live2D 及角色资产许可声明 / Live2D & Character Assets License Notice

> 本文件是 Mochi 许可体系的组成部分。根目录 `LICENSE`（MIT）**仅覆盖源代码**；
> `assets/` 目录下的全部角色资产（Live2D 模型、静态皮肤图片、贴图、动作数据等）
> **不包含在 MIT 授权范围内**，按本文件及各资产目录内的独立许可条款发布。
>
> 此隔离策略参考了同类开源项目的成熟先例（Open-LLM-VTuber 的
> `LICENSE` + `LICENSE-Live2D.md` 双文件模式）。

## 1. Live2D Cubism SDK 相关

Mochi 通过第三方渲染库（如 pixi-live2d-display）使用 Live2D Cubism Core。
Live2D Cubism SDK 及其 Core 库为 Live2D Inc. 的**专有软件**，受
《Live2D Proprietary Software License Agreement》约束，不属于开源协议覆盖范围。

- 使用 Live2D 功能前，终端用户需同意 Live2D 官方许可条款：
  <https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html>
- Mochi 不以 MIT 或任何开源协议对 Live2D SDK / Core 进行再许可。

## 2. 内置角色资产（逐条登记）

<!-- 登记规则：使用 Live2D 官方示例模型须遵循 Live2D Free Material License Agreement
     与 Terms of Use for Live2D Cubism Sample Data；自制或采购模型登记其作者授权。 -->

| 资产目录 | 名称 | 作者 | 许可条款 | 备注 |
| --- | --- | --- | --- | --- |
| `assets/motion-packs/hiyori-greeting/` | Mochi 招手/鞠躬动作扩展包 | Mochi contributors | CC0 1.0 | 原创动作数据（不含模型）；目标皮肤 live2d-hiyori |
| `assets/skins/mochi-vrm/` | VRM1_Constraint_Twist_Sample | pixiv Inc.（three-vrm 示例） | [VRM Public License 1.0](https://vrm.dev/licenses/1.0/) 与模型内许可设置 | VRM 1.0；Bone 型 LookAt；`scripts/download-vrm-assets.mjs` 固定 commit 下载 |
| `assets/VRMA_MotionPack/` | 用户下载的 VRoid 官方七动作包 | pixiv Inc. / VRoid Project | 原始说明：允许本地使用与修改；禁止未经许可分发可提取的动作；商用须署名 | 公开发行版不预装；原文件不进入 Git 或公开安装包，由用户自行选择 VRMA 导入 |
<!-- 2026-09-28：内置静态皮肤（pikachu/eevee/snorlax，pokesprite）已随静态皮肤类型下线移除。
历史版本（≤ 2026-09-28 之前）曾包含上述三只精灵图皮肤，许可：© Nintendo / Creatures Inc. / GAME FREAK inc.
（精灵图来源：<https://github.com/msikma/pokesprite>）。 -->

## 3. 第三方皮肤包（skin.json 许可字段）

依据皮肤包清单规范，所有皮肤包的 `skin.json` **必须**包含 `license` 字段。
皮肤商店（V2）上架审查与用户本地导入校验均以该字段为准。
分发 Live2D 模型资产时，分发者须自行确保拥有相应授权。

## 4. 免责声明

角色资产按「现状」提供。资产引发的授权纠纷由资产提供者承担，
Mochi 项目保留在接到有效权利通知后下架相关资产的权利。

## 5. README 演示素材

`docs/images/mochi-dance.gif` 为应用实际播放的短录制，无配乐。角色为上述
pixiv VRM 示例；演示动作「愛包ダンスホール」作者为八ツ橋まろん
（Maron Yatsuhashi）。原包 `Terms_of_service.txt` 允许视频与影像作品使用，
禁止未授权再分发原始动作；GIF 仅包含渲染画面，公开安装包不含该 VRMA。
作者说明：[动作使用指引](https://maron.fanbox.cc/posts/6813390)。

默认角色的内嵌元数据声明允许再分发和修改后再分发，版权为
(c) 2022 pixiv Inc.；保持原始模型及许可设置。three-vrm 渲染库的 MIT 许可
与模型的 VRM 许可分别适用。角色目录的 README 同时随前端资产打包。
