"""在真实浏览器中验证恢复入口及搜索请求的项目隔离。"""
import os
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    args = dict(browser_type_launch_args)
    if executable := os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"):
        args["executable_path"] = executable
    return args


def volume(code="D0401"):
    return {"folder_path": f"C:/library/{code}", "folder_name": code, "scan_root": "C:/library",
            "title": "照明册", "code": code, "entry_count": 1, "file_count": 2, "parse_status": "ok"}


def search_result(text):
    return {"entry_groups": [{"drawing_no": "F10001-D0401-01", "versions": [
        {"title": text, "folder_name": text, "folder_path": "C:/library", "files": []}]}],
        "volume_hits": [], "loose_files": []}


@pytest.fixture()
def ui(page):
    state = {"volumes": [], "ignored": [], "hold_search": False,
             "searches": [], "pending": [], "restored": [], "errors": []}

    def handle(route):
        request = route.request
        url = urlparse(request.url)
        path = url.path
        if not path.startswith("/api/"):
            file = STATIC / (path.lstrip("/") or "index.html")
            if file.is_file():
                route.fulfill(path=str(file))
            else:
                route.fulfill(status=404)
            return
        if path == "/api/projects":
            result = [{"id": 1, "name": "项目1", "folders": 1},
                      {"id": 2, "name": "项目2", "folders": 1}]
        elif path == "/api/scan/status":
            result = {"running": False, "log": [], "report": None, "error": None, "last_root": None}
        elif path == "/api/folders":
            result = {}
        elif path == "/api/volumes":
            result = state["volumes"]
        elif path == "/api/volumes/ignored":
            result = state["ignored"]
        elif path in ("/api/volumes/delete", "/api/folders/delete"):
            body = request.post_data_json
            removed = [v for v in state["volumes"] if
                       (v["folder_path"] == body.get("folder_path") if path.endswith("volumes/delete")
                        else v["scan_root"] == body["root"])]
            state["volumes"] = [v for v in state["volumes"] if v not in removed]
            state["ignored"].extend(removed)
            result = {"ok": True, "removed": len(removed)}
        elif path == "/api/volumes/restore":
            restored = request.post_data_json["folder_path"]
            state["restored"].append(restored)
            state["ignored"] = [v for v in state["ignored"] if v["folder_path"] != restored]
            result = {"ok": True}
        elif path == "/api/search":
            params = parse_qs(url.query)
            state["searches"].append(params)
            if state["hold_search"]:
                state["pending"].append(route)
                return
            result = search_result(f"项目{params['project'][0]}的结果：{params['q'][0]}")
        else:
            route.fulfill(status=404, json={"detail": "未知测试接口"})
            return
        route.fulfill(json=result)

    page.on("dialog", lambda dialog: dialog.accept())
    page.on("pageerror", lambda error: state["errors"].append(str(error)))
    page.route("http://127.0.0.1:8000/**", handle)
    page.goto("http://127.0.0.1:8000/")
    expect(page.locator("#projSel option")).to_have_count(2)
    yield state
    assert not state["errors"]


def wait_pending(page, ui, count):
    deadline = time.monotonic() + 5
    while len(ui["pending"]) < count and time.monotonic() < deadline:
        page.wait_for_timeout(10)
    assert len(ui["pending"]) == count


def test_empty_index_still_allows_restore(page, ui):
    ui["ignored"] = [volume()]
    page.locator('[data-view="volumes"]').click()
    expect(page.locator(".vol-restore")).to_be_visible()
    page.locator(".vol-restore").click()
    expect(page.locator(".vol-restore")).to_have_count(0)
    assert ui["restored"] == [volume()["folder_path"]]


def test_removing_last_volume_keeps_restore_entry(page, ui):
    ui["volumes"] = [volume()]
    page.locator('[data-view="volumes"]').click()
    page.locator(".volcard").click()
    page.locator(".vol-del").click()
    expect(page.locator(".vol-restore")).to_be_visible()
    expect(page.locator("#vol-results")).to_contain_text("索引为空")
    page.locator(".vol-restore").click()
    expect(page.locator(".vol-restore")).to_have_count(0)
    assert ui["restored"] == [volume()["folder_path"]]


def test_removing_entire_library_keeps_restore_all(page, ui):
    ui["volumes"] = [volume(), volume("D0402")]
    page.locator('[data-view="volumes"]').click()
    page.locator(".fol-del").click()
    expect(page.locator(".vol-restore")).to_have_count(2)
    page.locator("#restoreAllBtn").click()
    expect(page.locator(".vol-restore")).to_have_count(0)
    assert ui["restored"] == [volume()["folder_path"], volume("D0402")["folder_path"]]


def test_project_switch_refreshes_search(page, ui):
    page.locator("#q").fill("照明")
    page.locator("#searchBtn").click()
    expect(page.locator("#results")).to_contain_text("项目1的结果")
    page.locator("#projSel").select_option("2")
    expect(page.locator("#results")).to_contain_text("项目2的结果")
    expect(page.locator("#results")).not_to_contain_text("项目1的结果")
    assert [r["project"][0] for r in ui["searches"]] == ["1", "2"]


def test_project_switch_in_another_view_invalidates_search(page, ui):
    page.locator("#q").fill("照明")
    page.locator("#searchBtn").click()
    expect(page.locator("#results")).to_contain_text("项目1的结果")
    page.locator('[data-view="scan"]').click()
    page.locator("#projSel").select_option("2")
    page.locator('[data-view="search"]').click()
    expect(page.locator("#results")).to_contain_text("项目2的结果")
    expect(page.locator("#results")).not_to_contain_text("项目1的结果")


@pytest.mark.parametrize("switch_project", [False, True])
def test_late_search_response_cannot_replace_new_results(page, ui, switch_project):
    # 模拟请求已到达服务器、取消失效的情况，验证身份校验而不只依赖 abort。
    page.evaluate("""() => {
        const fetch = window.fetch;
        window.fetch = (url, opts = {}) => fetch(url, {...opts, signal: undefined});
    }""")
    ui["hold_search"] = True
    page.locator("#q").fill("旧查询")
    page.locator("#searchBtn").click()
    wait_pending(page, ui, 1)
    if switch_project:
        page.locator("#projSel").select_option("2")
    else:
        page.locator("#q").fill("新查询")
        page.locator("#searchBtn").click()
    wait_pending(page, ui, 2)
    ui["pending"][1].fulfill(json=search_result("新结果"))
    expect(page.locator("#results")).to_contain_text("新结果")
    with page.expect_response(lambda r: r.url == ui["pending"][0].request.url):
        ui["pending"][0].fulfill(json=search_result("旧结果"))
    page.wait_for_timeout(50)
    expect(page.locator("#results")).to_contain_text("新结果")
    expect(page.locator("#results")).not_to_contain_text("旧结果")


def test_blank_search_does_not_restore_cached_results(page, ui):
    page.locator("#q").fill("照明")
    page.locator("#searchBtn").click()
    expect(page.locator("#results")).to_contain_text("项目1的结果")
    page.locator("#q").fill("")
    page.locator("#searchBtn").click()
    expect(page.locator("#sortbar")).to_be_hidden()
    page.locator('[data-view="scan"]').click()
    page.locator('[data-view="search"]').click()
    expect(page.locator("#results")).not_to_contain_text("项目1的结果")
    assert len(ui["searches"]) == 1
