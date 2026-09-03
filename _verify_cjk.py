"""回归:修改文字把西文改成中文时,保存烘焙自动回退中文字体,不出现方块。

场景1: 纯西文(Arial)英文行 → 改中文 → 保存后 span 使用回退 CJK 字体且字形覆盖
场景2: 中文(SimSun)行 → 改中文 → 仍走原字体(不误回退)
场景3: 同一页两处英文行都改中文 → 同名 CJK 字体重复注册不报错
"""
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("APPDATA", os.path.abspath("_verify_appdata"))
import pymupdf
from PySide6.QtWidgets import QApplication
app = QApplication([])

F = r"C:/Windows/Fonts"
tmp = tempfile.gettempdir()

# 保存后 span 报告的字体名(可能去掉注册前缀) → 本机对应文件
LABEL2FILE = {
    "MicrosoftYaHei": os.path.join(F, "msyh.ttc"),
    "SimSun": os.path.join(F, "simsun.ttc"),
    "SimHei": os.path.join(F, "simhei.ttf"),
    "KaiTi": os.path.join(F, "simkai.ttf"),
    "DengXian": os.path.join(F, "deng.ttf"),
    "FangSong": os.path.join(F, "simfang.ttf"),
    "ArialMT": os.path.join(F, "arial.ttf"),
}

def glyph_ok(label, text):
    """span 的字体名能否覆盖文本全部字形(能否正常显示、不出现方块)。

    保存子集化后 span font 名可能带变体后缀（如 'Microsoft YaHei
    Regular' / 'KaiTi Regular'），映射时先剥掉 Regular/Bold/Italic/
    Oblique 等尾缀再查表。
    """
    import re as _re
    cand = label
    if cand not in LABEL2FILE:
        cand = _re.sub(r"\s+(Regular|Bold|Italic|Oblique|Light|Medium)$",
                       "", cand or "").strip()
        cand = cand.replace("MT", "") if "Arial" in cand else cand
    p = LABEL2FILE.get(cand)
    if not p or not os.path.exists(p):
        # 映射不到系统文件时退回按族名模糊匹配（中文族名带空格等别名）
        low = (cand or label or "").lower()
        if "arial" in low:
            p = os.path.join(F, "arial.ttf")
        elif "times" in low or "roman" in low:
            p = os.path.join(F, "times.ttf")
        elif "yahei" in low or "雅黑" in low or "微软" in low:
            p = os.path.join(F, "msyh.ttc")
        elif "simsun" in low or "song" in low or "宋" in low:
            p = os.path.join(F, "simsun.ttc")
        elif "simhei" in low or "hei" in low or "黑" in low:
            p = os.path.join(F, "simhei.ttf")
        elif "kai" in low or "楷" in low:
            p = os.path.join(F, "simkai.ttf")
        elif "deng" in low or "等线" in low:
            p = os.path.join(F, "deng.ttf")
        elif "fang" in low or "仿宋" in low:
            p = os.path.join(F, "simfang.ttf")
        else:
            return False
    fo = pymupdf.Font(fontfile=p)
    return all(fo.has_glyph(ord(c)) for c in text if not c.isspace())

src = pymupdf.open()
pg = src.new_page(width=520, height=260)
pg.insert_text((50, 70), "Part NO 4NW071726CHI", fontsize=14,
               fontfile=os.path.join(F, "arial.ttf"), fontname="Arial")
pg.insert_text((50, 130), "中文原文行", fontsize=14,
               fontfile=os.path.join(F, "simsun.ttc"), fontname="SimSun")
pg.insert_text((50, 190), "Second English Line", fontsize=12,
               fontfile=os.path.join(F, "arial.ttf"), fontname="Arial")
doc_path = os.path.join(tmp, "_v_cjk.pdf")
src.save(doc_path); src.close()

from document_view import DocumentView

def new_view():
    v = DocumentView(); v.resize(900, 700); v.show()
    app.processEvents()
    assert v.load(doc_path)
    v.set_mode("replace_text"); app.processEvents()
    return v

def edit_line(v, page, want, new_text):
    for ln in v.page_view._edit_line_hits(page):
        txt = ln["text"].replace("\xa0", " ").strip()
        if want.split()[0] in txt and len(want.split()) <= len(txt.split()):
            v._begin_row_edit(page, ln); app.processEvents()
            v._row_edit.setText(new_text)
            v._commit_row_edit(commit=True); app.processEvents()
            return True
    return False

# 场景1: 英文行改中文 → 保存烘焙自动回退中文字体
view = new_view()
assert edit_line(view, 0, "Part NO", "中文货号 4NW071726CHI"), "scenario1 hit failed"
out = os.path.join(tmp, "_v_cjk_out.pdf")
if os.path.exists(out): os.remove(out)
view._save_to(out)

def collect(re_doc):
    rows = []
    for bl in re_doc[0].get_text("dict").get("blocks", []):
        if bl.get("type") != 0: continue
        for ln in bl.get("lines", []):
            for s in ln.get("spans", []):
                t = s.get("text", "")
                if t.strip():
                    rows.append((t, s["font"]))
    return rows

re_doc = pymupdf.open(out)
rows = collect(re_doc)
print("SAVED_SPANS=", rows)
hit = next(((t, fo) for t, fo in rows if "货号" in t), None)
assert hit, "saved text missing after edit"
t, fo = hit
assert glyph_ok(fo, t) and fo not in ("ArialMT",), \
    f"expected fallback CJK font covering glyphs, got {fo}"
print("SC1_CJK_FALLBACK_OK  saved_font=", fo)

# 场景2: 中文行改中文,仍走原字体 SimSun(不误回退)
view2 = new_view()
assert edit_line(view2, 0, "中文原文行", "中文改后行"), "scenario2 hit failed"
out2 = os.path.join(tmp, "_v_cjk_out2.pdf")
if os.path.exists(out2): os.remove(out2)
view2._save_to(out2)
re2 = pymupdf.open(out2)
hit2 = next(((t, fo) for t, fo in collect(re2) if "改后" in t), None)
assert hit2, "scenario2 saved text missing"
assert "SimSun" in hit2[1], f"scenario2 should keep SimSun, got {hit2[1]}"
print("SC2_ORIGINAL_FONT_KEPT  saved_font=", hit2[1])
re2.close()

# 场景3: 同一页两处英文行都改中文 → 保存不炸且都有字形
view3 = new_view()
assert edit_line(view3, 0, "Part NO", "第一处中文行"), "scenario3a hit failed"
assert edit_line(view3, 0, "Second English", "第二处中文行"), "scenario3b hit failed"
out3 = os.path.join(tmp, "_v_cjk_out3.pdf")
if os.path.exists(out3): os.remove(out3)
view3._save_to(out3)
re3 = pymupdf.open(out3)
rows3 = collect(re3)
want_texts = ["第一处中文行", "第二处中文行"]
got = {t: fo for t, fo in rows3 if any(w in t for w in want_texts)}
assert len(got) == 2, f"expected 2 edited CJK rows, got {got}"
for t, fo in got.items():
    assert glyph_ok(fo, t), f"row {t!r} not renderable: font {fo}"
print("SC3_DOUBLE_FALLBACK_OK  fonts=", sorted(set(got.values())))
re3.close()
print("CJK_FALLBACK_ALL_OK")
