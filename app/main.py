"""FastAPI 入口：扫描 / 搜索 / 打开文件夹，并托管前端页面。仅监听 127.0.0.1。"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, inventory, scanner, versioning

app = FastAPI(title="工程图纸文件管理")

_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


@app.middleware("http")
async def reject_foreign_host(request, call_next):
    """只接受本机回环地址的 Host 头，阻断恶意网页经 DNS 重绑定读写本地接口。"""
    host = (request.headers.get("host") or "").lower().split(":", 1)[0]
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    if host not in _ALLOWED_HOSTS:
        return JSONResponse(status_code=403, content={"detail": "forbidden host"})
    return await call_next(request)

def _static_dir() -> Path:
    """开发态：app/static；PyInstaller 打包态：解包目录里的 app/static。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "app" / "static"
    return Path(__file__).resolve().parent / "static"


STATIC_DIR = _static_dir()
CONFIG_PATH = db.DATA_DIR / "config.json"

_scan_state = {"running": False, "log": [], "report": None, "error": None}
_scan_lock = threading.Lock()


def _log(msg):
    _scan_state["log"].append(msg)
    _scan_state["log"] = _scan_state["log"][-500:]


class ScanReq(BaseModel):
    root: str
    project_id: int = 1


class FolderRenameReq(BaseModel):
    root: str
    name: str = ""


class ProjectReq(BaseModel):
    name: str


class ProjectDelReq(BaseModel):
    id: int


class ProjectRenameReq(BaseModel):
    id: int
    name: str


class FolderAssignReq(BaseModel):
    root: str
    project_id: int


class OpenReq(BaseModel):
    path: str
    select: bool = False  # True=在资源管理器中定位文件，False=直接打开


@app.post("/api/scan")
def start_scan(req: ScanReq):
    with _scan_lock:
        if _scan_state["running"]:
            raise HTTPException(409, "扫描正在进行中")
        _scan_state.update(running=True, log=[], report=None, error=None)
    root = os.path.abspath(req.root.strip().strip('"'))
    project_id = req.project_id or 1

    def run():
        try:
            _scan_state["report"] = scanner.scan_root(root, _log)
            # 扫描完成后把根目录归入发起扫描时的项目（已有归属不动）
            with db.connect() as conn:
                conn.execute(
                    """INSERT INTO folder_projects(scan_root, project_id) VALUES(?, ?)
                       ON CONFLICT(scan_root) DO NOTHING""", (root, project_id))
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps({"last_root": root}, ensure_ascii=False),
                                   encoding="utf-8")
        except Exception as ex:
            _scan_state["error"] = f"{type(ex).__name__}: {ex}"
            _log(f"扫描出错: {ex}")
        finally:
            _scan_state["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return {"started": True, "root": root}


@app.get("/api/scan/status")
def scan_status():
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except UnicodeDecodeError:  # 兼容历史上按 GBK 写入的文件
            cfg = json.loads(CONFIG_PATH.read_text(encoding="gbk"))
    else:
        cfg = {}
    return {**_scan_state, "last_root": cfg.get("last_root")}


@app.get("/api/volumes")
def list_volumes(project: int = 1):
    pf = db.project_filter(project)
    with db.connect() as conn:
        scanner.purge_missing_volumes(conn)
        rows = conn.execute(
            f"""SELECT v.*, COUNT(DISTINCT e.id) AS entry_count, COUNT(DISTINCT f.id) AS file_count
               FROM volumes v
               LEFT JOIN entries e ON e.volume_id=v.id
               LEFT JOIN files f ON f.volume_id=v.id
               WHERE ({pf})
               GROUP BY v.id ORDER BY v.code, v.date_tag""", {"pid": project}).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d.pop("ml_raw_text", None)
            if d.get("ml_file"):
                d["ml_path"] = os.path.join(d["folder_path"], d["ml_file"])
            out.append(d)
        return out


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _haystack(*parts) -> str:
    return re.sub(r"\s+", "", " ".join(p or "" for p in parts)).upper()


def _match_score(hay: str, tokens) -> int:
    """每个关键字都必须命中：非中文按整体子串，中文拆单字全部在场即算命中。
    连续出现加分更多，用于结果排序。返回 -1 表示不命中。"""
    score = 0
    for tok in tokens:
        t = re.sub(r"\s+", "", tok).upper()
        if not t:
            continue
        if t in hay:
            score += len(t) * 2
            continue
        cjk = [c for c in t if _CJK_RE.match(c)]
        rest = "".join(c for c in t if not _CJK_RE.match(c))
        if (rest and rest not in hay) or any(c not in hay for c in cjk):
            return -1
        score += len(cjk)
    return score


@app.get("/api/search")
def search(q: str, project: int = 1):
    tokens = [t for t in re.split(r"\s+", q.strip()) if t]
    if not tokens:
        return {"q": q, "entry_groups": [], "loose_files": [], "volume_hits": []}
    pf = db.project_filter(project)
    with db.connect() as conn:
        entry_rows = [dict(r) for r in conn.execute(
            f"""SELECT e.id, e.seq, e.drawing_no, e.title, e.rev, e.page,
                      v.id AS volume_id, v.folder_name, v.folder_path, v.code,
                      v.title AS volume_title, v.date_tag, v.rev_tag, v.scanned_at,
                      v.project
               FROM entries e JOIN volumes v ON v.id=e.volume_id
               WHERE ({pf})""", {"pid": project}).fetchall()]
        for r in entry_rows:
            r["files"] = [dict(f) for f in conn.execute(
                "SELECT id, filename, path, ext, size, mtime FROM files WHERE matched_entry_id=?",
                (r["id"],)).fetchall()]
        all_files = [dict(r) for r in conn.execute(
            f"""SELECT f.id, f.filename, f.path, f.ext, f.size,
                      v.folder_name, v.folder_path, v.code, v.title AS volume_title,
                      v.date_tag, v.rev_tag, v.project
               FROM files f JOIN volumes v ON v.id=f.volume_id
               WHERE ({pf}) AND f.matched_entry_id IS NULL AND f.filename <> v.ml_file""",
            {"pid": project}).fetchall()]
        volume_rows = [dict(r) for r in conn.execute(
            f"""SELECT id, folder_name, folder_path, code, title, date_tag, rev_tag,
                      project, parse_status, ml_file, ml_raw_text
               FROM volumes
               WHERE ({db.project_filter(project, alias='volumes')})""",
            {"pid": project}).fetchall()]
        for r in volume_rows:
            r["entry_count"] = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE volume_id=?", (r["id"],)).fetchone()[0]

    def pick(rows, own_fn, extra_fn):
        """命中条件：所有关键字在 自身+所在册 字段合集中满足；
        排序：自身字段（图号/图名/文件名）命中的权重远高于册级字段。"""
        out = []
        for r in rows:
            own, extra = own_fn(r), extra_fn(r)
            if _match_score(own + extra, tokens) < 0:
                continue
            rank = max(_match_score(own, tokens), 0) * 3 + max(_match_score(extra, tokens), 0)
            r["_score"] = rank
            out.append(r)
        out.sort(key=lambda r: r["_score"], reverse=True)
        for r in out:
            r.pop("_score", None)
        return out

    matched_entries = pick(
        entry_rows,
        lambda r: _haystack(r["drawing_no"], r["title"]),
        lambda r: _haystack(r["folder_name"], r["folder_path"], r["code"],
                            r["volume_title"], r["project"]))
    loose_files = pick(
        all_files,
        lambda r: _haystack(r["filename"]),
        lambda r: _haystack(r["folder_name"], r["folder_path"], r["code"],
                            r["volume_title"], r["project"]))
    volume_hits = pick(
        volume_rows,
        lambda r: _haystack(r["folder_name"], r["title"], r["code"], r["project"], r["rev_tag"]),
        lambda r: _haystack(r["ml_raw_text"]))
    for r in volume_hits:
        r.pop("ml_raw_text", None)
        if r.get("ml_file"):
            r["ml_path"] = os.path.join(r["folder_path"], r["ml_file"])
    attached = {f["id"] for r in matched_entries for f in r["files"]}
    loose_files = [f for f in loose_files if f["id"] not in attached]
    return {"q": q, "entry_groups": versioning.group_entry_hits(matched_entries),
            "loose_files": loose_files, "volume_hits": volume_hits}


@app.get("/api/folders")
def get_folder_names():
    with db.connect() as conn:
        return {r["scan_root"]: r["name"] for r in
                conn.execute("SELECT scan_root, name FROM folder_names").fetchall()}


@app.post("/api/folders/rename")
def rename_folder(req: FolderRenameReq):
    if not req.root.strip():
        raise HTTPException(400, "文件夹路径不能为空")
    name = req.name.strip()
    with db.connect() as conn:
        if name:
            conn.execute(
                """INSERT INTO folder_names(scan_root, name) VALUES(?, ?)
                   ON CONFLICT(scan_root) DO UPDATE SET name=excluded.name""",
                (req.root, name))
        else:  # 留空 = 恢复默认名（文件夹名）
            conn.execute("DELETE FROM folder_names WHERE scan_root=?", (req.root,))
    return {"ok": True}


@app.get("/api/projects")
def list_projects():
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT p.id, p.name,
                      (SELECT COUNT(*) FROM folder_projects fp WHERE fp.project_id=p.id) AS folders
               FROM projects p ORDER BY p.id""").fetchall()
        return [dict(r) for r in rows]


@app.post("/api/projects")
def create_project(req: ProjectReq):
    name = req.name.strip()
    if not name:
        raise HTTPException(400, "项目名不能为空")
    with db.connect() as conn:
        dup = conn.execute("SELECT id FROM projects WHERE name=?", (name,)).fetchone()
        if dup:
            raise HTTPException(409, f"项目「{name}」已存在")
        cur = conn.execute("INSERT INTO projects(name, created_at) VALUES(?, ?)",
                           (name, time.time()))
        return {"id": cur.lastrowid, "name": name}


@app.post("/api/projects/rename")
def rename_project(req: ProjectRenameReq):
    name = req.name.strip()
    if not name:
        raise HTTPException(400, "项目名不能为空")
    with db.connect() as conn:
        if not conn.execute("SELECT id FROM projects WHERE id=?", (req.id,)).fetchone():
            raise HTTPException(404, "项目不存在")
        dup = conn.execute("SELECT id FROM projects WHERE name=? AND id<>?",
                           (name, req.id)).fetchone()
        if dup:
            raise HTTPException(409, f"项目「{name}」已存在")
        conn.execute("UPDATE projects SET name=? WHERE id=?", (name, req.id))
    return {"ok": True}


@app.post("/api/projects/delete")
def delete_project(req: ProjectDelReq):
    if req.id == 1:
        raise HTTPException(400, "默认项目不能删除")
    with db.connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM folder_projects WHERE project_id=?",
                         (req.id,)).fetchone()[0]
        if n:
            raise HTTPException(409, f"该项目下还有 {n} 个图纸文件夹，请先把它们归入其他项目")
        conn.execute("DELETE FROM projects WHERE id=?", (req.id,))
    return {"ok": True}


@app.post("/api/folders/assign")
def assign_folder(req: FolderAssignReq):
    if not req.root.strip():
        raise HTTPException(400, "文件夹路径不能为空")
    with db.connect() as conn:
        if not conn.execute("SELECT id FROM projects WHERE id=?", (req.project_id,)).fetchone():
            raise HTTPException(404, "目标项目不存在")
        conn.execute(
            """INSERT INTO folder_projects(scan_root, project_id) VALUES(?, ?)
               ON CONFLICT(scan_root) DO UPDATE SET project_id=excluded.project_id""",
            (req.root, req.project_id))
    return {"ok": True}


@app.get("/api/versions")
def version_groups(project: int = 1):
    """同一图号挂了多个文件的，按版本时间线分组返回（旧→新）。"""
    pf = db.project_filter(project)
    with db.connect() as conn:
        scanner.purge_missing_volumes(conn)
        rows = [dict(r) for r in conn.execute(
            f"""SELECT e.id AS entry_id, e.drawing_no, e.title, e.rev,
                      v.id AS volume_id, v.folder_name, v.folder_path, v.code,
                      v.title AS volume_title, v.date_tag AS vol_date, v.rev_tag AS vol_rev,
                      v.scan_root,
                      f.id AS file_id, f.filename, f.path, f.size, f.mtime
               FROM entries e
               JOIN volumes v ON v.id = e.volume_id
               JOIN files f ON f.matched_entry_id = e.id
               WHERE ({pf})
               ORDER BY v.code, e.drawing_no""", {"pid": project}).fetchall()]
    groups = {}
    for r in rows:
        key = (r["volume_id"], r["drawing_no"])
        g = groups.setdefault(key, {
            "drawing_no": r["drawing_no"], "title": r["title"], "rev": r["rev"],
            "folder_name": r["folder_name"], "folder_path": r["folder_path"],
            "volume_title": r["volume_title"], "code": r["code"],
            "vol_date": r["vol_date"], "vol_rev": r["vol_rev"],
            "scan_root": r["scan_root"], "versions": []})
        stem = versioning.normalize_no(Path(r["filename"]).stem)
        date_tag, note = versioning.parse_version_suffix(r["drawing_no"], stem)
        g["versions"].append({
            "filename": r["filename"], "path": r["path"], "size": r["size"],
            "mtime": r["mtime"], "ver_date": date_tag, "note": note,
            "is_base": date_tag is None and note is None})
    out = []
    for g in groups.values():
        if len(g["versions"]) < 2:
            continue
        g["versions"].sort(key=lambda v: (v["ver_date"] or "0000.00.00", v["mtime"]))
        out.append(g)
    out.sort(key=lambda g: (g["code"] or "", g["drawing_no"]))
    return {"groups": out, "total": len(out)}


@app.get("/api/inventory")
def get_inventory(project: int = 1):
    with db.connect() as conn:
        scanner.purge_missing_volumes(conn)
        return inventory.build_inventory(conn, project)


@app.get("/api/inventory/export")
def export_inventory(project: int = 1):
    with db.connect() as conn:
        inv = inventory.build_inventory(conn, project)
    data = inventory.make_xlsx(inv)
    fname = f"图纸清册_{datetime.now():%Y%m%d_%H%M}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"})


@app.post("/api/open")
def open_path(req: OpenReq):
    p = req.path
    if not os.path.exists(p):
        raise HTTPException(404, f"路径不存在: {p}")
    if req.select:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(p)])
    else:
        os.startfile(p)  # noqa: S606 本地单机工具，默认程序打开
    return {"ok": True}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
