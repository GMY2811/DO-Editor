"""DO阅读器 工具栏矢量图标（QPainter 绘制，无需图片资源）。"""
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QImage, QPainter, QPen, QColor, QIcon, QPixmap

_GRAY = QColor(90, 100, 115)
_LIGHT_GRAY = QColor(200, 206, 215)
_WHITE = QColor(255, 255, 255)
_CURRENT_COLOR = _GRAY


def _build(draw, s=24):
    color = _CURRENT_COLOR
    icon = QIcon()
    for c, state in ((color, QIcon.State.Off), (_WHITE, QIcon.State.On)):
        img = QImage(s * 2, s * 2, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(2, 2)
        p.setPen(QPen(c, 1.9, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        draw(p, s)
        p.end()
        icon.addPixmap(QPixmap.fromImage(img), QIcon.Mode.Normal, state)
        icon.addPixmap(QPixmap.fromImage(img), QIcon.Mode.Active, state)
    return icon


def _line(p, x1, y1, x2, y2):
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def icon_open():
    def d(p, s):
        _line(p, 3, 6, 3, 19)
        _line(p, 3, 19, 21, 19)
        _line(p, 3, 6, 9, 6)
        _line(p, 9, 6, 12, 9)
        _line(p, 12, 9, 21, 9)
        _line(p, 21, 9, 21, 19)
    return _build(d)


def icon_save():
    def d(p, s):
        p.drawRect(QRectF(5, 3, 14, 18))
        p.drawRect(QRectF(8, 3, 8, 4))
        p.drawRect(QRectF(8, 14, 8, 7))
    return _build(d)


def icon_prev():
    def d(p, s):
        p.drawPolyline([QPointF(14, 4), QPointF(8, 12), QPointF(14, 20)])
    return _build(d)


def icon_next():
    def d(p, s):
        p.drawPolyline([QPointF(10, 4), QPointF(16, 12), QPointF(10, 20)])
    return _build(d)


def _magnifier(d, s):
    p = None
    pass


def icon_zoom_in():
    def d(p, s):
        p.drawEllipse(QRectF(4, 4, 12, 12))
        _line(p, 14, 14, 20, 20)
        _line(p, 10, 7, 10, 13)
        _line(p, 7, 10, 13, 10)
    return _build(d)


def icon_zoom_out():
    def d(p, s):
        p.drawEllipse(QRectF(4, 4, 12, 12))
        _line(p, 14, 14, 20, 20)
        _line(p, 7, 10, 13, 10)
    return _build(d)


def icon_fit_width():
    def d(p, s):
        _line(p, 4, 12, 20, 12)
        _line(p, 4, 12, 8, 8)
        _line(p, 4, 12, 8, 16)
        _line(p, 20, 12, 16, 8)
        _line(p, 20, 12, 16, 16)
    return _build(d)


def icon_select():
    def d(p, s):
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline([QPointF(5, 4), QPointF(5, 16), QPointF(9, 13),
                        QPointF(11, 18), QPointF(13, 17), QPointF(11, 12),
                        QPointF(15, 12), QPointF(5, 4)])
    return _build(d)


def icon_highlight():
    def d(p, s):
        p.setBrush(QColor(253, 224, 71, 90))
        p.drawRect(QRectF(5, 7, 14, 8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(5, 7, 14, 8))
        _line(p, 19, 15, 21, 18)
    return _build(d)


def icon_underline():
    def d(p, s):
        p.drawPolyline([QPointF(6, 5), QPointF(6, 14), QPointF(12, 17),
                        QPointF(18, 14), QPointF(18, 5)])
        _line(p, 5, 20, 19, 20)
    return _build(d)


def icon_strikeout():
    def d(p, s):
        p.drawPolyline([QPointF(17, 5), QPointF(7, 5), QPointF(7, 9),
                        QPointF(15, 9), QPointF(15, 12), QPointF(7, 12),
                        QPointF(7, 16), QPointF(17, 16)])
        _line(p, 5, 10.5, 19, 10.5)
    return _build(d)


def icon_rect():
    def d(p, s):
        p.drawRect(QRectF(5, 6, 14, 12))
    return _build(d)


def icon_line():
    def d(p, s):
        _line(p, 5, 19, 19, 5)
        p.drawEllipse(QRectF(3.5, 17.5, 3, 3))
        p.drawEllipse(QRectF(17.5, 3.5, 3, 3))
    return _build(d)


def icon_ink():
    def d(p, s):
        p.drawPolyline([QPointF(5, 12), QPointF(9, 7), QPointF(13, 15),
                        QPointF(17, 8), QPointF(19, 12)])
    return _build(d)


def icon_note():
    def d(p, s):
        p.drawRect(QRectF(5, 4, 14, 16))
        _line(p, 14, 4, 14, 8)
        _line(p, 14, 8, 19, 8)
        _line(p, 8, 12, 16, 12)
        _line(p, 8, 15, 13, 15)
    return _build(d)


def icon_text():
    def d(p, s):
        _line(p, 12, 5, 12, 19)
        _line(p, 6, 5, 18, 5)
    return _build(d)


def icon_image():
    def d(p, s):
        p.drawRect(QRectF(4, 5, 16, 14))
        p.drawPolyline([QPointF(6, 16), QPointF(10, 11), QPointF(13, 14),
                        QPointF(17, 9)])
        p.drawEllipse(QRectF(16, 7, 2.4, 2.4))
    return _build(d)


def icon_sign():
    def d(p, s):
        p.drawPolyline([QPointF(4, 13), QPointF(9, 9), QPointF(13, 15),
                        QPointF(18, 6), QPointF(20, 8)])
        _line(p, 4, 19, 20, 19)
    return _build(d)


def icon_trash():
    def d(p, s):
        _line(p, 5, 7, 19, 7)
        _line(p, 8, 7, 9, 20)
        _line(p, 16, 7, 15, 20)
        _line(p, 9, 20, 15, 20)
        _line(p, 10, 4, 14, 4)
        _line(p, 10, 4, 8, 7)
        _line(p, 14, 4, 16, 7)
        _line(p, 11, 10, 11, 16)
        _line(p, 13, 10, 13, 16)
    return _build(d)


def icon_merge():
    def d(p, s):
        p.drawRect(QRectF(4, 4, 6, 8))
        p.drawRect(QRectF(4, 13, 6, 8))
        _line(p, 11, 8, 17, 12)
        _line(p, 11, 17, 17, 12)
        p.drawRect(QRectF(17, 8, 4, 8))
    return _build(d)


def icon_split():
    def d(p, s):
        p.drawRect(QRectF(17, 4, 4, 8))
        p.drawRect(QRectF(17, 13, 4, 8))
        _line(p, 12, 8, 5, 12)
        _line(p, 12, 17, 5, 12)
        p.drawRect(QRectF(4, 4, 6, 8))
    return _build(d)


def icon_search():
    def d(p, s):
        p.drawEllipse(QRectF(4, 4, 11, 11))
        _line(p, 13, 13, 20, 20)
    return _build(d)


def icon_print():
    def d(p, s):
        p.drawRect(QRectF(6, 7, 12, 10))
        _line(p, 9, 4, 15, 4)
        _line(p, 9, 4, 9, 7)
        _line(p, 15, 4, 15, 7)
        p.drawRect(QRectF(9, 14, 6, 4))
    return _build(d)


def icon_text_select():
    def d(p, s):
        _line(p, 7, 18, 12, 6)
        _line(p, 12, 6, 17, 18)
        _line(p, 9, 14, 15, 14)
    return _build(d)


def icon_library():
    def d(p, s):
        p.drawRect(QRectF(4, 5, 16, 14))
        p.drawRect(QRectF(7, 8, 4, 4))
        p.drawRect(QRectF(13, 8, 4, 4))
        p.drawRect(QRectF(7, 14, 4, 3))
        p.drawRect(QRectF(13, 14, 4, 3))
    return _build(d)


def icon_watermark():
    def d(p, s):
        _line(p, 5, 17, 14, 8)
        _line(p, 8, 19, 17, 10)
        _line(p, 11, 20, 19, 12)
    return _build(d)


def icon_edit():
    def d(p, s):
        _line(p, 6, 18, 16, 8)
        p.drawPolyline([QPointF(4, 20), QPointF(6, 18), QPointF(8, 20)])
        _line(p, 16, 8, 19, 5)
        _line(p, 14, 7, 18, 6)
    return _build(d)


def icon_sidebar():
    def d(p, s):
        p.drawRoundedRect(QRectF(3, 4, 18, 16), 2, 2)
        _line(p, 9, 4, 9, 20)
        _line(p, 5.5, 8, 7, 8)
        _line(p, 5.5, 11, 7, 11)
    return _build(d)


def icon_color():
    """调色板图标，用于编辑工具颜色选择。"""
    def d(p, s):
        p.drawEllipse(QRectF(3, 4, 18, 16))
        p.drawEllipse(QRectF(7, 7, 1.8, 1.8))
        p.drawEllipse(QRectF(11, 6, 1.8, 1.8))
        p.drawEllipse(QRectF(15, 8, 1.8, 1.8))
        p.drawEllipse(QRectF(8, 12, 1.8, 1.8))
        p.drawArc(QRectF(12, 12, 7, 6), 20 * 16, 190 * 16)
    return _build(d)


ICONS = {
    "open": icon_open,
    "save": icon_save,
    "prev": icon_prev,
    "next": icon_next,
    "zoom_in": icon_zoom_in,
    "zoom_out": icon_zoom_out,
    "fit_width": icon_fit_width,
    "sidebar": icon_sidebar,
    "select": icon_select,
    "highlight": icon_highlight,
    "underline": icon_underline,
    "strikeout": icon_strikeout,
    "rect": icon_rect,
    "line": icon_line,
    "ink": icon_ink,
    "text": icon_text,
    "text_select": icon_text_select,
    "edit": icon_edit,
    "library": icon_library,
    "watermark": icon_watermark,
    "image": icon_image,
    "sign": icon_sign,
    "trash": icon_trash,
    "merge": icon_merge,
    "split": icon_split,
    "search": icon_search,
    "print": icon_print,
    "color": icon_color,
}


def get(name, color=None):
    global _CURRENT_COLOR
    _CURRENT_COLOR = color if color is not None else _GRAY
    return ICONS[name]() if name in ICONS else QIcon()


def icon_color_for_dark(dark):
    """深色主题下用浅灰图标，浅色主题下用深灰图标。"""
    return _LIGHT_GRAY if dark else _GRAY
