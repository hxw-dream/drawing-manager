"""DWG 目录文件解析：ODA File Converter 转 DXF，再从 DXF 提取文字实体。

DXF 是文本格式，TEXT/MTEXT 实体自带精确坐标和内容（无 OCR 误差），
提取出的"伪 OCR 框"直接复用 parser_ml 的行解析引擎。
"""
import glob
import os
import re
import shutil
import subprocess

ODA_CANDIDATES = [
    r"D:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe",
    r"C:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe",
]
ODA_ENV = "ODA_CONVERTER"


def find_oda_converter():
    p = os.environ.get(ODA_ENV)
    if p and os.path.isfile(p):
        return p
    for c in ODA_CANDIDATES:
        if os.path.isfile(c):
            return c
    hits = glob.glob(r"D:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe") + \
           glob.glob(r"C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe") + \
           glob.glob(r"C:\Program Files (x86)\ODA\ODAFileConverter*\ODAFileConverter.exe")
    if hits:
        return sorted(hits)[-1]
    raise RuntimeError("未找到 ODA File Converter，请安装后重试，"
                       f"或设置环境变量 {ODA_ENV} 指向 ODAFileConverter.exe")


def dwg_to_dxf(dwg_path: str, workdir: str) -> str:
    """用 ODA File Converter 把单个 DWG 转成 DXF，返回 DXF 路径。"""
    exe = find_oda_converter()
    in_dir = os.path.join(workdir, "in")
    out_dir = os.path.join(workdir, "out")
    os.makedirs(in_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(in_dir, os.path.basename(dwg_path))
    if os.path.abspath(dst) != os.path.abspath(dwg_path):
        shutil.copy2(dwg_path, dst)
    subprocess.run(
        [exe, in_dir, out_dir, "ACAD2018", "DXF", "0", "1",
         f"*{os.path.splitext(dwg_path)[1].upper()}"],
        check=True, timeout=120,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = os.path.join(out_dir, os.path.splitext(os.path.basename(dwg_path))[0] + ".dxf")
    if not os.path.isfile(out):
        out_alt = glob.glob(os.path.join(out_dir, "*.dxf"))
        if not out_alt:
            raise RuntimeError("ODA 转换完成但未生成 DXF")
        out = out_alt[0]
    return out


_MTEXT_ESCAPES = re.compile(r"\\[A-Za-z][^;]*;|\\P|\\[{}\\]|^[{}]$|[{}]")


def _clean_mtext(s: str) -> str:
    s = _MTEXT_ESCAPES.sub(" ", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def parse_dxf_entities(dxf_path: str):
    """提取 DXF 的 TEXT/MTEXT 实体 → 伪 OCR 框列表（y 轴已转为向下增长）。"""
    raw = open(dxf_path, "rb").read()
    try:
        content = raw.decode("utf-8")           # DXF 2018+ 规范为 UTF-8
    except UnicodeDecodeError:
        content = raw.decode("gbk", errors="replace")  # 老版本 ANSI 按系统码页
    lines = content.splitlines()
    boxes = []
    ent = None

    def flush():
        nonlocal ent
        if ent and ent.get("text"):
            text = _clean_mtext(ent["text"])
            if text:
                h = ent.get("h") or 2.5
                x, y = ent.get("x", 0.0), ent.get("y", 0.0)
                width = len(text) * h * 1.05
                boxes.append({
                    "x0": x - h * 0.2, "x1": x + width,
                    # DXF y 向上，转为图像坐标 y 向下
                    "y0": -(y + h), "y1": -y,
                    "cy": -(y + h / 2), "text": text})
        ent = None

    in_entities = False
    i = 0
    while i + 1 < len(lines):
        code = lines[i].strip()
        val = lines[i + 1].strip()
        i += 2
        if code == "2" and val == "ENTITIES":
            in_entities = True
            continue
        if code == "0" and val == "ENDSEC":
            if in_entities:
                flush()
                break
            continue
        if not in_entities:
            continue
        if code == "0":
            flush()
            if val in ("TEXT", "MTEXT"):
                ent = {"text": ""}
        elif ent is not None:
            if code == "1":
                ent["text"] = (ent.get("text") or "") + val
            elif code == "3":  # MTEXT 长文本分片
                ent["text"] = (ent.get("text") or "") + val
            elif code == "10":
                ent["x"] = float(val)
            elif code == "20":
                ent["y"] = float(val)
            elif code == "40":
                ent["h"] = float(val)
    return boxes
