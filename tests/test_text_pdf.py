"""文字 PDF 应直接解析，保留表格列及图名中的数字。"""
import ctypes
import json
from contextlib import closing
from types import SimpleNamespace

import pdfplumber
import pypdfium2 as pdfium
import pytest

from app import db, parser_ml, scanner


def write_text_pdf(path, pages):
    """用运行时已有的 PDFium 生成带真实文字层的 PDF，无额外制图依赖。"""
    with pdfium.PdfDocument.new() as doc:
        for tokens in pages:
            page = doc.new_page(700, 900)
            for x, y, text in tokens:
                raw = pdfium.raw.FPDFPageObj_NewTextObj(doc, b"Helvetica", 12)
                data = ctypes.create_string_buffer(text.encode("utf-16-le") + b"\0\0")
                assert pdfium.raw.FPDFText_SetText(raw, ctypes.cast(data, pdfium.raw.FPDF_WIDESTRING))
                pdfium.raw.FPDFPageObj_Transform(raw, 1, 0, 0, 1, x, y)
                page.insert_obj(pdfium.PdfObject(raw))
            page.gen_content()
            page.close()
        doc.save(path)


def text_page(no="F10001-D0401-01", title="LIGHTING FOR UNIT 12", rev="00", seq="1"):
    return [(20, 850, "PROJECT"), (120, 850, "Demo plant expansion"),
            (20, 820, "VOLUME NAME"), (150, 820, "Lighting drawings"),
            (20, 790, "13-F10001-D0401"),
            (20, 750, "NO."), (70, 750, "DRAWING NO."), (290, 750, "FILE NAME"),
            (530, 750, "REV."), (600, 750, "PAGE"),
            (20, 710, seq), (70, 710, no), (290, 710, title), (530, 710, rev), (600, 710, "1")]


def forbid_ocr(path):
    raise AssertionError("文字目录不应调用 OCR")


def test_real_text_pdf_preserves_columns_and_header(tmp_path, monkeypatch):
    path = tmp_path / "F10001-D0401-ML.pdf"
    write_text_pdf(path, [text_page()])
    monkeypatch.setattr(parser_ml, "parse_ml_pdf_ocr", forbid_ocr)
    result = parser_ml.parse_ml(str(path))
    assert result["method"] == "text" and result["parse_status"] == "ok"
    assert len(result["entries"]) == 1
    entry = result["entries"][0]
    assert entry["drawing_no"] == "F10001-D0401-01"
    assert entry["seq"] == "1" and entry["rev"] == "00" and entry["page"] == "1"
    assert entry["title"] == "LIGHTING FOR UNIT 12"
    assert result["header"] == {"project": "Demo plant expansion",
                                "volume_name": "Lighting drawings",
                                "volume_ref_no": "13-F10001-D0401"}


def test_text_pdf_deduplicates_pages_and_keeps_later_entries(tmp_path, monkeypatch):
    path = tmp_path / "ml.pdf"
    write_text_pdf(path, [text_page(), text_page(),
                          text_page("F10001-D0401-02", "LIGHTING FOR UNIT 220", "01", "2")])
    monkeypatch.setattr(parser_ml, "parse_ml_pdf_ocr", forbid_ocr)
    result = parser_ml.parse_ml(str(path))
    assert [e["drawing_no"] for e in result["entries"]] == ["F10001-D0401-01", "F10001-D0401-02"]
    assert result["entries"][1]["title"] == "LIGHTING FOR UNIT 220"
    assert result["entries"][1]["rev"] == "01"


@pytest.mark.parametrize("line,no,title", [
    ("1 F10001-D0401-01 照明布置图", "F10001-D0401-01", "照明布置图"),
    ("2 F10001-D0403（1）-02 12号泵房照明", "F10001-D0403(1)-02", "12号泵房照明"),
    ("3 13 - F10001 - D0401 - 03 配电室 220V 接线图", "13-F10001-D0401-03", "配电室 220V 接线图"),
])
def test_split_text_number_fallback(line, no, title, monkeypatch):
    page = SimpleNamespace(extract_text=lambda: line, extract_words=list)

    class TextPDF:
        pages = [page]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(pdfplumber, "open", lambda _: TextPDF())
    monkeypatch.setattr(parser_ml, "parse_ml_pdf_ocr", forbid_ocr)
    result = parser_ml.parse_ml("unused.pdf")
    assert result["method"] == "text"
    assert len(result["entries"]) == 1
    assert result["entries"][0]["drawing_no"] == no
    assert result["entries"][0]["title"] == title


def test_unrecognized_text_pdf_still_falls_back_to_ocr(tmp_path, monkeypatch):
    path = tmp_path / "ml.pdf"
    write_text_pdf(path, [[(20, 800, "No recognizable table here")]])
    calls = []

    def ocr(path):
        calls.append(path)
        return {"entries": [{"drawing_no": "F10001-D0401-01"}],
                "header": {}, "raw_text": "ocr", "method": "ocr"}

    monkeypatch.setattr(parser_ml, "parse_ml_pdf_ocr", ocr)
    assert parser_ml.parse_ml(str(path))["method"] == "ocr"
    assert calls == [str(path)]


def test_old_pdf_cache_is_reparsed_and_saved_as_text(tmp_db, tmp_path, monkeypatch):
    root = tmp_path / "library"
    folder = root / "D0401"
    folder.mkdir(parents=True)
    path = folder / "F10001-D0401-ML.pdf"
    write_text_pdf(path, [text_page()])
    (folder / "F10001-D0401-01.pdf").write_bytes(b"drawing")
    stat = path.stat()
    with closing(db.connect()) as conn, conn:
        conn.execute("""INSERT INTO parse_cache(ml_path, sig, entries_json, header_json, method)
                        VALUES(?,?,?,?,?)""", (str(path), f"{stat.st_size}:{stat.st_mtime_ns}",
                                              json.dumps([{"drawing_no": "OLD-WRONG-01"}]), "{}", "ocr"))
    monkeypatch.setattr(parser_ml, "parse_ml_pdf_ocr", forbid_ocr)
    report = scanner.scan_root(str(root), log=lambda _: None)
    assert report["ok"] == 1
    with closing(db.connect()) as conn:
        assert conn.execute("SELECT parse_method FROM volumes").fetchone()[0] == "text"
        assert conn.execute("SELECT drawing_no FROM entries").fetchone()[0] == "F10001-D0401-01"
        assert conn.execute("SELECT COUNT(*) FROM files WHERE matched_entry_id IS NOT NULL").fetchone()[0] == 1
    # 新规则写入的缓存下一次重扫仍然可以复用。
    monkeypatch.setattr(scanner, "parse_ml", forbid_ocr)
    assert scanner.scan_root(str(root), log=lambda _: None)["ok"] == 1
