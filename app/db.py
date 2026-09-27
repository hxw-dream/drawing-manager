"""SQLite 存层：索引库只记录信息，从不改动用户图纸文件。"""
import sqlite3
import sys
import time
from pathlib import Path


def _base_dir() -> Path:
    """开发态：项目根目录；PyInstaller 打包态：exe 所在目录（data 跟着 exe 走）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


DATA_DIR = _base_dir() / "data"
DB_PATH = DATA_DIR / "index.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS volumes (
    id INTEGER PRIMARY KEY,
    folder_path TEXT UNIQUE NOT NULL,
    folder_name TEXT NOT NULL,
    code TEXT,                -- 卷册号，如 D0401
    title TEXT,               -- 册名，如 综合办公楼照明施工图
    date_tag TEXT,            -- 文件夹名里的日期，如 2024.5.7
    rev_tag TEXT,             -- 修订标记，如 改明敷
    project TEXT,
    volume_ref_no TEXT,       -- ML 表头里的卷册参考号，如 13-F10001-D0401
    ml_file TEXT,
    scan_root TEXT,           -- 导入时扫描的根目录（用于按图纸库文件夹分组）
    parse_status TEXT NOT NULL DEFAULT 'ok',   -- ok | empty | failed
    parse_method TEXT,        -- text | ocr | dwg | none
    parse_error TEXT,
    ml_raw_text TEXT,
    scanned_at REAL
);
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    volume_id INTEGER NOT NULL REFERENCES volumes(id) ON DELETE CASCADE,
    seq TEXT,
    drawing_no TEXT NOT NULL,
    title TEXT,
    rev TEXT,
    page TEXT,
    remark TEXT,
    raw_text TEXT
);
CREATE INDEX IF NOT EXISTS idx_entries_drawing ON entries(drawing_no);
CREATE INDEX IF NOT EXISTS idx_entries_volume ON entries(volume_id);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    volume_id INTEGER NOT NULL REFERENCES volumes(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    ext TEXT,
    size INTEGER,
    mtime REAL,
    matched_entry_id INTEGER REFERENCES entries(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_files_volume ON files(volume_id);
CREATE INDEX IF NOT EXISTS idx_files_entry ON files(matched_entry_id);
CREATE TABLE IF NOT EXISTS folder_names (
    scan_root TEXT PRIMARY KEY,
    name TEXT NOT NULL           -- 导入文件夹的自定义显示名
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,   -- 项目名
    created_at REAL
);
CREATE TABLE IF NOT EXISTS folder_projects (
    scan_root TEXT PRIMARY KEY,  -- 导入根目录 → 所属项目
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE
);
"""


def project_filter(pid: int, alias: str = "v") -> str:
    """SQL 片段（按别名限定 volumes 表，需绑定 :pid 参数）。

    项目隔离规则：默认项目(1)持有未映射来源的册（含历史数据），
    其余项目只包含明确归入的文件夹，互不混淆。
    """
    return (
        f"(({alias}.scan_root IS NULL OR {alias}.scan_root NOT IN "
        "(SELECT fp.scan_root FROM folder_projects fp)) AND :pid = 1) "
        f"OR {alias}.scan_root IN (SELECT fp.scan_root FROM folder_projects fp "
        "WHERE fp.project_id = :pid)"
    )


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(volumes)")}
    if "scan_root" not in cols:  # 旧库升级
        conn.execute("ALTER TABLE volumes ADD COLUMN scan_root TEXT")
        conn.commit()
    conn.execute("INSERT OR IGNORE INTO projects(id, name, created_at) VALUES(1, '默认项目', ?)",
                 (time.time(),))
    conn.commit()
    return conn
