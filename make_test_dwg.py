# 生成测试用 DWG 目录文件：手工构造 DXF 目录表 → ODA 转 DWG
import os
import subprocess
import sys
from pathlib import Path

ODA = r"D:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe"
WORK = Path(__file__).parent / "data" / "dwg_test"
VOL = WORK / "D7777【测试系统照明施工图】-2025.1.1"


def text(x, y, s, h=3.5):
    return f"0\nTEXT\n8\n0\n10\n{x}\n20\n{y}\n30\n0.0\n40\n{h}\n1\n{s}\n"


rows = [
    # 表头（y=260）
    (5, 260, "NO."), (20, 260, "DRAWING NO."), (60, 260, "FILE NAME"),
    (150, 260, "REV."), (160, 260, "PIECE"), (170, 260, "REMARK"),
    # 标题栏
    (20, 290, "PROJECT"), (60, 290, "XX电厂1642.6MW联合循环机组测试项目"),
    (20, 282, "VOLUME NAME"), (60, 282, "测试系统照明施工图"),
    (20, 274, "VOLUME REFERENCE NO."), (60, 274, "13-F10001-D7777"),
    # 目录条目
    (5, 250, "1"), (20, 250, "F10001-D7777-01"), (60, 250, "DESIGN SPECIFICATION 设计说明"), (150, 250, "00"), (160, 250, "1"),
    (5, 240, "2"), (20, 240, "F10001-D7777-02"), (60, 240, "LIGHTING LAYOUT FOR TEST ROOM 测试间照明布置图"), (150, 240, "00"), (160, 240, "1"),
    (5, 230, "3"), (20, 230, "F10001-D7777-03"), (60, 230, "材料设备清册 THE LIST OF MATERIAL"), (150, 230, "00"), (160, 230, "1"),
]
ents = "".join(text(x, y, s) for x, y, s in rows)
dxf = ("0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n0\nENDSEC\n"
       "0\nSECTION\n2\nENTITIES\n" + ents + "0\nENDSEC\n0\nEOF\n")

(WORK / "in").mkdir(parents=True, exist_ok=True)
(WORK / "out").mkdir(parents=True, exist_ok=True)
VOL.mkdir(parents=True, exist_ok=True)
(WORK / "in" / "test-ML.dxf").write_text(dxf, encoding="gbk")  # R12 DXF 按系统码页写中文

subprocess.run([ODA, str(WORK / "in"), str(WORK / "out"), "ACAD2018", "DWG", "0", "1", "*.DXF"],
               check=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
dwg = next((WORK / "out").glob("*.dwg"))
target = VOL / "F10001-D7777-ML.dwg"
dwg.replace(target)
for i in (1, 2, 3):
    (VOL / f"F10001-D7777-0{i}.pdf").write_bytes(b"%PDF-1.4 test")
print("生成的测试册:", VOL)
print("ML 文件:", target, target.stat().st_size, "bytes")
