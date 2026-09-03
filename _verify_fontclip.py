"""回归：1) 就地编辑保存后 span 字体保持原文；2) toolbar 不被视口裁切。"""
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("APPDATA", os.path.abspath("_verify_appdata"))
import pymupdf
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF
app = QApplication([])

F = r"C:/Windows/Fonts"
tmp = tempfile.gettempdir()

# 1) 字体保真：内嵌 SimSun/KaiTi 的 PDF → 就地编辑 → 保存后 span 字体 = 原字体
src = pymupdf.open()
pg = src.new_page(width=420, height=200)
pg.insert_text((50, 80), "楷体文字改", fontsize=12,
               fontfile=os.path.join(F, "simkai.ttf"), fontname="KaiTi")
doc_path = os.path.join(tmp, "_v_font.pdf")
src.save(doc_path); src.close()

from document_view import DocumentView
view = DocumentView(); view.resize(900, 700); view.show()
app.processEvents()
assert view.load(doc_path)
view.set_mode("replace_text"); app.processEvents()
ln = view.page_view._edit_line_hits(0)[0]
view._begin_row_edit(0, ln); app.processEvents()
view._row_edit.setText("楷体改后"); view._commit_row_edit(commit=True); app.processEvents()
out = os.path.join(tmp, "_v_font_out.pdf")
if os.path.exists(out): os.remove(out)
view._save_to(out)
re = pymupdf.open(out)
spans = [s for bl in re[0].get_text("dict").get("blocks", [])
         if bl.get("type") == 0 for ln in bl.get("lines", [])
         for s in ln.get("spans", []) if s.get("text")]
fonts = {s["font"] for s in spans if s["text"].strip()}
# 子集化后 span font 名可能带变体后缀（'KaiTi Regular'），按族名判定
assert any("KaiTi" in f for f in fonts), \
    f"KaiTi font lost in saved PDF: {fonts}"
print("FONT_FIDELITY_OK  saved_fonts=", fonts)
re.close()

# 2) 双击文字对象 → 就地编辑框在对象原位置且不超出页面（不再弹大编辑条）
view2 = DocumentView(); view2.resize(1000, 700); view2.show(); app.processEvents()
assert view2.load("sample.pdf"); app.processEvents()
view2.set_mode("text"); app.processEvents()
for tag, pt in [("tr", QPointF(450, 60)), ("br", QPointF(450, 720))]:
    view2._begin_inplace_text(0, pt); app.processEvents()
    view2._inplace_edit.setText(f"测试{tag}")
    view2._commit_inplace_text(commit=True); app.processEvents()
view2.set_mode("view"); app.processEvents()
content_w = view2.page_view.width()
for oid in [o["id"] for o in view2.objects[-2:]]:
    view2._on_object_double_clicked(oid); app.processEvents()
    edit = getattr(view2, "_obj_edit", None)
    assert edit is not None, "双击文字对象应进入就地编辑（编辑条已取消）"
    g = edit.geometry()
    assert g.width() > 10 and g.height() > 10, g
    assert g.x() >= 0 and g.right() <= content_w + 2, (
        f"oid={oid} box out of page: {g.x()},{g.y()} {g.width()}x{g.height()} "
        f"content_w={content_w}")
    view2._commit_object_edit(commit=True); app.processEvents()
print("EDIT_OBJECT_INLINE_OK")
print("FONT_CLIP_ALL_OK")
