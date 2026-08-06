"""skin.json v1 清单模型（功能清单 3.1，规范 docs/specs/skin-manifest-format.md）。

皮肤包清单是皮肤系统的唯一描述格式：
- ``resourceType`` 二选一：``live2d``（Cubism 模型）/ ``static``（单张图片）；
- ``capabilities`` 能力档案（motionGroups/expressions），前端状态机据此选动作；
- ``animation`` 静态皮肤逐状态动画开关；``emotionMapping`` 静态皮肤情绪表达；
- 缺字段给默认值——M0-S3 最小清单（仅展示字段）向后兼容。

清单文件为 camelCase（与前端 TS 类型一致）；Pydantic 经 alias 双向兼容
snake_case（populate_by_name），服务端内部读写均用字段名。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ResourceType = Literal["live2d", "static"]
SkinSource = Literal["builtin", "user"]

# 皮肤 id：小写字母/数字开头，可含连字符，≤32 字符（目录名安全）。
SKIN_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,31}$"


class SkinCapabilities(BaseModel):
    """模型能力档案：前端 resolveAnimation 据此挑选动作组/表情文件。"""

    motion_groups: list[str] = Field(default_factory=list, alias="motionGroups")
    expressions: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class AnimationParams(BaseModel):
    """静态皮肤单状态动画开关（live2d 忽略）。"""

    float: bool = False
    breathe: bool = False
    sway: bool = False


class EmotionEffect(BaseModel):
    """静态皮肤情绪表达：微缩放（tint 预留，当前渲染层不使用）。"""

    scale: float = Field(default=1.0, ge=0.5, le=2.0)
    tint: str | None = None


class SkinManifest(BaseModel):
    """skin.json v1 完整清单。resourceType 决定 modelFile/imageFile 必填性（运行时校验）。"""

    id: str = Field(..., pattern=SKIN_ID_PATTERN)
    name: str
    version: str = "1.0.0"
    resource_type: ResourceType = Field(..., alias="resourceType")
    license: str = ""
    cubism_version: int | None = Field(default=None, alias="cubismVersion")
    model_file: str | None = Field(default=None, alias="modelFile")
    image_file: str | None = Field(default=None, alias="imageFile")
    capabilities: SkinCapabilities = Field(default_factory=SkinCapabilities)
    animation: dict[str, AnimationParams] = Field(default_factory=dict)
    emotion_mapping: dict[str, EmotionEffect] = Field(default_factory=dict, alias="emotionMapping")
    credits: dict[str, str] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class SkinSummary(BaseModel):
    """GET /skins 列表条目：展示字段 + 来源 + 资源基址（前端不拼路径）。"""

    id: str
    name: str
    resource_type: ResourceType = Field(alias="resourceType")
    source: SkinSource
    resource_base_url: str = Field(alias="resourceBaseUrl")
    license: str = ""
    credits: dict[str, str] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


def manifest_to_summary(
    manifest: SkinManifest, *, source: SkinSource, base_url: str
) -> SkinSummary:
    return SkinSummary(
        id=manifest.id,
        name=manifest.name,
        resourceType=manifest.resource_type,
        source=source,
        resourceBaseUrl=base_url,
        license=manifest.license,
        credits=manifest.credits,
    )
