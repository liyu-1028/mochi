"""内置皮肤常量表（M1-S1，ADR-0006 D1）。

release 下 sidecar 经 PyInstaller 打包，看不到 Tauri frontendDist 内嵌的
内置皮肤资源，故内置清单以常量表登记（与 persona.CATALOG 同构）；皮肤资源
本身由前端资产链路分发（vite skinAssets / frontendDist），base URL 为
``/skins/<id>``。新增内置皮肤 = 改本表 + assets/skins/ 加资源，低频事件。

内置皮肤精灵图来源 pokesprite（https://github.com/msikma/pokesprite），
© Nintendo / Creatures Inc. / GAME FREAK inc.。三只静态皮肤：
pikachu（皮卡丘，默认）/ eevee（伊布）/ snorlax（卡比兽）。
"""

from __future__ import annotations

from ..skin_manifest import (
    SkinManifest,
    default_static_animation,
    default_static_emotion_mapping,
)

BUILTIN_SKINS: dict[str, SkinManifest] = {
    "pikachu": SkinManifest(
        id="pikachu",
        name="皮卡丘 Pikachu",
        version="1.0.0",
        resourceType="static",
        license="© Nintendo / Creatures Inc. / GAME FREAK inc.（pokesprite）",
        imageFile="avatar.png",
        animation=default_static_animation(),
        emotionMapping=default_static_emotion_mapping(),
        credits={
            "sprite": "pokesprite (msikma)",
            "character": "© Nintendo / Creatures Inc. / GAME FREAK inc.",
        },
    ),
    "eevee": SkinManifest(
        id="eevee",
        name="伊布 Eevee",
        version="1.0.0",
        resourceType="static",
        license="© Nintendo / Creatures Inc. / GAME FREAK inc.（pokesprite）",
        imageFile="avatar.png",
        animation=default_static_animation(),
        emotionMapping=default_static_emotion_mapping(),
        credits={
            "sprite": "pokesprite (msikma)",
            "character": "© Nintendo / Creatures Inc. / GAME FREAK inc.",
        },
    ),
    "snorlax": SkinManifest(
        id="snorlax",
        name="卡比兽 Snorlax",
        version="1.0.0",
        resourceType="static",
        license="© Nintendo / Creatures Inc. / GAME FREAK inc.（pokesprite）",
        imageFile="avatar.png",
        animation=default_static_animation(),
        emotionMapping=default_static_emotion_mapping(),
        credits={
            "sprite": "pokesprite (msikma)",
            "character": "© Nintendo / Creatures Inc. / GAME FREAK inc.",
        },
    ),
}
