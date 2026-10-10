"""皮肤导入测试（M1-S1，3.5 zip 导入校验）：清单校验、zip-slip、冲突。

PNG 图片导入（原 3.4「图片即皮肤」）已随静态皮肤类型下线移除；
static 清单的 zip 导入给出可读的「已下线」文案。
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


def _zip_skin(**manifest_over) -> bytes:
    manifest = {
        "id": "zipcat",
        "name": "ZipCat",
        "resourceType": "live2d",
        "modelFile": "m.model3.json",
    }
    manifest.update(manifest_over)
    manifest = {k: v for k, v in manifest.items() if v is not None}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("skin.json", json.dumps(manifest))
        zf.writestr("m.model3.json", b'{"type":"Model"}')
    return buf.getvalue()


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app(config=AppConfig())) as c:
        yield c


def _post(client, content: bytes, filename="up.bin", **forms):
    return client.post(
        "/skins/import", files={"file": (filename, content, "application/octet-stream")}, data=forms
    )


# ---------------------------------------------------------------------------
# zip 导入
# ---------------------------------------------------------------------------


def test_import_zip_live2d(client):
    resp = _post(client, _zip_skin())
    assert resp.status_code == 201
    body = resp.json()
    assert body["source"] == "user"
    assert body["resourceType"] == "live2d"
    assert (get_skins_dir() / "zipcat" / "skin.json").is_file()
    assert (get_skins_dir() / "zipcat" / "m.model3.json").is_file()


def test_import_zip_missing_model_file_422(client):
    """modelFile 已声明但 zip 内缺文件 → 可读 422。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "skin.json",
            json.dumps(
                {"id": "z2", "name": "Z", "resourceType": "live2d", "modelFile": "nope.json"}
            ),
        )
    resp = _post(client, buf.getvalue())
    assert resp.status_code == 422
    assert "模型文件" in resp.json()["detail"]


def test_import_zip_manifest_without_model_file_422(client):
    """清单缺 modelFile 字段 → 清单校验失败。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("skin.json", json.dumps({"id": "z3", "name": "Z", "resourceType": "live2d"}))
    resp = _post(client, buf.getvalue())
    assert resp.status_code == 422
    assert "skin.json 校验失败" in resp.json()["detail"]


def test_import_zip_static_manifest_rejected_friendly(client):
    """静态皮肤类型已下线：给出可读文案而非 pydantic 原始报错。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "skin.json",
            json.dumps({"id": "old", "name": "O", "resourceType": "static", "imageFile": "a.png"}),
        )
        zf.writestr("a.png", b"png")
    resp = _post(client, buf.getvalue())
    assert resp.status_code == 422
    assert "静态皮肤类型已下线" in resp.json()["detail"]


def test_import_zip_conflict_409(client):
    assert _post(client, _zip_skin(), skin_id="dup").status_code == 201
    resp = _post(client, _zip_skin(), skin_id="dup")
    assert resp.status_code == 409


def test_import_zip_bad_id_422(client):
    assert _post(client, _zip_skin(), skin_id="Bad_ID").status_code == 422


def test_import_zip_nested_top_dir_flattened(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        manifest = {
            "id": "nested",
            "name": "N",
            "resourceType": "live2d",
            "modelFile": "m.model3.json",
        }
        zf.writestr("pkg/skin.json", json.dumps(manifest))
        zf.writestr("pkg/m.model3.json", b'{"type":"Model"}')
    resp = _post(client, buf.getvalue())
    assert resp.status_code == 201
    assert (get_skins_dir() / "nested" / "skin.json").is_file()


def test_import_zip_missing_manifest_422(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("m.model3.json", b"{}")
    resp = _post(client, buf.getvalue())
    assert resp.status_code == 422
    assert "skin.json" in resp.json()["detail"]


def test_import_zip_bad_manifest_422(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("skin.json", "{broken")
    assert _post(client, buf.getvalue()).status_code == 422


def test_import_zip_slip_blocked(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("skin.json", json.dumps(_zip_skin_payload()))
        zf.writestr("m.model3.json", b'{"type":"Model"}')  # 资源齐备，唯一违规是越权成员
        zf.writestr("../evil.png", b"x")
    resp = _post(client, buf.getvalue())
    assert resp.status_code == 422
    assert "越权路径" in resp.json()["detail"]
    assert not (get_skins_dir() / "slip").exists()


def _zip_skin_payload() -> dict:
    return {
        "id": "slip",
        "name": "S",
        "resourceType": "live2d",
        "modelFile": "m.model3.json",
    }


# ---------------------------------------------------------------------------
# 分流兜底
# ---------------------------------------------------------------------------


def test_import_png_rejected_friendly(client):
    """PNG 导入已下线：给出可读文案。"""
    resp = _post(client, b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    assert resp.status_code == 422
    assert "PNG 图片导入已随静态皮肤类型下线" in resp.json()["detail"]


def test_import_unknown_format_422(client):
    resp = _post(client, b"\x00\x01\x02\x03garbage")
    assert resp.status_code == 422
    assert "zip 皮肤包" in resp.json()["detail"]


def _vrm_file(*, version="1.0", meta=None, extensions=None, resources=None) -> bytes:
    import struct

    if extensions is None:
        extension = (
            {
                "meta": meta
                or {
                    "name": "温柔角色",
                    "authors": ["角色作者"],
                    "licenseUrl": "https://example.com/license",
                },
                "humanoid": {"humanBones": {"hips": {"node": 0}}},
            }
            if version == "1.0"
            else {
                "meta": meta or {"title": "旧版角色", "author": "旧版作者", "licenseName": "CC_BY"},
                "humanoid": {"humanBones": [{"bone": "hips", "node": 0}]},
            }
        )
        extensions = {"VRMC_vrm" if version == "1.0" else "VRM": extension}
    document = {
        "asset": {"version": "2.0"},
        "nodes": [{}],
        "extensions": extensions,
        **(resources or {}),
    }
    data = json.dumps(document, ensure_ascii=False).encode()
    data += b" " * (-len(data) % 4)
    return struct.pack("<4sIIII", b"glTF", 2, 20 + len(data), len(data), 0x4E4F534A) + data


@pytest.mark.parametrize("version", ["1.0", "0.0"])
def test_import_raw_vrm_preserves_bytes_and_embedded_credits(client, version):
    from mochi_server.skin.registry import SkinRegistry

    content = _vrm_file(version=version)
    response = _post(client, content, filename="my-character.vrm")
    assert response.status_code == 201
    entry = response.json()
    assert entry["resourceType"] == "vrm"
    assert entry["source"] == "user"
    assert entry["id"].startswith("vrm-")
    assert entry["name"] == ("温柔角色" if version == "1.0" else "旧版角色")
    assert entry["credits"]["model"] == ("角色作者" if version == "1.0" else "旧版作者")
    assert entry["license"] == ("https://example.com/license" if version == "1.0" else "CC_BY")
    assert client.get(f"/user-skins/{entry['id']}/model.vrm").content == content
    assert SkinRegistry().get(entry["id"]).name == entry["name"]
    assert client.put("/config/character", json={"activeSkin": entry["id"]}).status_code == 200
    assert client.get("/config/character").json()["activeSkin"] == entry["id"]


def test_reimport_vrm_uses_distinct_ids_and_does_not_replace_mochi(client):
    first = _post(client, _vrm_file(), filename="same.vrm").json()
    second = _post(client, _vrm_file(), filename="same.vrm").json()
    assert first["id"] != second["id"]
    assert _post(client, _vrm_file(), filename="same.vrm", skin_id="mochi-vrm").status_code == 409
    assert [s["id"] for s in client.get("/skins").json() if s["source"] == "builtin"] == [
        "mochi-vrm"
    ]


@pytest.mark.parametrize(
    "content",
    [
        b"not-a-vrm",
        _vrm_file(extensions={}),
        _vrm_file(extensions={"VRMC_vrm_animation": {}}),
        _vrm_file()[:-1],
    ],
)
def test_raw_vrm_rejects_invalid_or_non_character_files_without_creating_dirs(client, content):
    response = _post(client, content, filename="renamed.vrm")
    assert response.status_code == 422
    assert "VRM 校验失败" in response.json()["detail"]
    assert list(get_skins_dir().iterdir()) == []


def test_vrm_rejects_external_resources(client):
    response = _post(
        client,
        _vrm_file(resources={"images": [{"uri": "https://example.com/texture.png"}]}),
        filename="external.vrm",
    )
    assert response.status_code == 422
    assert "外部资源" in response.json()["detail"]


def test_vrm_file_limit_is_checked_before_parsing(client, monkeypatch):
    monkeypatch.setattr("mochi_server.skin.importer.MAX_VRM_SIZE", 10)
    response = _post(client, _vrm_file(), filename="large.vrm")
    assert response.status_code == 422
    assert "文件过大" in response.json()["detail"]
