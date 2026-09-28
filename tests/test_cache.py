"""扫描增量缓存：ML 指纹未变时不重新解析。"""
import os
import time

from app import scanner
from app.db import connect


def test_rescan_uses_cache_not_reparse(tmp_db, sample_library, monkeypatch):
    scanner.scan_root(str(sample_library), log=lambda m: None)   # 首扫：真实解析并写缓存
    # 让解析器变成必炸的替身——若缓存未命中，扫描会失败
    def boom(path):
        raise AssertionError("不应重新解析：" + path)
    monkeypatch.setattr(scanner, "parse_ml", boom)

    report = scanner.scan_root(str(sample_library), log=lambda m: None)
    assert report["ok"] == 2 and report["total_entries"] == 8

    with connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM parse_cache").fetchone()[0] == 2  # 两册两条


def test_cache_invalidated_on_file_change(tmp_db, sample_library, monkeypatch):
    scanner.scan_root(str(sample_library), log=lambda m: None)
    ml = next(sample_library.rglob("*-ML.pdf"))
    # 触碰 ML 文件（mtime 变化）→ 指纹失效 → 必须重新解析
    st = ml.stat()
    os.utime(ml, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    time.sleep(0.01)
    scanner.scan_root(str(sample_library), log=lambda m: None)
    with connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM parse_cache").fetchone()[0] == 2  # 两册两条  # 仍是同一路径一行
        entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        assert entries == 8  # 重解析后结果一致

