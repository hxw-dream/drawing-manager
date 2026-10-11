"""API 集成测试：扫描 → 搜索 → 版本 → 项目隔离 → 清册导出。"""
import time

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, base_url="http://127.0.0.1")  # Host 校验只放行本机回环


def _scan_until_done(root, project_id=1, timeout=120):
    client.post("/api/scan", json={"root": root, "project_id": project_id})
    for _ in range(timeout * 2):
        st = client.get("/api/scan/status").json()
        if not st["running"]:
            return st
        time.sleep(0.5)
    raise AssertionError("扫描超时")


def test_full_flow_search_and_versions(tmp_db, sample_library):
    st = _scan_until_done(str(sample_library))
    assert st["report"]["ok"] == 2

    # 分字匹配：不连续的"照明布置"
    r = client.get("/api/search", params={"q": "照明布置", "project": 1}).json()
    assert r["entry_groups"]
    first = r["entry_groups"][0]
    assert "照明" in first["versions"][0]["title"]

    # 版本对比：D0401-02 多版本
    v = client.get("/api/versions", params={"project": 1}).json()
    g = next(x for x in v["groups"] if x["drawing_no"] == "F10001-D0401-02")
    assert len(g["versions"]) == 2
    dates = [x["ver_date"] for x in g["versions"]]
    assert "2025.03.09" in dates and dates[0] is None  # 旧→新，原版在前


def test_project_isolation(tmp_db, sample_library, tmp_path):
    _scan_until_done(str(sample_library))
    # 建第二项目，扫一个空目录归入它
    other = tmp_path / "empty"
    other.mkdir()
    pj = client.post("/api/projects", json={"name": "隔离测试"}).json()
    _scan_until_done(str(other), project_id=pj["id"])
    # 分配已有文件夹到第二项目 → 默认项目不再可见
    client.post("/api/folders/assign", json={"root": str(sample_library), "project_id": pj["id"]})
    in_p2 = client.get("/api/volumes", params={"project": pj["id"]}).json()
    in_p1 = client.get("/api/volumes", params={"project": 1}).json()
    assert len(in_p2) == 2 and len(in_p1) == 0
    # 搜索同步隔离
    s1 = client.get("/api/search", params={"q": "照明", "project": 1}).json()
    s2 = client.get("/api/search", params={"q": "照明", "project": pj["id"]}).json()
    assert not s1["entry_groups"] and s2["entry_groups"]


def test_project_crud_and_guards(tmp_db):
    assert client.get("/api/projects").json()[0]["name"] == "默认项目"
    pj = client.post("/api/projects", json={"name": "甲项目"}).json()
    assert client.post("/api/projects", json={"name": "甲项目"}).status_code == 409  # 重名
    assert client.post("/api/projects/delete", json={"id": 1}).status_code == 400  # 默认项目不可删
    assert client.post("/api/projects/delete", json={"id": pj["id"]}).json()["ok"]
    assert client.post("/api/projects/rename", json={"id": 1, "name": ""}).status_code == 400


def test_host_guard_and_inventory_export(tmp_db, sample_library):
    _scan_until_done(str(sample_library))
    # Host 校验：伪造 Host 被拒
    assert client.get("/api/projects", headers={"Host": "evil.com"}).status_code == 403
    # 导出为合法 xlsx
    resp = client.get("/api/inventory/export", params={"project": 1})
    assert resp.status_code == 200
    assert resp.content[:2] == b"PK"  # xlsx 是 zip 包
    assert "spreadsheetml" in resp.headers["content-type"]


def test_search_blank_query_returns_nothing(tmp_db, sample_library):
    _scan_until_done(str(sample_library))
    r = client.get("/api/search", params={"q": "   "}).json()
    assert r["entry_groups"] == [] and r["volume_hits"] == []


def test_rename_rejects_empty_root(tmp_db):
    assert client.post("/api/folders/rename",
                       json={"root": "  ", "name": "x"}).status_code == 400
