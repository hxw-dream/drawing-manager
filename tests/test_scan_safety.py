"""离线图纸库、扫描事务及修订图号匹配的回归测试。"""
import os
import shutil
import threading
from contextlib import closing
from pathlib import Path

import pytest

from app import db, main, scanner


def parsed_volume():
    return {"entries": [{"drawing_no": "F10001-D0401-01", "title": "照明布置图"}],
            "header": {}, "raw_text": "照明布置图", "method": "text", "parse_status": "ok"}


@pytest.fixture()
def fast_library(tmp_db, tmp_path, monkeypatch):
    root = tmp_path / "library"
    for name in ("A", "B"):
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "F10001-D0401-ML.pdf").write_bytes(b"ml")
        (folder / "F10001-D0401-01.pdf").write_bytes(b"drawing")
    monkeypatch.setattr(scanner, "parse_ml", lambda path: parsed_volume())
    return root


def index_counts():
    with closing(db.connect()) as conn:
        return tuple(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in ("volumes", "entries", "files"))


def test_read_views_preserve_offline_library(fast_library):
    scanner.scan_root(str(fast_library), log=lambda _: None)
    before = index_counts()
    offline = fast_library.with_name("offline-library")
    fast_library.rename(offline)
    try:
        assert len(main.list_volumes()) == 2
        assert main.search("照明")["entry_groups"]
        main.version_groups()
        assert len(main.get_inventory()["items"]) == 2
        assert index_counts() == before
    finally:
        offline.rename(fast_library)
    assert len(main.list_volumes()) == 2


def test_scan_does_not_purge_another_offline_source(fast_library, tmp_path):
    scanner.scan_root(str(fast_library), log=lambda _: None)
    offline = fast_library.with_name("offline-library")
    fast_library.rename(offline)
    other_root = tmp_path / "other-library"
    other_root.mkdir()
    try:
        report = scanner.scan_root(str(other_root), log=lambda _: None)
        assert report["removed_missing"] == 0
        assert index_counts() == (2, 2, 4)
    finally:
        offline.rename(fast_library)


def test_complete_rescan_removes_confirmed_deleted_volume(fast_library):
    scanner.scan_root(str(fast_library), log=lambda _: None)
    shutil.rmtree(fast_library / "A")
    report = scanner.scan_root(str(fast_library), log=lambda _: None)
    assert report["removed_missing"] == 1
    assert index_counts() == (1, 1, 2)  # 同时清理该册的条目及关联文件。


def test_purge_preserves_unavailable_root(fast_library):
    scanner.scan_root(str(fast_library), log=lambda _: None)
    offline = fast_library.with_name("offline-library")
    fast_library.rename(offline)
    try:
        with closing(db.connect()) as conn:
            assert scanner.purge_missing_volumes(conn, str(fast_library)) == []
        assert index_counts() == (2, 2, 4)
    finally:
        offline.rename(fast_library)


def test_purge_preserves_permission_errors(fast_library, monkeypatch):
    scanner.scan_root(str(fast_library), log=lambda _: None)
    original_stat = os.stat

    def denied_stat(path, *args, **kwargs):
        if os.fspath(path) == str(fast_library / "A"):
            raise PermissionError("图纸库暂时无权限")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(scanner.os, "stat", denied_stat)
    with closing(db.connect()) as conn:
        assert scanner.purge_missing_volumes(conn, str(fast_library)) == []
    assert index_counts() == (2, 2, 4)


@pytest.mark.parametrize("stopped", [False, True])
def test_incomplete_scan_preserves_unchecked_volumes(fast_library, monkeypatch, stopped):
    scanner.scan_root(str(fast_library), log=lambda _: None)
    shutil.rmtree(fast_library / "A")
    if not stopped:
        original_walk = scanner.os.walk

        def interrupted_walk(root, onerror):
            onerror(PermissionError("部分目录不可访问"))
            yield from original_walk(root, onerror=onerror)

        monkeypatch.setattr(scanner.os, "walk", interrupted_walk)
    report = scanner.scan_root(str(fast_library), log=lambda _: None,
                               should_stop=lambda: stopped)
    assert report["removed_missing"] == 0
    assert index_counts() == (2, 2, 4)


def test_scan_commits_each_volume_before_next_parse(fast_library, monkeypatch):
    entered_second_parse = threading.Event()
    release_parse = threading.Event()
    outcomes, errors = [], []
    db.initialize()
    original_connect = db.sqlite3.connect

    def short_connect(*args, **kwargs):
        kwargs["timeout"] = 0.2  # 锁回归应快速失败，而不是等待默认的 30 秒。
        return original_connect(*args, **kwargs)

    def slow_parse(path):
        if Path(path).parent.name == "B":
            entered_second_parse.set()
            assert release_parse.wait(10), "测试未释放解析线程"
        return parsed_volume()

    def scan():
        try:
            outcomes.append(scanner.scan_root(str(fast_library), log=lambda _: None))
        except Exception as ex:
            errors.append(ex)

    monkeypatch.setattr(db.sqlite3, "connect", short_connect)
    monkeypatch.setattr(scanner, "parse_ml", slow_parse)
    worker = threading.Thread(target=scan, daemon=True)
    worker.start()
    try:
        assert entered_second_parse.wait(5)
        assert len(main.list_volumes()) == 1  # 第一册已经提交，第二册尚未写入。
        assert main.search("照明")["entry_groups"]
        main.version_groups()
        assert len(main.get_inventory()["items"]) == 1
        assert main.create_project(main.ProjectReq(name="扫描中创建"))["id"] > 1
    finally:
        release_parse.set()
        worker.join(5)
    assert not worker.is_alive()
    assert not errors
    assert outcomes[0]["ok"] == 2
    assert index_counts() == (2, 2, 4)


@pytest.mark.parametrize("unavailable", [False, True])
def test_failed_volume_retains_previous_index(fast_library, monkeypatch, unavailable):
    scanner.scan_root(str(fast_library), log=lambda _: None)
    (fast_library / "A" / "F10001-D0401-ML.pdf").write_bytes(b"changed ml")

    def failing_parse(path):
        if unavailable:
            raise PermissionError("目录暂不可读取")
        result = parsed_volume()
        result["entries"].append({"drawing_no": None})  # 写入中途触发约束错误。
        return result

    monkeypatch.setattr(scanner, "parse_ml", failing_parse)
    report = scanner.scan_root(str(fast_library), log=lambda _: None)
    assert report["fail"] == 1 and report["ok"] == 1
    assert index_counts() == (2, 2, 4)
    assert all(v["parse_status"] == "ok" for v in main.list_volumes())


def test_volume_removed_during_parse_is_not_reinserted(fast_library, monkeypatch):
    scanner.scan_root(str(fast_library), log=lambda _: None)
    (fast_library / "A" / "F10001-D0401-ML.pdf").write_bytes(b"changed ml")

    def remove_during_parse(path):
        main.delete_volume(main.VolumePathReq(folder_path=str(Path(path).parent)))
        return parsed_volume()

    monkeypatch.setattr(scanner, "parse_ml", remove_during_parse)
    report = scanner.scan_root(str(fast_library), log=lambda _: None)
    assert report["ok"] == 1
    assert index_counts() == (1, 1, 2)
    assert [v["folder_path"] for v in main.list_ignored()] == [str(fast_library / "A")]


def test_revision_matching_is_saved_to_index(fast_library, monkeypatch):
    folder = fast_library / "A"
    (folder / "F10001-D0401-12.pdf").write_bytes(b"base")
    revised = "F10001-D0401-12-2025.3.9修改.pdf"
    (folder / revised).write_bytes(b"revision")

    def parse_numbers(path):
        result = parsed_volume()
        result["entries"] = [{"drawing_no": "F10001-D0401-1", "title": "其他图"},
                             {"drawing_no": "F10001-D0401-12", "title": "目标图"}]
        return result

    monkeypatch.setattr(scanner, "parse_ml", parse_numbers)
    scanner.scan_root(str(fast_library), log=lambda _: None)
    groups = main.version_groups()["groups"]
    assert len(groups) == 1 and groups[0]["drawing_no"] == "F10001-D0401-12"
    assert [v["ver_date"] for v in groups[0]["versions"]] == [None, "2025.03.09"]
    items = main.get_inventory()["items"]
    target = next(i for i in items if i["folder_path"] == str(folder)
                  and i["drawing_no"] == "F10001-D0401-12")
    assert target["file_count"] == 2 and target["latest_file"] == revised


@pytest.mark.parametrize("filename", ["X-12-2025.3.9修改.pdf", "X-12【2025.3.9】.pdf",
                                      "X-12修改.pdf", "前缀-X-12-修改.dwg"])
def test_revision_file_matches_whole_number(filename):
    entries = [{"_id": 1, "drawing_no": "X-1"}, {"_id": 2, "drawing_no": "X-12"}]
    files = [{"filename": filename, "matched_entry_id": None}]
    scanner._match_files_to_entries(entries, files)
    assert files[0]["matched_entry_id"] == 2
    assert [e["drawing_no"] for e in entries] == ["X-1", "X-12"]


def test_nested_number_prefers_longest_match():
    entries = [{"_id": 1, "drawing_no": "D0401-12"},
               {"_id": 2, "drawing_no": "F10001-D0401-12"}]
    files = [{"filename": "F10001-D0401-12-修改.pdf", "matched_entry_id": None}]
    scanner._match_files_to_entries(entries, files)
    assert files[0]["matched_entry_id"] == 2


def test_ambiguous_file_stays_unmatched():
    entries = [{"_id": 1, "drawing_no": "X-12"}, {"_id": 2, "drawing_no": "Y-12"}]
    files = [{"filename": "X-12-Y-12-修改.pdf", "matched_entry_id": None}]
    scanner._match_files_to_entries(entries, files)
    assert files[0]["matched_entry_id"] is None


def test_healing_matches_revision_before_base_file():
    entries = [{"_id": 1, "drawing_no": "F10001-D0401-0"}]
    files = [{"filename": "F10001-D0401-01-2025.3.9修改.pdf", "matched_entry_id": None},
             {"filename": "F10001-D0401-01.pdf", "matched_entry_id": None}]
    scanner._match_files_to_entries(entries, files)
    assert entries[0]["drawing_no"] == "F10001-D0401-01"
    assert all(f["matched_entry_id"] == 1 for f in files)


def test_ambiguous_healing_stays_unmatched():
    entries = [{"_id": 1, "drawing_no": "X-0"}]
    files = [{"filename": "X-01.pdf", "matched_entry_id": None},
             {"filename": "X-02.pdf", "matched_entry_id": None}]
    scanner._match_files_to_entries(entries, files)
    assert entries[0]["drawing_no"] == "X-0"
    assert all(f["matched_entry_id"] is None for f in files)


def test_existing_base_file_prevents_false_healing():
    entries = [{"_id": 1, "drawing_no": "X-1"}]
    files = [{"filename": "X-12.pdf", "matched_entry_id": None},
             {"filename": "X-1.pdf", "matched_entry_id": None}]
    scanner._match_files_to_entries(entries, files)
    assert entries[0]["drawing_no"] == "X-1"
    assert [f["matched_entry_id"] for f in files] == [None, 1]
