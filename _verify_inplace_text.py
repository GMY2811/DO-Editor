"""离屏回归：「文本」工具点击处就地输入（无弹窗操作条）。

验证：就地输入框出现且无 620 工具条 → 回车提交生成浮动文字对象并
保持 text 模式 → Esc 取消不产生对象 → 失焦提交 → 换工具自动提交 →
空文本不产生对象。
"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("APPDATA", os.path.abspath("_verify_appdata"))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF, QEvent, Qt
from PySide6.QtGui import QKeyEvent

app = QApplication([])
from document_view import DocumentView

view = DocumentView()
assert view.load("sample.pdf"), "load failed"
view.set_mode("text")
assert view._inplace_edit is None

# 1) 点击处应就地打开输入框，且不弹 620px 操作条
view._begin_inplace_text(0, QPointF(180, 260))
app.processEvents()
assert view._inplace_edit is not None, "text 工具应就地打开输入框"
assert view._inline_box is None, "不应再弹 620px 操作条"
edit = view._inplace_edit
assert edit.text() == "", "新输入框应预置空"

# 2) 输入后回车提交 → 生成浮动文字对象并保持在 text 模式
edit.setText("就地新增文字")
edit.returnPressed.emit()
app.processEvents()
assert view.objects and view.objects[-1]["kind"] == "text"
assert view.objects[-1]["text"] == "就地新增文字", "回车后应写入对象"
assert view.current_mode == "text", "添加后应保持在文本工具以便连续添加"
assert view._inplace_edit is None

# 3) 再次打开 → Esc 取消，不产生对象
n0 = len(view.objects)
view._begin_inplace_text(0, QPointF(220, 330))
app.processEvents()
assert view._inplace_edit is not None
view._inplace_edit.setText("不要这段")
ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
               Qt.KeyboardModifier.NoModifier)
view.eventFilter(view._inplace_edit, ev)
app.processEvents()
assert view._inplace_edit is None, "Esc 后输入框应关闭"
assert len(view.objects) == n0, "Esc 取消不应新增对象"

# 4) 输入后直接提交（模拟点击其它处失焦提交路径）
view._begin_inplace_text(0, QPointF(300, 390))
assert view._inplace_edit is not None
view._inplace_edit.setText("失焦提交")
view._commit_inplace_text(commit=True)
app.processEvents()
assert view.objects[-1]["text"] == "失焦提交"
assert view._inplace_edit is None

# 5) 输入中直接换工具 → 自动提交当前内容
view._begin_inplace_text(0, QPointF(150, 200))
assert view._inplace_edit is not None
view._inplace_edit.setText("换工具自动存")
view.set_mode("view")
app.processEvents()
assert view.objects[-1]["text"] == "换工具自动存"
assert view._inplace_edit is None
assert view.current_mode == "view"

# 6) 空白文本提交不产生对象
view.set_mode("text")
n0 = len(view.objects)
view._begin_inplace_text(0, QPointF(150, 240))
view._inplace_edit.setText("   ")
view._commit_inplace_text(commit=True)
assert len(view.objects) == n0, "空文本不应产生对象"

# 7) 格式还原：就地输入框应带与点击处一致的字号/颜色设置
view._begin_inplace_text(0, QPointF(180, 260))
assert view._inplace_edit is not None
meta = view._inplace_meta
assert meta is not None and meta["page"] == 0
assert meta["family"], "就地输入框应带字体族"
assert meta["size"] > 0, "就地输入框应带字号"
print("meta size/family:", meta["size"], meta["family"])
view._commit_inplace_text(commit=False)
assert view._inplace_edit is None
print("INPLACE_TEXT_OK")
