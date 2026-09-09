"""连续滚动页面画布：多页垂直连续渲染 + 浮动对象 + 标注交互 + 右键菜单。"""
from html import escape
import math

from PySide6.QtCore import Qt, QRectF, QPointF, QPoint, Signal
from PySide6.QtGui import (QImage, QPainter, QPen, QColor, QBrush, QFont,
                           QFontMetrics, QPolygonF, QCursor, QPixmap,
                           QPainterPath)
from PySide6.QtWidgets import QWidget, QLabel, QToolTip, QGraphicsDropShadowEffect

import backend
from rich_text import merge_runs, runs_all_same_style, _qt_safe_family

_ACCENT = QColor(37, 99, 235)
_PLACEHOLDER = QColor(255, 0, 255)   # 文本定位框高对比色（洋红）
_GAP = 18   # 页间距（逻辑像素）
_ANNOTATION_KINDS = {"highlight", "underline", "strikeout", "rect", "line", "ink"}


class PageView(QWidget):
    rectSelected = Signal(int, QRectF)              # (页, PDF矩形)
    lineSelected = Signal(int, QPointF, QPointF)    # (页, 两点)
    inkSelected = Signal(int, object)               # (页, list[QPointF])
    pointClicked = Signal(int, QPointF)             # (页, 点)
    # 整页文字编辑：点击某个文字行（line 为 {"rect","text"}，空白处为 None）
    textLineClicked = Signal(int, object)           # (页, 行信息或 None)
    # 对象拖动/缩放完成后同时发送新旧矩形，让文档层能把整次鼠标操作
    # 合并成一个可撤销步骤。
    objectChanged = Signal(object, QRectF, QRectF)
    objectRotated = Signal(object, float, float)
    pdfImageChanged = Signal(int, QRectF, QRectF)
    pdfImageRotated = Signal(int, float)
    objectSelected = Signal(object)
    objectDoubleClicked = Signal(object)          # 双击对象（oid）
    contextMenuRequested = Signal(QPoint)
    panRequested = Signal(QPointF)                # 空白处拖动增量（画布坐标）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc = None
        self._zoom = 1.0
        self._dpr = 1.0
        self._offsets = []
        self._page_h = []
        self._images = {}
        self._total_w = 0
        self._total_h = 0
        self._viewport_y = 0
        self._viewport_h = 600

        self._mode = "view"
        self._drawing = False
        self._start = QPointF()
        self._cur = QPointF()
        self._ink = []
        self._start_page = 0

        self._objects = []
        self._selected = None
        self._drag = None
        self._pan_last = None
        self._hover_note_id = None

        self._note_preview = QLabel(self)
        self._note_preview.setObjectName("noteHoverPreview")
        self._note_preview.setTextFormat(Qt.TextFormat.RichText)
        self._note_preview.setWordWrap(True)
        self._note_preview.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._note_preview.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        preview_shadow = QGraphicsDropShadowEffect(self._note_preview)
        preview_shadow.setBlurRadius(18)
        preview_shadow.setOffset(0, 4)
        preview_shadow.setColor(QColor(0, 0, 0, 70))
        self._note_preview.setGraphicsEffect(preview_shadow)
        self._note_preview.hide()

        # 文本选择
        self._sel_page = None
        self._sel_start = None
        self._sel_cur = None
        self._sel_words = []
        self._selecting = False

        # 搜索高亮
        self._search_all = {}        # page -> [rects]
        self._search_current = None  # (page, rect) 当前定位

        # 整页文字框编辑（Acrobat 风格）：缓存的各行可编辑框
        self._edit_overlay = False
        self._edit_lines = {}        # page -> [{rect(QRectF), text}]
        self._edit_hover = None      # (page, idx) 当前悬停的文字行
        self._edit_excl = None       # (page, QRectF PDF坐标) 就地编辑行：不铺框/不高亮
        self._edit_selected = None   # (page, QRectF) 独立图片等页面对象选中框
        self._edit_drag = None       # (page, pressPos, originalRect)
        self._edit_rotation_preview = 0.0
        self._edit_preview_record = None
        self._edit_rotation_background = None
        self._edit_rotation_source = None
        self._edit_rotation_base_angle = 0.0
        self._edit_rotation_base_size = None
        self._rotation_cursor_cache = None

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_custom_context_menu)

    # ---------------- 文档 ----------------
    def set_document(self, doc, zoom, dpr=1.0):
        self._hide_note_tooltip()
        self._doc = doc
        self._zoom = max(0.05, zoom)
        self._dpr = max(1.0, dpr)
        self._images = {}
        self._text_words = {}
        self._edit_lines.clear()
        self._edit_hover = None
        self._edit_selected = None
        self._edit_drag = None
        self._edit_rotation_preview = 0.0
        self._edit_preview_record = None
        self._clear_edit_rotation_preview()
        self._objects = []
        self._selected = None
        self._drag = None
        self._pan_last = None
        self._compute_layout()

    def _doc_open(self):
        """self._doc 是否指向一个“可安全访问”的文档。

        仅判断 is not None 不够：document_view 在保存流程中会 close 旧
        Document 再重开，若失败窗口内 PageView 持有了已 close 的对象，
        任何 len(self._doc)/backend.page_size 都会抛 ValueError
        (document closed)，在 paintEvent/mouseMoveEvent 等 Qt 回调里
        反复抛异常会导致界面崩溃。这里统一加一道 is_closed 防线，
        一旦文档已关闭就当“没有文档”处理。
        """
        return (self._doc is not None
                and not getattr(self._doc, "is_closed", False))

    def set_zoom(self, zoom):
        self._zoom = max(0.05, zoom)
        self._images = {}
        self._compute_layout()

    def _compute_layout(self):
        self._offsets = []
        self._page_h = []
        if not self._doc_open():
            self._total_w = 0
            self._total_h = 0
            self.setFixedSize(0, 0)
            return
        y = 0
        max_w = 0
        for i in range(len(self._doc)):
            pw, ph = backend.page_size(self._doc, i)
            w = pw * self._zoom
            h = ph * self._zoom
            self._offsets.append(y)
            self._page_h.append(h)
            max_w = max(max_w, w)
            y += h + _GAP
        self._total_w = int(max_w)
        self._total_h = int(max(0, y - _GAP))
        self.setFixedSize(self._total_w, self._total_h)
        self.set_viewport(self._viewport_y, self._viewport_h)

    def set_viewport(self, y, h):
        self._viewport_y = y
        self._viewport_h = max(1, h)
        self._update_visible()

    def _update_visible(self):
        if not self._doc_open():
            return
        buf = 400
        top = self._viewport_y - buf
        bottom = self._viewport_y + self._viewport_h + buf
        # offsets 单调递增：二分定位首个可能可见的页，避免超大 PDF
        # 每帧全量遍历所有页面（数千页时开销显著）。
        import bisect
        n = len(self._offsets)
        lo = bisect.bisect_right(self._offsets, top) - 1
        if lo < 0:
            lo = 0
        visible = set()
        for i in range(lo, n):
            o = self._offsets[i]
            if o > bottom:
                break
            ph = self._page_h[i]
            if o + ph >= top:
                visible.add(i)
                self._render_page(i)
        for i in list(self._images.keys()):
            if i not in visible:
                del self._images[i]

    def _render_page(self, i):
        if i in self._images:
            return
        pix = backend.page_pixmap(self._doc, i, self._zoom, self._dpr)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format.Format_RGB888).copy()
        img.setDevicePixelRatio(self._dpr)
        self._images[i] = img

    def page_count(self):
        return len(self._doc) if self._doc_open() else 0

    def current_page(self):
        if not self._offsets:
            return 0
        return self._page_at(self._viewport_y + 10)

    def scroll_to_page(self, pno):
        if not self._offsets:
            return 0
        pno = max(0, min(len(self._offsets) - 1, pno))
        return int(self._offsets[pno])

    def scroll_to_rect(self, pno, rect):
        """返回让指定 rect 显示在可视区中央的滚动值。"""
        if not self._offsets:
            return 0
        pno = max(0, min(len(self._offsets) - 1, pno))
        target_y = self._offsets[pno] + (rect.y0 + rect.y1) / 2 * self._zoom
        return int(target_y - self._viewport_h / 2)

    # ---------------- 坐标 ----------------
    def _page_at(self, y):
        for i in range(len(self._offsets) - 1, -1, -1):
            if y >= self._offsets[i]:
                return i
        return 0

    def _pdf_point(self, pos):
        i = self._page_at(pos.y())
        return i, QPointF(pos.x() / self._zoom,
                          (pos.y() - self._offsets[i]) / self._zoom)

    def pdf_point_at(self, pos):
        """将画布局部坐标转换为有效的页面/PDF 坐标并约束在页面内。"""
        if not self._doc_open() or not self._offsets:
            return None
        page, pt = self._pdf_point(QPointF(pos))
        pw, ph = backend.page_size(self._doc, page)
        return page, QPointF(
            max(0.0, min(float(pw), pt.x())),
            max(0.0, min(float(ph), pt.y())))

    def _point_hits_text(self, pos):
        """点击处是否有可选择文字；空白区域用于抓手拖动。"""
        if not self._doc_open() or not self._offsets:
            return False
        page, pt = self._pdf_point(QPointF(pos))
        pw, ph = backend.page_size(self._doc, page)
        if not (0 <= pt.x() <= pw and 0 <= pt.y() <= ph):
            return False
        if page not in self._text_words:
            self._text_words[page] = self._doc[page].get_text("words")
        tolerance = max(1.5, 3.0 / max(0.1, self._zoom))
        return any(
            (float(w[0]) - tolerance <= pt.x() <= float(w[2]) + tolerance and
             float(w[1]) - tolerance <= pt.y() <= float(w[3]) + tolerance)
            for w in self._text_words[page])

    def _widget_rect(self, page, r):
        return QRectF(r.x() * self._zoom,
                      self._offsets[page] + r.y() * self._zoom,
                      r.width() * self._zoom, r.height() * self._zoom)

    def _widget_to_pdf(self, page, wr):
        return QRectF(wr.x() / self._zoom,
                      (wr.y() - self._offsets[page]) / self._zoom,
                      wr.width() / self._zoom, wr.height() / self._zoom)

    # ---------------- 整页文字框编辑（Acrobat 风格） ----------------
    def set_edit_overlay(self, active):
        """开/关“编辑模式”的文字、图片和签名对象层。"""
        active = bool(active)
        if not active:
            self._selected = None
            self._drag = None
        if active == self._edit_overlay:
            self.update()
            return
        self._edit_overlay = active
        self._edit_hover = None
        self._edit_excl = None
        self._edit_selected = None
        self._edit_drag = None
        self._edit_rotation_preview = 0.0
        if not active:
            self._edit_lines.clear()
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.IBeamCursor)
        self.update()

    def set_inline_rect(self, page, rect, paper=None):
        """标记正在就地编辑的文字行区域（PDF 坐标），绘制时跳过该行的
        overlay 蓝框/hover 高亮（不给正在编辑的行铺框）。

        Acrobat 就地方案：编辑行的旧字形由文档层实时 redact 清除、新文字
        由同一 MuPDF 引擎 redact+insert 写回并重渲染位图——画布无需再以
        纸色覆盖层遮字（那只是旧 Qt 覆盖方案的遗留）。rect=None 时清除。
        paper 参数保留仅为兼容旧调用（忽略）。
        """
        if rect is None:
            if self._edit_excl is not None:
                self._edit_excl = None
                self._edit_hover = None
                self.update()
            return
        self._edit_excl = (int(page), QRectF(rect))
        self._edit_hover = None
        self.update()

    def set_edit_selection(self, page=-1, rect=None, record=None):
        """在编辑模式中标记一个可独立移动、缩放的页面对象。"""
        self._edit_selected = (int(page), QRectF(rect)) if rect is not None else None
        self._edit_preview_record = dict(record) if record is not None else None
        self._edit_drag = None
        self._edit_rotation_preview = 0.0
        self._clear_edit_rotation_preview()
        self.update()

    def _clear_edit_rotation_preview(self):
        self._edit_rotation_background = None
        self._edit_rotation_source = None
        self._edit_rotation_base_angle = 0.0
        self._edit_rotation_base_size = None

    def _prepare_edit_rotation_preview(self):
        """缓存已保存 PDF 图片的无残影拖动底图及独立前景图。"""
        if (not self._doc_open() or self._edit_preview_record is None or
                self._edit_selected is None):
            return False
        preview = backend.pdf_image_rotation_preview(
            self._doc, self._edit_preview_record, self._zoom, self._dpr)
        if not preview:
            return False
        background = QImage.fromData(preview[0])
        source = QImage.fromData(preview[1])
        if background.isNull() or source.isNull():
            return False
        background.setDevicePixelRatio(self._dpr)
        self._edit_rotation_background = background
        self._edit_rotation_source = source
        transform = list(self._edit_preview_record.get("transform") or [])
        if len(transform) == 6:
            a, b, c, d = (float(value) for value in transform[:4])
            width = math.hypot(a, b)
            height = math.hypot(c, d)
            if width > 1e-7 and height > 1e-7:
                self._edit_rotation_base_angle = math.degrees(math.atan2(b, a))
                self._edit_rotation_base_size = (width, height)
        return True

    def _rotation_cursor(self):
        """双向弯曲箭头旋转鼠标指针，深浅背景上均保持清晰。"""
        if self._rotation_cursor_cache is not None:
            return self._rotation_cursor_cache
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        upper = QPainterPath()
        upper.moveTo(5.5, 15.0)
        upper.cubicTo(6.5, 6.0, 21.0, 3.8, 26.0, 11.5)
        lower = QPainterPath()
        lower.moveTo(26.5, 17.0)
        lower.cubicTo(24.8, 26.0, 10.0, 28.0, 5.0, 20.5)
        # 白色外描边让指针在深色图片上不被吞没。
        painter.setPen(QPen(QColor(255, 255, 255, 235), 4.8,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(upper)
        painter.drawPath(lower)
        painter.setPen(QPen(QColor(24, 73, 145), 2.4,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(upper)
        painter.drawPath(lower)
        painter.setPen(Qt.PenStyle.NoPen)
        # 两端箭头方向相反：上方顺时针，下方逆时针。
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawPolygon(QPolygonF([
            QPointF(19.0, 8.0), QPointF(28.8, 12.2), QPointF(24.2, 2.7)]))
        painter.drawPolygon(QPolygonF([
            QPointF(13.0, 23.0), QPointF(3.0, 19.5), QPointF(8.2, 28.7)]))
        painter.setBrush(QColor(24, 73, 145))
        painter.drawPolygon(QPolygonF([
            QPointF(20.5, 8.5), QPointF(27.2, 11.6), QPointF(24.0, 5.1)]))
        painter.drawPolygon(QPolygonF([
            QPointF(11.5, 22.5), QPointF(4.7, 20.0), QPointF(8.3, 26.3)]))
        painter.end()
        self._rotation_cursor_cache = QCursor(pixmap, 16, 16)
        return self._rotation_cursor_cache

    @staticmethod
    def _rotate_widget_point(point, center, degrees):
        angle = math.radians(float(degrees))
        cosine, sine = math.cos(angle), math.sin(angle)
        dx, dy = point.x() - center.x(), point.y() - center.y()
        return QPointF(center.x() + cosine * dx - sine * dy,
                       center.y() + sine * dx + cosine * dy)

    @classmethod
    def _rotated_rect_points(cls, rect, degrees=0.0):
        center = rect.center()
        return [cls._rotate_widget_point(point, center, degrees)
                for point in (rect.topLeft(), rect.topRight(),
                              rect.bottomRight(), rect.bottomLeft())]

    @classmethod
    def _rotation_handle_point(cls, rect, degrees=0.0):
        point = QPointF(rect.center().x(), rect.top() - 24.0)
        return cls._rotate_widget_point(point, rect.center(), degrees)

    def _edit_rotation_handle_at(self, pos):
        if self._edit_selected is None:
            return False
        page, rect = self._edit_selected
        point = self._rotation_handle_point(self._widget_rect(page, rect))
        return self._dist(pos, point) <= 10.0

    def _edit_selection_handle_at(self, pos):
        if self._edit_selected is None:
            return None
        page, rect = self._edit_selected
        for index, point in enumerate(self._handles(self._widget_rect(page, rect))):
            delta = pos - point
            if abs(delta.x()) + abs(delta.y()) <= 10:
                return index
        return None

    def _resize_edit_selection(self, page, original, handle, pos):
        """按八个控制点自由调整 PDF 图片矩形，最小边长 6pt。"""
        px = float(pos.x() / self._zoom)
        py = float((pos.y() - self._offsets[page]) / self._zoom)
        left, top = float(original.left()), float(original.top())
        right, bottom = float(original.right()), float(original.bottom())
        minimum = 6.0
        if handle in (0, 3, 6):
            left = min(px, right - minimum)
        if handle in (1, 2, 7):
            right = max(px, left + minimum)
        if handle in (0, 1, 4):
            top = min(py, bottom - minimum)
        if handle in (2, 3, 5):
            bottom = max(py, top + minimum)
        return QRectF(left, top, right - left, bottom - top)

    def rerender_page_region(self, page, pdf_rect, pad=1.5):
        """就地编辑后按当前文档内容重新渲染页面上一个小区域（PDF 坐标）。

        编辑会话中每次 redact+insert 都会改变内存 PDF 文本层，本方法把该
        区域（按 zoom×dpr）重新 get_pixmap 并原位写回 _images 位图，实现
        「编辑行 = MuPDF 同引擎渲染」，与页面其它行视觉完全一致。区域外扩
        pad(pt) 以包含字形溢出；像素网格取整避免拼接缝隙。
        """
        if not self._doc_open() or page < 0 or page >= len(self._doc):
            return False
        img = self._images.get(page)
        if img is None:
            return False
        import math as _math
        import pymupdf
        try:
            dpr = img.devicePixelRatio() or 1.0
            kx = self._zoom * dpr
            pw, ph = backend.page_size(self._doc, page)
            x0 = _math.floor((max(0.0, float(pdf_rect.x()) - pad)) * kx) / kx
            y0 = _math.floor((max(0.0, float(pdf_rect.y()) - pad)) * kx) / kx
            x1 = _math.ceil((min(pw, float(pdf_rect.right()) + pad)) * kx) / kx
            y1 = _math.ceil((min(ph, float(pdf_rect.bottom()) + pad)) * kx) / kx
            if x1 - x0 < 0.1 or y1 - y0 < 0.1:
                return False
            clip = pymupdf.Rect(x0, y0, x1, y1)
            pix = self._doc[page].get_pixmap(
                matrix=pymupdf.Matrix(kx, kx), clip=clip, alpha=False)
            sub = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format.Format_RGB888).copy()
            # 逻辑像素目标 = 物理像素 / dpr（图像物理宽 = clip×kx）
            painter = QPainter(img)
            tx = (clip.x0 * self._zoom * dpr) / dpr
            ty = (clip.y0 * self._zoom * dpr) / dpr
            tw = sub.width() / dpr
            th = sub.height() / dpr
            painter.drawImage(
                QRectF(tx, ty, tw, th), sub,
                QRectF(0, 0, sub.width(), sub.height()))
            painter.end()
            self.update()
            self._rerender_err = None
            return True
        except Exception as exc:
            self._rerender_err = repr(exc)
            return False

    def _edit_line_hits(self, page):
        """返回一页的可编辑文字行列表（按 PDF 坐标，缓存）。

        每行除 rect/text 外附带 fmt（字体/字号/颜色/粗斜体，取该行
        中文字最长 span 的格式），供就地编辑时还原视觉外观。
        erase 为整行字符字形 bbox 的并集——PyMuPDF 的 line bbox 含
        字体上行/下行，行距紧凑时与相邻行 bbox 交叠，若直接用 line
        bbox 做擦除（redact）会连带吞掉相邻整行文字；字符级并集只
        覆盖真实字形区域，与相邻行不相交，擦除安全。
        """
        cached = self._edit_lines.get(page)
        if cached is not None:
            return cached
        out = []
        if self._doc_open() and 0 <= page < len(self._doc):
            try:
                data = self._doc[page].get_text("rawdict")
            except Exception:
                data = {}
            for block in data.get("blocks", []):
                if block.get("type") != 0:
                    continue    # 只框出文字块，忽略图片
                for line in block.get("lines", []) or []:
                    spans = line.get("spans", []) or []
                    if not spans:
                        continue
                    bb = line.get("bbox")
                    if not bb or len(bb) != 4:
                        continue
                    # rawdict 的 span 无 "text" 键，文本须由 chars 拼接；
                    # dict 结构则直接用 span["text"]。
                    def _span_text(s):
                        chs = s.get("chars") or []
                        if chs:
                            return "".join(ch.get("c", "") for ch in chs)
                        return s.get("text", "")
                    text = "".join(_span_text(s) for s in spans)
                    if not text.strip():
                        continue
                    x0, y0, x1, y1 = (float(bb[0]), float(bb[1]),
                                      float(bb[2]), float(bb[3]))
                    if x1 - x0 < 1.0 or y1 - y0 < 1.0:
                        continue
                    # 字符级并集：跳过空白字符（无字形），得出真实擦除区
                    erase = None
                    origin = None     # 行内首个字符的基线原点 (x, y)，live 写回起点
                    char_x = []       # 每字符 (x0, x1) 顺序表（含空格），供前缀保留
                    for s in spans:
                        for ch in s.get("chars", []) or []:
                            cb = ch.get("bbox")
                            if not cb or len(cb) != 4:
                                continue
                            char_x.append([float(cb[0]), float(cb[2])])
                            if origin is None and ch.get("origin"):
                                og = ch["origin"]
                                origin = [float(og[0]), float(og[1])]
                            if not ch.get("c") or ch["c"].isspace():
                                continue
                            if erase is None:
                                erase = [float(cb[0]), float(cb[1]),
                                         float(cb[2]), float(cb[3])]
                            else:
                                erase[0] = min(erase[0], float(cb[0]))
                                erase[1] = min(erase[1], float(cb[1]))
                                erase[2] = max(erase[2], float(cb[2]))
                                erase[3] = max(erase[3], float(cb[3]))
                    # 主 span = 该行中文字最长的一段，代表整行格式
                    main = max(spans, key=lambda s: len(s.get("text", "")))
                    col = int(main.get("color", 0)) & 0xFFFFFF
                    bold, italic = backend.font_style_flags(
                        main.get("font", ""), int(main.get("flags", 0)))
                    # 行内各 span 的样式明细：就地编辑以富文本预填时
                    # 保留行内原本的字符级格式差异（斜体词、变色字等），
                    # 用户不改就不会被整行统一样式抹平。
                    span_info = []
                    for s in spans:
                        st = _span_text(s)
                        if not st:
                            continue
                        sc = int(s.get("color", 0)) & 0xFFFFFF
                        sb, si = backend.font_style_flags(
                            s.get("font", ""), int(s.get("flags", 0)))
                        span_info.append({
                            "text": st,
                            "font": str(s.get("font", "") or ""),
                            "size": round(float(s.get("size", 10.0)), 2),
                            "color": ((sc >> 16) & 255,
                                      (sc >> 8) & 255, sc & 255),
                            "bold": sb,
                            "italic": si,
                        })
                    out.append({
                        "kind": "text",
                        "rect": QRectF(x0, y0, x1 - x0, y1 - y0),
                        "erase": erase,
                        "origin": origin,
                        "text": text,
                        "spans": span_info,
                        "char_x": (char_x if len(char_x) == len(text)
                                   else None),
                        "font": str(main.get("font", "") or ""),
                        "span_bbox": [float(v) for v in
                                      (main.get("bbox") or bb)],
                        "fmt": {
                            "font": str(main.get("font", "") or ""),
                            "size": round(float(main.get("size", 10.0)), 2),
                            "color": ((col >> 16) & 255,
                                      (col >> 8) & 255, col & 255),
                            "bold": bold,
                            "italic": italic,
                        },
                    })
            # Acrobat 的“编辑 PDF”会同时显示可独立操作的图片对象。这里只
            # 加入由单一内容流承载的图片，因此 Delete 的删除单位明确，
            # 不会误伤同一内容流中的正文或组合图形。
            try:
                for record in backend.isolated_image_objects(self._doc, page):
                    rb = record.get("rect")
                    if rb and len(rb) == 4:
                        out.append({
                            "kind": "image",
                            "rect": QRectF(float(rb[0]), float(rb[1]),
                                           float(rb[2]) - float(rb[0]),
                                           float(rb[3]) - float(rb[1])),
                            "text": "", "record": record,
                        })
            except Exception:
                pass
        self._edit_lines[page] = out
        return out

    def invalidate_text_cache(self, page=None):
        """就地编辑提交/取消后使文字缓存失效，下次按新文档内容重建。

        doc 文本已被 redact+insert 改写，缓存的该页可编辑行/words 与
        文档不一致；失效后再次进入编辑或文字选择会按新内容重新解析。
        """
        if page is None:
            self._edit_lines.clear()
            self._text_words.clear()
        else:
            self._edit_lines.pop(int(page), None)
            self._text_words.pop(int(page), None)

    def _edit_line_at(self, pos):
        """画布坐标 → 命中的文字行 (page, idx)，未命中返回 None。"""
        if not self._edit_overlay or not self._doc_open() or not self._offsets:
            return None
        page = self._page_at(pos.y())
        pt = self._pdf_point(pos)[1]
        hits = self._edit_line_hits(page)
        # 图片对象在列表尾部；图片仍按顶层优先选择。文字则按内容流的
        # 原始顺序选择，避免曾经编辑产生的后置覆盖文字挡住原字体对象，
        # 导致再次编辑时不断退化为 Helvetica / Arial。
        for idx in range(len(hits) - 1, -1, -1):
            ln = hits[idx]
            if ln.get("kind") == "image" and ln["rect"].contains(pt):
                return (page, idx)
        for idx, ln in enumerate(hits):
            if ln.get("kind") != "image" and ln["rect"].contains(pt):
                return (page, idx)
        return None

    # ---------------- 对象 ----------------
    def set_objects(self, objects):
        self._hide_note_tooltip()
        self._objects = objects or []
        self._selected = None
        self._drag = None
        self.update()

    def selected_id(self):
        return self._selected

    def select(self, oid):
        self._selected = oid
        self.update()

    def _find(self, oid):
        for o in self._objects:
            if o["id"] == oid:
                return o
        return None

    def _object_at(self, pos, allowed_kinds=None):
        for o in reversed(self._objects):
            kind = o.get("kind")
            if allowed_kinds is not None and kind not in allowed_kinds:
                continue
            hit_rect = self._widget_rect(o["page"], o["rect"])
            test_pos = QPointF(pos)
            if (kind in ("image", "signature") and
                    abs(float(o.get("rotation", 0.0))) > 1e-7):
                test_pos = self._rotate_widget_point(
                    test_pos, hit_rect.center(), -float(o.get("rotation", 0.0)))
            # 图标视觉尺寸缩小后仍保留舒适的鼠标命中范围。
            if kind == "note":
                hit_rect = hit_rect.adjusted(-5, -5, 5, 5)
            if kind in ("line", "ink"):
                points = self._annotation_widget_points(o, hit_rect)
                if any(self._distance_to_segment(test_pos, points[i], points[i + 1]) <= 6
                       for i in range(len(points) - 1)):
                    return o
            elif hit_rect.contains(test_pos):
                return o
        return None

    @staticmethod
    def _distance_to_segment(point, start, end):
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length2 = dx * dx + dy * dy
        if length2 <= 1e-9:
            return PageView._dist(point, start)
        t = ((point.x() - start.x()) * dx +
             (point.y() - start.y()) * dy) / length2
        t = max(0.0, min(1.0, t))
        nearest = QPointF(start.x() + t * dx, start.y() + t * dy)
        return PageView._dist(point, nearest)

    @staticmethod
    def _annotation_widget_points(obj, wr):
        return [QPointF(wr.x() + float(x) * wr.width(),
                        wr.y() + float(y) * wr.height())
                for x, y in obj.get("points", [])]

    @staticmethod
    def _handles(wr):
        """返回 8 个缩放手柄：0-3 四角（等比），4-5 上下边（垂直），6-7 左右边（水平）。"""
        tl = wr.topLeft(); tr = wr.topRight()
        br = wr.bottomRight(); bl = wr.bottomLeft()
        cx = wr.center().x(); cy = wr.center().y()
        return [tl, tr, br, bl,
                QPointF(cx, wr.top()), QPointF(cx, wr.bottom()),
                QPointF(wr.left(), cy), QPointF(wr.right(), cy)]

    def _handle_at(self, pos):
        if self._selected is None:
            return None
        obj = self._find(self._selected)
        if obj is None:
            return None
        # 便笺批注保持固定图标尺寸，只允许整体移动；在小图标周围绘制
        # 8 个缩放手柄会遮挡图形，也会让拖动命中变得困难。
        if obj.get("kind") == "note":
            return None
        rect = self._widget_rect(obj["page"], obj["rect"])
        points = self._handles(rect)
        if obj.get("kind") in ("image", "signature"):
            points = [self._rotate_widget_point(
                point, rect.center(), float(obj.get("rotation", 0.0)))
                      for point in points]
        for i, c in enumerate(points):
            d = pos - c
            if abs(d.x()) + abs(d.y()) <= 9:
                return i
        return None

    def _object_rotation_handle_at(self, pos):
        if self._selected is None:
            return False
        obj = self._find(self._selected)
        if obj is None or obj.get("kind") not in ("image", "signature"):
            return False
        rect = self._widget_rect(obj["page"], obj["rect"])
        point = self._rotation_handle_point(
            rect, float(obj.get("rotation", 0.0)))
        return self._dist(pos, point) <= 10.0

    # ---------------- 绘制 ----------------
    def paintEvent(self, event):
        p = QPainter(self)
        if self._doc_open():
            buf = 400
            top = self._viewport_y - buf
            bottom = self._viewport_y + self._viewport_h + buf
            for i in range(len(self._doc)):
                o = self._offsets[i]
                ph = self._page_h[i]
                if o + ph < top or o > bottom:
                    continue
                img = self._images.get(i)
                if img is not None:
                    dpr = img.devicePixelRatio() or 1.0
                    p.drawImage(QRectF(0, o, img.width() / dpr, img.height() / dpr), img)

            # 已保存的图片属于页面位图。旋转拖动时用“移除目标图片”的缓存
            # 页面覆盖当前页，再把目标图片作为独立前景实时旋转。
            if (self._edit_drag is not None and self._edit_drag[0] == "rotate" and
                    self._edit_rotation_background is not None and
                    self._edit_rotation_source is not None and
                    self._edit_selected is not None):
                sp, sr = self._edit_selected
                bg = self._edit_rotation_background
                bg_dpr = bg.devicePixelRatio() or 1.0
                p.drawImage(QRectF(0, self._offsets[sp],
                                   bg.width() / bg_dpr, bg.height() / bg_dpr), bg)
                wr = self._widget_rect(sp, sr)
                if self._edit_rotation_base_size is not None:
                    preview_width = self._edit_rotation_base_size[0] * self._zoom
                    preview_height = self._edit_rotation_base_size[1] * self._zoom
                    target = QRectF(wr.center().x() - preview_width / 2.0,
                                    wr.center().y() - preview_height / 2.0,
                                    preview_width, preview_height)
                else:
                    target = wr
                p.save()
                p.translate(wr.center())
                p.rotate(self._edit_rotation_base_angle +
                         self._edit_rotation_preview)
                p.translate(-wr.center())
                p.drawImage(target, self._edit_rotation_source)
                p.restore()

            # 文本选择高亮
            if self._sel_words and self._sel_page is not None:
                for w in self._sel_words:
                    x0, y0, x1, y1 = w[0], w[1], w[2], w[3]
                    wr = QRectF(x0 * self._zoom,
                                self._offsets[self._sel_page] + y0 * self._zoom,
                                (x1 - x0) * self._zoom, (y1 - y0) * self._zoom)
                    p.fillRect(wr, QColor(37, 99, 235, 90))

            # 搜索高亮：所有匹配黄色，当前定位深橙
            for pno, rects in self._search_all.items():
                for r in rects:
                    wr = QRectF(r.x0 * self._zoom,
                                self._offsets[pno] + r.y0 * self._zoom,
                                (r.x1 - r.x0) * self._zoom,
                                (r.y1 - r.y0) * self._zoom)
                    p.fillRect(wr, QColor(255, 200, 0, 110))
            if self._search_current is not None:
                pno, r = self._search_current
                wr = QRectF(r.x0 * self._zoom,
                            self._offsets[pno] + r.y0 * self._zoom,
                            (r.x1 - r.x0) * self._zoom,
                            (r.y1 - r.y0) * self._zoom)
                p.fillRect(wr, QColor(255, 140, 0, 210))

            # 整页文字编辑框：给可编辑文字行铺上轻量蓝框，悬停行加深
            if self._edit_overlay and self._mode == "point":
                hover = self._edit_hover
                excl = self._edit_excl
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                for pno in range(len(self._doc)):
                    o = self._offsets[pno]
                    ph = self._page_h[pno]
                    if o + ph < top or o > bottom:
                        continue
                    for idx, ln in enumerate(self._edit_line_hits(pno)):
                        # 正在就地编辑的行：其区域已由文档层 redact+insert
                        # 并重渲染（MuPDF 引擎），不铺框不高亮
                        if (excl is not None and excl[0] == pno
                                and ln["rect"].intersects(excl[1])):
                            continue
                        wr = self._widget_rect(pno, ln["rect"])
                        if (pno, idx) == hover:
                            p.fillRect(wr, QColor(37, 99, 235, 66))
                            p.setPen(QPen(QColor(37, 99, 235, 235), 1.5))
                        else:
                            p.fillRect(wr, QColor(37, 99, 235, 16))
                            p.setPen(QPen(QColor(37, 99, 235, 140), 1.0))
                        p.setBrush(Qt.BrushStyle.NoBrush)
                        p.drawRect(wr)

                # 独立页面对象（目前主要是图片）的 Acrobat 式选中框。
                if self._edit_selected is not None:
                    sp, sr = self._edit_selected
                    if 0 <= sp < len(self._doc):
                        wr = self._widget_rect(sp, sr)
                        p.setPen(QPen(_ACCENT, 2.0, Qt.PenStyle.SolidLine))
                        p.setBrush(Qt.BrushStyle.NoBrush)
                        points = self._rotated_rect_points(
                            wr, self._edit_rotation_preview)
                        p.drawPolygon(QPolygonF(points))
                        hs = 7.0
                        handles = self._handles(wr)
                        if abs(self._edit_rotation_preview) > 1e-7:
                            handles = [self._rotate_widget_point(
                                point, wr.center(), self._edit_rotation_preview)
                                       for point in handles]
                        for c in handles:
                            p.setPen(QPen(_ACCENT, 1.2))
                            p.setBrush(QBrush(QColor(255, 255, 255)))
                            p.drawRect(QRectF(c.x() - hs / 2, c.y() - hs / 2,
                                             hs, hs))
                        top_mid = QPointF((points[0].x() + points[1].x()) / 2,
                                          (points[0].y() + points[1].y()) / 2)
                        rotate_handle = self._rotation_handle_point(
                            wr, self._edit_rotation_preview)
                        p.setPen(QPen(_ACCENT, 1.4))
                        p.drawLine(top_mid, rotate_handle)
                        p.setBrush(QBrush(QColor(255, 255, 255)))
                        p.drawEllipse(rotate_handle, 5.0, 5.0)

            for obj in self._objects:
                wr = self._widget_rect(obj["page"], obj["rect"])
                kind = obj.get("kind")
                # 已存在于 PDF 中的原生批注由 MuPDF 页面位图绘制。这里的
                # 对象只是交互代理，再画一次会令高亮加深、线条变粗。
                if obj.get("native_proxy"):
                    continue
                if kind == "text":
                    p.setPen(QPen(_PLACEHOLDER, 1.6, Qt.PenStyle.DashLine))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(wr)
                    runs = obj.get("runs")
                    mixed = bool(runs) and not runs_all_same_style(runs)
                    if mixed:
                        self._paint_text_runs(p, wr, runs)
                    else:
                        family = _qt_safe_family(
                            obj.get("fontfamily") or "Microsoft YaHei UI")
                        f = QFont(family)
                        f.setPixelSize(max(10, int(obj.get("fontsize", 11) * self._zoom)))
                        f.setBold(bool(obj.get("bold", False)))
                        f.setItalic(bool(obj.get("italic", False)))
                        p.setFont(f)
                        p.setPen(obj.get("color") or QColor(0, 0, 0))
                        p.drawText(wr, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                                   obj.get("text", ""))
                elif kind == "note":
                    self._paint_note_marker(
                        p, wr, QColor(obj.get("color") or QColor("#ff9f0a")))
                elif kind in _ANNOTATION_KINDS:
                    color = QColor(obj.get("color") or QColor(200, 30, 30))
                    width = max(1.4, float(obj.get("width", 1.5)) * self._zoom)
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    if kind == "highlight":
                        fill = QColor(color)
                        fill.setAlpha(92)
                        p.fillRect(wr, fill)
                    elif kind == "underline":
                        p.setPen(QPen(color, width, Qt.PenStyle.SolidLine,
                                      Qt.PenCapStyle.RoundCap))
                        p.drawLine(wr.bottomLeft(), wr.bottomRight())
                    elif kind == "strikeout":
                        p.setPen(QPen(color, width, Qt.PenStyle.SolidLine,
                                      Qt.PenCapStyle.RoundCap))
                        p.drawLine(QPointF(wr.left(), wr.center().y()),
                                   QPointF(wr.right(), wr.center().y()))
                    elif kind == "rect":
                        p.setPen(QPen(color, width, Qt.PenStyle.SolidLine,
                                      Qt.PenCapStyle.RoundCap,
                                      Qt.PenJoinStyle.RoundJoin))
                        p.drawRect(wr)
                    else:
                        points = self._annotation_widget_points(obj, wr)
                        p.setPen(QPen(color, width, Qt.PenStyle.SolidLine,
                                      Qt.PenCapStyle.RoundCap,
                                      Qt.PenJoinStyle.RoundJoin))
                        for i in range(len(points) - 1):
                            p.drawLine(points[i], points[i + 1])
                else:
                    opacity = float(obj.get("opacity", 1.0))
                    angle = float(obj.get("rotation", 0.0))
                    if abs(angle) > 1e-7:
                        p.save()
                        p.translate(wr.center())
                        p.rotate(angle)
                        p.translate(-wr.center())
                    if opacity >= 1.0:
                        p.drawImage(wr, obj["img"])
                    else:
                        prev = p.opacity()
                        p.setOpacity(opacity)
                        p.drawImage(wr, obj["img"])
                        p.setOpacity(prev)
                    if abs(angle) > 1e-7:
                        p.restore()

            selected_obj = (self._find(self._selected)
                            if self._selected is not None else None)
            edit_selection = self._edit_overlay and self._mode == "point"
            annotation_selection = (
                self._mode == "view" and selected_obj is not None and
                selected_obj.get("kind") in ({"note"} | _ANNOTATION_KINDS))
            if ((edit_selection or annotation_selection) and
                    self._selected is not None):
                obj = self._find(self._selected)
                # 批注图标本身已经足够醒目，选中时不再额外绘制外框；
                # 选中状态仍保留，因此拖动、编辑和删除操作不受影响。
                if obj is not None and obj.get("kind") != "note":
                    wr = self._widget_rect(obj["page"], obj["rect"])
                    angle = (float(obj.get("rotation", 0.0))
                             if obj.get("kind") in ("image", "signature") else 0.0)
                    points = self._rotated_rect_points(wr, angle)
                    p.setPen(QPen(_ACCENT, 1.4, Qt.PenStyle.SolidLine))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawPolygon(QPolygonF(points))
                    hs = 7.0
                    handles = self._handles(wr)
                    if abs(angle) > 1e-7:
                        handles = [self._rotate_widget_point(
                            point, wr.center(), angle) for point in handles]
                    for c in handles:
                        p.setPen(QPen(_ACCENT, 1.2))
                        p.setBrush(QBrush(QColor(255, 255, 255)))
                        p.drawRect(QRectF(
                            c.x() - hs / 2, c.y() - hs / 2, hs, hs))
                    if obj.get("kind") in ("image", "signature"):
                        top_mid = QPointF((points[0].x() + points[1].x()) / 2,
                                          (points[0].y() + points[1].y()) / 2)
                        rotate_handle = self._rotation_handle_point(wr, angle)
                        p.setPen(QPen(_ACCENT, 1.4))
                        p.drawLine(top_mid, rotate_handle)
                        p.setBrush(QBrush(QColor(255, 255, 255)))
                        p.drawEllipse(rotate_handle, 5.0, 5.0)

            if self._drawing and self._mode != "view":
                p.setPen(QPen(QColor(200, 60, 60), 1.5, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                if self._mode == "rect":
                    r = QRectF(self._start, self._cur).normalized()
                    p.setBrush(QColor(255, 200, 0, 60))
                    p.drawRect(r)
                elif self._mode == "line":
                    p.drawLine(self._start, self._cur)
                elif self._mode == "ink":
                    pts = self._ink + [self._cur]
                    for i in range(len(pts) - 1):
                        p.drawLine(pts[i], pts[i + 1])
        p.end()

    def _paint_text_runs(self, painter, wr, runs):
        """按样式段逐段绘制混排文字（共用同一基线，观感贴近常规排版）。

        wr 为对象矩形按当前 zoom 放大后的画布矩形；每段字号换算为
        pt*zoom 的像素字号，与单样式文字路径一致。
        """
        runs = merge_runs(runs)
        if not runs:
            return
        infos = []
        for r in runs:
            f = QFont(_qt_safe_family(r.get("family") or "Microsoft YaHei UI"))
            f.setPixelSize(max(
                2, int(round(float(r.get("size") or 12.0) * self._zoom))))
            f.setBold(bool(r.get("bold")))
            f.setItalic(bool(r.get("italic")))
            infos.append((r, f, QFontMetrics(f)))
        max_h = max((fm.height() for _, _, fm in infos), default=12.0)
        max_asc = max((fm.ascent() for _, _, fm in infos),
                      default=max_h * 0.8)
        baseline = wr.top() + max(0.0, (wr.height() - max_h) / 2.0) + max_asc
        x = wr.left()
        for r, f, fm in infos:
            w = fm.horizontalAdvance(r.get("text", ""))
            painter.setFont(f)
            c = r.get("color")
            painter.setPen(c if isinstance(c, QColor) and c.isValid()
                           else QColor(0, 0, 0))
            top = baseline - fm.ascent()
            painter.drawText(
                QRectF(x, top, w, fm.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                r.get("text", ""))
            x += w

    @staticmethod
    def _paint_note_marker(painter, rect, color):
        """按屏幕实际尺寸绘制清晰的 Win10 风格扁平批注图标。"""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        size = min(rect.width(), rect.height())
        circle = QRectF(rect.center().x() - size / 2 + 1.0,
                        rect.center().y() - size / 2 + 1.0,
                        size - 2.0, size - 2.0)
        fill = QColor(color)
        if not fill.isValid():
            fill = QColor("#ff9f0a")
        fill.setAlpha(255)
        painter.setBrush(fill)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(circle)

        ink = QColor(255, 255, 255)
        cx = circle.center().x()
        top = circle.top()
        dot = max(1.6, size * 0.115)
        painter.setBrush(ink)
        painter.drawEllipse(QRectF(cx - dot / 2, top + size * 0.25,
                                   dot, dot))
        painter.setPen(QPen(ink, max(1.7, size * 0.105),
                            Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(cx, top + size * 0.51),
                         QPointF(cx, top + size * 0.76))
        painter.restore()

    # ---------------- 鼠标 ----------------
    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._hide_note_tooltip()
        pos = e.position()
        if (self._mode == "point" and self._edit_overlay and
                self._edit_selected is not None):
            page, rect = self._edit_selected
            if self._edit_rotation_handle_at(pos):
                center = self._widget_rect(page, rect).center()
                start_angle = math.degrees(math.atan2(
                    pos.y() - center.y(), pos.x() - center.x()))
                self._edit_drag = ("rotate", start_angle, page,
                                   QPointF(pos), QRectF(rect))
                self._edit_rotation_preview = 0.0
                self._prepare_edit_rotation_preview()
                self.setCursor(self._rotation_cursor())
                self.update()
                return
            handle = self._edit_selection_handle_at(pos)
            if handle is not None:
                self._edit_drag = ("resize", handle, page,
                                   QPointF(pos), QRectF(rect))
                self.update()
                return
            if self._widget_rect(page, rect).contains(pos):
                self._edit_drag = ("move", None, page,
                                   QPointF(pos), QRectF(rect))
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.update()
                return
        if self._mode == "view":
            # 阅读模式允许直接操作批注，但图片、签名和文字对象仍只在
            # “编辑模式”激活。优先检查已选批注的控制点，再检查批注本体。
            annotation_kinds = {"note"} | _ANNOTATION_KINDS
            selected_obj = self._find(self._selected)
            if (selected_obj is not None and
                    selected_obj.get("kind") in annotation_kinds):
                h = self._handle_at(pos)
                if h is not None:
                    self._drag = ("resize", h, pos,
                                  QRectF(selected_obj["rect"]),
                                  selected_obj["page"])
                    self.update()
                    return
            obj = self._object_at(pos, annotation_kinds)
            if obj is not None:
                self._selected = obj["id"]
                self.objectSelected.emit(obj["id"])
                self._drag = ("move", None, pos, QRectF(obj["rect"]), obj["page"])
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.update()
                return
            self._selected = None
            if self._point_hits_text(pos):
                self._selecting = True
                self._sel_start = pos
                self._sel_cur = pos
                self._sel_words = []
                self._sel_page = self._page_at(pos.y())
            else:
                self._pan_last = QPointF(e.globalPosition())
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.update()
        else:
            # 只有编辑覆盖层开启时，point 模式才允许操作页面对象。
            if self._mode == "point" and self._edit_overlay:
                if self._object_rotation_handle_at(pos):
                    obj = self._find(self._selected)
                    wr = self._widget_rect(obj["page"], obj["rect"])
                    start_angle = math.degrees(math.atan2(
                        pos.y() - wr.center().y(),
                        pos.x() - wr.center().x()))
                    self._drag = (
                        "rotate",
                        (start_angle, float(obj.get("rotation", 0.0))),
                        pos, QRectF(obj["rect"]), obj["page"])
                    self.update()
                    return
                h = self._handle_at(pos)
                if h is not None:
                    obj = self._find(self._selected)
                    if obj is not None:
                        self._drag = ("resize", h, pos, QRectF(obj["rect"]), obj["page"])
                        self.update()
                        return
                obj = self._object_at(pos)
                if obj is not None:
                    self._selected = obj["id"]
                    self.objectSelected.emit(obj["id"])
                    self._drag = ("move", None, pos, QRectF(obj["rect"]), obj["page"])
                    self.update()
                    return
            self._drawing = True
            self._start = pos
            self._cur = pos
            self._ink = [pos]
            self._start_page = self._page_at(pos.y())
            self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._edit_drag is not None:
            kind, handle, page, start, original = self._edit_drag
            if kind == "move":
                delta = pos - start
                changed = QRectF(original).translated(
                    delta.x() / self._zoom, delta.y() / self._zoom)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            elif kind == "resize":
                changed = self._resize_edit_selection(
                    page, original, handle, pos)
            else:
                center = self._widget_rect(page, original).center()
                angle = math.degrees(math.atan2(
                    pos.y() - center.y(), pos.x() - center.x()))
                self._edit_rotation_preview = angle - float(handle)
                changed = QRectF(original)
                self.setCursor(self._rotation_cursor())
            self._edit_selected = (page, changed)
            self.update()
        elif self._drag is not None:
            kind, h, start, orig, page = self._drag
            if kind == "move":
                delta = pos - start
                wr = QRectF(orig).translated(delta.x() / self._zoom,
                                             delta.y() / self._zoom)
                self._apply_rect(self._selected, wr)
            elif kind == "resize":
                off = self._offsets[page]
                obj = self._find(self._selected)
                if (obj is not None and obj.get("kind") in ("image", "signature")
                        and abs(float(obj.get("rotation", 0.0))) > 1e-7):
                    pos = self._rotate_widget_point(
                        pos, self._widget_rect(page, orig).center(),
                        -float(obj.get("rotation", 0.0)))
                if h <= 3:
                    # 四角：等比缩放
                    corners = self._handles(self._widget_rect(page, orig))
                    opp = corners[(h + 2) % 4]
                    o_corner = corners[h]
                    s = self._dist(pos, opp) / max(1e-6, self._dist(o_corner, opp))
                    s = max(0.05, min(50.0, s))
                    new_w = orig.width() * s
                    new_h = orig.height() * s
                    x = opp.x() / self._zoom - (new_w if h in (0, 3) else 0.0)
                    y = (opp.y() - off) / self._zoom - (new_h if h in (0, 1) else 0.0)
                    self._apply_rect(self._selected, QRectF(x, y, new_w, new_h))
                elif h in (4, 5):
                    # 上下边中点：垂直缩放（宽度不变）
                    py = (pos.y() - off) / self._zoom
                    if h == 4:  # 上边：底边固定
                        bottom = orig.y() + orig.height()
                        new_h = max(6.0, bottom - py)
                        self._apply_rect(self._selected,
                                         QRectF(orig.x(), py, orig.width(), new_h))
                    else:  # 下边：顶边固定
                        new_h = max(6.0, py - orig.y())
                        self._apply_rect(self._selected,
                                         QRectF(orig.x(), orig.y(), orig.width(), new_h))
                else:
                    # 左右边中点：水平缩放（高度不变）
                    px = pos.x() / self._zoom
                    if h == 6:  # 左边：右边固定
                        right = orig.x() + orig.width()
                        new_w = max(6.0, right - px)
                        self._apply_rect(self._selected,
                                         QRectF(px, orig.y(), new_w, orig.height()))
                    else:  # 右边：左边固定
                        new_w = max(6.0, px - orig.x())
                        self._apply_rect(self._selected,
                                         QRectF(orig.x(), orig.y(), new_w, orig.height()))
            elif kind == "rotate":
                obj = self._find(self._selected)
                if obj is not None:
                    start_angle, original_rotation = h
                    center = self._widget_rect(page, orig).center()
                    current_angle = math.degrees(math.atan2(
                        pos.y() - center.y(), pos.x() - center.x()))
                    obj["rotation"] = float(original_rotation) + (
                        current_angle - float(start_angle))
            self.update()
        elif self._pan_last is not None:
            global_pos = QPointF(e.globalPosition())
            delta = QPointF(global_pos - self._pan_last)
            self._pan_last = global_pos
            if not delta.isNull():
                self.panRequested.emit(delta)
        elif self._selecting:
            self._sel_cur = pos
            self._compute_selection()
            self.update()
        elif self._drawing:
            self._cur = pos
            if self._mode == "ink":
                self._ink.append(pos)
            self.update()
        else:
            prev_hover = self._edit_hover
            self._edit_hover = None
            if self._edit_overlay and self._mode == "point":
                hit = self._edit_line_at(pos)
                if hit is not None:
                    self._edit_hover = hit
            self._update_cursor(pos)
            if self._edit_hover != prev_hover:
                self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._edit_drag is not None:
            _kind, _handle, page, _start, original = self._edit_drag
            current = (QRectF(self._edit_selected[1])
                       if self._edit_selected is not None else QRectF(original))
            rotation = float(self._edit_rotation_preview)
            kind = self._edit_drag[0]
            self._edit_drag = None
            self._edit_rotation_preview = 0.0
            self._clear_edit_rotation_preview()
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            if kind == "rotate" and abs(rotation) > 1e-5:
                self.pdfImageRotated.emit(page, rotation)
            elif current != original:
                self.pdfImageChanged.emit(page, current, QRectF(original))
            self.update()
            return
        if self._drag is not None:
            oid = self._selected
            obj = self._find(oid)
            if obj is not None:
                if self._drag[0] == "rotate":
                    old_rotation = float(self._drag[1][1])
                    new_rotation = float(obj.get("rotation", 0.0))
                    if abs(new_rotation - old_rotation) > 1e-5:
                        self.objectRotated.emit(oid, new_rotation, old_rotation)
                else:
                    self.objectChanged.emit(
                        oid, QRectF(obj["rect"]), QRectF(self._drag[3]))
            self._drag = None
            self.update()
            return
        if self._pan_last is not None:
            self._pan_last = None
            self._update_cursor(e.position())
            self.update()
            return
        if self._selecting:
            self._selecting = False
            self._sel_cur = e.position()
            self._compute_selection()
            self.update()
            return
        if not self._drawing:
            return
        self._drawing = False
        page = self._start_page
        if self._mode == "rect":
            r = QRectF(self._start, self._cur).normalized()
            self.rectSelected.emit(page, self._widget_to_pdf(page, r))
        elif self._mode == "line":
            _, p1 = self._pdf_point(self._start)
            _, p2 = self._pdf_point(self._cur)
            self.lineSelected.emit(page, p1, p2)
        elif self._mode == "ink":
            pdf_pts = [self._pdf_point(x)[1] for x in self._ink]
            self._ink = []
            if len(pdf_pts) > 1:
                self.inkSelected.emit(page, pdf_pts)
        elif self._mode == "point":
            d = self._cur - self._start
            if abs(d.x()) + abs(d.y()) < 4:
                if self._edit_overlay:
                    # 整页文字编辑：把命中的行交给文档层就地编辑，
                    # 附带点击的 PDF 横坐标（用于定位光标）。
                    hit = self._edit_line_at(self._start)
                    if hit is not None:
                        line = dict(self._edit_line_hits(hit[0])[hit[1]])
                        line["cx"] = self._pdf_point(self._start)[1].x()
                        self.textLineClicked.emit(page, line)
                    else:
                        self.textLineClicked.emit(page, None)
                else:
                    self.pointClicked.emit(page, self._pdf_point(self._start)[1])
        self.update()

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._edit_overlay and self._mode == "point":
            hit = self._edit_line_at(e.position())
            if hit is not None:
                line = dict(self._edit_line_hits(hit[0])[hit[1]])
                if line.get("kind") == "image":
                    line["double_click"] = True
                    self._drawing = False
                    self._drag = None
                    self._edit_drag = None
                    self.textLineClicked.emit(hit[0], line)
                    self.update()
                    return
        if self._mode == "view":
            obj = self._object_at(e.position(), {"note"} | _ANNOTATION_KINDS)
            if obj is not None:
                self._selected = obj["id"]
                self._drag = None
                self._selecting = False
                self.update()
                self.objectDoubleClicked.emit(obj["id"])
                return
        # 新建文本确认后会继续停留在 point（文本）模式；此时双击已有
        # 文本也应进入编辑，而不是被模式判断直接忽略。
        if not (self._mode == "point" and self._edit_overlay):
            return
        obj = self._object_at(e.position())
        if obj is not None and obj.get("kind") in (
                {"text", "note", "image"} | _ANNOTATION_KINDS):
            self._selected = obj["id"]
            self._drag = None
            self._drawing = False
            self._selecting = False
            self._ink = []
            self.update()
            self.objectDoubleClicked.emit(obj["id"])
        else:
            super().mouseDoubleClickEvent(e)

    def _on_custom_context_menu(self, pos):
        obj = None
        if self._mode == "point" and self._edit_overlay:
            obj = self._object_at(QPointF(pos))
        elif self._mode == "view":
            obj = self._object_at(QPointF(pos), {"note"} | _ANNOTATION_KINDS)
        if obj is not None:
            self._selected = obj["id"]
            self.objectSelected.emit(obj["id"])
            self.update()
        elif self._edit_overlay and self._mode == "point":
            hit = self._edit_line_at(QPointF(pos))
            if hit is not None:
                line = dict(self._edit_line_hits(hit[0])[hit[1]])
                if line.get("kind") == "image":
                    self.textLineClicked.emit(hit[0], line)
        self.contextMenuRequested.emit(self.mapToGlobal(pos))

    # ---------------- 文本选择 ----------------
    def _compute_selection(self):
        if self._sel_start is None or self._sel_cur is None or not self._doc_open():
            self._sel_words = []
            return
        page = self._page_at(self._sel_start.y())
        r = self._widget_to_pdf(page, QRectF(self._sel_start, self._sel_cur).normalized())
        words = self._doc[page].get_text("words")
        sel = []
        for w in words:
            x0, y0, x1, y1 = w[0], w[1], w[2], w[3]
            if x1 >= r.x() and x0 <= r.right() and y1 >= r.y() and y0 <= r.bottom():
                sel.append(w)
        self._sel_words = sel
        self._sel_page = page

    def has_selection(self):
        return bool(self._sel_words)

    def selected_text(self):
        if not self._sel_words:
            return ""
        return " ".join(w[4] for w in self._sel_words)

    def clear_selection(self):
        self._sel_words = []
        self._sel_page = None
        self._sel_start = None
        self._sel_cur = None
        self._selecting = False
        self.update()

    def set_search_all(self, all_dict):
        """设置所有匹配 {page: [rects]}，全部黄色高亮。"""
        self._search_all = all_dict or {}
        self._search_current = None
        self.update()

    def set_search_current(self, page, rect):
        """设置当前定位的匹配（深橙色高亮）。"""
        self._search_current = (page, rect)
        self.update()

    def clear_search_highlights(self):
        self._search_all = {}
        self._search_current = None
        self.update()

    def _apply_rect(self, oid, rect):
        obj = self._find(oid)
        if obj is not None:
            obj["rect"] = rect

    def set_mode(self, mode):
        self._hide_note_tooltip()
        self._mode = mode
        self._drawing = False
        self._ink = []
        self._drag = None
        self._pan_last = None
        self._selecting = False
        self._sel_words = []
        self._edit_hover = None
        if mode != "point":
            # 行框编辑只在 point 类交互下有效，切走即整体隐藏
            self._edit_overlay = False
            self._edit_lines.clear()
        if mode == "view":
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)
        self.update()

    def mode(self):
        return self._mode

    def _update_cursor(self, pos):
        if self._mode not in ("view", "point"):
            self._hide_note_tooltip()
            return
        if (self._mode == "point" and self._edit_overlay and
                self._edit_selected is not None):
            page, rect = self._edit_selected
            if self._edit_rotation_handle_at(pos):
                self.setCursor(self._rotation_cursor())
                QToolTip.showText(self.mapToGlobal(pos.toPoint()), "拖动旋转", self)
                self._hide_note_tooltip()
                return
            handle = self._edit_selection_handle_at(pos)
            if handle is not None:
                if handle in (0, 2):
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                elif handle in (1, 3):
                    self.setCursor(Qt.CursorShape.SizeBDiagCursor)
                elif handle in (4, 5):
                    self.setCursor(Qt.CursorShape.SizeVerCursor)
                else:
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
                self._hide_note_tooltip()
                return
            if self._widget_rect(page, rect).contains(pos):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                self._hide_note_tooltip()
                return
        selected_obj = self._find(self._selected)
        reading_annotation = (
            self._mode == "view" and selected_obj is not None and
            selected_obj.get("kind") in ({"note"} | _ANNOTATION_KINDS))
        editing_objects = ((self._mode == "point" and self._edit_overlay) or
                           reading_annotation)
        # 阅读模式下批注无需先点击选中：鼠标直接悬停即可显示便笺内容，
        # 同时仍只把批注视为可交互对象，不激活图片、签名和编辑文字。
        hover_obj = self._object_at(
            pos, ({"note"} | _ANNOTATION_KINDS)
            if self._mode == "view" else None
        ) if (editing_objects or self._mode == "view") else None
        if editing_objects and self._object_rotation_handle_at(pos):
            self.setCursor(self._rotation_cursor())
            QToolTip.showText(self.mapToGlobal(pos.toPoint()), "拖动旋转", self)
            self._hide_note_tooltip()
            return
        h = self._handle_at(pos) if editing_objects else None
        if h is not None:
            tips = {0: "等比缩放", 1: "等比缩放", 2: "等比缩放", 3: "等比缩放",
                    4: "上下缩放", 5: "上下缩放", 6: "左右缩放", 7: "左右缩放"}
            if h in (0, 2):            # 左上↔右下角
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif h in (1, 3):          # 右上↔左下角
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif h in (4, 5):          # 上下边中点：垂直缩放
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            else:                      # 6, 7 左右边中点：水平缩放
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            self._hide_note_tooltip()
            QToolTip.showText(self.mapToGlobal(pos.toPoint()), tips[h], self)
        elif hover_obj is not None:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            if (hover_obj.get("kind") == "note" and
                    str(hover_obj.get("text", "")).strip()):
                self._show_note_tooltip(hover_obj, pos)
            else:
                self._hide_note_tooltip()
        else:
            if self._mode == "view":
                self.setCursor(Qt.CursorShape.IBeamCursor
                               if self._point_hits_text(pos)
                               else Qt.CursorShape.OpenHandCursor)
            elif self._edit_overlay:
                hit = self._edit_line_at(pos)
                self.setCursor(Qt.CursorShape.IBeamCursor
                               if hit is not None
                               else Qt.CursorShape.ArrowCursor)
            else:
                self.setCursor(Qt.CursorShape.CrossCursor)
            self._hide_note_tooltip()

    @staticmethod
    def _note_tooltip_html(text):
        """生成安全、保留换行并限制宽度的批注悬停预览。"""
        content = escape(str(text).strip()).replace("\n", "<br>")
        return ("<div style='max-width: 360px; white-space: normal;'>"
                f"{content}</div>")

    def _show_note_tooltip(self, obj, pos):
        oid = obj.get("id")
        if oid == self._hover_note_id:
            return
        self._hover_note_id = oid
        text = str(obj.get("text", "")).strip()
        self._note_preview.setText(self._note_tooltip_html(text))

        longest_line = max(text.splitlines() or [text], key=len, default="")
        natural_width = self._note_preview.fontMetrics().horizontalAdvance(
            longest_line) + 28
        self._note_preview.setFixedWidth(max(96, min(320, natural_width)))
        self._note_preview.adjustSize()

        icon_rect = self._widget_rect(obj["page"], obj["rect"]).toRect()
        bounds = self.visibleRegion().boundingRect()
        if bounds.isEmpty():
            bounds = self.rect()
        gap = 5
        x = icon_rect.right() + gap
        if x + self._note_preview.width() > bounds.right() - 4:
            x = icon_rect.left() - self._note_preview.width() - gap
        x = max(bounds.left() + 4,
                min(x, bounds.right() - self._note_preview.width() - 4))
        y = icon_rect.top() - 2
        y = max(bounds.top() + 4,
                min(y, bounds.bottom() - self._note_preview.height() - 4))
        self._note_preview.move(x, y)
        self._note_preview.show()
        self._note_preview.raise_()

    def _hide_note_tooltip(self):
        QToolTip.hideText()
        self._note_preview.hide()
        self._hover_note_id = None

    def leaveEvent(self, event):
        self._hide_note_tooltip()
        if self._edit_hover is not None:
            self._edit_hover = None
            self.update()
        super().leaveEvent(event)

    @staticmethod
    def _dist(a, b):
        return ((a.x() - b.x()) ** 2 + (a.y() - b.y()) ** 2) ** 0.5
