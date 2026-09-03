"""验证 FormatDialog 的 B/I 按钮不再被裁切。"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, r"D:\Project\2026-08-16-16-15-44\do-reader")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QFont, QFontMetrics

app = QApplication([])

# 用真实主题样式表覆盖默认，否则 padding 全局规则会污染 _verify 截图
import theme as _th
app.setStyleSheet(_th.LIGHT)
from rich_text import FormatDialog

# 让按钮在 offscreen 下也能渲染出可见字符（缺省 QPA 平台可能拿不到系统字体，
# 会画成方框；这里显式给字体族并把按钮字号稍大一些不影响真实渲染）。
app.setFont(QFont("Segoe UI", 10))

snap = {
    "family": "Arial",
    "size": 9.0,
    "color": QColor(0, 0, 0),
    "bold": True,
    "italic": True,
}
dlg = FormatDialog(snap)
dlg.show()
app.processEvents()


def _glyph_extent(btn):
    """返回 btn 字体下单个字符占的实际像素 (宽, 高)，以及 ascent/descent。

    用 sizeHint 验证按钮已经按 fixedSize 真正撑到 34px 高度。
    """
    f = btn.font()
    fm = QFontMetrics(f)
    return {
        "h_advance": fm.horizontalAdvance(btn.text()),
        "height": fm.height(),
        "ascent": fm.ascent(),
        "descent": fm.descent(),
    }


problems = []
for btn, want in [(dlg.bold_btn, "B"), (dlg.italic_btn, "I")]:
    sz = btn.size()
    text = btn.text()
    f: QFont = btn.font()
    ext = _glyph_extent(btn)
    if sz.height() != 34:
        problems.append(f"{text!r} height={sz.height()} (expected 34)")
    if sz.width() < 44:
        problems.append(f"{text!r} width={sz.width()} (expected >=44)")
    if text == "B" and not f.bold():
        problems.append("Bold button font is not bold")
    if text == "I" and not f.italic():
        problems.append("Italic button font is not italic")
    if abs(f.pointSize() - 13) > 0.5:
        problems.append(f"{text!r} font pt={f.pointSize()} (expected ~13)")
    # glyph 必须完整落在按钮内：水平 horizontalAdvance 远小于按钮宽，
    # 垂直 ascent+descent 远小于按钮高。
    if ext["h_advance"] >= sz.width() - 4:
        problems.append(
            f"{text!r} horizontal glyph {ext['h_advance']}px "
            f"too wide for {sz.width()}px button")
    if ext["height"] >= sz.height() - 4:
        problems.append(
            f"{text!r} vertical glyph {ext['height']}px "
            f"too tall for {sz.height()}px button")
    print(f"  {text!r}: btn={sz.width()}x{sz.height()}, pt={f.pointSize()}, "
          f"glyph={ext['h_advance']}x{ext['height']} "
          f"(asc {ext['ascent']}, desc {ext['descent']}), "
          f"bold={f.bold()}, italic={f.italic()}")

# 检查 checked 状态正常 toggle（确保 setFixedSize 后功能未坏）
assert dlg.bold_btn.isChecked()
dlg.bold_btn.click()
app.processEvents()
assert not dlg.bold_btn.isChecked(), "Bold toggle should still work"
dlg.bold_btn.click()
app.processEvents()
assert dlg.bold_btn.isChecked(), "Bold toggle should still work"

# 截屏便于目检（保存到项目根目录）
shot_path = r"D:\Project\2026-08-16-16-15-44\do-reader\_verify_formatdialog.png"
dlg.adjustSize()
dlg.resize(dlg.sizeHint())
dlg.grab().save(shot_path)

if problems:
    print("FAIL:")
    for p in problems:
        print("  -", p)
    sys.exit(1)
print("OK: B/I buttons render fully, height aligned with row, toggle still works")
