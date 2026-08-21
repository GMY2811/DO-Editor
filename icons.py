"""DO阅读器 工具栏矢量图标（QPainter 绘制，无需图片资源）。"""
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (QImage, QPainter, QPen, QColor, QIcon, QPixmap,
                           QPainterPath)

_GRAY = QColor(90, 100, 115)
_LIGHT_GRAY = QColor(200, 206, 215)
_WHITE = QColor(255, 255, 255)
_CURRENT_COLOR = _GRAY
_CURRENT_WIDE = False

# 功能图标采用克制的分组强调色。浅色主题使用较深的颜色保证对比度，
# 深色主题使用更明亮的同色系；危险操作始终保留红色语义。
_ACCENT_LIGHT = {
    "open": "#2474d2", "save": "#2474d2", "fit_width": "#2474d2",
    "sidebar": "#526f91", "merge": "#6d55c7", "split": "#8057c8",
    "watermark": "#087d91", "text": "#2468c9", "edit": "#087ca5",
    "sign": "#7056c8", "library": "#7657bf", "text_select": "#3e63c7",
    "highlight": "#a86f08", "annotation": "#b46908", "underline": "#087f75",
    "strikeout": "#c34843", "rect": "#2870ae", "line": "#2870ae",
    "ink": "#6755b5", "color": "#d15d2f", "image": "#168068",
    "ocr": "#5368c9", "ocr_all": "#6757c8",
    "trash": "#cf4545", "select": "#3e63c7",
    "slideshow": "#0e8a5f",
}
_ACCENT_DARK = {
    "open": "#69adff", "save": "#69adff", "fit_width": "#69adff",
    "sidebar": "#a8c9ec", "merge": "#b6a0ff", "split": "#c09cff",
    "watermark": "#62d9ed", "text": "#72b3ff", "edit": "#67d7f4",
    "sign": "#c0a5ff", "library": "#c7a7ff", "text_select": "#91adff",
    "highlight": "#f2c45c", "annotation": "#ffc45c", "underline": "#5bd4c7",
    "strikeout": "#ff8178", "rect": "#77baff", "line": "#77baff",
    "ink": "#b7a4ff", "color": "#ff9a66", "image": "#62d5af",
    "ocr": "#9caeff", "ocr_all": "#b7a5ff",
    "trash": "#ff746f", "select": "#91adff",
    "slideshow": "#4ecf96",
}
_WIDE_ICONS = frozenset(_ACCENT_LIGHT)


def _build(draw, s=24):
    color = _CURRENT_COLOR
    width = 32 if _CURRENT_WIDE else s
    icon = QIcon()
    # 选中时保持原有功能色，避免彩色图标突然跳变为纯白。
    for c, state in ((color, QIcon.State.Off), (color, QIcon.State.On)):
        # 为每种显示缩放提供原生像素资源，并标记正确 DPR。此前只生成
        # 96x72 普通位图，Qt 会再缩小到 32x24，造成明显的二次插值模糊。
        for dpr in (1, 2, 3):
            img = QImage(width * dpr, s * dpr,
                         QImage.Format.Format_ARGB32)
            img.fill(Qt.GlobalColor.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.scale(dpr, dpr)
            p.setPen(QPen(c, 2.0, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            if _CURRENT_WIDE:
                # 无背景纯线图标略微横向舒展；控制变形幅度以保持边缘锐利。
                p.translate(width / 2, s / 2)
                p.scale(1.20, 1.0)
                p.translate(-s / 2, -s / 2)
            draw(p, s)
            p.end()
            pixmap = QPixmap.fromImage(img)
            pixmap.setDevicePixelRatio(dpr)
            icon.addPixmap(pixmap, QIcon.Mode.Normal, state)
            icon.addPixmap(pixmap, QIcon.Mode.Active, state)
    # 禁用状态：使用中灰色 + 半透明描边，强制所有图标在 disabled 时
    # 视觉一致地灰度化，避免彩色图标（尤其绿/青色调）看起来仍鲜艳。
    disabled_color = QColor(170, 176, 184, 210)
    for state in (QIcon.State.Off, QIcon.State.On):
        for dpr in (1, 2, 3):
            img = QImage(width * dpr, s * dpr,
                         QImage.Format.Format_ARGB32)
            img.fill(Qt.GlobalColor.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.scale(dpr, dpr)
            p.setPen(QPen(disabled_color, 2.0, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            if _CURRENT_WIDE:
                p.translate(width / 2, s / 2)
                p.scale(1.20, 1.0)
                p.translate(-s / 2, -s / 2)
            draw(p, s)
            p.end()
            pixmap = QPixmap.fromImage(img)
            pixmap.setDevicePixelRatio(dpr)
            icon.addPixmap(pixmap, QIcon.Mode.Disabled, state)
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


def icon_search_up():
    """搜索结果向上导航；与向下图标共用完全一致的几何尺寸。"""
    def d(p, s):
        pen = p.pen()
        pen.setWidthF(2.5)
        p.setPen(pen)
        p.drawPolyline([QPointF(4, 16), QPointF(12, 8), QPointF(20, 16)])
    return _build(d)


def icon_search_down():
    """搜索结果向下导航；与向上图标共用完全一致的几何尺寸。"""
    def d(p, s):
        pen = p.pen()
        pen.setWidthF(2.5)
        p.setPen(pen)
        p.drawPolyline([QPointF(4, 8), QPointF(12, 16), QPointF(20, 8)])
    return _build(d)


def icon_more_down():
    """带圆润转角的实心倒三角，用于工具栏溢出入口。"""
    def d(p, s):
        color = p.pen().color()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        path = QPainterPath(QPointF(7.0, 7.5))
        path.lineTo(17.0, 7.5)
        path.quadTo(18.8, 7.5, 17.7, 9.0)
        path.lineTo(13.3, 15.5)
        path.quadTo(12.0, 17.3, 10.7, 15.5)
        path.lineTo(6.3, 9.0)
        path.quadTo(5.2, 7.5, 7.0, 7.5)
        path.closeSubpath()
        p.drawPath(path)
    return _build(d)


def icon_close():
    """轻量关闭图标，用于标签页等紧凑控件。"""
    def d(p, s):
        # 保留适中安全边距，避免高 DPI 和主题切换后叉线贴边溢出。
        _line(p, 4.0, 4.0, 20.0, 20.0)
        _line(p, 20.0, 4.0, 4.0, 20.0)
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


def icon_ocr():
    """OCR 扫描框与文字标识，缩小后仍保持清晰。"""
    def d(p, s):
        _line(p, 4, 9, 4, 5)
        _line(p, 4, 5, 8, 5)
        _line(p, 16, 5, 20, 5)
        _line(p, 20, 5, 20, 9)
        _line(p, 4, 15, 4, 19)
        _line(p, 4, 19, 8, 19)
        _line(p, 16, 19, 20, 19)
        _line(p, 20, 19, 20, 15)
        _line(p, 8, 9, 16, 9)
        _line(p, 12, 9, 12, 16)
    return _build(d)


def icon_ocr_all():
    """叠放页面与扫描线，表示对全部页面执行 OCR。"""
    def d(p, s):
        # 后方页面只露出顶部与右侧，和单页扫描框形成明显区别。
        _line(p, 8, 3.5, 19, 3.5)
        _line(p, 19, 3.5, 19, 17)
        p.drawRect(QRectF(5, 6.5, 11, 14))
        _line(p, 7.5, 11, 13.5, 11)
        _line(p, 7.5, 14, 13.5, 14)
        _line(p, 7.5, 17, 11.5, 17)
    return _build(d)


def icon_annotation():
    """带折角的便笺图标。"""
    def d(p, s):
        p.drawRect(QRectF(5, 4, 14, 16))
        _line(p, 14, 4, 14, 9)
        _line(p, 14, 9, 19, 9)
        _line(p, 8, 12, 16, 12)
        _line(p, 8, 15, 14, 15)
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


def icon_slideshow():
    """幻灯片放映：播放三角 + 幕布底条。"""
    def d(p, s):
        p.drawPolygon([QPointF(7, 5), QPointF(18.5, 11.5),
                       QPointF(7, 18)])
        _line(p, 4.5, 20.5, 19.5, 20.5)
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
    "slideshow": icon_slideshow,
    "select": icon_select,
    "highlight": icon_highlight,
    "underline": icon_underline,
    "strikeout": icon_strikeout,
    "rect": icon_rect,
    "line": icon_line,
    "ink": icon_ink,
    "text": icon_text,
    "text_select": icon_text_select,
    "ocr": icon_ocr,
    "ocr_all": icon_ocr_all,
    "annotation": icon_annotation,
    "edit": icon_edit,
    "library": icon_library,
    "watermark": icon_watermark,
    "image": icon_image,
    "sign": icon_sign,
    "trash": icon_trash,
    "merge": icon_merge,
    "split": icon_split,
    "search": icon_search,
    "search_up": icon_search_up,
    "search_down": icon_search_down,
    "more_down": icon_more_down,
    "close": icon_close,
    "print": icon_print,
    "color": icon_color,
}


_ICON_CACHE = {}


def get(name, color=None):
    color_key = color if isinstance(color, str) else (
        color.name() if color is not None else None)
    key = (name, color_key)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    global _CURRENT_COLOR, _CURRENT_WIDE
    base = QColor(color if color is not None else _GRAY)
    # 传入的主题基色较亮表示当前为深色背景。
    dark_background = base.lightness() >= 145
    palette = _ACCENT_DARK if dark_background else _ACCENT_LIGHT
    _CURRENT_COLOR = QColor(palette.get(name, base.name()))
    _CURRENT_WIDE = name in _WIDE_ICONS
    icon = ICONS[name]() if name in ICONS else QIcon()
    # 相同 name+color 只生成一次，显著减少启动时重复绘制
    # （36 个图标 x 浅/深 2 色 = 上限 72 项）。
    _ICON_CACHE[key] = icon
    return icon


def icon_color_for_dark(dark):
    """深色主题下用浅灰图标，浅色主题下用深灰图标。"""
    return _LIGHT_GRAY if dark else _GRAY
