"""离屏回归：文字修改/添加文字 → 选中字符设置格式（字符级混排）。

新交互（v2.6.8 前瞻）：
- 「修改文字」就地编辑框改为富文本，行内按原 PDF span 预填保留混排；
- 框内拖动选中部分字符 → 右键「格式设置」→ 粗体/斜体/颜色/字体/字号
  只作用于选中字符；
- 提交后若出现多种样式，对象带 runs（多段），保存烘焙逐段写回。

用例：
1) RichEditBox 多段载入/导出保真；选区局部改斜体+颜色后只影响该段。
2) 就地添加文字：输入混排内容 → 对象带 runs；烘焙后页面同段不同颜色/
   粗斜并存。
3) 修改原 PDF 行：Arial 行改为「普通+局部红色斜体」混排 → 对象带 runs
   （不走原行 embed 直写），烘焙后写回文字含 italic/红色 span。
4) 混排对象在 PageView 绘制不崩溃。
"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("APPDATA", os.path.abspath("_verify_appdata"))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtCore import QPointF
app = QApplication([])

import tempfile
import pymupdf
from rich_text import RichEditBox, merge_runs, single_run, runs_text
from document_view import DocumentView


def _mk_single_line_pdf(path):
    d = pymupdf.open()
    pg = d.new_page()
    pg.insert_text((60, 100), "Part A normal words", fontname="helv", fontsize=12)
    d.save(path)
    d.close()


def _span_flags(page):
    """收集页面全部文字 span 的 (text, font, flags, color)。"""
    out = []
    for b in page.get_text("dict").get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []) or []:
            for s in ln.get("spans", []) or []:
                out.append((s.get("text", ""), s.get("font", ""),
                            int(s.get("flags", 0)), int(s.get("color", 0))))
    return out


def _norm(s):
    return "".join(ch for ch in s if not ch.isspace())


# ================= 用例1：RichEditBox 行为 =================
edit = RichEditBox()
edit.set_scale(1.4)
edit.set_runs([
    {"text": "普通文字", "family": "Microsoft YaHei", "size": 12.0,
     "color": QColor(0, 0, 0), "bold": False, "italic": False},
    {"text": "强调内容", "family": "Microsoft YaHei", "size": 12.0,
     "color": QColor(200, 30, 30), "bold": True, "italic": True},
    {"text": " 结尾", "family": "SimSun", "size": 14.0,
     "color": QColor(0, 0, 0), "bold": False, "italic": False},
])
out = edit.to_runs()
assert len(out) == 3, out
assert runs_text(out) == "普通文字强调内容 结尾"
# 选中「强调内容」把斜体取消并改成蓝色 → 只影响这段
cur = edit.textCursor()
pos = edit.document().find("强调内容")
assert not pos.isNull(), "应能找到目标段"
cur.setPosition(pos.selectionStart())
cur.setPosition(pos.selectionEnd(), QTextCursor.MoveMode.KeepAnchor)
edit.setTextCursor(cur)
edit._apply_char(italic=False, color=QColor(0, 40, 200))
out2 = merge_runs(edit.to_runs())
mid = next(x for x in out2 if x["text"] == "强调内容")
assert mid["italic"] is False and mid["bold"] is True and \
    mid["color"].name() == "#0028c8", f"局部格式未生效: {mid}"
first = next(x for x in out2 if x["text"] == "普通文字")
assert first["italic"] is False and first["color"].name() == "#000000", \
    "未选中文字不应被改动"
print("CASE1_OK rich-edit-local-format")
edit.deleteLater()

# ================= 用例2：添加文字混排 → 对象 runs → 烘焙 =================
tmp = tempfile.mkdtemp(prefix="do_verify_rich_")
pdf_path = os.path.join(tmp, "src.pdf")
_mk_single_line_pdf(pdf_path)

view = DocumentView()
assert view.load(pdf_path)
pv = view.page_view
view.set_mode("text")
view._begin_inplace_text(0, QPointF(120, 240))
assert view._inplace_edit is not None
ie = view._inplace_edit
ie.set_scale(pv._zoom)
ie.set_runs([
    {"text": "红字", "family": "Microsoft YaHei", "size": 14.0,
     "color": QColor(200, 0, 0), "bold": False, "italic": False},
    {"text": "斜体字", "family": "Microsoft YaHei", "size": 14.0,
     "color": QColor(0, 0, 0), "bold": False, "italic": True},
])
view._commit_inplace_text(commit=True)
app.processEvents()
objs = [o for o in view.objects if o.get("kind") == "text"]
assert objs, "添加文字应生成文本对象"
obj = objs[-1]
assert obj.get("text") == "红字斜体字", obj.get("text")
assert obj.get("runs") and len(obj["runs"]) == 2, "混排输入对象应带 2 段 runs"
# 混排绘制不崩溃
pv.set_objects([o for o in view.objects if o["page"] == 0])
pv.update()
_pm = pv.grab()
assert not _pm.isNull(), "混排对象绘制结果不应为空"
view._bake_objects()
assert view.objects == [] or all(o.get("kind") != "text"
                                  for o in view.objects), "烘焙后文字对象应清空"
spans = _span_flags(view.doc[0])
print("case2 baked spans:", [(s[0], s[2], hex(s[3])) for s in spans])
joined = "".join(t for t, _f, _fl, _c in spans)
assert "红字斜体字" in _norm(joined), "烘焙后应存在混排文字"
# 中文斜体受 Story 内置字体限制不落 italic flags（无中文斜体字形变体），
# 拉丁斜体由用例3 验证；此处验证混排内容与颜色都已写回
assert any(_norm(t) == "红字" and ((_c >> 16) & 0xFF) > 120
           and ((_c >> 8) & 0xFF) < 90 and (_c & 0xFF) < 90
           for t, _f, _fl, _c in spans), "红色段颜色应写回"
assert any(_norm(t) == "斜体字" and (_c & 0xFF) < 40
           for t, _f, _fl, _c in spans), "普通段应为黑"
print("CASE2_OK add-text-mixed-runs-bake")

# ================= 用例3：修改原行 → 局部混排 =================
view2 = DocumentView()
assert view2.load(pdf_path)
pv2 = view2.page_view
view2.set_mode("replace_text")
ln = pv2._edit_line_hits(0)[0]
view2._on_text_line_clicked(0, ln)
app.processEvents()
assert view2._row_edit is not None
re = view2._row_edit
re.set_runs([
    {"text": "Part A ", "family": "Arial", "size": 12.0,
     "color": QColor(0, 0, 0), "bold": False, "italic": False},
    {"text": "special", "family": "Arial", "size": 12.0,
     "color": QColor(190, 10, 30), "bold": False, "italic": True},
])
view2._commit_row_edit(commit=True)
app.processEvents()
objs2 = [o for o in view2.objects if o.get("kind") == "text"]
assert objs2, "行编辑应生成对象"
o2 = objs2[-1]
assert o2.get("runs") and len(o2["runs"]) == 2, "局部混排行应带 runs"
assert not o2.get("embed"), "多段混排不应带单字体 embed"
view2._bake_objects()
spans2 = _span_flags(view2.doc[0])
print("case3 baked spans:", [(s[0], s[1], s[2], hex(s[3])) for s in spans2])
assert any("special" in t for t, *_ in spans2), "special 应写回"
assert any("special" in t and (f & 2) for t, _fn, f, _c in spans2), \
    "special 段应为斜体"
print("CASE3_OK edit-line-local-mixed-bake")

view.doc.close()
view2.doc.close()
print("VERIFY_RICH_FORMAT_OK")
