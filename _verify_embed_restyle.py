"""离屏回归：修改文字后「设置个性格式」保存应生效（斜体/粗细/换字体）。

链路：replace_text 就地编辑原 PDF 行 → 产生带 embed 的浮层文本对象
（embed 按原行样式生成，保存时 _bake_text_original_font 用 embed 字体
直写）。此前用户在格式条把斜体/粗细/字体改掉后，obj 样式字段已更新、
屏幕预览也是新样式，但 embed 仍指向旧样式字体 → 保存烘焙忽略新格式。

修复：_sync_embed_after_restyle 在样式变化时重建 embed（按新字族+粗斜
选系统变体字体文件）；系统无该族则移除 embed 转 htmlbox（粗斜同样生效）。

用例：
1) Arial 常规行就地编辑 → obj.embed 指向 arial.ttf（常规）。
2) 模拟格式条勾斜体 → embed 应重建指向 ariali.ttf；烘焙后页面文字
   以斜体变体呈现（span 带 italic 标识）。
3) 只改文字不改样式 → embed 保持不变（保留原行字体观感）。
"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("APPDATA", os.path.abspath("_verify_appdata"))

from PySide6.QtWidgets import QApplication
app = QApplication([])

import tempfile
import pymupdf
from document_view import DocumentView


def _mk_pdf(path):
    d = pymupdf.open()
    pg = d.new_page()
    # 单行 Arial 常规英文（就地编辑场景字体族可映射到系统全量字体）
    pg.insert_text((60, 100), "Hello inline world 123",
                   fontname="helv", fontsize=12)
    d.save(path)
    d.close()


def _spans(page):
    out = []
    for b in page.get_text("dict").get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []) or []:
            for s in ln.get("spans", []) or []:
                out.append(s)
    return out


tmp = tempfile.mkdtemp(prefix="do_verify_restyle_")
pdf_path = os.path.join(tmp, "src.pdf")
_mk_pdf(pdf_path)

view = DocumentView()
assert view.load(pdf_path), "load failed"
pv = view.page_view

# ---------- 就地编辑原行 → 产生 embed 对象 ----------
view.set_mode("replace_text")
lines = pv._edit_line_hits(0)
assert lines, "应检测到可编辑行"
ln = lines[0]
fmt = ln.get("fmt") or {}
assert fmt.get("bold") is False and fmt.get("italic") is False, \
    "样例行应为 Arial 常规样式"
view._on_text_line_clicked(0, ln)
app.processEvents()
assert view._row_edit is not None
view._row_edit.setText("Hello inline world 123 edited")
view._commit_row_edit(commit=True)
app.processEvents()

assert view.objects, "就地编辑后应有浮层文本对象"
obj = view.objects[0]
assert obj.get("kind") == "text" and obj.get("embed"), \
    "就地编辑对象应带 embed"
emb0 = obj["embed"]
print("after row-edit embed file:", (emb0 or {}).get("file"))
assert (emb0 or {}).get("file", "").lower().endswith("arial.ttf"), \
    "常规样式 embed 应指向 arial.ttf"

# ---------- 用例1：勾斜体 → embed 重建指向斜体文件 ----------
changed = view._sync_embed_after_restyle(
    obj, obj.get("fontfamily", "Arial"), obj.get("fontsize", 12.0),
    False, True)
assert changed, "斜体变化应触发 embed 重建"
emb1 = obj["embed"]
print("after set-italic embed file:", (emb1 or {}).get("file"))
assert (emb1 or {}).get("file", "").lower().endswith("ariali.ttf"), \
    f"勾斜体后 embed 应指向 ariali.ttf, got {emb1}"
# 同步 obj 上其它样式字段（UI on_ok 更新；脚本需手工置 italic）
obj["italic"] = True

# ---------- 烘焙保存 → 页面文字应为斜体 ----------
view._bake_objects()
pg = view.doc[0]
spans = _spans(pg)
print("baked spans:", [(s["text"][:18], s["font"], s.get("flags"))
                       for s in spans])
assert spans, "bake 后页面应有文字"
assert any(
    ("italic" in (s["font"] or "").lower() or "oblique" in
     (s["font"] or "").lower()) or (s.get("flags", 0) & 2)
    for s in spans), "烘焙后文字应以斜体变体呈现"
assert any("Hello inline world" in s["text"] for s in spans) or any(
    "".join(ch for ch in s["text"] if not ch.isspace())
    == "Helloinlineworld123edited" for s in spans), \
    "编辑后的文字应完整写回"
print("CASE1_OK embed-restyle-italic-effective-on-save")

# ---------- 用例2：只改文字不改样式 → embed 保留 ----------
view2 = DocumentView()
assert view2.load(pdf_path)
pv2 = view2.page_view
view2.set_mode("replace_text")
ln2 = pv2._edit_line_hits(0)[0]
view2._on_text_line_clicked(0, ln2)
app.processEvents()
view2._row_edit.setText("Hello inline world 123 edited2")
view2._commit_row_edit(commit=True)
app.processEvents()
obj2 = view2.objects[0]
emb2_before = dict(obj2["embed"])
touched = view2._sync_embed_after_restyle(
    obj2, obj2.get("fontfamily", "Arial"), obj2.get("fontsize", 12.0),
    False, False)
assert touched is False, "样式未变不应触碰 embed"
assert obj2["embed"] == emb2_before, "样式未变时 embed 应原样保留"
print("CASE2_OK embed-kept-when-style-unchanged")

view.doc.close()
view2.doc.close()
print("VERIFY_EMBED_RESTYLE_OK")
