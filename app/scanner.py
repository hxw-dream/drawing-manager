"""扫描根目录：识别册（含 -ML 文件的文件夹）→ 解析 ML → 索引文件并匹配图号。"""
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from . import db
from .parser_ml import parse_ml
from .versioning import normalize_no


# 目录文件命名约定：按 -_ 切分后存在 ML 段（如 F10001-D0401-ML.pdf）
def is_ml_file(filename: str) -> bool:
    stem = Path(filename).stem.upper()
    return any(seg in ("ML", "MULU") for seg in re.split(r"[-_ ]+", stem))

DATE_RE = re.compile(r"(20\d{2})[.\-/年](\d{1,2})(?:[.\-/月](\d{1,2}))日?")


def parse_folder_name(name: str):
    """D0401【综合办公楼照明施工图】-2024.5.7-改明敷 → 各字段。
    兼容 D0403(1)【…】 这类带括号批次号的写法，图册号取括号前的主体。"""
    code = title = date_tag = rev_tag = None
    raw_code = None
    m = re.match(r"^\s*([A-Za-z0-9]{2,}(?:[（(]\d+[）)])?)\s*【", name)
    if not m:
        m = re.match(r"^\s*([A-Za-z0-9]{2,}(?:[（(]\d+[）)])?)\s*[-_ ]", name)
    if m:
        raw_code = m.group(1)
        code = re.sub(r"[（(]\d+[）)]$", "", raw_code).upper()
    m = re.search(r"【([^】]+)】", name)
    if m:
        title = m.group(1).strip()
    m = DATE_RE.search(name)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3) or "1"
        date_tag = f"{y}.{int(mo):02d}.{int(d):02d}"
        date_raw = m.group(0)
    else:
        date_raw = None
    rest = name
    for part in [raw_code or code or "", (f"【{title}】" if title else ""), date_raw or ""]:
        if part:
            rest = rest.replace(part, " ", 1)
    pieces = []
    for p in re.split(r"[-_—]+", rest):
        token = p.strip().strip("【】[]()（） ").strip()
        if token:
            pieces.append(token)
    rev_tag = " ".join(pieces) or None
    return code, title, date_tag, rev_tag


def _match_files_to_entries(entries, files_rows):
    """文件名 ↔ 目录条目匹配：先整体图号匹配，退化为末段序号匹配。

    图号愈合：OCR 偶尔会吃掉图号末尾的数字（如 -01 识别成 -0）。
    当某条目的图号恰好等于某文件名去掉末尾 1~2 位数字、且没有其他
    条目精确对应这个文件名时，用文件名（人工命名，更可靠）纠正图号。
    """
    all_nos = {normalize_no(e["drawing_no"]) for e in entries}
    for f in files_rows:
        stem = normalize_no(Path(f["filename"]).stem)
        # 先全量找精确匹配（避免 X-1 靠包含错抢 X-12.pdf），找不到再做包含匹配
        hit = next((e for e in entries
                    if normalize_no(e["drawing_no"]) == stem), None)
        if hit is None:
            for e in entries:
                no = normalize_no(e["drawing_no"])
                if stem.endswith("-" + no) or no in stem:
                    hit = e
                    if stem not in all_nos and re.fullmatch(r"\d{1,2}", stem[len(no):]):
                        e["drawing_no"] = stem  # OCR 掉尾数字，按文件名愈合
                        e["_healed"] = True
                    break
        if hit is None:
            stem_last = stem.rsplit("-", 1)[-1]
            if stem_last.isdigit():
                cands = [e for e in entries
                         if e["drawing_no"].rsplit("-", 1)[-1] == stem_last]
                if len(cands) == 1:
                    hit = cands[0]
        if hit is not None:
            f["matched_entry_id"] = hit["_id"]


def _ml_fingerprint(path: str) -> str:
    st = os.stat(path)
    return f"{st.st_size}:{st.st_mtime_ns}"


def parse_ml_cached(conn, ml_path: str) -> dict:
    """ML 解析结果按文件指纹缓存：内容未变直接复用，跳过 OCR/DXF 解析。

    两百册量级的例行重扫因此从数十分钟降到秒级。"""
    ml_path = os.path.abspath(ml_path)
    sig = _ml_fingerprint(ml_path)
    hit = conn.execute(
        "SELECT entries_json, header_json, raw_text, method FROM parse_cache "
        "WHERE ml_path=? AND sig=?", (ml_path, sig)).fetchone()
    if hit:
        entries = json.loads(hit["entries_json"])
        return {"entries": entries,
                "header": json.loads(hit["header_json"] or "null") or {},
                "raw_text": hit["raw_text"] or "", "method": hit["method"],
                "parse_status": "ok" if entries else "empty"}
    parsed = parse_ml(ml_path)
    conn.execute(
        """INSERT INTO parse_cache(ml_path, sig, entries_json, header_json, raw_text, method)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(ml_path) DO UPDATE SET sig=excluded.sig, entries_json=excluded.entries_json,
             header_json=excluded.header_json, raw_text=excluded.raw_text, method=excluded.method""",
        (ml_path, sig, json.dumps(parsed["entries"], ensure_ascii=False),
         json.dumps(parsed["header"], ensure_ascii=False),
         parsed["raw_text"][:60000], parsed["method"]))
    return parsed


def scan_volume(conn, folder: str, log, root=None):
    folder_name = os.path.basename(folder.rstrip("\\/"))
    code, title, date_tag, rev_tag = parse_folder_name(folder_name)
    names = sorted(os.listdir(folder))
    ml_files = [n for n in names if is_ml_file(n)]
    pdfs = sorted(n for n in ml_files if n.lower().endswith(".pdf"))
    if pdfs:  # 同时存在 PDF 与 DWG 目录文件时，优先识别 PDF
        ml_files = pdfs[:1] + [n for n in ml_files if n not in pdfs]
    other_files = [n for n in names if os.path.isfile(os.path.join(folder, n))]

    row = {
        "folder_path": folder, "folder_name": folder_name, "code": code,
        "title": title, "date_tag": date_tag, "rev_tag": rev_tag,
        "project": None, "volume_ref_no": None,
        "ml_file": ml_files[0] if ml_files else None, "scan_root": root,
        "parse_status": "failed", "parse_method": "none", "parse_error": None,
        "ml_raw_text": None, "scanned_at": time.time(),
    }
    entries = []
    if not ml_files:
        row["parse_status"] = "empty"
        row["parse_error"] = "文件夹内没有 -ML 目录文件，无法解析目录条目"
        log(f"  [skip] {folder_name}: 未找到 -ML 目录文件")
    else:
        try:
            parsed = parse_ml_cached(conn, os.path.join(folder, ml_files[0]))
            entries = parsed["entries"]
            row["parse_status"] = parsed["parse_status"]
            row["parse_method"] = parsed["method"]
            row["ml_raw_text"] = parsed["raw_text"][:60000]
            row["project"] = parsed["header"].get("project")
            row["volume_ref_no"] = parsed["header"].get("volume_ref_no")
            # 册名以 ML 目录文件识别出的为准，文件夹名里的【】仅作后备
            ml_title = parsed["header"].get("volume_name")
            if ml_title:
                row["title"] = ml_title
            elif not row["title"]:
                row["title"] = None
            if not row["code"] and row["volume_ref_no"]:
                row["code"] = re.sub(r"[（(]\d+[）)]", "",
                                     normalize_no(row["volume_ref_no"]).rsplit("-", 1)[-1])
            # 纯图号命名的文件夹（如内层 "D0401"）不会把图号本身当修订标记
            if row["rev_tag"] and row["code"] and row["rev_tag"].upper() == row["code"]:
                row["rev_tag"] = None
            if entries:
                log(f"  [ok  ] {folder_name}: {len(entries)} 条 ({parsed['method']})")
            else:
                row["parse_error"] = "ML 解析不出条目（可能是空目录或版式特殊）"
                log(f"  [warn] {folder_name}: {row['parse_error']}")
        except Exception as ex:
            row["parse_error"] = f"{type(ex).__name__}: {ex}"
            log(f"  [fail] {folder_name}: {row['parse_error']}")

    old = conn.execute("SELECT id FROM volumes WHERE folder_path=?", (folder,)).fetchone()
    if old:
        conn.execute("DELETE FROM volumes WHERE id=?", (old["id"],))
    cur = conn.execute(
        """INSERT INTO volumes(folder_path,folder_name,code,title,date_tag,rev_tag,
           project,volume_ref_no,ml_file,scan_root,parse_status,parse_method,parse_error,
           ml_raw_text,scanned_at)
           VALUES(:folder_path,:folder_name,:code,:title,:date_tag,:rev_tag,
           :project,:volume_ref_no,:ml_file,:scan_root,:parse_status,:parse_method,:parse_error,
           :ml_raw_text,:scanned_at)""", row)
    vid = cur.lastrowid
    entry_rows = []
    for e in entries:
        c = conn.execute(
            """INSERT INTO entries(volume_id,seq,drawing_no,title,rev,page,remark,raw_text)
               VALUES(?,?,?,?,?,?,?,?)""",
            (vid, e.get("seq"), e["drawing_no"], e.get("title"), e.get("rev"),
             e.get("page"), e.get("remark"), None))
        entry_rows.append({"_id": c.lastrowid, "drawing_no": e["drawing_no"]})
    files_rows = []
    for n in other_files:
        p = os.path.join(folder, n)
        try:
            st = os.stat(p)
        except OSError:
            continue
        files_rows.append({"filename": n, "path": p, "ext": Path(n).suffix.lower(),
                           "size": st.st_size, "mtime": st.st_mtime,
                           "matched_entry_id": None})
    _match_files_to_entries(entry_rows, files_rows)
    for e in entry_rows:
        if e.pop("_healed", False):
            conn.execute("UPDATE entries SET drawing_no=? WHERE id=?",
                         (e["drawing_no"], e["_id"]))
    for f in files_rows:
        conn.execute(
            """INSERT INTO files(volume_id,filename,path,ext,size,mtime,matched_entry_id)
               VALUES(?,?,?,?,?,?,?)""",
            (vid, f["filename"], f["path"], f["ext"], f["size"], f["mtime"],
             f["matched_entry_id"]))
    unmatched = [f["filename"] for f in files_rows if f["matched_entry_id"] is None
                 and not is_ml_file(f["filename"])]
    return {"folder": folder, "status": row["parse_status"],
            "reason": row["parse_error"], "ml_file": row["ml_file"],
            "entries": len(entries), "files": len(files_rows),
            "unmatched": unmatched}


def purge_missing_volumes(conn):
    """删掉磁盘上已不存在的册记录（文件夹被移动/删除后索引自动跟上现实）。"""
    gone = [r["folder_path"] for r in conn.execute(
        "SELECT folder_path FROM volumes").fetchall()
        if not os.path.isdir(r["folder_path"])]
    for g in gone:
        conn.execute("DELETE FROM volumes WHERE folder_path=?", (g,))
    return gone


def scan_root(root: str, log=print, should_stop=None):
    """递归扫描 root 下所有册。log 为进度回调。"""
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise ValueError(f"不是有效目录: {root}")
    report = {"root": root, "started": datetime.now().isoformat(timespec="seconds"),
              "volumes": [], "ok": 0, "warn": 0, "fail": 0, "total_entries": 0,
              "unmatched": []}
    log(f"开始扫描: {root}")
    targets = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "$"))
                       and d not in ("System Volume Information",)]
        if any(is_ml_file(f) for f in filenames):
            targets.append(dirpath)
            dirnames[:] = []  # 册内不再嵌套找册
    report["found"] = len(targets)
    log(f"发现 {len(targets)} 个含 -ML 目录文件的文件夹")
    with db.connect() as conn:
        ignored = {r["folder_path"] for r in
                   conn.execute("SELECT folder_path FROM ignored_volumes").fetchall()}
        for folder in sorted(targets):
            if folder in ignored:
                log(f"  [skip] {os.path.basename(folder)}: 已手动从索引移除（可在册列表恢复）")
                continue
            if should_stop and should_stop():
                report["stopped"] = True
                log("⏹ 收到停止请求，本次扫描中止（已入库的册保留，未扫的下次继续）")
                break
            try:
                v = scan_volume(conn, folder, log, root=root)
            except Exception as ex:
                v = {"folder": folder, "status": "failed", "entries": 0, "files": 0,
                     "unmatched": [], "reason": f"{type(ex).__name__}: {ex}",
                     "ml_file": None}
                log(f"  [fail] {folder}: {v['reason']}")
            report["volumes"].append(v)
            report["total_entries"] += v.get("entries", 0)
            report["unmatched"].extend(v.get("unmatched", []))
            if v["status"] == "ok":
                report["ok"] += 1
            elif v["status"] in ("failed", "dwg_unsupported"):
                report["fail"] += 1
            else:
                report["warn"] += 1
        # 旧数据回填：本根目录下尚未记录来源的册补上 scan_root
        for r in conn.execute(
                "SELECT id, folder_path FROM volumes WHERE scan_root IS NULL").fetchall():
            if r["folder_path"].startswith(root + os.sep):
                conn.execute("UPDATE volumes SET scan_root=? WHERE id=?", (root, r["id"]))
        # 清理磁盘上已不存在的册（不限当前根目录，索引始终反映磁盘现状）
        gone = purge_missing_volumes(conn)
        report["removed_missing"] = len(gone)
        for g in gone:
            log(f"  [清理] {g} 文件夹已不存在，移出索引")
    report["finished"] = datetime.now().isoformat(timespec="seconds")
    log(f"扫描完成: {report['ok']} 册成功 / {report['warn']} 警告 / {report['fail']} 失败，"
        f"共 {report['total_entries']} 条目录条目")
    return report
