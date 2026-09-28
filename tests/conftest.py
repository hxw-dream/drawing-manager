"""测试公共设施：临时索引库 + 用真实 ML 黄金用例搭出的临时图纸库。"""
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db as db_mod  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """每个测试一套独立的索引库与配置文件。"""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(db_mod, "DATA_DIR", data_dir)
    monkeypatch.setattr(db_mod, "DB_PATH", data_dir / "index.db")
    from app import main as main_mod
    monkeypatch.setattr(main_mod, "CONFIG_PATH", data_dir / "config.json")
    yield data_dir


def make_volume(root: Path, folder: str, ml_fixture: str, drawing_exts=(".pdf",)):
    """在 root 下搭一册：真实 ML + 按图号命名的假图纸文件。"""
    vol = root / folder
    vol.mkdir(parents=True)
    shutil.copy2(FIXTURES / ml_fixture, vol / "F10001-D0401-ML.pdf")
    for i in (1, 2, 3):
        (vol / f"F10001-D0401-0{i}{drawing_exts[0] if i <= len(drawing_exts) else '.pdf'}").write_bytes(b"%PDF-1.4 test")
    return vol


@pytest.fixture()
def sample_library(tmp_path):
    """一个含两册的临时图纸库（同一图号前缀 D0401，便于版本/搜索断言）。"""
    root = tmp_path / "tuzhi"
    root.mkdir()
    v1 = make_volume(root, "D0401【综合办公楼照明施工图】-2024.5.7-改明敷", "ml-D0401-scanned.pdf")
    # 第二册：同名文件夹加日期后缀形成整册版本对
    make_volume(root, "D0401【综合办公楼照明施工图】-2025.1.1", "ml-D0401-scanned.pdf")
    # 一份带版本后缀的单图文件
    (v1 / "F10001-D0401-02-2025.3.9桥架调整-模型.pdf").write_bytes(b"%PDF-1.4 rev")
    return root
