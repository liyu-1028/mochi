"""v0.15.x 发布批次边界补测（2026-10-13 测试计划 §5.5/§5.6 缺口）。

用例 ID 对应 docs/test-reports/2026-10/2026-10-13_full-system_v015x-test-plan.md：
- TC-SKIN-B01 上传体积上限 / 空文件
- TC-SKIN-B02 create 侧文件名穿越（资源侧 404 已有覆盖）
- TC-SKIN-F02 内置动作禁删与可编辑面
- TC-SKIN-B03 索引损坏自愈
- TC-SKIN-S01 并发导入索引一致性（压力）
- TC-SETTING-S02 导出→导入循环无漂移（压力）
"""

from __future__ import annotations

import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from mochi_server import paths
from mochi_server.config import AppConfig
from mochi_server.main import create_app
from mochi_server.motion.library import MotionEntry, MotionLibrary


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app(config=AppConfig())) as c:
        yield c


def _import(
    client: TestClient,
    motion_id: str,
    *,
    content: bytes = b"glb-container-bytes",
    filename: str = "clip.vrma",
    **overrides,
):
    fields = {
        "id": motion_id,
        "label": "测试动作",
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
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
    )


# ---------------------------------------------------------------------------
# TC-SKIN-B01 上传体积与空文件
# ---------------------------------------------------------------------------


def test_import_rejects_file_over_50mb(client: TestClient) -> None:
    oversize = b"x" * (50 * 1024 * 1024 + 1)
    resp = _import(client, "too_big", content=oversize)
    assert resp.status_code == 422
    assert "50MB" in resp.json()["detail"]


def test_import_rejects_empty_file(client: TestClient) -> None:
    resp = _import(client, "empty_motion", content=b"")
    assert resp.status_code == 422
    assert "为空" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# TC-SKIN-B02 create 侧文件名收敛（服务端只取后缀，落盘名由 id 派生）
# ---------------------------------------------------------------------------


def test_import_filename_traversal_is_sanitized(client: TestClient) -> None:
    resp = _import(client, "ext.demo.sneak", filename="../../evil.vrma")
    assert resp.status_code == 201
    body = resp.json()
    assert body["file"] == "ext.demo.sneak.vrma"
    motions_dir = paths.get_motion_library_dir() / "motions"
    assert [p.name for p in motions_dir.iterdir()] == ["ext.demo.sneak.vrma"]


# ---------------------------------------------------------------------------
# TC-SKIN-F02 内置动作：禁删、播放设置可调、category/credit 不可改
# ---------------------------------------------------------------------------


@pytest.fixture
def builtin_client(monkeypatch, tmp_path) -> TestClient:
    pack = tmp_path / "builtin-motions"
    (pack / "motions").mkdir(parents=True)
    (pack / "motions" / "wave.vrma").write_bytes(b"glb-container-bytes")
    (pack / "index.json").write_text(
        json.dumps(
            {
                "motions": [
                    {
                        "id": "wave",
                        "label": "挥手",
                        "kind": "oneshot",
                        "durationMs": 1600,
                        "file": "wave.vrma",
                        "credit": "CC0 author",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MOCHI_BUILTIN_MOTIONS_DIR", str(pack))
    with TestClient(create_app(config=AppConfig())) as c:
        yield c


def test_builtin_motion_delete_forbidden_and_edit_surface(builtin_client: TestClient) -> None:
    listing = builtin_client.get("/motions").json()
    assert [m["id"] for m in listing] == ["wave"]
    assert listing[0]["source"] == "builtin"
    assert listing[0]["credit"] == "CC0 author"

    resp = builtin_client.delete("/motions/wave")
    assert resp.status_code == 403
    assert "内置" in resp.json()["detail"]

    # 播放设置可调（升级保留机制承诺：素材固定、设置归用户）
    resp = builtin_client.patch("/motions/wave", json={"label": "打招呼", "agentSelectable": True})
    assert resp.status_code == 200
    assert resp.json()["label"] == "打招呼"
    assert resp.json()["agentSelectable"] is True

    # category/credit 对内置动作静默忽略，保持原值
    resp = builtin_client.patch("/motions/wave", json={"category": "custom", "credit": "hack"})
    assert resp.status_code == 200
    assert resp.json()["category"] == "builtin"
    assert resp.json()["credit"] == "CC0 author"


# ---------------------------------------------------------------------------
# TC-SKIN-B03 索引损坏自愈
# ---------------------------------------------------------------------------


def test_corrupt_index_self_heals(client: TestClient) -> None:
    assert _import(client, "first").status_code == 201
    index_path = paths.get_motion_library_dir() / "index.json"
    index_path.write_text("{broken-json", encoding="utf-8")

    # 损坏索引按空库处理，不 500
    assert client.get("/motions").json() == []

    # 可继续导入重建索引
    assert _import(client, "second").status_code == 201
    listing = client.get("/motions").json()
    assert [m["id"] for m in listing] == ["second"]
    json.loads(index_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# TC-SKIN-S01 并发导入索引一致性（压力）
# D-1 已修复（2026-10-13）：_write_index 改 tmp+replace 原子写，
# create/update/delete 读改写全程持锁；本用例从 xfail 转正。
# ---------------------------------------------------------------------------


def test_concurrent_imports_keep_index_consistent() -> None:
    library = MotionLibrary()
    count = 16
    barrier = threading.Barrier(count)

    def create_one(i: int) -> str:
        entry = MotionEntry.model_validate(
            {
                "id": f"ext.load.motion_{i}",
                "label": f"压测 {i}",
                "kind": "oneshot",
                "durationMs": 500,
                "file": "placeholder.vrma",
            }
        )
        barrier.wait()
        library.create(entry, b"glb-container-bytes")
        return "ok"

    with ThreadPoolExecutor(max_workers=count) as pool:
        results = list(pool.map(create_one, range(count)))
    assert results == ["ok"] * count

    index = json.loads((paths.get_motion_library_dir() / "index.json").read_text(encoding="utf-8"))
    assert len(index["motions"]) == count  # 无丢失更新


# ---------------------------------------------------------------------------
# TC-SETTING-S02 导出→导入循环无漂移（压力）
# ---------------------------------------------------------------------------


def _snapshot(client: TestClient) -> dict:
    data = client.get("/config/export").json()
    data.pop("exportedAt", None)
    return data


def test_transfer_loop_is_drift_free(client: TestClient) -> None:
    for target, payload in (
        ("/config/voice", {"ttsEnabled": True, "volume": 0.66, "rate": 1.25}),
        ("/config/agent", {"maxReplyChars": 777}),
        ("/config/persona", {"soulCustom": "温柔的伙伴"}),
    ):
        assert client.put(target, json=payload).status_code == 200

    baseline = _snapshot(client)
    for _ in range(10):
        backup = client.get("/config/export").json()
        assert client.post("/config/import", json=backup).status_code == 200
        assert _snapshot(client) == baseline
