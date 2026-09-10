"""CheckMenu 右侧勾选标记渲染验证。

背景：QMenu::indicator（左侧勾选区）与菜单项图标冲突，勾选标记不可见。
改为 check_menu.CheckMenu 在条目右侧自绘对勾。本测试离屏渲染一个
"可勾选 + 带图标" 的菜单项，验证：
1. 条目右侧区域出现主题蓝勾选像素；
2. 未勾选条目右侧无勾选像素；
3. 悬停(active)态勾选变白（蓝底可辨）。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMenu

from check_menu import CheckMenu

LIGHT_QSS = ("QMenu { background: #ffffff; border: 1px solid #d2d2d7; }"
             "QMenu::item { padding: 7px 30px 7px 12px; color: #2c2c2e; }"
             "QMenu::item:selected { background: #007aff; color: #ffffff; }")

_ACCENT = QColor("#0071e3")


def _has_accent(img, rect):
    """矩形区域内是否存在接近主题蓝的像素（容差收紧，避免误匹配
    图标深灰 #333333、文字 #2c2c2e、高亮蓝 #007aff 等相近色）。"""
    for x in range(max(0, rect.left()), min(img.width() - 1, rect.right()) + 1):
        for y in range(max(0, rect.top()), min(img.height() - 1, rect.bottom()) + 1):
            c = img.pixelColor(x, y)
            if (abs(c.red() - _ACCENT.red()) < 25 and
                    abs(c.green() - _ACCENT.green()) < 25 and
                    abs(c.blue() - _ACCENT.blue()) < 25):
                return True
    return False


def _grab(menu):
    menu.ensurePolished()
    menu.resize(menu.sizeHint())
    menu.show()
    QApplication.processEvents()
    img = menu.grab().toImage()
    menu.hide()
    return img


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(LIGHT_QSS)

    menu = CheckMenu()
    # 带图标的可勾选项——正是左侧 indicator 冲突的场景
    pm = QPixmap(16, 16)
    pm.fill(QColor("#333333"))
    act_on = menu.addAction("Sidebar")
    act_on.setCheckable(True)
    act_on.setChecked(True)
    act_on.setIcon(QIcon(pm))
    act_off = menu.addAction("Fullscreen")
    act_off.setCheckable(True)
    act_off.setChecked(False)
    act_off.setIcon(QIcon(pm))

    img = _grab(menu)
    rect_on = menu.actionGeometry(act_on)
    rect_off = menu.actionGeometry(act_off)
    img.save(os.path.join(os.path.dirname(__file__) or ".",
                          "_check_menu_render.png"))

    # 右侧 30px 内边距区应出现蓝色对勾（勾选项）
    right_zone = rect_on.adjusted(rect_on.width() - 30, 2, -2, -2)
    assert _has_accent(img, right_zone), "勾选项右侧未检测到勾选标记"

    # 图标区（左侧 30px）不应出现蓝色对勾（避免与图标冲突的老问题）
    # 注意 adjusted 的 dx2 为负才是收缩：右侧收缩到 left+31，只留左侧 30px。
    icon_zone = rect_on.adjusted(2, 2, -(rect_on.width() - 32), -2)
    assert not _has_accent(img, icon_zone), "左侧不应绘制勾选标记"

    # 未勾选项右侧不应有对勾
    right_off = rect_off.adjusted(rect_off.width() - 30, 2, -2, -2)
    assert not _has_accent(img, right_off), "未勾选项右侧不应有勾选标记"

    # 悬停态：勾选变白（蓝底 #007aff 上白/蓝色都可辨，仅验证不崩溃且仍绘制）
    menu.setActiveAction(act_on)
    img2 = _grab(menu)
    zone2 = rect_on.adjusted(rect_on.width() - 30, 2, -2, -2)
    white = QColor("#ffffff")
    hit = any(
        abs(img2.pixelColor(x, y).red() - white.red()) < 30 and
        abs(img2.pixelColor(x, y).green() - white.green()) < 30 and
        abs(img2.pixelColor(x, y).blue() - white.blue()) < 30
        for x in range(zone2.left(), zone2.right() + 1)
        for y in range(zone2.top(), zone2.bottom() + 1)
    )
    assert hit, "悬停高亮态右侧未检测到白色勾选标记"

    print("[OK] CheckMenu 右侧勾选标记渲染验证通过")


if __name__ == "__main__":
    main()
