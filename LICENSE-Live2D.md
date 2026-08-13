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
| `assets/skins/pikachu/` | 皮卡丘 Pikachu | pokesprite（msikma） | © Nintendo / Creatures Inc. / GAME FREAK inc.（精灵图来源：<https://github.com/msikma/pokesprite>） | 内置默认静态皮肤（功能清单 3.2）；68×56 透明底 PNG |
| `assets/skins/eevee/` | 伊布 Eevee | pokesprite（msikma） | © Nintendo / Creatures Inc. / GAME FREAK inc.（精灵图来源：<https://github.com/msikma/pokesprite>） | 内置静态皮肤（功能清单 3.2）；68×56 透明底 PNG |
| `assets/skins/snorlax/` | 卡比兽 Snorlax | pokesprite（msikma） | © Nintendo / Creatures Inc. / GAME FREAK inc.（精灵图来源：<https://github.com/msikma/pokesprite>） | 内置静态皮肤（功能清单 3.2）；68×56 透明底 PNG |

## 3. 第三方皮肤包（skin.json 许可字段）

依据皮肤包清单规范，所有皮肤包的 `skin.json` **必须**包含 `license` 字段。
皮肤商店（V2）上架审查与用户本地导入校验均以该字段为准。
分发 Live2D 模型资产时，分发者须自行确保拥有相应授权。

## 4. 免责声明

角色资产按「现状」提供。资产引发的授权纠纷由资产提供者承担，
Mochi 项目保留在接到有效权利通知后下架相关资产的权利。
