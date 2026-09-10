"""自定义菜单类：勾选状态绘制在菜单项右侧。

背景：QMenu 自带的 QMenu::indicator（左侧勾选区）与菜单项图标冲突——
带图标的可勾选菜单项上，左侧指示器无法正常显示（被图标挤占/覆盖）。
因此弃用左侧 indicator（QSS 中已移除相关规则），改在 paintEvent 里
把勾选标记统一画在条目右侧，与图标互不干扰。

用法：直接用 CheckMenu 替换 QMenu 即可（含菜单栏 addMenu 与右键菜单）。
"""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QMenu


class CheckMenu(QMenu):
    """勾选标记绘制在条目右侧的 QMenu。"""

    # 右侧对勾的几何参数（相对条目右边缘/垂直中心）
    _CHECK_MARGIN = 18   # 对勾中心距条目右边缘的横向距离
    _PEN_WIDTH = 2.4

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 主题自适应：按菜单底色亮度选勾选颜色；悬停高亮（蓝底）用白色。
        win = self.palette().color(self.palette().ColorRole.Window)
        accent = QColor("#64a8ff") if win.lightness() < 128 else QColor("#0071e3")
        white = QColor("#ffffff")
        pen = QPen(accent, self._PEN_WIDTH, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        for act in self.actions():
            if act.isSeparator():
                continue
            if not (act.isCheckable() and act.isChecked()):
                continue
            rect = self.actionGeometry(act)
            if rect.width() <= 0 or rect.height() <= 0:
                continue
            if act is self.activeAction():
                pen.setColor(white)
            else:
                pen.setColor(accent)
            painter.setPen(pen)
            cx = rect.right() - self._CHECK_MARGIN
            cy = rect.center().y()
            painter.drawPolyline([
                QPointF(cx - 4.2, cy + 0.4),
                QPointF(cx - 1.0, cy + 3.4),
                QPointF(cx + 5.2, cy - 3.6),
            ])
        painter.end()
