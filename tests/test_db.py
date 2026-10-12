"""索引库初始化不应让读取连接争抢写锁。"""
from contextlib import closing

from app import db


def test_reader_connects_while_another_connection_holds_write_lock(tmp_db, monkeypatch):
    original_connect = db.sqlite3.connect

    def short_connect(*args, **kwargs):
        kwargs["timeout"] = 0.2
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(db.sqlite3, "connect", short_connect)
    with closing(db.connect()) as writer:
        writer.execute("INSERT INTO projects(name) VALUES('未提交项目')")
        with closing(db.connect()) as reader:
            rows = reader.execute("SELECT name FROM projects").fetchall()
            assert [r["name"] for r in rows] == ["默认项目"]
        writer.rollback()


def test_initialize_preserves_legacy_data_and_adds_scan_root(tmp_db):
    db.DATA_DIR.mkdir(parents=True)
    with closing(db.sqlite3.connect(db.DB_PATH)) as conn, conn:
        conn.execute("""CREATE TABLE volumes (
            id INTEGER PRIMARY KEY, folder_path TEXT UNIQUE NOT NULL, folder_name TEXT NOT NULL
        )""")
        conn.execute("INSERT INTO volumes(folder_path, folder_name) VALUES('old/path', '旧册')")
    with closing(db.connect()) as conn:
        row = conn.execute("SELECT folder_name, scan_root FROM volumes").fetchone()
        assert row["folder_name"] == "旧册" and row["scan_root"] is None
        assert conn.execute("SELECT name FROM projects WHERE id=1").fetchone()[0] == "默认项目"
