"""解析每册的 ML 目录文件（PDF）。

两条路径：
1. 文字层 PDF：pdfplumber 直接取文本行；
2. 扫描件：pypdfium2 渲染成图 → RapidOCR → 按坐标聚类成表格行。

统一输出 entries（图号/图名/版本等）和 header（工程名/册名等），
raw_text 全文保留，即使列解析失败也能被关键字搜索命中。
"""
import logging
import re
from pathlib import Path

from .versioning import normalize_no

logging.getLogger("rapidocr_onnxruntime").setLevel(logging.ERROR)

# 表头关键词 → 逻辑列。识别到就能按 x 坐标分列
HEADER_KEYWORDS = {
    "seq":    ["NO.", "NO", "序号", "顺序号"],
    "no":     ["DRAWING NO", "图号", "图纸编号"],
    "title":  ["FILE NAME", "图纸名称", "图名", "文件名称", "名称"],
    "rev":    ["REV", "版本", "修改标记"],
    "piece":  ["PIECE", "张数", "页数"],
    "page":   ["PAGE", "页码"],
    "book":   ["BOOK", "册号"],
    "remark": ["REMARK", "备注"],
}

LABEL_PROJECT = ["PROJECT", "工程名称", "项目名称"]
LABEL_VOLNAME = ["VOLUME NAME", "册名", "卷册名称", "卷名", "NAME"]


def _norm_token(t: str) -> str:
    return normalize_no(t)


def _is_drawing_no(text: str) -> bool:
    """图号锚点：至少 3 段横杠、末段为纯数字、前段含字母
    （如 F10001-D0401-01、13-F10001-D0403(1)-02）。
    表头卷册参考号（13-F10001-D0401）末段非纯数字，纯日期（2025-03-09）无字母，均被排除。"""
    t = _norm_token(text)
    if not re.fullmatch(r"[A-Z0-9()\-]+", t):
        return False
    segs = t.split("-")
    if len(segs) < 3 or not segs[-1].isdigit() or not (1 <= len(segs[-1]) <= 4):
        return False
    return any(re.search(r"[A-Z]", s) for s in segs[:-1])


def _boxes_from_ocr(result):
    """RapidOCR 结果 → [{x0,y0,x1,y1,cy,text}]"""
    boxes = []
    if not result:
        return boxes
    for box, text, _conf in result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        boxes.append({
            "x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys),
            "cy": sum(ys) / len(ys), "text": str(text).strip(),
        })
    return boxes


def _detect_columns(boxes):
    """识别表头关键词框。返回 (右侧数值列的 x 区间 dict, 表格顶部 y)。

    只认与"图号"列表头同一行的关键词，排除标题栏里同名的
    BOOK/VOLUME（如 "VOLUME 14 BOOK 20SECTION"）和页眉的 PAGE。
    """
    hits = {}
    for b in boxes:
        t = _norm_token(b["text"])
        if not (1 < len(t) < 16):
            continue
        for col, kws in HEADER_KEYWORDS.items():
            for kw in kws:
                if t == _norm_token(kw) or (_norm_token(kw) in t and len(t) <= len(kw) + 6):
                    hits.setdefault(col, []).append(b)
                    break
    no_cands = hits.get("no") or []
    title_cands = hits.get("title") or []
    # 图号/图名两个表头必须大致同行，以此定位表头行
    pair = None
    for n in no_cands:
        for t in title_cands:
            if abs(n["cy"] - t["cy"]) < 40:
                pair = (n, t)
                break
        if pair:
            break
    if not pair:
        return None, None
    hy0, hy1 = pair[0]["y0"], pair[0]["y1"]
    confirmed = {}
    for col, cands in hits.items():
        same_row = [b for b in cands if hy0 - 40 <= b["cy"] <= hy1 + 40]
        if same_row:
            confirmed[col] = min(same_row, key=lambda b: abs(b["cy"] - (hy0 + hy1) / 2))
    # 只保留图号列右侧的数值列，右边界取下一列起点，避免区间重叠
    right_cols = {c: b for c, b in confirmed.items()
                  if c in ("rev", "piece", "page", "book", "remark")
                  and b["x0"] > pair[0]["x0"]}
    ordered = sorted(right_cols.items(), key=lambda kv: kv[1]["x0"])
    bands = {}
    for i, (col, b) in enumerate(ordered):
        right = ordered[i + 1][1]["x0"] if i + 1 < len(ordered) else 10**9
        bands[col] = (b["x0"] - 10, right - 4)
    table_top = max(b["y1"] for b in confirmed.values()) + 4
    return bands, table_top


def _label_value(boxes, labels, exclude_labels):
    """取标签的值：优先同行右侧，其次紧邻下方。"""
    label_box = None
    for b in boxes:
        if any(_norm_token(b["text"]) == _norm_token(lb) for lb in labels):
            label_box = b
            break
    if not label_box:
        return None
    cands = []
    for b in boxes:
        if b is label_box or not b["text"]:
            continue
        t = _norm_token(b["text"])
        if any(_norm_token(lb) in t for lb in exclude_labels):
            continue
        same_row_right = b["cy"] <= label_box["y1"] + 8 and b["x0"] >= label_box["x1"] - 12
        below = label_box["y1"] - 5 <= b["cy"] <= label_box["y1"] + 55
        if same_row_right or below:
            dist = abs(b["x0"] - label_box["x1"]) + abs(b["cy"] - label_box["cy"])
            cands.append((0 if same_row_right else 1, dist, b["text"]))
    # 双语表头里优先取中文值（英文行通常是同一标签的另一语言）
    if any(re.search(r"[\u4e00-\u9fff]", t) for _, _, t in cands):
        cands = [c for c in cands if re.search(r"[\u4e00-\u9fff]", c[2])]
    cands.sort()
    return cands[0][2] if cands else None


def _parse_ocr_boxes(boxes, x_margin=100.0):
    """锚点法解析表格行：图号框为行锚，按 y 分带归拢同行其他文本。

    x_margin：丢弃最左侧边缘小字的阈值（扫描图有图框边噪声设 100；
    DXF 提取的矢量文字无噪声，设 0）。
    """
    entries, header = [], {}
    right_bands, table_top = _detect_columns(boxes)
    anchors = sorted(
        [b for b in boxes if _is_drawing_no(b["text"]) and len(b["text"]) <= 32],
        key=lambda b: b["cy"],
    )
    for i, a in enumerate(anchors):
        if i == 0:
            top = table_top if table_top is not None else a["y0"] - 60
        else:
            top = (anchors[i - 1]["y1"] + a["y0"]) / 2
        if i + 1 < len(anchors):
            bottom = (a["y1"] + anchors[i + 1]["y0"]) / 2 + 4
        else:
            bottom = a["y1"] + 90  # 末行下限，避免把页脚 NOTE 收进来
        row = [b for b in boxes
               if b is not a and top <= b["cy"] < bottom and (b["y1"] - b["y0"]) < 90
               and b["x0"] > x_margin]
        no = _norm_token(a["text"])
        entry = {"drawing_no": no, "seq": None, "title": [], "rev": None,
                 "piece": None, "page": None, "remark": []}
        for b in sorted(row, key=lambda b: (b["cy"], b["x0"])):
            t = b["text"]
            col = None
            if right_bands:
                cx = (b["x0"] + b["x1"]) / 2
                col = next((c for c, (x0, x1) in right_bands.items() if x0 <= cx < x1), None)
            if col == "rev":
                entry["rev"] = t
            elif col in ("piece", "page", "book"):
                entry["page"] = entry["page"] or t
            elif col == "remark":
                entry["remark"].append(t)
            elif b["x1"] <= a["x0"] + 5 and re.fullmatch(r"\d{1,3}", t):
                entry["seq"] = t  # 图号左边的序号
            else:
                entry["title"].append(t)  # 其余（图号与右侧数值列之间）都是图名
        entry["title"] = " ".join(entry["title"]).strip()
        entry["remark"] = " ".join(entry["remark"]).strip()
        if no not in [e["drawing_no"] for e in entries]:
            entries.append(entry)
    excl = LABEL_PROJECT + LABEL_VOLNAME + ["SPECIALTY", "PHASE", "专业", "阶段",
                                            "APPROVED", "REVIEWED", "DESIGNED"]
    header["project"] = _label_value(boxes, LABEL_PROJECT, excl)
    header["volume_name"] = _label_value(boxes, LABEL_VOLNAME, excl)
    for b in boxes:  # 卷册参考号按框单独匹配，避免跨行正则串字
        t = _norm_token(b["text"])
        if re.fullmatch(r"\d{1,4}-[A-Z][A-Z0-9]*-[A-Z0-9]+", t):
            header["volume_ref_no"] = t
            break
    return entries, header


def parse_ml_pdf_text(path: str):
    """路径1：文字层 PDF。"""
    import pdfplumber
    lines, entries = [], []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            lines.extend(ln.strip() for ln in t.splitlines() if ln.strip())
    if not lines:
        return None
    header = {}
    for line in lines:
        norm = _norm_token(line)
        if not _is_drawing_no(norm):
            continue
        rest = line.upper().replace(norm, " ", 1)
        nums = re.findall(r"\b(\d{1,3})\b", rest)
        title = re.sub(r"\b\d{1,3}\b", " ", rest)
        title = re.sub(r"[-|/\s]{2,}", " ", title).strip(" -|/")
        entries.append({"drawing_no": norm, "seq": nums[0] if nums else None,
                        "title": title, "rev": None, "page": None, "remark": ""})
    for labels, key in ((LABEL_PROJECT, "project"), (LABEL_VOLNAME, "volume_name")):
        for i, line in enumerate(lines):
            if any(_norm_token(lb) in _norm_token(line) for lb in labels):
                val = re.sub("|".join(labels), "", line, flags=re.I).strip(" :-")
                if not val and i + 1 < len(lines):
                    val = lines[i + 1]
                header[key] = val
                break
    return {"entries": entries, "header": header,
            "raw_text": "\n".join(lines), "method": "text"}


def parse_ml_pdf_ocr(path: str):
    """路径2：扫描件 → 渲染 → OCR。"""
    import numpy as np
    import pypdfium2 as pdfium
    from rapidocr_onnxruntime import RapidOCR

    all_entries, header = [], {}
    raw_lines = []
    engine = RapidOCR()
    doc = pdfium.PdfDocument(path)
    for pageno in range(len(doc)):
        pil = doc[pageno].render(scale=300 / 72).to_pil().convert("RGB")
        result, _ = engine(np.array(pil))
        boxes = _boxes_from_ocr(result)
        raw_lines.extend(b["text"] for b in boxes)
        page_entries, page_header = _parse_ocr_boxes(boxes)
        for e in page_entries:
            if e["drawing_no"] not in [x["drawing_no"] for x in all_entries]:
                all_entries.append(e)
        for k, v in page_header.items():
            header.setdefault(k, v)
    return {"entries": all_entries, "header": header,
            "raw_text": "\n".join(raw_lines), "method": "ocr"}


def parse_ml_dwg(path: str):
    """路径3：DWG/DXF 目录文件 → ODA 转 DXF → 提取文字实体 → 行解析。"""
    import shutil
    import tempfile

    from . import dwg as dwg_mod

    ext = Path(path).suffix.lower()
    tmp = tempfile.mkdtemp(prefix="dwgml_")
    try:
        if ext == ".dxf":
            dxf = path
        else:
            dxf = dwg_mod.dwg_to_dxf(path, tmp)
        boxes = dwg_mod.parse_dxf_entities(dxf)
        # DXF 是毫米级模型坐标，归一化到图像尺度，行解析的边距过滤才有意义
        xmax = max((b["x1"] for b in boxes), default=0)
        if xmax > 0:
            k = 2000.0 / xmax
            for b in boxes:
                b["x0"] *= k
                b["x1"] *= k
                b["y0"] *= k
                b["y1"] *= k
                b["cy"] *= k
        entries, header = _parse_ocr_boxes(boxes, x_margin=0)
        raw_text = "\n".join(b["text"] for b in boxes)
        return {"entries": entries, "header": header,
                "raw_text": raw_text, "method": "dwg"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def parse_ml(path: str):
    """解析 ML 文件：PDF 走文字层/OCR，DWG/DXF 走 ODA 转换管道。"""
    ext = Path(path).suffix.lower()
    if ext in (".dwg", ".dxf"):
        result = parse_ml_dwg(path)
    else:
        result = parse_ml_pdf_text(path)
        if result is None or not result["entries"]:
            result = parse_ml_pdf_ocr(path)
    result["parse_status"] = "ok" if result["entries"] else "empty"
    return result
