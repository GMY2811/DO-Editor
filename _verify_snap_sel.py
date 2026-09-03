"""回归: 选中加粗/斜体/彩色字符后, 右键「格式编辑…」快照正确反映真实样式。

历史 bug: 选区起点恰在新样式 fragment 边界时(选中字符=片段第一个字符),
QTextCursor.setPosition(anchor).charFormat() 退化为上一段样式, 对话框
B/I/颜色读成普通样式。

场景: "HELLO " 普通 + "WORLD" 红(#c81e1e)粗斜。
1) 选中 WORLD(边界起点 anchor=6) → 快照应为红粗斜
2) 选中 O(内部 anchor=7) → 应为红粗斜
3) 无选区光标在 fragment 边界 (pos=6, 后续输入语义=左段) → 普通样式
4) 整段红粗斜选中 → 快照红粗斜(新样式自身起点边界, 亦应正确)
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"D:\Project\2026-08-16-16-15-44\do-reader")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QTextCursor

app = QApplication([])
from rich_text import RichEditBox

RED = QColor(200, 30, 30)


def _box():
    b = RichEditBox()
    b.set_scale(1.0)
    b.set_runs([
        {"text": "HELLO ", "family": "Arial", "size": 12.0,
         "color": QColor(0, 0, 0), "bold": False, "italic": False},
        {"text": "WORLD", "family": "Arial", "size": 12.0,
         "color": RED, "bold": True, "italic": True},
    ])
    b.show()
    app.processEvents()
    return b


def _select(b, a, z):
    c = QTextCursor(b.document())
    c.setPosition(a)
    c.setPosition(z, QTextCursor.MoveMode.KeepAnchor)
    b.setTextCursor(c)
    app.processEvents()


def _snap_of(b):
    c = b.textCursor()
    had = bool(c.hasSelection() and c.selectedText())
    return b._format_selection_snapshot(
        c.selectionStart() if had else c.position(),
        c.selectionEnd() if had else c.position(),
        had)


def _check(label, snap, expect_bold, expect_italic, expect_color):
    ok = (snap["bold"] == expect_bold and snap["italic"] == expect_italic
          and snap["color"] == expect_color)
    print(f"  {label}: bold={snap['bold']} italic={snap['italic']} "
          f"color={snap['color'].name()} "
          f"family={snap['family']!r} => {'OK' if ok else 'FAIL'}")
    assert ok, f"{label} snapshot mismatch"


# 1) 选区起点=fragment 边界(历史 bug 场景)
b = _box()
_select(b, 6, 11)
_check("选区 WORLD(边界起点6)", _snap_of(b), True, True, RED)

# 2) 选区从 fragment 内部开始
b = _box()
_select(b, 7, 11)
_check("选区 ORLD(内部起点7)", _snap_of(b), True, True, RED)

# 3) 无选区、光标停边界: 后续输入沿用左段样式(输入语义不受影响)
b = _box()
c = QTextCursor(b.document())
c.setPosition(6)
b.setTextCursor(c)
app.processEvents()
s = _snap_of(b)
_check("无选区光标pos6(输入继承左段)", s, False, False, QColor(0, 0, 0))

# 4) 整行都是红粗斜: 起点0在自身片段边界(文档首)
b2 = RichEditBox()
b2.set_scale(1.0)
b2.set_runs([{"text": "全部红粗斜", "family": "Arial", "size": 12.0,
              "color": RED, "bold": True, "italic": True}])
b2.show()
app.processEvents()
_select(b2, 0, 5)
_check("整段红粗斜(起点0)", _snap_of(b2), True, True, RED)

print("SNAP_SELECTION_OK")
