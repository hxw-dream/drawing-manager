"""扫描器测试：入库、文件夹名解析、文件匹配、失效清理、图号愈合。"""

from app import scanner
from app.db import connect
from app.scanner import parse_folder_name


def test_parse_folder_name():
    assert parse_folder_name("D0401【综合办公楼照明施工图】-2024.5.7-改明敷") == (
        "D0401", "综合办公楼照明施工图", "2024.05.07", "改明敷")
    assert parse_folder_name("D0401【综合办公楼照明施工图】") == (
        "D0401", "综合办公楼照明施工图", None, None)
    code, _t, _d, rev = parse_folder_name("D0403(1)【电控楼照明检修】-2024.7.5")
    assert code == "D0403" and rev is None  # 括号批次号并入图册号，不进修订标记


def test_scan_root_indexes_and_matches(tmp_db, sample_library):
    report = scanner.scan_root(str(sample_library), log=lambda m: None)
    assert report["ok"] == 2 and report["total_entries"] == 8  # 两册 × 4 条
    with connect() as conn:
        vols = conn.execute("SELECT * FROM volumes ORDER BY id").fetchall()
        assert len(vols) == 2
        assert {v["code"] for v in vols} == {"D0401"}
        assert all(v["parse_status"] == "ok" for v in vols)
        # 文件匹配：每册 4 张图纸 + 1 份版本后缀文件挂到对应图号
        matched = conn.execute(
            """SELECT e.drawing_no, COUNT(f.id) FROM entries e
               JOIN files f ON f.matched_entry_id=e.id GROUP BY e.drawing_no""").fetchall()
        counts = {r[0]: r[1] for r in matched}
        assert counts["F10001-D0401-02"] == 3   # 两册原版 + 2025.3.9 版本文件
        assert counts["F10001-D0401-01"] == 2   # 两册各自的 01 号


def test_rescan_is_idempotent(tmp_db, sample_library):
    scanner.scan_root(str(sample_library), log=lambda m: None)
    scanner.scan_root(str(sample_library), log=lambda m: None)  # 重复扫描不重复入库
    with connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM volumes").fetchone()[0] == 2


def test_purge_missing_volumes(tmp_db, tmp_path):
    with connect() as conn:  # 直接造指向不存在路径的记录，验证清理逻辑本身
        for n in ("X1", "X2"):
            conn.execute(
                """INSERT INTO volumes(folder_path, folder_name, parse_status)
                   VALUES(?, ?, 'ok')""", (str(tmp_path / "gone" / n), n))
        assert len(scanner.purge_missing_volumes(conn)) == 2
        assert conn.execute("SELECT COUNT(*) FROM volumes").fetchone()[0] == 0


def test_scan_root_records_scan_root(tmp_db, sample_library):
    scanner.scan_root(str(sample_library), log=lambda m: None)
    with connect() as conn:
        roots = {r[0] for r in conn.execute("SELECT DISTINCT scan_root FROM volumes")}
    assert roots == {str(sample_library)}
