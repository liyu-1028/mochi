"""zip 导入边缘场景（清单缺资源键）。"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from mochi_server.config import AppConfig
from mochi_server.main import create_app


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app(config=AppConfig())) as c:
        yield c


def test_missing_model_file_key(client):
    """清单缺 modelFile 字段 → 清单校验失败（422 可读文案）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        manifest = {"id": "nomodel", "name": "N", "resourceType": "live2d"}
        zf.writestr("skin.json", json.dumps(manifest))
    resp = client.post(
        "/skins/import", files={"file": ("skin.zip", buf.getvalue(), "application/zip")}
    )
    assert resp.status_code == 422
