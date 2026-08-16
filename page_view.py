"""连续滚动页面画布：多页垂直连续渲染 + 浮动对象 + 标注交互 + 右键菜单。"""
from PySide6.QtCore import Qt, QRectF, QPointF, QPoint, Signal
from PySide6.QtGui import QImage, QPainter, QPen, QColor, QBrush, QFont
from PySide6.QtWidgets import QWidget

import backend

_ACCENT = QColor(37, 99, 235)
_PLACEHOLDER = QColor(255, 0, 255)   # 文本定位框高对比色（洋红）
_GAP = 12   # 页间距（逻辑像素）


class PageView(QWidget):
    rectSelected = Signal(int, QRectF)              # (页, PDF矩形)
    lineSelected = Signal(int, QPointF, QPointF)    # (页, 两点)
    inkSelected = Signal(int, object)               # (页, list[QPointF])
    pointClicked = Signal(int, QPointF)             # (页, 点)
    objectChanged = Signal(object, QRectF)
    objectSelected = Signal(object)
    objectDoubleClicked = Signal(object)          # 双击对象（oid）
    contextMenuRequested = Signal(QPoint)

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

        # 文本选择
        self._sel_page = None
        self._sel_start = None
        self._sel_cur = None
        self._sel_words = []
        self._selecting = False

        # 搜索高亮
        self._search_page = None
        self._search_rects = []

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_custom_context_menu)

    # ---------------- 文档 ----------------
    def set_document(self, doc, zoom, dpr=1.0):
        self._doc = doc
        self._zoom = max(0.05, zoom)
        self._dpr = max(1.0, dpr)
        self._images = {}
        self._objects = []
        self._selected = None
        self._drag = None
        self._compute_layout()

    def set_zoom(self, zoom):
        self._zoom = max(0.05, zoom)
        self._images = {}
        self._compute_layout()

    def _compute_layout(self):
        self._offsets = []
        self._page_h = []
        if self._doc is None:
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
        if self._doc is None:
            return
        buf = 400
        top = self._viewport_y - buf
        bottom = self._viewport_y + self._viewport_h + buf
        visible = set()
        for i in range(len(self._doc)):
            o = self._offsets[i]
            ph = self._page_h[i]
            if o + ph >= top and o <= bottom:
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
        return len(self._doc) if self._doc else 0

    def current_page(self):
        if not self._offsets:
            return 0
        return self._page_at(self._viewport_y + 10)

    def scroll_to_page(self, pno):
        if not self._offsets:
            return 0
        pno = max(0, min(len(self._offsets) - 1, pno))
        return int(self._offsets[pno])

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

    def _widget_rect(self, page, r):
        return QRectF(r.x() * self._zoom,
                      self._offsets[page] + r.y() * self._zoom,
                      r.width() * self._zoom, r.height() * self._zoom)

    def _widget_to_pdf(self, page, wr):
        return QRectF(wr.x() / self._zoom,
                      (wr.y() - self._offsets[page]) / self._zoom,
                      wr.width() / self._zoom, wr.height() / self._zoom)

    # ---------------- 对象 ----------------
    def set_objects(self, objects):
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

    def _object_at(self, pos):
        for o in reversed(self._objects):
            if self._widget_rect(o["page"], o["rect"]).contains(pos):
                return o
        return None

    @staticmethod
    def _corners(wr):
        return [wr.topLeft(), wr.topRight(), wr.bottomRight(), wr.bottomLeft()]

    def _handle_at(self, pos):
        if self._selected is None:
            return None
        obj = self._find(self._selected)
        if obj is None:
            return None
        corners = self._corners(self._widget_rect(obj["page"], obj["rect"]))
        for i, c in enumerate(corners):
            d = pos - c
            if abs(d.x()) + abs(d.y()) <= 8:
                return i
        return None

    # ---------------- 绘制 ----------------
    def paintEvent(self, event):
        p = QPainter(self)
        if self._doc is not None:
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

            # 文本选择高亮
            if self._sel_words and self._sel_page is not None:
                for w in self._sel_words:
                    x0, y0, x1, y1 = w[0], w[1], w[2], w[3]
                    wr = QRectF(x0 * self._zoom,
                                self._offsets[self._sel_page] + y0 * self._zoom,
                                (x1 - x0) * self._zoom, (y1 - y0) * self._zoom)
                    p.fillRect(wr, QColor(37, 99, 235, 90))

            # 搜索高亮（黄色）
            if self._search_rects and self._search_page is not None:
                for r in self._search_rects:
                    wr = QRectF(r.x0 * self._zoom,
                                self._offsets[self._search_page] + r.y0 * self._zoom,
                                (r.x1 - r.x0) * self._zoom,
                                (r.y1 - r.y0) * self._zoom)
                    p.fillRect(wr, QColor(255, 200, 0, 130))

            for obj in self._objects:
                wr = self._widget_rect(obj["page"], obj["rect"])
                if obj.get("kind") == "text":
                    p.setPen(QPen(_PLACEHOLDER, 1.6, Qt.PenStyle.DashLine))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(wr)
                    family = obj.get("fontfamily") or "Microsoft YaHei UI"
                    f = QFont(family)
                    f.setPixelSize(max(10, int(obj.get("fontsize", 11) * self._zoom)))
                    p.setFont(f)
                    p.setPen(obj.get("color") or QColor(0, 0, 0))
                    p.drawText(wr, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                               obj.get("text", ""))
                else:
                    p.drawImage(wr, obj["img"])

            if self._selected is not None:
                obj = self._find(self._selected)
                if obj is not None:
                    wr = self._widget_rect(obj["page"], obj["rect"])
                    p.setPen(QPen(_ACCENT, 1.4, Qt.PenStyle.SolidLine))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(wr)
                    hs = 7.0
                    for c in self._corners(wr):
                        p.setPen(QPen(_ACCENT, 1.2))
                        p.setBrush(QBrush(QColor(255, 255, 255)))
                        p.drawRect(QRectF(c.x() - hs / 2, c.y() - hs / 2, hs, hs))

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

    # ---------------- 鼠标 ----------------
    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position()
        if self._mode == "view":
            h = self._handle_at(pos)
            if h is not None:
                obj = self._find(self._selected)
                self._drag = ("resize", h, pos, QRectF(obj["rect"]), obj["page"])
            else:
                obj = self._object_at(pos)
                if obj is not None:
                    self._selected = obj["id"]
                    self.objectSelected.emit(obj["id"])
                    self._drag = ("move", None, pos, QRectF(obj["rect"]), obj["page"])
                else:
                    if self._selected is not None:
                        self._selected = None
                        self.objectSelected.emit(None)
                    # 空白处：开始文本选择
                    self._selecting = True
                    self._sel_start = pos
                    self._sel_cur = pos
                    self._sel_words = []
                    self._sel_page = self._page_at(pos.y())
            self.update()
        else:
            self._drawing = True
            self._start = pos
            self._cur = pos
            self._ink = [pos]
            self._start_page = self._page_at(pos.y())
            self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag is not None:
            kind, h, start, orig, page = self._drag
            if kind == "move":
                delta = pos - start
                wr = QRectF(orig).translated(delta.x() / self._zoom,
                                             delta.y() / self._zoom)
                self._apply_rect(self._selected, wr)
            elif kind == "resize":
                corners = self._corners(self._widget_rect(page, orig))
                opp = corners[(h + 2) % 4]
                o_corner = corners[h]
                s = self._dist(pos, opp) / max(1e-6, self._dist(o_corner, opp))
                s = max(0.05, min(50.0, s))
                new_w = orig.width() * s
                new_h = orig.height() * s
                off = self._offsets[page]
                x = opp.x() / self._zoom - (new_w if h in (0, 3) else 0.0)
                y = (opp.y() - off) / self._zoom - (new_h if h in (0, 1) else 0.0)
                self._apply_rect(self._selected, QRectF(x, y, new_w, new_h))
            self.update()
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
            self._update_cursor(pos)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._drag is not None:
            oid = self._selected
            obj = self._find(oid)
            if obj is not None:
                self.objectChanged.emit(oid, QRectF(obj["rect"]))
            self._drag = None
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
                self.pointClicked.emit(page, self._pdf_point(self._start)[1])
        self.update()

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._mode != "view":
            return
        obj = self._object_at(e.position())
        if obj is not None and obj.get("kind") == "text":
            self._selected = obj["id"]
            self._drag = None
            self._selecting = False
            self.update()
            self.objectDoubleClicked.emit(obj["id"])
        else:
            super().mouseDoubleClickEvent(e)

    def _on_custom_context_menu(self, pos):
        self.contextMenuRequested.emit(self.mapToGlobal(pos))

    # ---------------- 文本选择 ----------------
    def _compute_selection(self):
        if self._sel_start is None or self._sel_cur is None or self._doc is None:
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

    def set_search_highlights(self, page, rects):
        self._search_page = page
        self._search_rects = rects or []
        self.update()

    def clear_search_highlights(self):
        self._search_page = None
        self._search_rects = []
        self.update()

    def _apply_rect(self, oid, rect):
        obj = self._find(oid)
        if obj is not None:
            obj["rect"] = rect

    def set_mode(self, mode):
        self._mode = mode
        self._drawing = False
        self._ink = []
        self._drag = None
        self._selecting = False
        self._sel_words = []
        if mode == "view":
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)
        self.update()

    def mode(self):
        return self._mode

    def _update_cursor(self, pos):
        if self._mode != "view":
            return
        if self._handle_at(pos) is not None:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif self._object_at(pos) is not None:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    @staticmethod
    def _dist(a, b):
        return ((a.x() - b.x()) ** 2 + (a.y() - b.y()) ** 2) ** 0.5
