# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：onedir 绿色文件夹模式
from PyInstaller.utils.hooks import collect_all

datas = [("app/static", "app/static")]
binaries = []
hiddenimports = [
    "uvicorn", "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
    "app", "app.main", "app.db", "app.scanner", "app.parser_ml",
    "app.versioning", "app.inventory", "app.dwg",
]
# OCR 模型（onnx）、pdfium 渲染库、onnxruntime DLL 都在包数据里，需显式收集
for pkg in ("rapidocr_onnxruntime", "pypdfium2", "onnxruntime"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name="DrawingManager", console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, name="drawing-manager")
