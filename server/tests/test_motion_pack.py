"""动作扩展包导入测试（G4，动作扩展方案 M-G L3 层）。

覆盖：pack.json 解析、motion3.json 结构校验、model3.json 合并、skin.json
动作/能力合并、授权登记、备份回滚、冲突拒绝（组名/动作 id）、zip-slip。
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from mochi_server.config import AppConfig
from mochi_server.main import create_app
from mochi_server.paths import get_skins_dir

VALID_MOTION3 = {
    "Version": 3,
    "Meta": {"Duration": 1.0, "Fps": 30, "Loop": True},
    "Curves": [
        {
            "Target": "Parameter",
            "Id": "ParamAngleX",
            "Segments": [0, 0, 0, 0.1, 10, 1, 0.13, 13, 0.16, 16, 0.2, 20, 2, 0.25, 20],
        }
    ],
}


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app(config=AppConfig())) as c:
        yield c


def _zip_skin(model3_motions: dict | None = None) -> bytes:
    model3: dict = {"FileReferences": {"Motions": model3_motions or {}}}
    if model3_motions is None:
        model3 = {"FileReferences": {}}
    manifest = {
        "id": "zipcat",
        "name": "ZipCat",
        "resourceType": "live2d",
        "modelFile": "m.model3.json",
        "capabilities": {"motionGroups": list((model3_motions or {}).keys())},
        "actions": [
            {
                "id": "wave",
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


def _zip_pack(
    *,
    target="zipcat",
    motions=None,
    actions=None,
    pack_over: dict | None = None,
    motion3: dict | None = None,
    extra_members: dict[str, bytes] | None = None,
    subdir: str = "",
    license_text="CC0 原创动作",
) -> bytes:
    motions = (
        motions
        if motions is not None
        else [{"group": "MochiWave", "file": "motions/wave.motion3.json"}]
    )
    actions = (
        actions
        if actions is not None
        else [
            {
                "id": "wave_hand",
                "channels": ["body"],
                "agentSelectable": True,
                "live2d": {"motionGroups": ["MochiWave"]},
            }
        ]
    )
    pack = {
        "targetSkin": target,
        "name": "test-pack",
        "license": license_text,
        "motions": motions,
        "actions": actions,
    }
    pack.update(pack_over or {})
    motion3 = motion3 if motion3 is not None else VALID_MOTION3
    p = f"{subdir}/" if subdir else ""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{p}pack.json", json.dumps(pack))
        for m in motions:
            zf.writestr(f"{p}{m['file']}", json.dumps(motion3))
        for name, data in (extra_members or {}).items():
            zf.writestr(f"{p}{name}", data)
    return buf.getvalue()


def _post_skin(client, content: bytes):
    return client.post("/skins/import", files={"file": ("skin.zip", content)})


def _post_pack(client, content: bytes):
    return client.post(
        "/skins/import-motion-pack",
        files={"file": ("pack.zip", content, "application/octet-stream")},
    )


def _skin_json(skin_id: str = "zipcat") -> dict:
    return json.loads((get_skins_dir() / skin_id / "skin.json").read_text(encoding="utf-8"))


def _model3_json(skin_id: str = "zipcat") -> dict:
    return json.loads((get_skins_dir() / skin_id / "m.model3.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 正常导入
# ---------------------------------------------------------------------------


def test_import_motion_pack_merges_model3_and_skin(client):
    resp = _post_skin(client, _zip_skin())
    assert resp.status_code == 201
    resp = _post_pack(client, _zip_pack())
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "zipcat"
    assert body["capabilities"]["motionGroups"] == ["MochiWave"]
    assert {a["id"] for a in body["actions"]} == {"wave", "wave_hand"}

    # 落盘核对
    skin_dir = get_skins_dir() / "zipcat"
    assert (skin_dir / "motions" / "wave.motion3.json").is_file()
    model3 = _model3_json()
    assert model3["FileReferences"]["Motions"]["MochiWave"] == [
        {"File": "motions/wave.motion3.json"}
    ]
    skin = _skin_json()
    assert "MochiWave" in skin["capabilities"]["motionGroups"]
    assert any(a["id"] == "wave_hand" for a in skin["actions"])
    assert skin["credits"]["motionPack:test-pack"] == "CC0 原创动作"

    # 备份（首次原始状态）与注册表更新
    backup = json.loads((skin_dir / "m.model3.orig.json").read_text(encoding="utf-8"))
    assert backup["FileReferences"].get("Motions", {}) == {}
    assert any(a["id"] == "wave_hand" for a in (resp.json()["actions"]))


def test_import_motion_pack_nested_dir(client):
    """pack.json 在单层子目录内（与皮肤包同惯例），动作文件随前缀解包。"""
    _post_skin(client, _zip_skin())
    resp = _post_pack(client, _zip_pack(subdir="pack"))
    assert resp.status_code == 200
    assert (get_skins_dir() / "zipcat" / "motions" / "wave.motion3.json").is_file()


def test_envelope_only_action_allowed_without_motion_group(client):
    """包络-only 动作（不引用 motion 组）合法——L2/L3 混合扩展包。"""
    _post_skin(client, _zip_skin())
    resp = _post_pack(
        client,
        _zip_pack(
            actions=[
                {
                    "id": "wink",
                    "channels": ["body"],
                    "agentSelectable": True,
                    "live2d": {
                        "paramEnvelope": {
                            "durationMs": 700,
                            "keyframes": [{"param": "ParamEyeLOpen", "points": [[0, 0], [700, 1]]}],
                        }
                    },
                }
            ]
        ),
    )
    assert resp.status_code == 200


def test_second_pack_appends_and_keeps_first_backup(client):
    """同一皮肤多次扩展：组名不同则成功，且首次备份不被覆盖。"""
    _post_skin(client, _zip_skin())
    assert _post_pack(client, _zip_pack()).status_code == 200
    first_backup = (get_skins_dir() / "zipcat" / "m.model3.orig.json").read_bytes()
    resp = _post_pack(
        client,
        _zip_pack(
            motions=[{"group": "MochiJump", "file": "motions/jump.motion3.json"}],
            actions=[
                {
                    "id": "jump",
                    "channels": ["body"],
                    "agentSelectable": True,
                    "live2d": {"motionGroups": ["MochiJump"]},
                }
            ],
            pack_over={"name": "pack-2"},
        ),
    )
    assert resp.status_code == 200
    assert _model3_json()["FileReferences"]["Motions"]["MochiJump"] == [
        {"File": "motions/jump.motion3.json"}
    ]
    assert (get_skins_dir() / "zipcat" / "m.model3.orig.json").read_bytes() == first_backup
    assert _skin_json()["credits"]["motionPack:pack-2"] == "CC0 原创动作"


# ---------------------------------------------------------------------------
# 校验拒绝
# ---------------------------------------------------------------------------


def test_reject_missing_pack_json(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("other.json", "{}")
    resp = _post_pack(client, buf.getvalue())
    assert resp.status_code == 422
    assert "pack.json" in resp.json()["detail"]


def test_reject_bad_pack_json(client):
    _post_skin(client, _zip_skin())
    resp = _post_pack(
        client,
        _zip_pack(
            actions=[
                {"id": "wave_hand", "channels": ["body"], "agentSelectable": True, "live2d": {}}
            ]
        ),
    )
    # 动作未引用组且无包络 → motionGroups 缺省为空 → 合法结构；改用引用未声明组触发 422
    assert resp.status_code == 200
    resp = _post_pack(
        client,
        _zip_pack(
            motions=[{"group": "MochiJump", "file": "motions/jump.motion3.json"}],
            actions=[
                {
                    "id": "wave_hand2",
                    "channels": ["body"],
                    "agentSelectable": True,
                    "live2d": {"motionGroups": ["NotDeclared"]},
                }
            ],
        ),
    )
    assert resp.status_code == 422
    assert "NotDeclared" in resp.json()["detail"]


def test_reject_missing_motion_file(client):
    _post_skin(client, _zip_skin())
    buf = io.BytesIO()
    pack = {
        "targetSkin": "zipcat",
        "license": "CC0",
        "motions": [{"group": "G", "file": "motions/wave.motion3.json"}],
        "actions": [{"id": "wave_hand", "channels": ["body"], "live2d": {"motionGroups": ["G"]}}],
    }
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("pack.json", json.dumps(pack))
    resp = _post_pack(client, buf.getvalue())
    assert resp.status_code == 422
    assert "wave.motion3.json" in resp.json()["detail"]


def test_reject_invalid_motion3(client):
    _post_skin(client, _zip_skin())
    for name, motion3 in [
        ("version", {**VALID_MOTION3, "Version": 2}),
        ("duration", {**VALID_MOTION3, "Meta": {"Duration": 0}}),
        (
            "endpoint-exceeds",
            {
                "Version": 3,
                "Meta": {"Duration": 0.05},
                "Curves": VALID_MOTION3["Curves"],
            },
        ),
        (
            "bad-mark",
            {
                "Version": 3,
                "Meta": {"Duration": 1.0},
                "Curves": [{"Target": "Parameter", "Id": "P", "Segments": [0, 0, 9, 0.1, 10]}],
            },
        ),
        (
            "target-model",
            {
                "Version": 3,
                "Meta": {"Duration": 1.0},
                "Curves": [{"Target": "Model", "Id": "P", "Segments": [0, 0, 0, 0.1, 10]}],
            },
        ),
    ]:
        resp = _post_pack(client, _zip_pack(motion3=motion3))
        assert resp.status_code == 422, name


def test_reject_unknown_target_skin(client):
    resp = _post_pack(client, _zip_pack(target="ghost"))
    assert resp.status_code == 422
    assert "ghost" in resp.json()["detail"]


def test_reject_group_name_clash(client):
    """组名冲突 409：不静默覆盖既有组。"""
    _post_skin(client, _zip_skin(model3_motions={"TapBody": []}))
    resp = _post_pack(
        client,
        _zip_pack(
            motions=[{"group": "TapBody", "file": "motions/w.motion3.json"}],
            actions=[
                {"id": "tap_body", "channels": ["body"], "live2d": {"motionGroups": ["TapBody"]}}
            ],
        ),
    )
    assert resp.status_code == 409
    assert "TapBody" in resp.json()["detail"]


def test_reject_action_id_clash(client):
    _post_skin(client, _zip_skin())
    resp = _post_pack(
        client,
        _zip_pack(
            actions=[
                {"id": "wave", "channels": ["body"], "live2d": {"motionGroups": ["MochiWave"]}}
            ]
        ),
    )
    assert resp.status_code == 409
    assert "wave" in resp.json()["detail"]


def test_reject_zip_slip(client):
    _post_skin(client, _zip_skin())
    resp = _post_pack(
        client,
        _zip_pack(
            motions=[{"group": "MochiWave", "file": "motions/wave.motion3.json"}],
            extra_members={"motions/../../evil.txt": b"evil"},
        ),
    )
    assert resp.status_code == 422
    assert "越权" in resp.json()["detail"]


def test_reject_non_zip(client):
    resp = _post_pack(client, b"not a zip")
    assert resp.status_code == 422
