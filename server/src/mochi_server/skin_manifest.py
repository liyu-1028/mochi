"""skin.json 清单模型（功能清单 3.1，规范 docs/specs/skin-manifest-format.md）。

皮肤包清单是皮肤系统的唯一描述格式：
- ``resourceType`` 仅 ``live2d``（Cubism 模型）；``static``（单张图片）类型已下线
  （2026-09-28 产品决策：只保留 Live2D 及未来扩展的动态类型）；
- ``capabilities`` 能力档案（motionGroups/expressions），前端状态机据此选动作；
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

ResourceType = Literal["live2d"]
SkinSource = Literal["builtin", "user"]

# 皮肤 id：小写字母/数字开头，可含连字符，≤32 字符（目录名安全）。
SKIN_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,31}$"

# 语义动作 id：snake_case，≤48 字符（与协议规范 §11 词表同命名规则）。
ACTION_ID_PATTERN = r"^[a-z][a-z0-9_]{0,47}$"

ActionKind = Literal["oneshot", "loop"]
InterruptPolicy = Literal["replace", "queue", "ignore"]
EnvelopeEasing = Literal["linear", "smoothstep"]

# 包络时长上限（ms）：微动作，超过视为配置错误
ENVELOPE_DURATION_MAX_MS = 10_000
# 包络关键帧值安全范围：物理范围由前端按模型钳制，清单层只防数值爆炸
ENVELOPE_VALUE_LIMIT = 10_000
# Cubism 参数 id：字母/下划线开头，可含数字（如 ParamEyeLOpen、ParamMouthForm）
ENVELOPE_PARAM_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{0,63}$"


class EnvelopeKeyframe(BaseModel):
    """单参数关键帧：points 为 [t(ms), value] 点列（manifest v3，G3）。"""

    param: str = Field(..., pattern=ENVELOPE_PARAM_PATTERN)
    points: list[tuple[int, float]]

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _validate_points(self) -> EnvelopeKeyframe:
        if len(self.points) < 2:
            raise ValueError(
                f"包络参数 {self.param} 至少需要 2 个关键帧点（收到 {len(self.points)}）"
            )
        prev_t = -1
        for t, _v in self.points:
            if t <= prev_t:
                raise ValueError(f"包络参数 {self.param} 的时间戳必须严格递增：{prev_t} -> {t}")
            prev_t = t
        if self.points[0][0] != 0:
            raise ValueError(f"包络参数 {self.param} 首点时间必须为 0（收到 {self.points[0][0]}）")
        for _t, v in self.points:
            if abs(v) > ENVELOPE_VALUE_LIMIT:
                raise ValueError(
                    f"包络参数 {self.param} 值超出安全范围 ±{ENVELOPE_VALUE_LIMIT}：{v}"
                )
        return self


class ParamEnvelope(BaseModel):
    """声明式参数包络（manifest v3，G3）：皮肤作者免 Editor 自定义动作。"""

    duration_ms: int = Field(..., gt=0, le=ENVELOPE_DURATION_MAX_MS, alias="durationMs")
    easing: EnvelopeEasing = "linear"
    keyframes: list[EnvelopeKeyframe] = Field(..., min_length=1)

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _validate_keyframes(self) -> ParamEnvelope:
        if self.keyframes[0].points[-1][0] != self.duration_ms:
            raise ValueError(
                "包络末点时间必须等于 durationMs："
                f"{self.keyframes[0].param} 末点 {self.keyframes[0].points[-1][0]} ≠ {self.duration_ms}"
            )
        params = [k.param for k in self.keyframes]
        duplicates = sorted({p for p in params if params.count(p) > 1})
        if duplicates:
            raise ValueError(f"包络参数重复：{', '.join(duplicates)}")
        return self


class SkinCapabilities(BaseModel):
    """模型能力档案：前端 resolveAnimation 据此挑选动作组/表情文件。"""

    motion_groups: list[str] = Field(default_factory=list, alias="motionGroups")
    expressions: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class Live2dActionBinding(BaseModel):
    """语义动作的 Live2D 实现绑定。

    v2：motionGroups / expression；v3（G3）：paramEnvelope 声明式包络。
    motionGroups 是否真实存在于模型由前端加载时判；paramEnvelope 由此处
    强校验（时长/点列/值域）。
    """

    motion_groups: list[str] = Field(default_factory=list, alias="motionGroups")
    expression: str | None = None
    param_envelope: ParamEnvelope | None = Field(default=None, alias="paramEnvelope")

    model_config = {"populate_by_name": True}


class SkinAction(BaseModel):
    """语义动作注册表条目（skin manifest v2，M-A）。

    服务端只验结构；live2d.motionGroups 是否真实存在于模型由前端加载时判。
    """

    id: str = Field(..., pattern=ACTION_ID_PATTERN)
    kind: ActionKind = "oneshot"
    channels: list[str] = Field(default_factory=list)
    live2d: Live2dActionBinding = Field(..., alias="live2d")
    priority: int = Field(default=50, ge=0, le=100)
    interrupt_policy: InterruptPolicy = Field("replace", alias="interruptPolicy")
    cooldown_ms: int = Field(default=0, ge=0, alias="cooldownMs")
    # 白名单铁律：模型（LLM）只能选择 agentSelectable=true 的动作（协议规范 §11）
    agent_selectable: bool = Field(default=False, alias="agentSelectable")
    # 降级链：指向同清单其他动作或语义词表（SEMANTIC_ACTIONS）内的内置安全动作
    fallback: str | None = Field(default=None, pattern=ACTION_ID_PATTERN)
    # 动作时长（ms，v3/G3）：占位窗口（Live2D 动作位），缺省用前端默认值
    duration_ms: int | None = Field(
        default=None, ge=1, le=ENVELOPE_DURATION_MAX_MS, alias="durationMs"
    )

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _validate_bindings(self) -> SkinAction:
        unknown = [ch for ch in self.channels if ch not in ACTION_CHANNELS]
        if unknown:
            raise ValueError(
                f"动作 {self.id} 含未知通道：{', '.join(unknown)}（合法：{', '.join(ACTION_CHANNELS)}）"
            )
        return self


class SkinManifest(BaseModel):
    """skin.json 完整清单（v2，M-A 起 actions 为可选字段）。modelFile 必填性由运行时校验。"""

    id: str = Field(..., pattern=SKIN_ID_PATTERN)
    name: str
    version: str = "1.0.0"
    resource_type: ResourceType = Field(..., alias="resourceType")
    license: str = ""
    cubism_version: int | None = Field(default=None, alias="cubismVersion")
    model_file: str = Field(..., alias="modelFile")
    capabilities: SkinCapabilities = Field(default_factory=SkinCapabilities)
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

    前端渲染依赖 modelFile/capabilities 等清单字段（拼资源 URL、选动作档案），
    列表必须带全量清单而非仅展示字段。
    """

    source: SkinSource
    resource_base_url: str = Field(alias="resourceBaseUrl")


def manifest_to_summary(
    manifest: SkinManifest, *, source: SkinSource, base_url: str
) -> SkinSummary:
    return SkinSummary(
        source=source,
        resourceBaseUrl=base_url,
        **manifest.model_dump(by_alias=True, exclude_none=True),
    )
