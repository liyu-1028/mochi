"""皮肤导入测试（M1-S1，3.4/3.5）：PNG/zip 分流、校验、zip-slip、冲突。"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from mochi_server.config import AppConfig
from mochi_server.main import create_app
from mochi_server.paths import get_skins_dir

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _fake_png(width: int = 512, height: int = 512) -> bytes:
    """仅满足 magic + IHDR 宽高读取的最小 PNG 形状（导入不做解码）。"""
    return _PNG_MAGIC + b"\x00" * 8 + width.to_bytes(4, "big") + height.to_bytes(4, "big")


def _zip_skin(**manifest_over) -> bytes:
    manifest = {"id": "zipcat", "name": "ZipCat", "resourceType": "static", "imageFile": "a.png"}
    manifest.update(manifest_over)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("skin.json", json.dumps(manifest))
        zf.writestr("a.png", _fake_png())
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
# PNG
# ---------------------------------------------------------------------------


def test_import_png_creates_static_skin(client):
    resp = _post(client, _fake_png(), skin_name="我的猫")
    assert resp.status_code == 201
    body = resp.json()
    assert body["source"] == "user"
    assert body["resourceType"] == "static"
    skin_id = body["id"]
    assert skin_id.startswith("png-")

    skin_dir = get_skins_dir() / skin_id
    assert (skin_dir / "avatar.png").is_file()
    manifest = json.loads((skin_dir / "skin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "我的猫"
    assert manifest["animation"]["idle"]["float"] is True


def test_import_png_rejects_non_png(client):
    resp = _post(client, b"definitely not a png")
    assert resp.status_code == 422
    assert "PNG" in resp.json()["detail"]


def test_import_png_rejects_truncated(client):
    assert _post(client, _PNG_MAGIC + b"\x00").status_code == 422


def test_import_png_rejects_bad_dimensions(client):
    assert _post(client, _fake_png(width=8000)).status_code == 422
    assert _post(client, _fake_png(width=16)).status_code == 422


def test_import_png_oversize(client):
    assert _post(client, _fake_png() + b"\x00" * (11 * 1024 * 1024)).status_code == 422


def test_import_png_conflict_409(client):
    first = _post(client, _fake_png(), skin_id="dup")
    assert first.status_code == 201
    resp = _post(client, _fake_png(), skin_id="dup")
    assert resp.status_code == 409


def test_import_png_bad_id_422(client):
    assert _post(client, _fake_png(), skin_id="Bad_ID").status_code == 422


# ---------------------------------------------------------------------------
# zip
# ---------------------------------------------------------------------------


def test_import_zip_static(client):
    resp = _post(client, _zip_skin())
    assert resp.status_code == 201
    assert (get_skins_dir() / "zipcat" / "skin.json").is_file()
    assert (get_skins_dir() / "zipcat" / "a.png").is_file()


def test_import_zip_live2d_missing_model_422(client):
    resp = _post(
        client, _zip_skin(resourceType="live2d", modelFile="m.model3.json", imageFile=None)
    )
    assert resp.status_code == 422
    assert "模型文件" in resp.json()["detail"]


def test_import_zip_nested_top_dir_flattened(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        manifest = {"id": "nested", "name": "N", "resourceType": "static", "imageFile": "a.png"}
        zf.writestr("pkg/skin.json", json.dumps(manifest))
        zf.writestr("pkg/a.png", _fake_png())
    resp = _post(client, buf.getvalue())
    assert resp.status_code == 201
    assert (get_skins_dir() / "nested" / "skin.json").is_file()


def test_import_zip_missing_manifest_422(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.png", _fake_png())
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
        manifest = {"id": "slip", "name": "S", "resourceType": "static", "imageFile": "a.png"}
        zf.writestr("skin.json", json.dumps(manifest))
        zf.writestr("a.png", _fake_png())  # 资源齐备，唯一违规是越权成员
        zf.writestr("../evil.png", b"x")
    resp = _post(client, buf.getvalue())
    assert resp.status_code == 422
    assert "越权路径" in resp.json()["detail"]
    assert not (get_skins_dir() / "slip").exists()


# ---------------------------------------------------------------------------
# 分流兜底
# ---------------------------------------------------------------------------


def test_import_unknown_format_422(client):
    resp = _post(client, b"\x00\x01\x02\x03garbage")
    assert resp.status_code == 422
    assert "PNG" in resp.json()["detail"]
