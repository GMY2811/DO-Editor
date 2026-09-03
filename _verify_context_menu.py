"""回归: 文字对象右键菜单去掉「编辑文字/更改颜色」, 批注仍保留「更改颜色」,
双击文字对象→就地编辑仍生效。"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"D:\Project\2026-08-16-16-15-44\do-reader")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, QPointF, QRectF
from PySide6.QtGui import QColor

app = QApplication([])

import theme as _th
app.setStyleSheet(_th.LIGHT)

import i18n
from document_view import DocumentView

SAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample.pdf")

view = DocumentView()
view.resize(900, 700)
view.show()
assert view.load(SAMPLE), "sample.pdf 加载失败"
app.processEvents()

# -- text 对象: 右键菜单不应有 编辑文字/更改颜色, 应保留 删除对象
view.set_mode("text")
view._add_text_object("右键测试", 0, QPointF(120, 120), keep_mode=True)
text_oid = view.objects[-1]["id"]
view.page_view.select(text_oid)
app.processEvents()
menu = view._build_context_menu(QPoint(0, 0))
texts = [a.text() for a in menu.actions() if a.text()]
print("text 右键菜单:", texts)
assert i18n.tr("edit_text") not in texts, \
    f"text 右键不应含「{i18n.tr('edit_text')}」: {texts}"
assert i18n.tr("change_color") not in texts, \
    f"text 右键不应含「{i18n.tr('change_color')}」: {texts}"
assert i18n.tr("delete_object") in texts, \
    f"text 右键应保留「{i18n.tr('delete_object')}」: {texts}"
menu.deleteLater()

# -- 双击 text 对象 → 就地编辑不受影响
view.set_mode("text")
view._on_object_double_clicked(text_oid)
app.processEvents()
assert getattr(view, "_obj_edit", None) is not None, \
    "双击文字对象仍应进入就地编辑"
assert view._obj_edit.text() == "右键测试"
view._commit_object_edit(commit=True)
app.processEvents()

# -- rect 批注对象: 右键「更改颜色」应保留
view.set_mode("rect")
view._on_rect(0, QRectF(70, 200, 150, 60))
rect_oid = view.objects[-1]["id"]
view.page_view.select(rect_oid)
app.processEvents()
menu2 = view._build_context_menu(QPoint(0, 0))
texts2 = [a.text() for a in menu2.actions() if a.text()]
print("rect 右键菜单:", texts2)
assert i18n.tr("change_color") in texts2, \
    f"rect 批注右键应保留「{i18n.tr('change_color')}」: {texts2}"
menu2.deleteLater()

view.close_doc()
print("CONTEXT_MENU_CLEAN_OK")
