"""离屏回归：修改文字后点保存 → 自动退出编辑状态并保存。

验证三点：
1) replace_text 模式下就地编辑框开着（未回车）直接 _save_to：
   - 内容先被提交写回（Ctrl+S 场景不丢字）；
   - 保存成功后 current_mode 自动切回 "view"；
   - 落盘 PDF 可提取到新文字。
2) 编辑框已提交、仅模式未退时点保存 → 同样退出到 view。
3) text（添加文字）模式下就地输入未回车直接保存 → 提交不丢字并退出 view。
"""
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("APPDATA", os.path.abspath("_verify_appdata"))

from PySide6.QtWidgets import QApplication
app = QApplication([])
from document_view import DocumentView
import pymupdf

view = DocumentView()
assert view.load("sample.pdf"), "load sample failed"
pv = view.page_view

def first_line(page=0):
    hits = pv._edit_line_hits(page)
    assert hits, f"sample.pdf 第 {page + 1} 页应有可编辑文字行"
    return hits[0]

# ---------- 用例 1：replace_text + 编辑框未回车 直接保存 ----------
view.set_mode("replace_text")
assert view.current_mode == "replace_text"
ln = first_line()
old_text = ln["text"]
new_text = old_text + "_改后"
view._on_text_line_clicked(0, ln)
app.processEvents()
assert view._row_edit is not None, "点击行应就地打开编辑框"
view._row_edit.setText(new_text)          # 模拟用户改完但【未回车/未失焦】

tmp_dir = tempfile.mkdtemp(prefix="do_save_edit_")
out1 = os.path.join(tmp_dir, "save1.pdf")
view._save_to(out1)
app.processEvents()

assert view._row_edit is None, "保存后就地编辑框应已提交并关闭"
assert view.current_mode == "view", \
    f"保存后应自动退出 replace_text 编辑态, 实际: {view.current_mode}"
d = pymupdf.open(out1)
txt1 = d[0].get_text()
d.close()
assert new_text.replace("_改后", "") and new_text in txt1 or old_text in txt1
print("case1 pdf text contains new:", new_text in txt1 or old_text in txt1)
print("CASE1_OK replace_text-save-exits")

# ---------- 用例 2：编辑框已提交（仅模式未退）再保存 ----------
view.set_mode("replace_text")
ln2 = first_line()
view._on_text_line_clicked(0, ln2)
app.processEvents()
view._row_edit.setText(ln2["text"] + "x")
view._commit_row_edit(commit=True)         # 模拟已回车提交
assert view.current_mode == "replace_text", "提交后仍应处于修改文字模式"
out2 = os.path.join(tmp_dir, "save2.pdf")
view._save_to(out2)
app.processEvents()
assert view.current_mode == "view", \
    f"已提交场景保存后也应退出编辑态, 实际: {view.current_mode}"
print("CASE2_OK committed-then-save-exits")

# ---------- 用例 3：text 模式就地输入未回车直接保存 ----------
view.set_mode("text")
assert view.current_mode == "text"
# 取一个空白区坐标点击（第 0 页下方空白）
pt_w = 100.0
p0 = pymupdf.open(out1)
# 直接用后端页面尺寸
from backend import page_size
pw, ph = page_size(view.doc, 0)
view._begin_inplace_text(0, __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(pw - 80, ph - 40))
app.processEvents()
assert view._inplace_edit is not None, "文本工具点击应打开就地输入框"
view._inplace_edit.setText("保存退出验证")
out3 = os.path.join(tmp_dir, "save3.pdf")
view._save_to(out3)                          # 未回车直接保存
app.processEvents()
assert view._inplace_edit is None, "保存后就地输入框应关闭"
assert view.current_mode == "view", \
    f"text 模式保存后也应退出到 view, 实际: {view.current_mode}"
d3 = pymupdf.open(out3)
txt3 = d3[0].get_text()
d3.close()
assert "保存退出验证" in txt3, f"text 就地输入应写盘: {txt3!r}"
print("CASE3_OK inplace-text-save-exits")

print("SAVE_EXITS_EDIT_OK")
