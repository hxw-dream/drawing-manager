"""ML 解析器黄金用例：三份合成目录文件（扫描件/双语表头/全角括号图号）。

合成件由 tools/make_synthetic_fixtures.py 生成（版式复刻真实工程目录页），
固化了历史上踩过的解析回归：
- 表头关键词误匹配标题栏（BOOK/PAGE）
- 中文候选优先（双语表头）
- 全角括号图号（F10001-D0403（1）-XX 曾整册解析失败）
"""
from pathlib import Path

import pytest

from app.parser_ml import _is_drawing_no, parse_ml

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("text,expected", [
    ("F10001-D0401-01", True),
    ("13-F10001-D0401-02", True),          # 带工程前缀
    ("F10001-D0403（1）-03", True),        # 全角括号
    ("F10001-D0403(1)-03", True),          # 半角括号
    ("13-F10001-D0401", False),            # 卷册参考号（末段非纯数字）
    ("2025-03-09", False),                  # 日期（无字母段）
    ("D0401", False),                       # 两段
    ("DESIGN SPECIFICATION", False),
])
def test_is_drawing_no(text, expected):
    assert _is_drawing_no(text) is expected


def test_parse_scanned_bilingual():
    """合成扫描件：OCR 管道，双语表头，4 条目录。"""
    r = parse_ml(str(FIX / "ml-demo-lighting-scanned.pdf"))
    assert r["parse_status"] == "ok" and r["method"] == "ocr"
    nos = [e["drawing_no"] for e in r["entries"]]
    assert nos == ["F10001-D0401-01", "F10001-D0401-02",
                   "F10001-D0401-03", "F10001-D0401-04"]
    titles = " ".join(e["title"] for e in r["entries"])
    assert "设计说明" in titles
    assert "照明布置图" in titles
    assert "材料设备清册" in titles
    assert all(e["rev"] == "00" for e in r["entries"])
    assert r["header"]["volume_name"] == "综合办公楼照明施工图"
    assert r["header"]["volume_ref_no"] == "13-F10001-D0401"
    assert "XX电厂" in (r["header"]["project"] or "")


def test_parse_fullwidth_drawing_no():
    """全角括号图号曾整册解析失败（回归用例）。"""
    r = parse_ml(str(FIX / "ml-demo-fullwidth-scanned.pdf"))
    assert r["parse_status"] == "ok"
    nos = [e["drawing_no"] for e in r["entries"]]
    assert len(nos) >= 5
    assert all(n.startswith("F10001-D0403(1)-") for n in nos), nos
    assert r["header"]["volume_name"] == "电控楼照明检修接线图"


def test_parse_cable_volume():
    """六条目册：中文册名取自 ML。"""
    r = parse_ml(str(FIX / "ml-demo-cable-scanned.pdf"))
    assert r["parse_status"] == "ok"
    assert len(r["entries"]) == 6
    assert r["header"]["volume_name"] == "化学水系统电缆敷设施工图"
