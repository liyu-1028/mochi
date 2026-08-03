# assets/ —— 角色资产目录（许可隔离区）

⚠️ **本目录下的所有资产不受根目录 MIT 协议约束**，许可边界见
[`LICENSE-Live2D.md`](../LICENSE-Live2D.md)。

## 规则

1. 每个皮肤包一个子目录：`assets/skins/<skin-id>/`，内含 `skin.json` 清单与资源文件。
2. `skin.json` 的 `license` 字段**必填**（皮肤包清单规范，M0 冻结）。
3. Live2D 模型资产入库前必须在 `LICENSE-Live2D.md` §2 表格中完成许可登记。
4. 二进制资产不做 git diff（已在 `.gitattributes` 声明）；
   单文件 >5MB 的资产入库需在 commit 规范 §5 中登记例外。
