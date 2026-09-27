"""skin.json 清单模型（功能清单 3.1，规范 docs/specs/skin-manifest-format.md）。

皮肤包清单是皮肤系统的唯一描述格式：
- ``resourceType`` 二选一：``live2d``（Cubism 模型）/ ``static``（单张图片）；
- ``capabilities`` 能力档案（motionGroups/expressions），前端状态机据此选动作；
- ``animation`` 静态皮肤逐状态动画开关；``emotionMapping`` 静态皮肤情绪表达；
- ``actions``（v2，M-A）语义动作注册表：皮肤声明自己支持的语义动作与实现绑定，
  前端 ActionRegistry 据此解析，未实现的沿 fallback 链降级；
- 缺字段给默认值——M0-S3 最小清单（仅展示字段）向后兼容。

清单文件为 camelCase（与前端 TS 类型一致）；Pydantic 经 alias 双向兼容
snake_case（populate_by_name），服务端内部读写均用字段名。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .events import ACTION_CHANNELS, SEMANTIC_ACTIONS

ResourceType = Literal["live2d", "static"]
SkinSource = Literal["builtin", "user"]

# 皮肤 id：小写字母/数字开头，可含连字符，≤32 字符（目录名安全）。
SKIN_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,31}$"

# 语义动作 id：snake_case，≤48 字符（与协议规范 §11 词表同命名规则）。
ACTION_ID_PATTERN = r"^[a-z][a-z0-9_]{0,47}$"

ActionKind = Literal["oneshot", "loop"]
InterruptPolicy = Literal["replace", "queue", "ignore"]


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


class Live2dActionBinding(BaseModel):
    """语义动作的 Live2D 实现绑定（motionGroups 按偏好取首个模型实际拥有的）。"""

    motion_groups: list[str] = Field(default_factory=list, alias="motionGroups")
    expression: str | None = None

    model_config = {"populate_by_name": True}


class StaticActionBinding(BaseModel):
    """语义动作的静态皮肤实现绑定：animation 指向前端包络 id（现与语义动作 id 同名）。"""

    animation: str = Field(min_length=1)


class SkinAction(BaseModel):
    """语义动作注册表条目（skin manifest v2，M-A）。

    服务端只验结构；live2d.motionGroups 是否真实存在于模型由前端加载时判。
    """

    id: str = Field(..., pattern=ACTION_ID_PATTERN)
    kind: ActionKind = "oneshot"
    channels: list[str] = Field(default_factory=list)
    live2d: Live2dActionBinding | None = None
    static: StaticActionBinding | None = None
    priority: int = Field(default=50, ge=0, le=100)
    interrupt_policy: InterruptPolicy = Field("replace", alias="interruptPolicy")
    cooldown_ms: int = Field(default=0, ge=0, alias="cooldownMs")
    # 白名单铁律：模型（LLM）只能选择 agentSelectable=true 的动作（协议规范 §11）
    agent_selectable: bool = Field(default=False, alias="agentSelectable")
    # 降级链：指向同清单其他动作或语义词表（SEMANTIC_ACTIONS）内的内置安全动作
    fallback: str | None = Field(default=None, pattern=ACTION_ID_PATTERN)

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _validate_bindings(self) -> SkinAction:
        if self.live2d is None and self.static is None:
            raise ValueError(f"动作 {self.id} 缺少 live2d/static 任一实现绑定")
        unknown = [ch for ch in self.channels if ch not in ACTION_CHANNELS]
        if unknown:
            raise ValueError(
                f"动作 {self.id} 含未知通道：{', '.join(unknown)}（合法：{', '.join(ACTION_CHANNELS)}）"
            )
        return self


class SkinManifest(BaseModel):
    """skin.json 完整清单（v2，M-A 起 actions 为可选字段）。resourceType 决定 modelFile/imageFile 必填性（运行时校验）。"""

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
    actions: list[SkinAction] = Field(default_factory=list)
    credits: dict[str, str] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _validate_actions(self) -> SkinManifest:
        """动作注册表交叉校验（422 可读文案由 ValueError 直接给出）。"""
        if not self.actions:
            return self
        ids = [action.id for action in self.actions]
        duplicates = sorted({aid for aid in ids if ids.count(aid) > 1})
        if duplicates:
            raise ValueError(f"动作 id 重复：{', '.join(duplicates)}")
        local_ids = set(ids)
        # fallback 引用必须可解析：同清单其他动作或语义词表内置安全动作
        for action in self.actions:
            # 全链路兑底约束：idle_neutral 是终点，不得再指向任何动作
            if action.id == "idle_neutral" and action.fallback is not None:
                raise ValueError("动作 idle_neutral 是全链路兑底终点，不得声明 fallback")
            if (
                action.fallback is not None
                and action.fallback not in local_ids
                and action.fallback not in SEMANTIC_ACTIONS
            ):
                raise ValueError(
                    f"动作 {action.id} 的 fallback 指向未定义动作：{action.fallback}"
                    "（须为同清单动作 id 或语义词表内动作）"
                )
        # fallback 链循环检测：仅沿本清单内引用下探，语义词表引用即终止
        for start in self.actions:
            seen: set[str] = set()
            current: str | None = start.id
            while current is not None and current in local_ids:
                if current in seen:
                    raise ValueError(f"动作 fallback 链循环：{' -> '.join([*seen, current])}")
                seen.add(current)
                current = next(a.fallback for a in self.actions if a.id == current)
        return self


class SkinSummary(SkinManifest):
    """GET /skins 列表条目：完整清单 + 来源 + 资源基址。

    前端渲染双路径依赖 modelFile/imageFile/capabilities/animation 等清单
    字段（拼资源 URL、选动作档案），列表必须带全量清单而非仅展示字段。
    """

    source: SkinSource
    resource_base_url: str = Field(alias="resourceBaseUrl")


# 静态皮肤逐状态动画默认表（内置/导入共用，参数理由见 ADR-0006 D9）。
STATIC_STATES = ("idle", "talking", "thinking", "working", "error", "sleeping")


def default_static_animation() -> dict[str, AnimationParams]:
    return {
        "idle": AnimationParams(float=True, breathe=True),
        "talking": AnimationParams(float=True, breathe=True),
        "thinking": AnimationParams(float=True),
        "working": AnimationParams(breathe=True, sway=True),
        "error": AnimationParams(),
        "sleeping": AnimationParams(breathe=True),
    }


def default_static_emotion_mapping() -> dict[str, EmotionEffect]:
    return {
        "happy": EmotionEffect(scale=1.05),
        "sad": EmotionEffect(scale=0.95),
        "angry": EmotionEffect(scale=1.02),
        "surprised": EmotionEffect(scale=1.08),
        "confused": EmotionEffect(scale=1.0),
        "embarrassed": EmotionEffect(scale=1.02),
    }


# 静态皮肤语义动作基线（内置/导入共用，M-A）：包络实现由前端
# actionEnvelopes 提供，animation id 与语义动作 id 同名。
# 刻意不含 think/listen：头部姿态语义对精灵图无诚实实现，
# 让真实清单里也存在「需降级」的动作，验证 fallback 链。
_STATIC_ACTION_BASELINE: tuple[tuple[str, int, int, bool], ...] = (
    # (id, priority, cooldownMs, agentSelectable)
    ("idle_neutral", 10, 0, False),
    ("look_around", 20, 15_000, True),
    ("wave", 50, 3_000, True),
    ("nod", 50, 3_000, True),
    ("shake_head", 50, 3_000, True),
    ("celebrate", 60, 10_000, True),
    ("comfort", 60, 10_000, True),
    ("surprised", 70, 8_000, True),
    ("stretch", 30, 20_000, True),
    ("doze", 20, 30_000, True),
)


def default_static_actions() -> list[SkinAction]:
    """静态皮肤动作注册表基线：未实现的动作（think/listen）不登记，
    由前端沿 fallback 链降级到 idle_neutral。"""
    return [
        SkinAction(
            id=action_id,
            kind="oneshot",
            channels=["body", "face"],
            static=StaticActionBinding(animation=action_id),
            priority=priority,
            cooldownMs=cooldown_ms,
            agentSelectable=agent_selectable,
            # idle_neutral 是全链路兜底终点，不得再指向任何动作
            fallback=None if action_id == "idle_neutral" else "idle_neutral",
        )
        for action_id, priority, cooldown_ms, agent_selectable in _STATIC_ACTION_BASELINE
    ]


def manifest_to_summary(
    manifest: SkinManifest, *, source: SkinSource, base_url: str
) -> SkinSummary:
    return SkinSummary(
        source=source,
        resourceBaseUrl=base_url,
        **manifest.model_dump(by_alias=True, exclude_none=True),
    )
