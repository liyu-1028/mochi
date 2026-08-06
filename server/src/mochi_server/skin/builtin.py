"""内置皮肤常量表（M1-S1，ADR-0006 D1）。

release 下 sidecar 经 PyInstaller 打包，看不到 Tauri frontendDist 内嵌的
内置皮肤资源，故内置清单以常量表登记（与 persona.CATALOG 同构）；皮肤资源
本身由前端资产链路分发（vite skinAssets / frontendDist），base URL 为
``/skins/<id>``。新增内置皮肤 = 改本表 + assets/skins/ 加资源，低频事件。
"""

from __future__ import annotations

from ..skin_manifest import (
    SkinCapabilities,
    SkinManifest,
    default_static_animation,
    default_static_emotion_mapping,
)

_USER_PROVIDED_LICENSE = "用户提供的原创素材，版权归提供者所有"

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
    "mochi-julia": SkinManifest(
        id="mochi-julia",
        name="Julia",
        version="1.0.0",
        resourceType="static",
        license=_USER_PROVIDED_LICENSE,
        imageFile="avatar.png",
        animation=default_static_animation(),
        emotionMapping=default_static_emotion_mapping(),
        credits={"illustration": "Mochi 用户"},
    ),
    "mochi-snj": SkinManifest(
        id="mochi-snj",
        name="Snj",
        version="1.0.0",
        resourceType="static",
        license=_USER_PROVIDED_LICENSE,
        imageFile="avatar.png",
        animation=default_static_animation(),
        emotionMapping=default_static_emotion_mapping(),
        credits={"illustration": "Mochi 用户"},
    ),
}
