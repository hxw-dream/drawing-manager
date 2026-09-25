"""SQLite 存层：索引库只记录信息，从不改动用户图纸文件。"""
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
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
    parse_status TEXT NOT NULL DEFAULT 'ok',   -- ok | empty | failed | dwg_unsupported
    parse_method TEXT,        -- text | ocr | none
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
"""


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn
