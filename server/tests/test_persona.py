"""人格系统测试：预设目录完整性 + system prompt 拼装（功能清单 6.13）。"""

from __future__ import annotations

import pytest

from mochi_server.agent.llm_agent import DEFAULT_SYSTEM_PROMPT
from mochi_server.config import PersonaConfig
from mochi_server.persona import (
    CATALOG,
    DIMENSIONS,
    build_system_prompt,
    valid_preset_id,
)


def _first_id(dimension: str) -> str:
    return CATALOG.dimension(dimension)[0].id


# ---------------------------------------------------------------------------
# 目录完整性
# ---------------------------------------------------------------------------


def test_catalog_has_three_dimensions():
    assert DIMENSIONS == ("soul", "personality", "style")
    view = CATALOG.view()
    assert set(view) == {"soul", "personality", "style"}


def test_catalog_each_dimension_has_presets():
    for dim in DIMENSIONS:
        assert len(CATALOG.dimension(dim)) >= 4, f"{dim} 预设不足"


def test_catalog_preset_ids_unique_within_dimension():
    for dim in DIMENSIONS:
        ids = [p.id for p in CATALOG.dimension(dim)]
        assert len(ids) == len(set(ids)), f"{dim} 预设 id 重复"


def test_catalog_presets_have_bilingual_names_and_prompts():
    for dim in DIMENSIONS:
        for preset in CATALOG.dimension(dim):
            assert preset.id, f"{dim} 存在空 id"
            assert preset.name["zh-CN"] and preset.name["en"], f"{dim}/{preset.id} 名称缺语言"
            assert preset.description["zh-CN"] and preset.description["en"]
            assert preset.prompt.strip(), f"{dim}/{preset.id} prompt 为空"


# ---------------------------------------------------------------------------
# preset id 校验
# ---------------------------------------------------------------------------


def test_valid_preset_id_accepts_empty_and_known():
    assert valid_preset_id("soul", "") is True
    assert valid_preset_id("soul", _first_id("soul")) is True


def test_valid_preset_id_rejects_unknown_or_wrong_dimension():
    assert valid_preset_id("soul", "no_such_preset") is False
    # 跨维度引用不合法：soul 的 id 不属于 style 目录
    assert valid_preset_id("style", _first_id("soul")) is False
    assert valid_preset_id("unknown_dim", "whatever") is False


# ---------------------------------------------------------------------------
# build_system_prompt 拼装
# ---------------------------------------------------------------------------


def test_all_empty_returns_default_prompt():
    """Zero Config 兼容：全空人格与既有行为逐字一致。"""
    assert build_system_prompt(PersonaConfig()) == DEFAULT_SYSTEM_PROMPT


def test_single_dimension_preset_injected():
    persona = PersonaConfig(soul_preset=_first_id("soul"))
    prompt = build_system_prompt(persona)
    assert prompt != DEFAULT_SYSTEM_PROMPT
    assert "【灵魂设定】" in prompt
    assert "【性格特征】" not in prompt
    assert "【说话风格】" not in prompt
    assert CATALOG.dimension("soul")[0].prompt in prompt


def test_all_dimensions_injected_in_order():
    persona = PersonaConfig(
        soul_preset=_first_id("soul"),
        personality_preset=_first_id("personality"),
        style_preset=_first_id("style"),
    )
    prompt = build_system_prompt(persona)
    soul_idx = prompt.index("【灵魂设定】")
    personality_idx = prompt.index("【性格特征】")
    style_idx = prompt.index("【说话风格】")
    assert soul_idx < personality_idx < style_idx


def test_custom_overrides_preset():
    persona = PersonaConfig(soul_preset=_first_id("soul"), soul_custom="我是一只会讲冷笑话的龙")
    prompt = build_system_prompt(persona)
    assert "我是一只会讲冷笑话的龙" in prompt
    assert CATALOG.dimension("soul")[0].prompt not in prompt


def test_whitespace_custom_falls_back_to_preset():
    persona = PersonaConfig(soul_preset=_first_id("soul"), soul_custom="   ")
    prompt = build_system_prompt(persona)
    assert CATALOG.dimension("soul")[0].prompt in prompt


def test_custom_only_without_preset():
    persona = PersonaConfig(style_custom="说话像海盗")
    prompt = build_system_prompt(persona)
    assert "说话像海盗" in prompt
    assert "【说话风格】" in prompt


def test_invalid_preset_id_ignored():
    """脏值防御：无效 id 该维度不注入，不崩溃。"""
    persona = PersonaConfig(soul_preset="no_such_preset")
    assert build_system_prompt(persona) == DEFAULT_SYSTEM_PROMPT

    persona2 = PersonaConfig(soul_preset="no_such_preset", style_custom="说话像海盗")
    prompt = build_system_prompt(persona2)
    assert "【灵魂设定】" not in prompt
    assert "说话像海盗" in prompt


@pytest.mark.parametrize("dim", DIMENSIONS)
def test_catalog_view_serializable_shape(dim: str):
    view = CATALOG.view()
    for item in view[dim]:
        assert set(item) == {"id", "name", "description", "prompt"}
