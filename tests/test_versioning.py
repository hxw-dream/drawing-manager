"""版本与归一化的纯函数测试。"""
from app.versioning import group_entry_hits, normalize_no, parse_version_suffix, volume_sort_key


def test_normalize_no_fullwidth():
    assert normalize_no("F10001-D0403（1）-02") == "F10001-D0403(1)-02"
    assert normalize_no(" f10001-d0401 - 01 ") == "F10001-D0401-01"
    assert normalize_no("Ａ－１") == "A-1"  # 全角字母/数字/长横线


def test_parse_version_suffix():
    no = "F10001-D0401-03"
    assert parse_version_suffix(no, "F10001-D0401-03") == (None, None)  # 原版
    d, note = parse_version_suffix(no, "F10001-D0401-03-2025.3.9电缆桥架定位变化-模型")
    assert d == "2025.03.09" and note == "电缆桥架定位变化 模型"
    d, note = parse_version_suffix(no, "F10001-D0401-02【2025.1.14】".replace("D0401", "D0401"))
    assert d == "2025.01.14" and note is None  # 括号日期格式，说明为空
    d, note = parse_version_suffix(no, "F10001-D0401-03-2025年3月9日")
    assert d == "2025.03.09"


def test_volume_sort_key_prefers_newer():
    old = {"date_tag": "2024.05.07", "rev_tag": None, "scanned_at": 1}
    new = {"date_tag": "2025.01.01", "rev_tag": "改明敷", "scanned_at": 2}
    assert volume_sort_key(new) > volume_sort_key(old)
    undated = {"date_tag": None, "rev_tag": None, "scanned_at": 5}
    assert volume_sort_key(old) > volume_sort_key(undated)


def test_group_entry_hits_keeps_relevance_order():
    rows = [  # 模拟 main.py 的相关度降序输入
        {"drawing_no": "X-2", "title": "", "date_tag": None, "rev_tag": None, "scanned_at": 1},
        {"drawing_no": "X-1", "title": "", "date_tag": "2025.01.01", "rev_tag": None, "scanned_at": 1},
    ]
    groups = group_entry_hits(rows)
    assert [g["drawing_no"] for g in groups] == ["X-2", "X-1"]
