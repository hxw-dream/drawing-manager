"""停止扫描 / 删除册（忽略与恢复） / PDF 优先识别。"""
import time

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import make_volume

client = TestClient(app, base_url="http://127.0.0.1")


def _scan_until_done(root, project_id=1, timeout=180):
    client.post("/api/scan", json={"root": root, "project_id": project_id})
    for _ in range(timeout * 2):
        st = client.get("/api/scan/status").json()
        if not st["running"]:
            return st
        time.sleep(0.5)
    raise AssertionError("扫描超时")


def test_stop_scan_between_volumes(tmp_db, sample_library):
    # 冷扫（每册都要 OCR，有充足的停止窗口）
    client.post("/api/scan", json={"root": str(sample_library), "project_id": 1})
    time.sleep(1.0)  # 等第一册开始解析
    assert client.post("/api/scan/stop").status_code == 200
    st = None
    for _ in range(120):
        st = client.get("/api/scan/status").json()
        if not st["running"]:
            break
        time.sleep(0.5)
    assert st["report"]["stopped"] is True
    assert st["report"]["ok"] < st["report"]["found"]
    assert client.post("/api/scan/stop").status_code == 409  # 空闲时停止被拒


def test_delete_and_restore_volume(tmp_db, sample_library):
    _scan_until_done(str(sample_library))
    vols = client.get("/api/volumes", params={"project": 1}).json()
    target = vols[0]["folder_path"]

    client.post("/api/volumes/delete", json={"folder_path": target})
    rest = client.get("/api/volumes", params={"project": 1}).json()
    assert target not in [v["folder_path"] for v in rest]
    ignored = client.get("/api/volumes/ignored").json()
    assert [i["folder_path"] for i in ignored] == [target]

    _scan_until_done(str(sample_library))  # 重扫不会把已移除的册带回来
    rest = client.get("/api/volumes", params={"project": 1}).json()
    assert target not in [v["folder_path"] for v in rest]

    client.post("/api/volumes/restore", json={"folder_path": target})
    assert client.get("/api/volumes/ignored").json() == []
    _scan_until_done(str(sample_library))  # 恢复后重扫重新入库
    rest = client.get("/api/volumes", params={"project": 1}).json()
    assert target in [v["folder_path"] for v in rest]
    # 重复删除已有索引外的册 → 404
    assert client.post("/api/volumes/delete",
                       json={"folder_path": r"D:\不存在"}).status_code == 404


def test_pdf_ml_preferred_over_dwg(tmp_db, tmp_path):
    root = tmp_path / "tuzhi"
    root.mkdir()
    vol = make_volume(root, "D0401【综合办公楼照明施工图】-2024.5.7-改明敷", "ml-demo-lighting-scanned.pdf")
    # 同册再放入一个 DWG 目录文件：应仍按 PDF 解析
    (vol / "F10001-D0401-ML.dwg").write_bytes(b"fake dwg")
    st = _scan_until_done(str(root))
    assert st["report"]["ok"] == 1
    from app.db import connect
    with connect() as conn:
        v = conn.execute("SELECT parse_method, ml_file FROM volumes").fetchone()
        assert v["ml_file"].lower().endswith(".pdf")
        assert v["parse_method"] in ("ocr", "text")  # 走的是 PDF 管道
    # 双 ML 场景：DWG 那份不算"未入目录的散文件"
    r = client.get("/api/search", params={"q": "ML.dwg", "project": 1}).json()
    assert r["loose_files"] == []


def test_delete_whole_folder_and_restore_all(tmp_db, sample_library):
    _scan_until_done(str(sample_library))
    root = str(sample_library)
    before = len(client.get("/api/volumes", params={"project": 1}).json())
    assert before == 2

    r = client.post("/api/folders/delete", json={"root": root}).json()
    assert r["removed"] == 2
    assert client.get("/api/volumes", params={"project": 1}).json() == []
    assert len(client.get("/api/volumes/ignored").json()) == 2

    _scan_until_done(root)  # 重扫不回来
    assert client.get("/api/volumes", params={"project": 1}).json() == []

    for g in client.get("/api/volumes/ignored").json():  # 全部恢复
        client.post("/api/volumes/restore", json={"folder_path": g["folder_path"]})
    _scan_until_done(root)
    assert len(client.get("/api/volumes", params={"project": 1}).json()) == 2
    # 空路径/未知路径保护
    assert client.post("/api/folders/delete", json={"root": "  "}).status_code == 400
    assert client.post("/api/folders/delete",
                       json={"root": r"D:\不存在"}).status_code == 404
