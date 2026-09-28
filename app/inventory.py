"""图纸清册：全部入库图纸按类别汇总，可导出 Excel。

类别按图纸名称关键词归类（顺序即优先级，先命中先归类），
覆盖电气专业常见类别：设计说明、材料清册、防雷接地、电缆敷设、
照明安装、配电装置、电气接线、布置安装图。
"""
import os
import re
from collections import Counter
from datetime import datetime
from io import BytesIO
from pathlib import Path

from . import db as _db
from . import versioning

CATEGORIES = [    ("设计说明", ["设计说明", "说明书", "DESIGN SPECIFICATION", "SPECIFICATION"]),
    ("材料设备清册", ["材料", "清册", "设备表", "EQUIPMENT AND MATERIAL", "MATERIAL LIST", "BILL OF"]),
    ("防雷接地", ["防雷", "避雷", "接地", "LPS", "EARTHING", "GROUNDING"]),
    ("电缆敷设", ["电缆", "敷设", "桥架", "CABLE"]),
    ("照明安装", ["照明", "LIGHTING"]),
    ("配电装置安装", ["配电", "开关柜", "POWER DISTRIBUTION", "SWITCHGEAR"]),
    ("电气接线", ["接线", "WIRING", "INTERCONNECTION", "SCHEMATIC"]),
    ("布置与安装图", ["布置", "安装", "LAYOUT", "INSTALLATION"]),
]
CATEGORY_ORDER = [c for c, _ in CATEGORIES] + ["其他"]


def categorize(title: str) -> str:
    t = (title or "").upper()
    for cat, kws in CATEGORIES:
        if any(k.upper() in t for k in kws):
            return cat
    return "其他"


def build_inventory(conn, project: int = 1):
    """聚合指定项目的目录条目：类别、版本文件数、最新版文件名。"""
    pf = None if project == 0 else _db.project_filter(project)  # 0 = 全部项目
    rows = conn.execute(
        f"""SELECT e.id, e.seq, e.drawing_no, e.title, e.rev,
                  v.code, v.title AS volume_title, v.folder_name, v.folder_path,
                  v.date_tag, v.rev_tag, v.parse_status, v.project
           FROM entries e JOIN volumes v ON v.id=e.volume_id
           {f"WHERE ({pf})" if pf else ""}
           ORDER BY v.code, e.drawing_no""",
        {"pid": project} if pf else ()).fetchall()
    items = []
    for r in rows:
        files = conn.execute(
            "SELECT filename, path, size, mtime FROM files WHERE matched_entry_id=?",
            (r["id"],)).fetchall()
        latest = None
        for f in files:
            stem = versioning.normalize_no(Path(f["filename"]).stem)
            d, _n = versioning.parse_version_suffix(
                versioning.normalize_no(r["drawing_no"]), stem)
            key = (d or "0000.00.00", f["mtime"])
            if latest is None or key > latest[0]:
                latest = (key, f["filename"])
        items.append({
            "category": categorize(r["title"] or r["volume_title"] or ""),
            "code": r["code"], "volume_title": r["volume_title"] or r["folder_name"],
            "drawing_no": r["drawing_no"], "title": r["title"] or "", "rev": r["rev"],
            "file_count": len(files), "latest_file": latest[1] if latest else None,
            "folder_path": r["folder_path"],
        })
    cat_counts = Counter(i["category"] for i in items)
    vf = f"WHERE ({pf})" if pf else ""
    vparams = {"pid": project} if pf else ()
    entry_counts = dict(conn.execute(
        f"SELECT v.id, COUNT(e.id) FROM volumes v "
        f"LEFT JOIN entries e ON e.volume_id=v.id {vf} GROUP BY v.id", vparams).fetchall())
    file_counts = dict(conn.execute(
        "SELECT volume_id, COUNT(*) FROM files GROUP BY volume_id").fetchall())
    vols = {}
    for vr in conn.execute(
            f"SELECT id, code, title, folder_name, folder_path, scan_root FROM volumes v {vf}",
            vparams).fetchall():
        vols[vr["folder_path"]] = {
            "code": vr["code"], "title": vr["title"] or vr["folder_name"],
            "path": vr["folder_path"], "scan_root": vr["scan_root"],
            "entries": entry_counts.get(vr["id"], 0),
            "files": file_counts.get(vr["id"], 0)}
    order = {c: n for n, c in enumerate(CATEGORY_ORDER)}
    items.sort(key=lambda i: (order.get(i["category"], 99), i["code"] or "", i["drawing_no"]))
    return {"generated_at": datetime.now().isoformat(timespec="seconds"),
            "items": items,
            "categories": {c: cat_counts.get(c, 0) for c in CATEGORY_ORDER if cat_counts.get(c)},
            "volumes": sorted(vols.values(), key=lambda v: v["code"] or ""),
            "folder_names": {r["scan_root"]: r["name"] for r in conn.execute(
                "SELECT scan_root, name FROM folder_names").fetchall()}}


def make_xlsx(inv) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.remove(wb.active)  # 去掉默认空表，工作表全部按导入文件夹生成
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="0F62D6")
    bold = Font(bold=True)
    thin = Side(style="thin", color="B8BEC9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def style_header(ws, ncols):
        for c in range(1, ncols + 1):
            cell = ws.cell(row=1, column=c)
            cell.font = head_font
            cell.fill = head_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.freeze_panes = "A2"

    def natural_code(code):
        return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", code or "")]

    def sheet_name_for(path, used):
        raw = inv["folder_names"].get(path) or \
            (os.path.basename(path.rstrip("\\/")) if path else "") or "未分组"
        name = re.sub(r"[\\/:*?\[\]]", "_", raw)[:28] or "未分组"
        base, n = name, 2
        while name in used:
            name = f"{base}({n})"
            n += 1
        used.add(name)
        return name

    def write_register_sheet(ws, vols):
        """ZX 样式清册表：每册一行、图册号升序、相邻同类合并块。"""
        cols = ["序号", "图册号", "卷册名称", "类别", "图纸张数", "版本文件数",
                "已完成", "已核对", "备注"]
        ws.append(cols)
        style_header(ws, len(cols))
        ordered = sorted((dict(v, category=categorize(v["title"])) for v in vols),
                         key=lambda v: natural_code(v["code"]))
        total_entries = sum(v["entries"] for v in ordered)
        total_files = sum(v["files"] for v in ordered)
        ws.cell(row=1, column=5).value = f"图纸张数\n合计 {total_entries}"
        ws.cell(row=1, column=6).value = f"版本文件数\n合计 {total_files}"
        for c in (5, 6):
            ws.cell(row=1, column=c).alignment = Alignment(
                horizontal="center", vertical="center", wrap_text=True)
        runs = []
        for n, v in enumerate(ordered, 1):
            ws.append([n, v["code"] or "", v["title"], None,
                       v["entries"], v["files"], None, None, None])
            if runs and runs[-1][0] == v["category"]:
                runs[-1][2] = n + 1
            else:
                runs.append([v["category"], n + 1, n + 1])
        for cat, r0, r1 in runs:
            if r1 > r0:
                ws.merge_cells(start_row=r0, start_column=4, end_row=r1, end_column=4)
            cell = ws.cell(row=r0, column=4)
            cell.value = f"{cat}\n{r1 - r0 + 1}"
            cell.font = bold
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for r in range(1, ws.max_row + 1):
            for c in range(1, len(cols) + 1):
                ws.cell(row=r, column=c).border = border
        for c, w in zip(range(1, 10), [6, 12, 40, 12, 11, 12, 8, 8, 14], strict=False):
            ws.column_dimensions[get_column_letter(c)].width = w

    # ---- 每个导入文件夹一张清册工作表 ----
    by_root = {}
    for v in inv["volumes"]:
        by_root.setdefault(v["scan_root"], []).append(v)
    used_names = set()
    for root_path in sorted(by_root, key=lambda p: (p is None, p or "")):
        name = sheet_name_for(root_path, used_names)
        write_register_sheet(wb.create_sheet(name), by_root[root_path])

    # ---- 图纸明细（逐张，全库汇总）----
    ws2 = wb.create_sheet("图纸明细")
    cols2 = ["序号", "类别", "图册号", "卷册名称", "图号", "图纸名称", "目录REV",
             "版本文件数", "最新版文件", "所在文件夹"]
    ws2.append(cols2)
    style_header(ws2, len(cols2))
    for n, i in enumerate(inv["items"], 1):
        ws2.append([n, i["category"], i["code"], i["volume_title"], i["drawing_no"],
                    i["title"], i["rev"], i["file_count"], i["latest_file"] or "",
                    i["folder_path"]])
    for c, w in zip(range(1, 11), [6, 14, 10, 24, 20, 36, 8, 10, 40, 50], strict=False):
        ws2.column_dimensions[get_column_letter(c)].width = w

    # ---- Sheet 3: 分类统计 ----
    ws3 = wb.create_sheet("分类统计")
    ws3.append([f"图纸清册 · 生成于 {inv['generated_at']}"])
    ws3["A1"].font = bold
    ws3.append([])
    total = len(inv["items"])
    ws3.append(["总图册数", len(inv["volumes"])])
    ws3.append(["图纸条目总数", total])
    ws3.append(["图纸文件总数", sum(v["files"] for v in inv["volumes"])])
    for r in range(3, 6):
        ws3.cell(row=r, column=1).font = bold
    ws3.append([])
    ws3.append(["类别", "图纸数量", "占比"])
    style_header(ws3, 3)
    for cat, n in inv["categories"].items():
        ws3.append([cat, n, f"{n / total:.1%}" if total else ""])
    ws3.append(["合计", total, "100%"])
    for c in range(1, 4):
        ws3.cell(row=ws3.max_row, column=c).font = bold
    for c, w in zip("ABC", [30, 12, 10], strict=False):
        ws3.column_dimensions[c].width = w

    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()
