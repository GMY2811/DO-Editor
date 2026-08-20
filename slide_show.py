"""全屏幻灯片演示：从当前页开始逐页放映 PDF，支持键盘/鼠标翻页。"""
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QKeyEvent
from PySide6.QtWidgets import QWidget

import backend
import i18n

_BG = QColor(22, 22, 24)


class SlideShowWindow(QWidget):
    """无边框全屏放映窗口。Esc 退出；→/空格/回车/下 下一页；
    ←/退格/上 上一页；Home/End 首末页；单击下一页、右键上一页、滚轮翻页。"""
    closed = Signal()

    def __init__(self, doc, start_page=0, parent=None):
        super().__init__(parent)
        self._doc = doc
        self._count = len(doc) if doc else 0
        self._page = max(0, min(start_page, self._count - 1))
        self._image = None
        self._zoom = 1.0
        self._dpr = 1.0
        self.setWindowTitle(i18n.tr("slideshow"))
        self.setWindowFlags(Qt.WindowType.Window
                            | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    def showEvent(self, event):
        super().showEvent(event)
        self._dpr = self.devicePixelRatioF()
        self._render_current()
        self.setCursor(Qt.CursorShape.BlankCursor)

    def _render_current(self):
        if self._doc is None or self._count <= 0:
            return
        w, h = backend.page_size(self._doc, self._page)
        if w <= 0 or h <= 0:
            return
        vw = max(100, self.width())
        vh = max(100, self.height())
        # 整页适配屏幕，四周留 2% 边距。
        self._zoom = min(vw / w, vh / h) * 0.96
        pix = backend.page_pixmap(self._doc, self._page, self._zoom, self._dpr)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format.Format_RGB888).copy()
        img.setDevicePixelRatio(self._dpr)
        self._image = img

    def _goto(self, page):
        page = max(0, min(self._count - 1, page))
        if page == self._page:
            return
        self._page = page
        self._render_current()
        self.update()

    def _next(self):
        self._goto(self._page + 1)

    def _prev(self):
        self._goto(self._page - 1)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), _BG)
        if self._image is not None:
            img = self._image
            lw = img.width() / self._dpr
            lh = img.height() / self._dpr
            x = (self.width() - lw) / 2
            y = (self.height() - lh) / 2
            p.drawImage(QRectF(x, y, lw, lh), img)
        # 底部页码条
        if self._count > 0:
            text = i18n.tr("page_of").format(p=self._page + 1, t=self._count)
            p.setPen(QColor(216, 216, 220))
            font = QFont(self.font())
            font.setPointSizeF(max(11.0, font.pointSizeF() * 0.95))
            p.setFont(font)
            p.drawText(self.rect().adjusted(0, -28, 0, -10),
                       Qt.AlignmentFlag.AlignHCenter, text)
        p.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isVisible():
            self._dpr = self.devicePixelRatioF()
            self._render_current()
            self.update()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_Q):
            self.close()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Space, Qt.Key.Key_Down,
                     Qt.Key.Key_Enter, Qt.Key.Key_Return,
                     Qt.Key.Key_PageDown):
            self._next()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_Backspace,
                     Qt.Key.Key_PageUp):
            self._prev()
        elif key == Qt.Key.Key_Home:
            self._goto(0)
        elif key == Qt.Key.Key_End:
            self._goto(self._count - 1)
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._next()
        elif event.button() == Qt.MouseButton.RightButton:
            self._prev()
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.close()
        else:
            super().mousePressEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta < 0:
            self._next()
        elif delta > 0:
            self._prev()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.close()

    def closeEvent(self, event):
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.closed.emit()
        super().closeEvent(event)
