"""动作库 REST 端点测试（ADR-0011 P2.7）：导入/修改/删除/资源分发。

动画内容由前端加载时校验；此处覆盖结构与生命周期语义
（id 命名空间、扩展白名单、409/422/404、路径穿越）。
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from mochi_server.config import AppConfig
from mochi_server.main import create_app


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app(config=AppConfig())) as c:
        yield c


def _import(client: TestClient, motion_id: str, label: str = "测试动作", **overrides) -> object:
    fields = {
        "id": motion_id,
        "label": label,
        "kind": "oneshot",
        "durationMs": 2000,
        "priority": 50,
        "cooldownMs": 0,
        "agentSelectable": False,
        "tags": "",
    }
    fields.update(overrides)
    return client.post(
        "/motions",
        data=fields,
        files={"file": ("my.vrma", io.BytesIO(b"glb-container-bytes"), "application/octet-stream")},
    )


# ---------------------------------------------------------------------------
# GET /motions + POST /motions
# ---------------------------------------------------------------------------


def test_list_empty_then_import_roundtrip(client: TestClient) -> None:
    assert client.get("/motions").json() == []

    credit = "Animation credits to pixiv Inc.'s VRoid Project"
    resp = _import(
        client, "ext.demo.my_wave", label="我的挥手", tags="idle,greeting", credit=credit
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == "ext.demo.my_wave"
    assert body["file"] == "ext.demo.my_wave.vrma"
    assert body["agentSelectable"] is False  # 白名单铁律默认关
    assert sorted(body["tags"]) == ["greeting", "idle"]
    assert body["createdAt"]
    assert body["credit"] == credit

    listed = client.get("/motions").json()
    assert [m["id"] for m in listed] == ["ext.demo.my_wave"]
    assert listed[0]["credit"] == credit

    # 资源分发：文件可取回
    file_resp = client.get(f"/motion-library/{body['file']}")
    assert file_resp.status_code == 200
    assert file_resp.content == b"glb-container-bytes"


def test_import_official_word_id_allowed(client: TestClient) -> None:
    """下载的文件可绑定挥手用途，不需要代码内置实现。"""
    assert _import(client, "wave").status_code == 201


def test_import_categories_credit_and_duration(client: TestClient) -> None:
    resp = _import(client, "wave", category="builtin", durationMs=7267, credit="作者署名")
    assert resp.status_code == 201
    assert resp.json()["category"] == "builtin"
    updated = client.patch(
        "/motions/wave",
        json={
            "category": "custom",
            "credit": "新署名",
            "durationMs": 1000,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["category"] == "custom"
    assert updated.json()["credit"] == "新署名"
    assert updated.json()["durationMs"] == 7267
    assert client.patch("/motions/wave", json={"category": "generated"}).status_code == 422


@pytest.mark.parametrize("suffix", ["glb", "fbx"])
def test_only_downloaded_vrma_extension_allowed(client: TestClient, suffix: str) -> None:
    resp = client.post(
        "/motions",
        data={"id": "wave", "label": "挥手"},
        files={"file": (f"motion.{suffix}", b"bytes", "application/octet-stream")},
    )
    assert resp.status_code == 422
    assert client.get("/motions").json() == []


def test_vrm_capabilities_follow_imports_and_deletes(client: TestClient) -> None:
    from mochi_server.agent.cue_extractor import cue_prompt_section
    from mochi_server.skin_manifest import SkinManifest

    registry = client.app.state.registry
    skin = SkinManifest(id="test-vrm", name="Mochi", resourceType="vrm", modelFile="model.vrm")
    registry._skin_registry.get = lambda _: skin
    assert registry._performance_skin().actions == []
    empty_prompt = cue_prompt_section(registry._performance_skin())
    assert "尚未导入" in empty_prompt
    assert "挥手(wave)" not in empty_prompt

    assert _import(client, "wave", category="builtin", agentSelectable=True).status_code == 201
    assert _import(client, "nod", agentSelectable=False).status_code == 201
    assert _import(client, "ext.user.manual").status_code == 201
    prompt = cue_prompt_section(registry._performance_skin())
    assert "挥手(wave)" in prompt
    assert "点头(nod)" not in prompt
    assert "manual" not in prompt
    client.delete("/motions/wave")
    assert "尚未导入" in cue_prompt_section(registry._performance_skin())


def test_browser_metadata_patch_preflight(client: TestClient) -> None:
    response = client.options(
        "/motions/wave",
        headers={
            "Origin": "http://localhost:1420",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert "PATCH" in response.headers["access-control-allow-methods"]


def test_import_conflict_409(client: TestClient) -> None:
    assert _import(client, "ext.demo.x").status_code == 201
    assert _import(client, "ext.demo.x").status_code == 409


def test_conflict_identifies_visible_name_and_keeps_existing_motion(client: TestClient) -> None:
    assert _import(client, "wave", label="比V").status_code == 201
    response = _import(client, "wave", label="打招呼")
    assert response.status_code == 409
    assert "比V" in response.json()["detail"]
    assert "挥手" in response.json()["detail"]
    assert client.get("/motions").json()[0]["label"] == "比V"


def test_import_bad_extension_422(client: TestClient) -> None:
    resp = client.post(
        "/motions",
        data={"id": "ext.demo.x", "label": "x"},
        files={"file": ("evil.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
    )
    assert resp.status_code == 422
    assert "不支持的动作文件格式" in resp.json()["detail"]


def test_import_bad_id_422(client: TestClient) -> None:
    assert _import(client, "Bad-ID").status_code == 422
    assert _import(client, "ext.x").status_code == 422  # 命名空间过短
    assert _import(client, "ext.demo.BAD_NAME").status_code == 422


def test_import_unknown_tag_422(client: TestClient) -> None:
    assert _import(client, "ext.demo.x", tags="swim").status_code == 422


# ---------------------------------------------------------------------------
# PATCH /motions/{id}
# ---------------------------------------------------------------------------


def test_update_metadata(client: TestClient) -> None:
    assert _import(client, "ext.demo.y", label="旧名").status_code == 201
    resp = client.patch(
        "/motions/ext.demo.y",
        json={
            "label": "新名",
            "priority": 80,
            "cooldownMs": 5000,
            "agentSelectable": True,
            "tags": ["idle"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["label"] == "新名"
    assert body["priority"] == 80
    assert body["agentSelectable"] is True


def test_update_id_or_file_rejected(client: TestClient) -> None:
    assert _import(client, "ext.demo.z").status_code == 201
    assert client.patch("/motions/ext.demo.z", json={"id": "ext.demo.other"}).status_code == 422
    assert client.patch("/motions/ext.demo.z", json={"file": "a.vrma"}).status_code == 422


def test_update_missing_404(client: TestClient) -> None:
    assert client.patch("/motions/ext.demo.none", json={"label": "x"}).status_code == 404


# ---------------------------------------------------------------------------
# DELETE /motions/{id} + 资源穿越
# ---------------------------------------------------------------------------


def test_delete_roundtrip(client: TestClient) -> None:
    assert _import(client, "ext.demo.del").status_code == 201
    assert client.delete("/motions/ext.demo.del").status_code == 204
    assert client.delete("/motions/ext.demo.del").status_code == 404
    assert client.get("/motions").json() == []
    # 文件一并清除
    assert client.get("/motion-library/ext.demo.del.vrma").status_code == 404


def test_motion_file_path_traversal_404(client: TestClient) -> None:
    assert client.get("/motion-library/..%2Findex.json").status_code == 404
    assert client.get("/motion-library/../../etc/passwd").status_code == 404


@pytest.fixture
def role_pack(tmp_path, monkeypatch):
    import json

    pack = tmp_path / "role-defaults"
    (pack / "motions").mkdir(parents=True)
    (pack / "motions/wave.vrma").write_bytes(b"original-role-wave")
    entry = {
        "id": "wave",
        "label": "角色挥手",
        "durationMs": 5000,
        "file": "wave.vrma",
        "category": "builtin",
        "source": "builtin",
        "skinId": "mochi-vrm",
        "credit": "原作者",
        "agentSelectable": True,
    }
    (pack / "index.json").write_text(json.dumps({"motions": [entry]}))
    monkeypatch.setenv("MOCHI_BUILTIN_MOTIONS_DIR", str(pack))
    return pack


def test_role_defaults_available_on_fresh_install(role_pack):
    with TestClient(create_app(config=AppConfig())) as client:
        entries = client.get("/motions?skinId=mochi-vrm").json()
        assert [(e["label"], e["source"]) for e in entries] == [("角色挥手", "builtin")]
        assert client.get("/motion-library/wave.vrma").content == b"original-role-wave"
        assert client.get("/motions?skinId=seed-san").json() == []
        assert _import(client, "wave").status_code == 409
        assert client.delete("/motions/wave").status_code == 403
        assert (role_pack / "motions/wave.vrma").read_bytes() == b"original-role-wave"


def test_role_metadata_overrides_persist_without_modifying_resources(role_pack):
    from mochi_server.motion.library import MotionLibrary

    original_index = (role_pack / "index.json").read_bytes()
    with TestClient(create_app(config=AppConfig())) as client:
        response = client.patch(
            "/motions/wave",
            json={
                "label": "温柔挥手",
                "agentSelectable": False,
                "tags": ["idle"],
                "credit": "覆盖署名",
                "category": "custom",
            },
        )
        assert response.status_code == 200
        entry = response.json()
        assert entry["credit"] == "原作者"
        assert entry["category"] == "builtin"
        client.app.state.motion_library = MotionLibrary()
        entries = client.get("/motions").json()
        assert len(entries) == 1
        assert entries[0]["label"] == "温柔挥手"
        assert entries[0]["agentSelectable"] is False
        assert entries[0]["tags"] == ["idle"]
        assert client.get("/motion-library/wave.vrma").content == b"original-role-wave"
    assert (role_pack / "index.json").read_bytes() == original_index


def test_existing_user_import_is_merged_with_role_default(tmp_path, monkeypatch):
    import json

    from mochi_server.motion.library import MotionLibrary

    empty = tmp_path / "empty"
    library = MotionLibrary(defaults_dir=empty)
    from mochi_server.motion.library import MotionEntry

    library.create(MotionEntry(id="wave", label="我保留的名称", file="wave.vrma"), b"original")
    pack = tmp_path / "defaults"
    (pack / "motions").mkdir(parents=True)
    (pack / "motions/wave.vrma").write_bytes(b"original")
    (pack / "index.json").write_text(
        json.dumps(
            {
                "motions": [
                    {
                        "id": "wave",
                        "label": "默认名称",
                        "file": "wave.vrma",
                        "skinId": "mochi-vrm",
                    }
                ]
            }
        )
    )
    entries = MotionLibrary(defaults_dir=pack).list_all("mochi-vrm")
    assert len(entries) == 1
    assert entries[0].label == "我保留的名称"
    assert entries[0].source == "builtin"
