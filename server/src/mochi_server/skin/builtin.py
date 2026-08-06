"""内置皮肤常量表（M1-S1，ADR-0006 D1）。

release 下 sidecar 经 PyInstaller 打包，看不到 Tauri frontendDist 内嵌的
内置皮肤资源，故内置清单以常量表登记（与 persona.CATALOG 同构）；皮肤资源
本身由前端资产链路分发（vite skinAssets / frontendDist），base URL 为
``/skins/<id>``。新增内置皮肤 = 改本表 + assets/skins/ 加资源，低频事件。

内置静态皮肤曾登记 mochi-julia/mochi-snj（用户开发期素材），按产品决策
撤回——素材仅开发验证用，不随版提供；静态皮肤路径由用户导入（3.4）承载，
正式内置静态美术待后续专项（功能清单 3.2）。
"""

from __future__ import annotations

from ..skin_manifest import SkinCapabilities, SkinManifest

BUILTIN_SKINS: dict[str, SkinManifest] = {
    "hiyori": SkinManifest(
        id="hiyori",
        name="Hiyori（桃瀬ひより）",
        version="1.0.0",
        resourceType="live2d",
        license="Live2D Free Material License Agreement + Terms of Use for Live2D Cubism Sample Data",
        cubismVersion=3,
        modelFile="hiyori_pro_t11.model3.json",
        capabilities=SkinCapabilities(
            motionGroups=[
                "Idle",
                "Flick",
                "FlickDown",
                "FlickUp",
                "Tap",
                "Tap@Body",
                "Flick@Body",
            ],
            expressions=[],
        ),
        credits={"illustration": "Kani Biimu", "model": "Live2D Inc."},
    ),
}
