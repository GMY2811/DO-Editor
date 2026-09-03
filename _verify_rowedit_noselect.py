"""离屏回归：修改文字点击行进入编辑时不再默认全选。

验证：进入 replace_text 点击行 → 就地编辑框预填原文但无选中态，
光标在点击字符处/行尾；此时直接键入字符是插入而非覆盖整行；
Esc 取消不写回、不破坏 PDF。
"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("APPDATA", os.path.abspath("_verify_appdata"))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

app = QApplication([])
from document_view import DocumentView

view = DocumentView()
assert view.load("sample.pdf"), "load sample failed"
pv = view.page_view

# 1) 进入“修改文字”模式并取第一行
view.set_mode("replace_text")
lines0 = pv._edit_line_hits(0)
assert lines0, "sample.pdf 第 1 页应有可编辑文字行"
ln = lines0[0]
old_text = ln["text"]
assert len(old_text) >= 2, "需要至少 2 字符的行做插入验证"

# 2) 点击该行 → 就地编辑框出现，且【不再默认全选】
view._on_text_line_clicked(0, ln)
app.processEvents()          # 让 singleShot 光标定位执行完
assert view._row_edit is not None, "点击文字行应就地打开编辑框"
edit = view._row_edit
assert edit.text() == old_text, "编辑框应预填原行文字"
assert edit.hasSelectedText() is False, "点击进入不应默认全选文字"
assert edit.selectedText() == "", "不应存在任何选中区"
cp = edit.cursorPosition()
assert 0 <= cp <= len(old_text), f"光标位置越界: {cp}"
print("row text:", repr(old_text), "| cursor:", cp, "| selected:", repr(edit.selectedText()))

# 3) 直接键入一个字符 → 应是插入（原文保留），而非覆盖整行
ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_X,
               Qt.KeyboardModifier.NoModifier, "x")
QApplication.sendEvent(edit, ev)
after = edit.text()
print("after typing 'x':", repr(after))
assert old_text in after, "键入不应覆盖/删除原有文字"
assert len(after) == len(old_text) + 1, "键入一个字符应只插入一位"
assert not edit.hasSelectedText()

# 4) Esc 取消 → 编辑框关闭、不写回 PDF
view._commit_row_edit(commit=False)
assert view._row_edit is None, "Esc 取消后编辑框应关闭"
assert not view.objects, "取消不应产生文字对象/撤销记录"

print("ROWEDIT_NOSELECT_OK")
