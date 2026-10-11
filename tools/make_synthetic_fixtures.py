# 生成脱敏合成 ML 目录 PDF（三份黄金用例的替代品）。
# 版式复刻真实 ML 的 OCR 坐标几何（实测 300dpi 框位），
# 使合成件与真实文件走完全相同的解析路径。
# 跑法：.venv/Scripts/python tools/make_synthetic_fixtures.py
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def font(size, bold=False):
    for name in (["msyhbd.ttc", "msyh.ttc"] if bold else ["msyh.ttc", "simhei.ttf", "arial.ttf"]):
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_page(path, rows, header, title_x=930):
    """rows: [(seq, drawing_no, en_title, cn_title, rev)]，坐标复刻真实 ML 版式。
    title_x：标题起始 x（全角长图号需右移避免与标题物理重叠被 OCR 合并）。"""
    W, H = 2481, 3508
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f_en, f_cn, f_lab = font(44), font(44), font(36)

    def text(x, y, s, f=None):
        d.text((x, y), s, fill="black", font=f or f_en)

    # --- 标题栏（坐标取自真实 ML OCR 框位）---
    text(410, 118, "VOLUME REFERENCE NO.", f_lab)
    text(362, 190, header["ref"])
    text(1182, 186, "图纸&文件目录（首页）", f_cn)
    text(773, 270, "CONTENT OF DRAWINGS & FILES (1ST PAGE)")
    text(403, 381, "PROJECT", f_lab)
    text(622, 386, header["project"])
    text(407, 505, "SPECIALTY", f_lab)
    text(632, 490, header["specialty"])
    text(407, 608, "VOLUME", f_lab)
    text(403, 654, "NAME", f_lab)
    text(634, 645, header["volume_name"])

    # --- 表头行（y≈790，与真实 ML 表头带一致）---
    hy = 790
    for x, label in ((324, "NO."), (533, "DRAWING NO."), (1298, "FILE NAME"),
                     (1880, "REV.")):
        text(x, hy, label, f_lab)
    d.line((120, hy + 52, 2400, hy + 52), fill="black", width=5)

    # --- 条目行（首行 y≈905，行距 ≈130，与真实版式一致）---
    y = 905
    d.line((120, y - 20, 2400, y - 20), fill="black", width=5)
    for seq, no, en, cn, rev in rows:
        text(343, y + 2, seq, f_lab)
        text(431, y, no)
        text(title_x, y - 18, en)
        text(title_x, y + 52, cn)
        text(1932, y, rev, f_lab)
        y += 130
        d.line((120, y - 20, 2400, y - 20), fill="black", width=3)

    text(162, 3241, "NOTE:", f_lab)
    # 无损嵌入 PNG → PDF（PIL 默认 JPEG 压缩会糊掉细笔画，OCR 掉字）
    import io
    import img2pdf
    buf = io.BytesIO()
    img.save(buf, "PNG")
    path.write_bytes(img2pdf.convert(buf.getvalue(), layout_fun=img2pdf.get_fixed_dpi_layout_fun((300, 300))))


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    # 用例1：普通扫描件
    make_page(OUT / "ml-demo-lighting-scanned.pdf",
              [("1", "F10001-D0401-01", "DESIGN SPECIFICATION", "设计说明", "00"),
               ("2", "F10001-D0401-02", "LIGHTING LAYOUT FOR OFFICE", "综合办公楼照明布置图", "00"),
               ("3", "F10001-D0401-03", "LIGHTING LAYOUT FOR PUMP HOUSE", "泵房照明布置图", "00"),
               ("4", "F10001-D0401-04", "MATERIAL LIST", "材料设备清册", "00")],
              {"ref": "13-F10001-D0401", "project": "XX电厂一期扩建项目",
               "specialty": "PRIMARY ELECTRICAL", "volume_name": "综合办公楼照明施工图"})

    # 用例2：六条目电缆敷设
    make_page(OUT / "ml-demo-cable-scanned.pdf",
              [("1", "F10001-D0402-01", "CABLE TRAY DESIGN SPEC", "化学水系统电缆敷设设计说明", "00"),
               ("2", "F10001-D0402-02", "WATER PLANT TRAY LAYOUT", "水处理室电缆通道布置图", "00"),
               ("3", "F10001-D0402-03", "STORAGE ROOM TRAY LAYOUT", "储藏间电缆通道布置图", "00"),
               ("4", "F10001-D0402-04", "LABORATORY TRAY LAYOUT", "化验楼电缆通道布置图", "01"),
               ("5", "F10001-D0402-05", "OUTDOOR TRENCH LAYOUT", "室外电缆沟布置图", "01"),
               ("6", "F10001-D0402-06", "MATERIAL LIST", "材料设备清册", "01")],
              {"ref": "13-F10001-D0402", "project": "XX电厂一期扩建项目",
               "specialty": "PRIMARY ELECTRICAL", "volume_name": "化学水系统电缆敷设施工图"})

    # 用例3：全角括号图号
    make_page(OUT / "ml-demo-fullwidth-scanned.pdf",
              [("1", "F10001-D0403（1）-02", "WIRING DESIGN SPEC", "接线图设计说明", "00"),
               ("2", "F10001-D0403（1）-03", "WIRING DIAGRAM GT PC 12", "燃机PC段接线图", "00"),
               ("3", "F10001-D0403（1）-04", "WIRING DIAGRAM LIGHTING PC", "照明PC段接线图", "00"),
               ("4", "F10001-D0403（1）-05", "WIRING DIAGRAM COMMON PC", "公用段接线图", "00"),
               ("5", "F10001-D0403（1）-11", "MATERIAL LIST", "材料设备清册", "00")],
              {"ref": "13-F10001-D0403", "project": "XX电厂一期扩建项目",
               "specialty": "PRIMARY ELECTRICAL", "volume_name": "电控楼照明检修接线图"},
              title_x=1080)

    print("合成用例已生成:", *sorted(p.name for p in OUT.glob("ml-demo-*")), sep="\n  ")


if __name__ == "__main__":
    main()
