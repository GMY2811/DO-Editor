"""单个文档的视图：连续滚动页面 + 侧边栏（缩略图/书签）+ 编辑逻辑。"""
import os
import pymupdf
from PySide6.QtCore import Qt, QSize, QRectF, QPointF, Signal, QEvent
from PySide6.QtGui import (QImage, QPixmap, QIcon, QColor, QPainter, QShortcut,
                           QKeySequence)
from PySide6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QSplitter,
                               QScrollArea, QListWidget, QListWidgetItem,
                               QTreeWidget, QTreeWidgetItem, QTabWidget,
                               QLabel, QLineEdit, QFileDialog, QMessageBox,
                               QInputDialog, QApplication, QMenu, QColorDialog)
from PySide6.QtPrintSupport import QPrinter, QPrintDialog

import backend
import i18n
from page_view import PageView
from sign_dialog import (SignatureDialog, SignatureLibraryDialog,
                         qimage_to_png_bytes)

MODE_DEFS = [
    ("view",         "选择",     "view",  "select"),
    ("text_select",  "选择文字", "rect",  "text_select"),
    ("replace_text", "修改文字", "rect",  "edit"),
    ("highlight",    "高亮",     "rect",  "highlight"),
    ("underline",    "下划线",   "rect",  "underline"),
    ("strikeout",    "删除线",   "rect",  "strikeout"),
    ("rect",         "矩形",     "rect",  "rect"),
    ("line",         "直线",     "line",  "line"),
    ("ink",          "手绘",     "ink",   "ink"),
    ("text",         "文本",     "point", "text"),
]
MODE_VIEW = {k: v for k, _l, v, _i in MODE_DEFS}


class ReplaceTextDialog(QDialog):
    """修改文字对话框：文字 + 字号 + 颜色。"""

    def __init__(self, parent=None, old_text="", default_size=10):
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("replace_text"))
        from PySide6.QtWidgets import (QTextEdit, QSpinBox, QPushButton,
                                      QHBoxLayout)
        self._fontsize = default_size
        self._color = QColor(0, 0, 0)

        self._edit = QTextEdit()
        self._edit.setPlainText(old_text)
        self._edit.setFixedHeight(90)

        self._size_spin = QSpinBox()
        self._size_spin.setRange(6, 72)
        self._size_spin.setValue(default_size)

        self._color_btn = QPushButton(i18n.tr("color"))
        self._color_btn.setFixedWidth(52)
        self._color_btn.clicked.connect(self._pick_color)
        self._style_color_btn()

        btn_ok = QPushButton(i18n.tr("confirm"))
        btn_cancel = QPushButton(i18n.tr("cancel"))
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)

        row = QHBoxLayout()
        row.addWidget(QLabel(i18n.tr("font_size")))
        row.addWidget(self._size_spin)
        row.addWidget(self._color_btn)
        row.addStretch(1)
        row.addWidget(btn_ok)
        row.addWidget(btn_cancel)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(i18n.tr("new_text")))
        lay.addWidget(self._edit)
        lay.addLayout(row)
        self.resize(480, 220)

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self, i18n.tr("color"))
        if c.isValid():
            self._color = c
            self._style_color_btn()

    def _style_color_btn(self):
        self._color_btn.setStyleSheet(
            f"background:{self._color.name()};color:#ffffff;"
            f"border:1px solid #666;border-radius:4px;padding:2px 6px;")

    def result(self):
        return (self._edit.toPlainText(), self._size_spin.value(),
                (self._color.redF(), self._color.greenF(), self._color.blueF()))


class AddWatermarkDialog(QDialog):
    """添加水印对话框：文字 + 字号 + 颜色 + 透明度 + 旋转 + 平铺。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("add_watermark"))
        from PySide6.QtWidgets import (QPushButton, QHBoxLayout, QVBoxLayout,
                                      QSpinBox, QSlider, QCheckBox)
        self._color = QColor(0.5, 0.5, 0.5)
        self._opacity = 0.3

        self._text_edit = QLineEdit(i18n.tr("watermark_default"))

        self._size_spin = QSpinBox()
        self._size_spin.setRange(10, 200)
        self._size_spin.setValue(50)

        self._rotate_spin = QSpinBox()
        self._rotate_spin.setRange(0, 360)
        self._rotate_spin.setValue(45)

        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(5, 100)
        self._opacity_slider.setValue(30)

        self._tiled_check = QCheckBox(i18n.tr("tiled"))
        self._tiled_check.setChecked(True)

        self._color_btn = QPushButton(i18n.tr("color"))
        self._color_btn.setFixedWidth(52)
        self._color_btn.clicked.connect(self._pick_color)
        self._style_color_btn()

        btn_ok = QPushButton(i18n.tr("confirm"))
        btn_cancel = QPushButton(i18n.tr("cancel"))
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel(i18n.tr("watermark_text")))
        row1.addWidget(self._text_edit, 1)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel(i18n.tr("font_size")))
        row2.addWidget(self._size_spin)
        row2.addWidget(QLabel(i18n.tr("watermark_rotate")))
        row2.addWidget(self._rotate_spin)
        row2.addWidget(self._color_btn)
        row3 = QHBoxLayout()
        row3.addWidget(QLabel(i18n.tr("watermark_opacity")))
        row3.addWidget(self._opacity_slider, 1)
        row3.addWidget(self._tiled_check)
        row4 = QHBoxLayout()
        row4.addStretch(1)
        row4.addWidget(btn_ok)
        row4.addWidget(btn_cancel)

        lay = QVBoxLayout(self)
        lay.addLayout(row1)
        lay.addLayout(row2)
        lay.addLayout(row3)
        lay.addLayout(row4)
        self.resize(460, 180)

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self, i18n.tr("color"))
        if c.isValid():
            self._color = c
            self._style_color_btn()

    def _style_color_btn(self):
        self._color_btn.setStyleSheet(
            f"background:{self._color.name()};color:#ffffff;"
            f"border:1px solid #666;border-radius:4px;padding:2px 6px;")

    def result(self):
        return (self._text_edit.text().strip(), self._size_spin.value(),
                (self._color.redF(), self._color.greenF(), self._color.blueF()),
                self._opacity_slider.value() / 100.0,
                self._rotate_spin.value(), self._tiled_check.isChecked())


class DocumentView(QWidget):
    statusMessage = Signal(str, int)
    titleChanged = Signal(str)
    pageChanged = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc = None
        self.file_path = None
        self.zoom = 1.4
        self.modified = False
        self.current_mode = "view"
        self.edit_color = QColor(200, 30, 30)
        self.objects = []
        self._obj_counter = 0
        self.pending_image_qimg = None
        self.pending_sign_qimg = None
        self.pending_paste_text = None
        self.mode_actions = {}
        self._build_ui()

    # ================= UI =================
    def _build_ui(self):
        self.side_tabs = QTabWidget()
        self.side_tabs.setFixedWidth(180)
        self.side_tabs.setVisible(False)

        self.thumb_list = QListWidget()
        self.thumb_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumb_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumb_list.setIconSize(QSize(96, 128))
        self.thumb_list.setGridSize(QSize(140, 160))
        self.thumb_list.setMovement(QListWidget.Movement.Static)
        self.thumb_list.itemClicked.connect(self._on_thumb_clicked)

        self.bookmark_tree = QTreeWidget()
        self.bookmark_tree.setHeaderHidden(True)
        self.bookmark_tree.itemClicked.connect(self._on_bookmark_clicked)

        self.side_tabs.addTab(self.thumb_list, "页面")
        self.side_tabs.addTab(self.bookmark_tree, "书签")

        self.page_view = PageView()
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.page_view)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidgetResizable(False)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)

        splitter = QSplitter()
        splitter.addWidget(self.side_tabs)
        splitter.addWidget(self.scroll)
        splitter.setStretchFactor(1, 1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(splitter)

        self.page_view.rectSelected.connect(self._on_rect)
        self.page_view.lineSelected.connect(self._on_line)
        self.page_view.inkSelected.connect(self._on_ink)
        self.page_view.pointClicked.connect(self._on_point)
        self.page_view.objectChanged.connect(self._on_object_changed)
        self.page_view.objectSelected.connect(self._on_object_selected)
        self.page_view.objectDoubleClicked.connect(self._on_object_double_clicked)
        self.page_view.contextMenuRequested.connect(self._on_context_menu)

        self.scroll.viewport().installEventFilter(self)

    # ================= 打开 / 保存 =================
    def load(self, path):
        try:
            doc = backend.open_pdf(path)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开该文件：\n{e}")
            return False
        if self.doc:
            self.doc.close()
        self.doc = doc
        self.file_path = path
        self.modified = False
        self.objects = []
        self._obj_counter = 0
        self.titleChanged.emit(os.path.basename(path))
        self._refresh()
        self._rebuild_thumbnails()
        self._rebuild_bookmarks()
        self.fit_width()
        self.set_mode("view")
        return True

    def close_doc(self):
        if self.doc:
            self.doc.close()
        self.doc = None
        self.file_path = None
        self.modified = False
        self.objects = []
        self._obj_counter = 0
        self.pending_image_qimg = None
        self.pending_sign_qimg = None
        self.pending_paste_text = None
        self.titleChanged.emit("未命名")
        self.page_view.set_document(None, 1.0, 1.0)
        self.thumb_list.clear()
        self.bookmark_tree.clear()
        self.pageChanged.emit(0, 0)

    def save(self):
        if self.doc is None:
            return
        if self.file_path:
            self._save_to(self.file_path)
        else:
            self.save_as()

    def save_as(self):
        if self.doc is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "另存为", "未命名.pdf",
                                              "PDF 文件 (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self._save_to(path)

    def _save_to(self, path):
        try:
            self._bake_objects()
            tmp = path + ".tmp"
            self.doc.save(tmp, garbage=3, deflate=True)
            self.doc.close()
            os.replace(tmp, path)
            self.doc = backend.open_pdf(path)
            self.file_path = path
            self.modified = False
            self.titleChanged.emit(os.path.basename(path))
            self._rebuild_bookmarks()
            self._refresh()
            self.statusMessage.emit("已保存", 2000)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：\n{e}")

    def _bake_objects(self):
        for obj in self.objects:
            page = self.doc[obj["page"]]
            r = obj["rect"]
            fr = pymupdf.Rect(r.x(), r.y(), r.right(), r.bottom())
            if obj.get("kind") == "text":
                c = obj.get("color")
                rgb = (c.redF(), c.greenF(), c.blueF()) if c else (0, 0, 0)
                try:
                    backend.insert_text_auto(
                        page, fr, obj.get("text", ""),
                        fontsize=obj.get("fontsize", 12), color=rgb)
                except Exception:
                    backend.insert_text_auto(
                        page, fr, obj.get("text", ""),
                        fontsize=obj.get("fontsize", 12), color=(0, 0, 0))
            else:
                page.insert_image(fr, stream=obj["png"])
        self.objects = []
        self._obj_counter = 0

    @staticmethod
    def _pdf_fontname(family):
        if not family:
            return "helv"
        low = family.lower()
        if any(k in low for k in ("yahei", "microsoft", "simsun", "simhei",
                                  "宋体", "黑体", "雅黑", "微软", "楷", "仿宋",
                                  "song", "hei")):
            return "china-s"
        if any(k in low for k in ("times", "roman")):
            return "times-roman"
        if any(k in low for k in ("courier", "mono")):
            return "cour"
        if any(k in low for k in ("arial", "helvetica", "helv")):
            return "helv"
        return family

    # ================= 渲染 / 导航 =================
    def _refresh(self):
        dpr = max(1.0, self.page_view.devicePixelRatioF())
        self.page_view.set_document(self.doc, self.zoom, dpr)
        self.page_view.set_objects(self._objects_for_current_page())

    def _objects_for_current_page(self):
        return self.objects

    def _on_scroll(self, value):
        self.page_view.set_viewport(value, self.scroll.viewport().height())
        self.page_view.update()
        if self.doc is not None:
            pno = self.page_view.current_page()
            self.thumb_list.setCurrentRow(pno)
            self.pageChanged.emit(pno, len(self.doc))

    def show_page(self, pno):
        if self.doc is None:
            return
        self.scroll.verticalScrollBar().setValue(self.page_view.scroll_to_page(pno))

    def next_page(self):
        self.show_page(self.page_view.current_page() + 1)

    def prev_page(self):
        self.show_page(self.page_view.current_page() - 1)

    def zoom_in(self):
        self._set_zoom(self.zoom * 1.25)

    def zoom_out(self):
        self._set_zoom(self.zoom / 1.25)

    def fit_width(self):
        if self.doc is None:
            return
        w, _h = backend.page_size(self.doc, 0)
        vw = max(200, self.scroll.viewport().width() - 40)
        self._set_zoom(vw / w)

    def _set_zoom(self, z):
        keep = self.page_view.current_page()
        self.zoom = max(0.1, min(10.0, z))
        self.page_view.set_zoom(self.zoom)
        self.page_view.set_objects(self._objects_for_current_page())
        if self.doc is not None:
            self.scroll.verticalScrollBar().setValue(
                self.page_view.scroll_to_page(keep))

    def toggle_sidebar(self):
        self.side_tabs.setVisible(not self.side_tabs.isVisible())

    # ================= 侧边栏 =================
    def _rebuild_thumbnails(self):
        self.thumb_list.clear()
        if self.doc is None:
            return
        for i in range(len(self.doc)):
            page = self.doc[i]
            w = max(1.0, page.rect.width)
            scale = 96.0 / w
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format.Format_RGB888).copy()
            item = QListWidgetItem(QIcon(QPixmap.fromImage(img)), f"{i + 1}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.thumb_list.addItem(item)

    def _rebuild_bookmarks(self):
        self.bookmark_tree.clear()
        if self.doc is None:
            return
        toc = self.doc.get_toc()
        stack = []
        for level, title, page in toc:
            node = QTreeWidgetItem([title])
            node.setData(0, Qt.ItemDataRole.UserRole, page - 1)
            if stack:
                while stack and stack[-1][0] >= level:
                    stack.pop()
                if stack:
                    stack[-1][1].addChild(node)
                else:
                    self.bookmark_tree.addTopLevelItem(node)
            else:
                self.bookmark_tree.addTopLevelItem(node)
            stack.append((level, node))

    def _on_thumb_clicked(self, item):
        pno = item.data(Qt.ItemDataRole.UserRole)
        if pno is not None:
            self.show_page(int(pno))

    def _on_bookmark_clicked(self, item, col):
        pno = item.data(0, Qt.ItemDataRole.UserRole)
        if pno is not None:
            self.show_page(int(pno))

    # ================= 搜索 / 复制 =================
    def search(self, text):
        if not text or self.doc is None:
            return
        total = len(self.doc)
        start = self.page_view.current_page()
        for off in range(total):
            pno = (start + off) % total
            rects = self.doc[pno].search_for(text)
            if rects:
                self.show_page(pno)
                self.page_view.set_search_highlights(pno, rects)
                self.statusMessage.emit(
                    f"找到“{text}”：第 {pno + 1} 页，共 {len(rects)} 处", 3000)
                return
        self.page_view.clear_search_highlights()
        self.statusMessage.emit(f"未找到“{text}”", 3000)

    def copy_page_text(self):
        if self.doc is None:
            return
        pno = self.page_view.current_page()
        text = backend.extract_text(self.doc, pno)
        if text:
            QApplication.clipboard().setText(text)
            self.statusMessage.emit(
                f"已复制第 {pno + 1} 页全部文字（{len(text)} 字）", 3000)
        else:
            self.statusMessage.emit("当前页没有可复制的文字", 3000)

    def paste_text(self):
        text = QApplication.clipboard().text().strip()
        if not text:
            self.statusMessage.emit("剪贴板没有文字", 3000)
            return
        self.pending_paste_text = text
        self.current_mode = "paste"
        self._check_none()
        self.page_view.set_mode("point")
        self.statusMessage.emit("在页面上点击要粘贴文字的位置", 6000)

    # ================= 编辑 =================
    def _edit_rgb(self):
        return (self.edit_color.redF(), self.edit_color.greenF(), self.edit_color.blueF())

    def _clamp_rect(self, page, r):
        pr = self.doc[page].rect
        return pymupdf.Rect(max(pr.x0, r.x0), max(pr.y0, r.y0),
                            min(pr.x1, r.x1), min(pr.y1, r.y1))

    def _on_rect(self, page, rect):
        r = self._clamp_rect(page, pymupdf.Rect(rect.x(), rect.y(),
                                                rect.right(), rect.bottom()))
        if self.current_mode == "text_select":
            text = backend.extract_text(self.doc, page, r)
            if text:
                QApplication.clipboard().setText(text)
                self.statusMessage.emit(f"已复制 {len(text)} 字", 3000)
            else:
                self.statusMessage.emit("该区域没有文字", 3000)
            return
        if self.current_mode == "replace_text":
            old = backend.extract_text(self.doc, page, r)
            dlg = ReplaceTextDialog(self, old_text=old, default_size=10)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                text, fontsize, color = dlg.result()
                if text.strip():
                    backend.replace_text(self.doc[page], r, text,
                                         fontsize=fontsize, color=color)
                    self.modified = True
                    self._refresh()
            return
        p = self.doc[page]
        color = self._edit_rgb()
        m = self.current_mode
        if m == "highlight":
            backend.add_highlight(p, r)
        elif m == "underline":
            backend.add_underline(p, r, color)
        elif m == "strikeout":
            backend.add_strikeout(p, r, color)
        elif m == "rect":
            backend.add_rect(p, r, color)
        else:
            return
        self.modified = True
        self._refresh()

    def _on_line(self, page, p1, p2):
        if self.current_mode != "line":
            return
        backend.add_line(self.doc[page], (p1.x(), p1.y()), (p2.x(), p2.y()),
                         self._edit_rgb())
        self.modified = True
        self._refresh()

    def _on_ink(self, page, points):
        if self.current_mode != "ink":
            return
        backend.add_ink(self.doc[page], [(p.x(), p.y()) for p in points],
                        self._edit_rgb())
        self.modified = True
        self._refresh()

    def _on_point(self, page, pt):
        m = self.current_mode
        if m == "text":
            self._start_inline_text(page, pt)
        elif m == "image" and self.pending_image_qimg is not None:
            self._add_object(self.pending_image_qimg, "image", page, pt, 160.0)
            self.pending_image_qimg = None
        elif m == "sign" and self.pending_sign_qimg is not None:
            self._add_object(self.pending_sign_qimg, "signature", page, pt, 180.0)
            self.pending_sign_qimg = None
        elif m == "paste" and self.pending_paste_text:
            self._add_text_object(self.pending_paste_text, page, pt)
            self.pending_paste_text = None
        self._refresh()

    def _detect_font_at(self, page, pt):
        """检测点击位置附近文字的字体，映射为系统字体名（用于文本默认字体）。"""
        try:
            p = self.doc[page]
            clip = pymupdf.Rect(pt.x() - 4, pt.y() - 4, pt.x() + 4, pt.y() + 4)
            d = p.get_text("dict", clip=clip)
            for block in d.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        mapped = self._map_pdf_font(span.get("font", ""))
                        if mapped:
                            return mapped
            # 回退：取整页出现最多的字体
            counts = {}
            for block in p.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        f = span.get("font", "")
                        if f:
                            counts[f] = counts.get(f, 0) + 1
            if counts:
                best = max(counts, key=counts.get)
                mapped = self._map_pdf_font(best)
                if mapped:
                    return mapped
        except Exception:
            pass
        return ""

    @staticmethod
    def _map_pdf_font(pdf_font):
        """PDF 内部字体名 → 系统字体名（找不到则返回空串）。"""
        low = (pdf_font or "").lower()
        if any(k in low for k in ("simsun", "song", "宋")):
            return "SimSun"
        if any(k in low for k in ("simhei", "hei", "黑")):
            return "SimHei"
        if any(k in low for k in ("kaiti", "kai", "楷")):
            return "KaiTi"
        if any(k in low for k in ("fangsong", "fang", "仿")):
            return "FangSong"
        if any(k in low for k in ("yahei", "msyh", "雅黑", "microsoft")):
            return "Microsoft YaHei"
        if any(k in low for k in ("timesnewroman", "times")):
            return "Times New Roman"
        if any(k in low for k in ("arial", "helvetica", "helv")):
            return "Arial"
        if any(k in low for k in ("courier", "mono")):
            return "Courier New"
        return ""

    def _start_inline_text(self, page, pt, oid=None):
        """在页面位置显示 inline 文字输入框（字体/字号/颜色），oid 非空则为编辑模式。"""
        from PySide6.QtWidgets import (QTextEdit, QFontComboBox, QSpinBox,
                                      QPushButton, QHBoxLayout)
        from PySide6.QtGui import QFont
        self._close_inline_editor()

        existing = None
        if oid is not None:
            existing = next((o for o in self.objects if o["id"] == oid), None)

        if existing is not None:
            wx = int(existing["rect"].x() * self.page_view._zoom)
            wy = int(self.page_view._offsets[page] + existing["rect"].y() * self.page_view._zoom)
            init_text = existing.get("text", "")
            init_family = existing.get("fontfamily", "")
            init_size = existing.get("fontsize", 10)
            cur_color = existing.get("color") or QColor(self.edit_color)
        else:
            wx = int(pt.x() * self.page_view._zoom)
            wy = int(self.page_view._offsets[page] + pt.y() * self.page_view._zoom)
            init_text = ""
            init_family = self._detect_font_at(page, pt)
            init_size = 10
            cur_color = QColor(0, 0, 0)

        box = QWidget(self.page_view)
        lay = QHBoxLayout(box)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        edit = QLineEdit(init_text)
        edit.setMinimumWidth(180)
        edit.setStyleSheet("background:#ffffff;border:1px solid #4b9cf0;color:#000000;")
        font_combo = QFontComboBox()
        font_combo.setFixedWidth(120)
        if init_family:
            font_combo.setCurrentFont(QFont(init_family))
        size_spin = QSpinBox()
        size_spin.setRange(6, 72)
        size_spin.setValue(init_size)
        size_spin.setFixedWidth(52)

        color_state = {"color": QColor(cur_color)}
        btn_color = QPushButton("颜色")
        btn_color.setFixedWidth(50)
        btn_color.clicked.connect(lambda: self._pick_text_color(color_state, btn_color))
        self._style_color_btn(btn_color, color_state["color"])

        btn_ok = QPushButton("确定")
        btn_cancel = QPushButton("取消")
        lay.addWidget(edit, 1)
        lay.addWidget(font_combo)
        lay.addWidget(size_spin)
        lay.addWidget(btn_color)
        lay.addWidget(btn_ok)
        lay.addWidget(btn_cancel)
        box.setFixedWidth(640)
        box.adjustSize()
        box_w = box.width()
        box_h = box.height()
        pv_w = max(100, self.page_view.width())
        pv_h = max(100, self.page_view.height())
        if wx + box_w > pv_w:
            wx = max(0, pv_w - box_w - 8)
        if wy + box_h > pv_h:
            wy = max(0, wy - box_h - 12)
        box.move(wx, wy)
        box.show()
        edit.setFocus()

        def on_ok():
            text = edit.text()
            family = font_combo.currentFont().family()
            size = size_spin.value()
            color = color_state["color"]
            self._close_inline_editor()
            if not text.strip():
                if existing is not None:
                    self.delete_object(oid)
                return
            if existing is not None:
                existing["text"] = text
                existing["fontfamily"] = family
                existing["fontsize"] = size
                existing["color"] = color
                self.modified = True
                self._refresh_objects()
                self.page_view.select(oid)
            else:
                self._add_text_object(text, page, pt, family, size, color)

        btn_ok.clicked.connect(on_ok)
        btn_cancel.clicked.connect(self._close_inline_editor)
        self._inline_box = box
        self._inline_edit = edit
        self._inline_oid = oid

    @staticmethod
    def _style_color_btn(btn, color):
        btn.setStyleSheet(
            f"background:{color.name()};color:#ffffff;"
            f"border:1px solid #666;border-radius:4px;padding:2px 6px;")

    def _pick_text_color(self, color_state, btn):
        c = QColorDialog.getColor(color_state["color"], self, "选择文字颜色")
        if c.isValid():
            color_state["color"] = c
            self._style_color_btn(btn, c)

    def _close_inline_editor(self):
        if getattr(self, "_inline_box", None) is not None:
            self._inline_box.deleteLater()
        self._inline_box = None
        self._inline_edit = None

    def _add_object(self, img, kind, page, pt, base_w):
        aspect = img.height() / max(1, img.width())
        h = base_w * aspect
        self._obj_counter += 1
        self.objects.append({
            "id": self._obj_counter, "page": page,
            "rect": QRectF(pt.x(), pt.y(), base_w, h),
            "img": img, "png": qimage_to_png_bytes(img), "kind": kind,
        })
        self.modified = True
        self.set_mode("view")
        self._refresh_objects()
        self.page_view.select(self._obj_counter)

    def _add_text_object(self, text, page, pt, fontfamily="", fontsize=12, color=None):
        self._obj_counter += 1
        self.objects.append({
            "id": self._obj_counter, "page": page,
            "rect": QRectF(pt.x(), pt.y(), 240, 60),
            "text": text, "color": color if color is not None else QColor(0, 0, 0),
            "fontsize": fontsize, "fontfamily": fontfamily, "kind": "text",
        })
        self.modified = True
        self.set_mode("view")
        self._refresh_objects()
        self.page_view.select(self._obj_counter)

    def _find_object(self, oid):
        for o in self.objects:
            if o["id"] == oid:
                return o
        return None

    def delete_object(self, oid):
        if oid is None:
            return
        self.objects = [o for o in self.objects if o["id"] != oid]
        self.modified = True
        self._refresh_objects()
        self.page_view.update()

    def _on_object_double_clicked(self, oid):
        obj = self._find_object(oid)
        if obj is None or obj.get("kind") != "text":
            return
        self._start_inline_text(
            obj["page"], QPointF(obj["rect"].x(), obj["rect"].y()), oid)

    def _edit_text_object(self, oid):
        obj = self._find_object(oid)
        if obj is None or obj.get("kind") != "text":
            return
        self._start_inline_text(
            obj["page"], QPointF(obj["rect"].x(), obj["rect"].y()), oid)

    def _change_text_color(self, oid):
        obj = self._find_object(oid)
        if obj is None or obj.get("kind") != "text":
            return
        c = QColorDialog.getColor(obj.get("color") or QColor(self.edit_color),
                                  self, "选择文字颜色")
        if c.isValid():
            obj["color"] = c
            self.modified = True
            self._refresh_objects()
            self.page_view.update()

    def _refresh_objects(self):
        self.page_view.set_objects(self._objects_for_current_page())

    def _on_object_changed(self, oid, rect):
        for o in self.objects:
            if o["id"] == oid:
                o["rect"] = rect
                break
        self.modified = True

    def _on_object_selected(self, oid):
        if oid is not None:
            self.statusMessage.emit("拖动移动，拖动角点缩放，Delete 删除", 6000)

    def delete_selected(self):
        self.delete_object(self.page_view.selected_id())

    def _on_context_menu(self, global_pos):
        menu = QMenu(self)
        oid = self.page_view.selected_id()
        sel_obj = self._find_object(oid) if oid is not None else None
        if self.doc is not None:
            if self.page_view.has_selection():
                menu.addAction(i18n.tr("copy_selected"), self.copy_selected_text)
            menu.addAction(i18n.tr("select_text"), lambda: self.set_mode("text_select"))
            menu.addAction(i18n.tr("copy_page"), self.copy_page_text)
            menu.addAction(i18n.tr("paste_text"), self.paste_text)
            menu.addSeparator()
        if sel_obj is not None:
            if sel_obj.get("kind") == "text":
                menu.addAction(i18n.tr("edit_text"), lambda: self._edit_text_object(oid))
                menu.addAction(i18n.tr("change_color"), lambda: self._change_text_color(oid))
                menu.addSeparator()
            menu.addAction(i18n.tr("delete_object"), self.delete_selected)
        if self.pending_sign_qimg is not None or self.pending_image_qimg is not None \
                or self.pending_paste_text:
            menu.addAction(i18n.tr("cancel_place"), self._cancel_placement)
        menu.addSeparator()
        menu.addAction(i18n.tr("fit_width2"), self.fit_width)
        if menu.actions():
            menu.exec(global_pos)

    def copy_selected_text(self):
        text = self.page_view.selected_text()
        if text:
            QApplication.clipboard().setText(text)
            self.statusMessage.emit(f"已复制 {len(text)} 字", 3000)
        else:
            self.statusMessage.emit("未选中文字", 3000)

    def copy_selected_or_page(self):
        """有滑动选区时复制选区文字，否则复制本页全部文字。"""
        if self.page_view.has_selection():
            self.copy_selected_text()
        else:
            self.copy_page_text()

    def _cancel_placement(self):
        self.pending_sign_qimg = None
        self.pending_image_qimg = None
        self.pending_paste_text = None
        self.set_mode("view")

    # ================= 模式 =================
    def set_mode(self, key):
        if key not in MODE_VIEW:
            key = "view"
        self.current_mode = key
        self._close_inline_editor()
        for k, act in self.mode_actions.items():
            act.setChecked(k == key)
        self.page_view.set_mode(MODE_VIEW[key])

    def _check_none(self):
        for act in self.mode_actions.values():
            act.setChecked(False)

    def pick_edit_color(self):
        c = QColorDialog.getColor(self.edit_color, self, "选择编辑颜色")
        if c.isValid():
            self.edit_color = c

    # ================= 图片 / 签名 =================
    def start_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择图片", "",
                                              "图片 (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "提示", "无法读取该图片")
            return
        self.pending_image_qimg = img
        self.current_mode = "image"
        self._check_none()
        self.page_view.set_mode("point")
        self.statusMessage.emit("在页面上点击要插入图片的位置", 6000)

    def start_sign(self):
        dlg = SignatureDialog(self)
        if dlg.exec() != SignatureDialog.DialogCode.Accepted:
            return
        img = dlg.result_image()
        if img is None or img.isNull():
            return
        self._prepare_sign(img)

    def open_sign_lib(self):
        dlg = SignatureLibraryDialog(self)
        if dlg.exec() != SignatureLibraryDialog.DialogCode.Accepted:
            return
        img = dlg.result_image()
        if img is None or img.isNull():
            return
        self._prepare_sign(img)

    def _prepare_sign(self, img):
        self.pending_sign_qimg = img
        self.current_mode = "sign"
        self._check_none()
        self.page_view.set_mode("point")
        self.statusMessage.emit("在页面上点击要盖章的位置", 6000)

    # ================= 页面操作 =================
    def delete_current_page(self):
        if self.doc is None:
            return
        if len(self.doc) <= 1:
            QMessageBox.information(self, "提示", "文档只剩一页，无法删除")
            return
        pno = self.page_view.current_page()
        r = QMessageBox.question(self, "删除页面", f"确定删除第 {pno + 1} 页吗？")
        if r != QMessageBox.StandardButton.Yes:
            return
        self.doc.delete_page(pno)
        self.objects = [o for o in self.objects if o["page"] != pno]
        for o in self.objects:
            if o["page"] > pno:
                o["page"] -= 1
        self.modified = True
        self._refresh()
        self._rebuild_thumbnails()
        self._rebuild_bookmarks()

    # ================= 打印 =================
    def print_pdf(self):
        if self.doc is None:
            QMessageBox.information(self, "提示", "请先打开一个 PDF 文件")
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.critical(self, "错误", "无法启动打印")
            return
        try:
            page_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
            res = max(72, printer.resolution())
            total = len(self.doc)
            from_page, to_page = 0, total - 1
            if printer.printRange() == QPrinter.PrintRange.PageRange:
                from_page = max(0, printer.fromPage() - 1)
                to_page = min(total - 1, printer.toPage() - 1)
            for i in range(from_page, to_page + 1):
                if i > from_page:
                    printer.newPage()
                page = self.doc[i]
                zoom = res / 72.0
                pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                             QImage.Format.Format_RGB888).copy()
                iw, ih = img.width(), img.height()
                scale = min(page_rect.width() / iw, page_rect.height() / ih)
                dw, dh = iw * scale, ih * scale
                x = page_rect.x() + (page_rect.width() - dw) / 2
                y = page_rect.y() + (page_rect.height() - dh) / 2
                painter.drawImage(QRectF(x, y, dw, dh), img)
            self.statusMessage.emit("已发送打印任务", 3000)
        finally:
            painter.end()

    # ================= 事件过滤器 =================
    def eventFilter(self, obj, event):
        if obj is self.scroll.viewport() and event.type() == QEvent.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                delta = event.angleDelta().y()
                if delta > 0:
                    self.zoom_in()
                else:
                    self.zoom_out()
                return True
        return super().eventFilter(obj, event)
