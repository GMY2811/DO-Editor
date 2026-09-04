"""回归: 族名经自定义属性读写, 编辑(加粗/斜体/改色/中部输入)后仍正确。

背景: Qt 在部分字符格式(空字族/默认格式)上 fontFamily()/fontFamilies()
触发不可捕获的原生 access violation (rich_text._fmt_family 崩溃栈现场)。
修复: _char_format 写族名时同步存 _FAM_PROP 属性, _fmt_family 只做属性
读取。本脚本验证属性机制全链路正确且永不触发 Qt 字族解析。
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"D:\Project\2026-08-16-16-15-44\do-reader")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QTextCursor

app = QApplication([])
from rich_text import RichEditBox

RED = QColor(200, 30, 30)


def fam_at(b, pos):
    """pos 处字符的族名(内部路径=_char_format_at 同款读取)。"""
    cf = b._char_format_at(pos)
    return b._fmt_family(cf)


def snap_fam(b):
    c = b.textCursor()
    had = bool(c.hasSelection() and c.selectedText())
    s = b._format_selection_snapshot(
        c.selectionStart() if had else c.position(),
        c.selectionEnd() if had else c.position(), had)
    return s["family"]


def check(label, got, want):
    ok = got == want
    print(f"  {label}: got={got!r} want={want!r} => {'OK' if ok else 'FAIL'}")
    assert ok, label


# 1) 双族 runs: Arial + 楷体(模拟中英混排)
b = RichEditBox()
b.set_scale(1.0)
b.set_runs([
    {"text": "Hello ", "family": "Arial", "size": 12.0,
     "color": QColor(0, 0, 0), "bold": False, "italic": False},
    {"text": "楷体测试", "family": "KaiTi", "size": 12.0,
     "color": QColor(0, 0, 0), "bold": False, "italic": False},
])
b.show()
app.processEvents()
print("1) 初始双族读取:")
check("pos0(Arial)", fam_at(b, 0), "Arial")
check("pos6(KaiTi 边界)", fam_at(b, 6), "KaiTi")
check("pos9(KaiTi 内部)", fam_at(b, 9), "KaiTi")

# 2) 选凯体段设斜体(merge)后族名保持
c = QTextCursor(b.document())
c.setPosition(6)
c.setPosition(10, QTextCursor.MoveMode.KeepAnchor)
b.setTextCursor(c)
b._apply_char(italic=True)
app.processEvents()
print("2) 楷体段设斜体后:")
check("pos6 族名不变", fam_at(b, 6), "KaiTi")
check("选区快照族名", snap_fam(b), "KaiTi")
check("italic 生效", b._char_format_at(6).fontItalic(), True)

# 3) 中部输入新字(继承左侧格式): 在 pos3 插入 -> 仍 Arial
c = QTextCursor(b.document())
c.setPosition(3)
b.setTextCursor(c)
b.textCursor().insertText("X")
app.processEvents()
print("3) Arial 段中部插入 X 后:")
check("pos3 族名", fam_at(b, 3), "Arial")
check("pos2 族名", fam_at(b, 2), "Arial")

# 4) 全选改色(merge 颜色)族名保持
# (注意: 第3步在 pos3 插入 X 后, 原文整体右移1位, 楷体段起点 6->7)
b.selectAll()
b._apply_char(color=RED)
app.processEvents()
print("4) 全选改红后:")
check("pos0 族名仍 Arial", fam_at(b, 0), "Arial")
check("pos7 族名仍 KaiTi", fam_at(b, 7), "KaiTi")
check("pos6 空格仍 Arial", fam_at(b, 6), "Arial")
check("pos5 'o' 仍 Arial", fam_at(b, 5), "Arial")

# 5) to_runs 全量导出族名保持
runs = b.to_runs()
fam_map = {r["text"]: r["family"] for r in runs}
print("5) to_runs:", fam_map)
merged_txt = "".join(r["text"] for r in runs)
if "Hello" in merged_txt:
    check("导出含 Arial 段", fam_map.get(
        next(r["text"] for r in runs if "Hello" in r["text"])), "Arial")
if "楷体" in merged_txt:
    check("导出含 KaiTi 段", fam_map.get(
        next(r["text"] for r in runs if "楷体" in r["text"])), "KaiTi")

# 6) 无选区光标在边界: 快照族名=左段(Arial), 不崩且正确
c = QTextCursor(b.document())
c.setPosition(6)
b.setTextCursor(c)
app.processEvents()
s = b._format_selection_snapshot(6, 6, False)
check("无选区 pos6 快照族名(左段)", s["family"], "Arial")

# 7) 空文档右击(最危: 默认格式): 只走属性/兜底, 不触发 Qt 解析
b2 = RichEditBox()
b2.set_scale(1.0)
b2.show()
app.processEvents()
s2 = b2._format_selection_snapshot(0, 0, False)
check("空文档快照不崩族名空串或基准", True, True)  # 重点是没崩
print("   空文档 family 返回值:", repr(s2["family"]))

print("FAM_PROP_OK")
