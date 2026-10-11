"""版本聚类：同卷册号多文件夹 = 整册多版本；同图号多文件 = 单图多版本。"""
import re
import unicodedata

VER_DATE_RE = re.compile(r"(20\d{2})[.\-/年](\d{1,2})(?:[.\-/月](\d{1,2}))日?")


def normalize_no(s: str) -> str:
    """图号/文件名归一化：全角转半角（NFKC）、长划线归一、去空白、转大写。
    如 F10001-D0403（1）-01 → F10001-D0403(1)-01"""
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("—", "-").replace("－", "-")
    return re.sub(r"\s+", "", s).upper()


def parse_version_suffix(drawing_no: str, stem: str):
    """从带版本后缀的文件名里解出（日期, 修改说明）。

    如 F10001-D0401-03-2025.3.9电缆桥架定位调整-模型
      → ('2025.03.09', '电缆桥架进化学储藏间定位变化 模型')
    无后缀（原版）→ (None, None)
    """
    rem = stem[len(drawing_no):].strip("-_ ")
    if not rem:
        return None, None
    date_tag = None
    m = VER_DATE_RE.search(rem)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3) or "1"
        date_tag = f"{y}.{int(mo):02d}.{int(d):02d}"
        rem = (rem[:m.start()] + " " + rem[m.end():]).strip("-_ ")
    rem = re.sub(r"[【】\[\]（）()]", " ", rem)
    note = re.sub(r"\s{2,}", " ", rem.replace("-", " ")).strip()
    return date_tag, (note or None)


def volume_sort_key(volume_row):
    """整册版本排序键：日期新在前，其次修订标记有值优先，再次扫描时间新在前。"""
    d = volume_row["date_tag"] or ""
    m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", d)
    key_date = m.group(1) + m.group(2) + m.group(3) if m else "00000000"
    has_rev = 1 if volume_row.get("rev_tag") else 0
    return (key_date, has_rev, volume_row.get("scanned_at") or 0)


def group_entry_hits(entry_rows):
    """搜索命中的条目按图号归组。

    entry_rows 按相关度降序传入：分组保持首次出现顺序（相关度高的在前），
    组内各版本按所在册的新旧排序。
    """
    groups = {}
    for r in entry_rows:
        no = normalize_no(r["drawing_no"])
        groups.setdefault(no, []).append(r)
    out = [{"drawing_no": no, "versions": sorted(rows, key=volume_sort_key, reverse=True)}
           for no, rows in groups.items()]
    return out
