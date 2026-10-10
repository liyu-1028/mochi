# assets/ —— 角色资产目录（许可隔离区）

⚠️ **本目录下的所有资产不受根目录 MIT 协议约束**，许可边界见
[`LICENSE-Live2D.md`](../LICENSE-Live2D.md)。

## 规则

1. 每个皮肤包一个子目录：`assets/skins/<skin-id>/`，内含 `skin.json` 清单与资源文件。
   支持 `resourceType: "vrm"` 和 `"live2d"`——静态皮肤类型已于
   2026-09-28 下线，不再随应用分发任何静态装扮。
2. `skin.json` 的 `license` 字段**必填**（皮肤包清单规范，M0 冻结）。
3. Live2D 模型资产入库前必须在 `LICENSE-Live2D.md` §2 表格中完成许可登记。
4. 动作扩展包（G4）：`assets/motion-packs/<pack-name>/`，内含 `pack.json` +
   `motions/*.motion3.json`（原创动作数据）；入库前须通过
   `node scripts/validate-motion3.mjs` 校验，并在 `LICENSE-Live2D.md` 登记。
   打包导入：`cd assets/motion-packs/<pack-name> && zip -r ../../<pack-name>.zip .`
   然后在衣橱面板「导入动作扩展包」上传。
5. 二进制资产不做 git diff（已在 `.gitattributes` 声明）；
   单文件 >5MB 的资产入库需在 commit 规范 §5 中登记例外。

## 默认角色和导入

应用只预装 Mochi（`assets/skins/mochi-vrm/`），其他角色通过装扮管理导入。
从 VRoid Hub 或 BOOTH 下载作者允许下载的 VRM 模型，解压后选择 `.vrm`；
也可以用 VRoid Studio 制作角色并「导出为 VRM」后导入，`.vroid` 是工程文件。

直接导入会保存原始 `.vrm`，自动生成本地 `skin.json`，读取 VRM 0.x/1.0 中的
角色名称、版本、作者和许可信息。作者对模型的使用约定仍以原说明为准。
模型副本放在本机应用数据目录的 `skins/<id>/`，不写入源码或预装资产目录。
