"""动作扩展包导入与 motion3.json 结构边界与极端情况测试。"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from mochi_server.config import AppConfig
from mochi_server.main import create_app
from mochi_server.paths import get_skins_dir
from mochi_server.skin.motion_pack import validate_motion3_json

VALID_BASE_MOTION3 = {
    "Version": 3,
    "Meta": {"Duration": 1.0, "Fps": 30, "Loop": True},
    "Curves": [
        {
            "Target": "Parameter",
            "Id": "ParamAngleX",
            "Segments": [0, 0, 0, 1.0, 10],
        }
    ],
}


# ---------------------------------------------------------------------------
# 1. validate_motion3_json 边界测试
# ---------------------------------------------------------------------------


def test_motion3_duration_epsilon_boundary() -> None:
    """浮点容差边界：last_t <= duration + 0.001 通过，> duration + 0.001 拒绝。"""
    # duration = 1.0, last_t = 1.0009 <= 1.001 -> 通过
    valid_curve = {
        "Version": 3,
        "Meta": {"Duration": 1.0},
        "Curves": [
            {
                "Target": "Parameter",
                "Id": "P",
                "Segments": [0, 0, 0, 1.0009, 10],
            }
        ],
    }
    dur = validate_motion3_json(valid_curve, "test.motion3.json")
    assert dur == 1.0

    # duration = 1.0, last_t = 1.0011 > 1.001 -> 拒绝
    invalid_curve = {
        "Version": 3,
        "Meta": {"Duration": 1.0},
        "Curves": [
            {
                "Target": "Parameter",
                "Id": "P",
                "Segments": [0, 0, 0, 1.0011, 10],
            }
        ],
    }
    with pytest.raises(HTTPException) as exc:
        validate_motion3_json(invalid_curve, "test.motion3.json")
    assert exc.value.status_code == 422
    assert "超出 Meta.Duration" in exc.value.detail


def test_motion3_all_four_segment_types() -> None:
    """覆盖 Cubism 3 全 4 种分段标记：0=linear, 1=bezier, 2=stepped, 3=type3。"""
    # 0: [t, v], 1: [t1, v1, t2, v2, t3, v3], 2: [t, v], 3: [t, v]
    segments = [
        0,
        0,  # t0, v0
        0,
        0.2,
        5,  # mark 0 (linear) -> t=0.2, v=5
        1,
        0.3,
        6,
        0.4,
        8,
        0.5,
        10,  # mark 1 (bezier) -> 3 points, end t=0.5
        2,
        0.8,
        10,  # mark 2 (stepped) -> end t=0.8
        3,
        1.0,
        0,  # mark 3 -> end t=1.0
    ]
    raw = {
        "Version": 3,
        "Meta": {"Duration": 1.0},
        "Curves": [{"Target": "Parameter", "Id": "ParamAllTypes", "Segments": segments}],
    }
    dur = validate_motion3_json(raw, "all.motion3.json")
    assert dur == 1.0


def test_motion3_bezier_insufficient_points_rejected() -> None:
    """贝塞尔曲线不足 6 个数值（只有 5 个）必须被拒绝。"""
    segments = [
        0,
        0,
        1,
        0.2,
        1,
        0.4,
        2,
        0.6,  # 缺 1 个 value
    ]
    raw = {
        "Version": 3,
        "Meta": {"Duration": 1.0},
        "Curves": [{"Target": "Parameter", "Id": "P", "Segments": segments}],
    }
    with pytest.raises(HTTPException) as exc:
        validate_motion3_json(raw, "test.motion3.json")
    assert exc.value.status_code == 422
    assert "段数据不完整" in exc.value.detail


def test_motion3_trailing_garbage_rejected() -> None:
    """段末尾有孤立的多余数字必须被拒绝。"""
    segments = [
        0,
        0,
        0,
        1.0,
        10,
        999,  # 多余孤立项
    ]
    raw = {
        "Version": 3,
        "Meta": {"Duration": 1.0},
        "Curves": [{"Target": "Parameter", "Id": "P", "Segments": segments}],
    }
    with pytest.raises(HTTPException) as exc:
        validate_motion3_json(raw, "test.motion3.json")
    assert exc.value.status_code == 422


def test_motion3_boolean_in_segments_rejected() -> None:
    """Segments 中包含 bool (True/False) 必须拒绝（防 Python bool 是 int 子类漏洞）。"""
    segments = [0, 0, 0, True, 10]
    raw = {
        "Version": 3,
        "Meta": {"Duration": 1.0},
        "Curves": [{"Target": "Parameter", "Id": "P", "Segments": segments}],
    }
    with pytest.raises(HTTPException) as exc:
        validate_motion3_json(raw, "test.motion3.json")
    assert exc.value.status_code == 422
    assert "含非数字" in exc.value.detail


def test_motion3_duration_not_positive_number() -> None:
    """Meta.Duration 为 0, 负数, bool, 字符串均拒绝。"""
    for bad in (0, -1.5, True, "1.0", None):
        raw = {
            "Version": 3,
            "Meta": {"Duration": bad},
            "Curves": [{"Target": "Parameter", "Id": "P", "Segments": [0, 0, 0, 1.0, 10]}],
        }
        with pytest.raises(HTTPException) as exc:
            validate_motion3_json(raw, "test.motion3.json")
        assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# 2. 扩展包 zip 解包与合并安全边界
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app(config=AppConfig())) as c:
        yield c


def _zip_skin(skin_id: str = "boundcat", model3_motions: dict | None = None) -> bytes:
    model3 = {"FileReferences": {"Motions": model3_motions or {}}}
    manifest = {
        "id": skin_id,
        "name": "BoundCat",
        "resourceType": "live2d",
        "modelFile": "m.model3.json",
        "capabilities": {"motionGroups": list((model3_motions or {}).keys())},
        "actions": [
            {
                "id": "base_act",
                "channels": ["body"],
                "agentSelectable": True,
                "live2d": {"motionGroups": []},
            }
        ],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("skin.json", json.dumps(manifest))
        zf.writestr("m.model3.json", json.dumps(model3))
    return buf.getvalue()


def _zip_pack_raw(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            if isinstance(content, str):
                zf.writestr(name, content)
            else:
                zf.writestr(name, content)
    return buf.getvalue()


def test_zip_naming_confusion_mypack_json_rejected(client):
    """严厉测试：zip 根目录下存在 mypack.json 而不是 pack.json，不得被误判为 pack.json。"""
    client.post("/skins/import", files={"file": ("skin.zip", _zip_skin("boundcat"))})
    pack_data = {
        "targetSkin": "boundcat",
        "license": "CC0",
        "motions": [{"group": "G", "file": "motions/w.motion3.json"}],
        "actions": [{"id": "a", "channels": ["body"], "live2d": {"motionGroups": ["G"]}}],
    }
    # 只有 mypack.json
    zip_bytes = _zip_pack_raw(
        {
            "mypack.json": json.dumps(pack_data),
            "motions/w.motion3.json": json.dumps(VALID_BASE_MOTION3),
        }
    )
    resp = client.post(
        "/skins/import-motion-pack",
        files={"file": ("pack.zip", zip_bytes, "application/octet-stream")},
    )
    assert resp.status_code == 422
    assert "pack.json" in resp.json()["detail"]


def test_model3_with_null_motions_table_handled(client):
    """边界测试：原 model3.json 中 FileReferences.Motions 为 None 时能够自愈而不抛 500。"""
    # 构造 Motions 显式为 None 的皮肤包
    skin_buf = io.BytesIO()
    manifest = {
        "id": "nullmotions",
        "name": "NullMotions",
        "resourceType": "live2d",
        "modelFile": "m.model3.json",
        "capabilities": {"motionGroups": []},
        "actions": [],
    }
    model3 = {"FileReferences": {"Motions": None}}
    with zipfile.ZipFile(skin_buf, "w") as zf:
        zf.writestr("skin.json", json.dumps(manifest))
        zf.writestr("m.model3.json", json.dumps(model3))
    client.post("/skins/import", files={"file": ("skin.zip", skin_buf.getvalue())})

    pack_data = {
        "targetSkin": "nullmotions",
        "license": "CC0",
        "motions": [{"group": "NewGroup", "file": "motions/w.motion3.json"}],
        "actions": [{"id": "act", "channels": ["body"], "live2d": {"motionGroups": ["NewGroup"]}}],
    }
    pack_bytes = _zip_pack_raw(
        {
            "pack.json": json.dumps(pack_data),
            "motions/w.motion3.json": json.dumps(VALID_BASE_MOTION3),
        }
    )
    resp = client.post(
        "/skins/import-motion-pack",
        files={"file": ("pack.zip", pack_bytes, "application/octet-stream")},
    )
    # 应正常导入或 422 提示，绝不 500
    assert resp.status_code in (200, 422)


def test_motion_pack_empty_license_rejected(client):
    """授权红线：license 为空字符串必须 422 拒绝。"""
    client.post("/skins/import", files={"file": ("skin.zip", _zip_skin("boundcat"))})
    pack_data = {
        "targetSkin": "boundcat",
        "license": "",  # 空 license
        "motions": [{"group": "G", "file": "motions/w.motion3.json"}],
        "actions": [{"id": "a", "channels": ["body"], "live2d": {"motionGroups": ["G"]}}],
    }
    pack_bytes = _zip_pack_raw(
        {
            "pack.json": json.dumps(pack_data),
            "motions/w.motion3.json": json.dumps(VALID_BASE_MOTION3),
        }
    )
    resp = client.post(
        "/skins/import-motion-pack",
        files={"file": ("pack.zip", pack_bytes, "application/octet-stream")},
    )
    assert resp.status_code == 422


def test_motion_pack_multiple_imports_credit_suffix(client):
    """多次导入同名扩展包：credits 键自动追加 #2, #3。"""
    client.post("/skins/import", files={"file": ("skin.zip", _zip_skin("multicredit"))})
    for i, group in enumerate(["GroupA", "GroupB", "GroupC"]):
        pack_data = {
            "targetSkin": "multicredit",
            "name": "same-pack",
            "license": f"CC0-{i}",
            "motions": [{"group": group, "file": f"motions/{group}.motion3.json"}],
            "actions": [
                {"id": f"act_{i}", "channels": ["body"], "live2d": {"motionGroups": [group]}}
            ],
        }
        pack_bytes = _zip_pack_raw(
            {
                "pack.json": json.dumps(pack_data),
                f"motions/{group}.motion3.json": json.dumps(VALID_BASE_MOTION3),
            }
        )
        resp = client.post(
            "/skins/import-motion-pack",
            files={"file": ("pack.zip", pack_bytes, "application/octet-stream")},
        )
        assert resp.status_code == 200

    skin_json = json.loads(
        (get_skins_dir() / "multicredit" / "skin.json").read_text(encoding="utf-8")
    )
    credits = skin_json["credits"]
    assert credits["motionPack:same-pack"] == "CC0-0"
    assert credits["motionPack:same-pack#2"] == "CC0-1"
    assert credits["motionPack:same-pack#3"] == "CC0-2"
