"""单个文档的视图：连续滚动页面 + 缩略图侧栏 + 编辑逻辑。"""
import os
import pymupdf
from PySide6.QtCore import Qt, QSize, QRectF, QPointF, Signal, QEvent
from PySide6.QtGui import (QImage, QPixmap, QIcon, QColor, QPainter, QShortcut,
                           QKeySequence)
from PySide6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QSplitter,
                               QScrollArea, QListWidget, QListWidgetItem,
                               QTabWidget, QStackedWidget, QFrame, QPushButton,
                               QLabel, QLineEdit, QFileDialog, QMessageBox,
                               QInputDialog, QApplication, QMenu, QColorDialog,
                               QGraphicsDropShadowEffect)
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
    """修改文字对话框：文字 + 字体 + 字号 + 颜色。"""

    def __init__(self, parent=None, old_text="", default_size=10, default_family="",
                 default_color=None, default_bold=False, default_italic=False):
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("replace_text"))
        from PySide6.QtWidgets import (QTextEdit, QSpinBox, QPushButton,
                                      QHBoxLayout, QFontComboBox, QCheckBox)
        from PySide6.QtGui import QFont
        self._fontsize = default_size
        self._color = QColor(default_color) if default_color is not None else QColor(0, 0, 0)

        self._edit = QTextEdit()
        self._edit.setPlainText(old_text)
        self._edit.setFixedHeight(56)

        self._font_combo = QFontComboBox()
        if default_family:
            self._font_combo.setCurrentFont(QFont(default_family))

        self._size_spin = QSpinBox()
        self._size_spin.setRange(6, 72)
        self._size_spin.setValue(default_size)

        self._color_btn = QPushButton(i18n.tr("color"))
        self._color_btn.setFixedWidth(52)
        self._color_btn.clicked.connect(self._pick_color)
        self._style_color_btn()

        self._bold_check = QCheckBox(i18n.tr("bold"))
        self._bold_check.setChecked(default_bold)

        self._italic_check = QCheckBox(i18n.tr("italic"))
        self._italic_check.setChecked(default_italic)

        btn_ok = QPushButton(i18n.tr("confirm"))
        btn_cancel = QPushButton(i18n.tr("cancel"))
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)

        row1 = QHBoxLayout()
        row1.setSpacing(4)
        row1.addWidget(QLabel(i18n.tr("font_family")))
        row1.addWidget(self._font_combo)
        row1.addWidget(QLabel(i18n.tr("font_size")))
        row1.addWidget(self._size_spin)
        row1.addWidget(self._color_btn)
        row1.addWidget(self._bold_check)
        row1.addWidget(self._italic_check)
        row1.addStretch(1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addStretch(1)
        row2.addWidget(btn_ok)
        row2.addWidget(btn_cancel)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 8)
        lay.setSpacing(6)
        row_text = QHBoxLayout()
        row_text.setSpacing(6)
        row_text.addWidget(QLabel(i18n.tr("new_text")))
        row_text.addWidget(self._edit, 1)
        lay.addLayout(row_text)
        lay.addLayout(row1)
        lay.addLayout(row2)
        self.resize(560, 160)

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
                (self._color.redF(), self._color.greenF(), self._color.blueF()),
                self._font_combo.currentFont().family(),
                self._bold_check.isChecked(),
                self._italic_check.isChecked())


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
    openRequested = Signal()

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
        self._search_results = []
        self._search_index = 0
        self._build_ui()

    # ================= UI =================
    def _build_ui(self):
        self.side_tabs = QTabWidget()
        self.side_tabs.setObjectName("sidePanel")
        self.side_tabs.setFixedWidth(196)
        self.side_tabs.setVisible(False)

        self.thumb_list = QListWidget()
        self.thumb_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumb_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumb_list.setIconSize(QSize(96, 128))
        self.thumb_list.setGridSize(QSize(140, 160))
        self.thumb_list.setMovement(QListWidget.Movement.Static)
        self.thumb_list.itemClicked.connect(self._on_thumb_clicked)

        self.side_tabs.addTab(self.thumb_list, "页面")
        self.side_tabs.setTabBarAutoHide(True)

        self.page_view = PageView()
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.page_view)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidgetResizable(False)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)

        # 无文档时显示欢迎页，避免主区域只剩一块空灰色画布。
        start_page = QWidget()
        start_page.setObjectName("startPage")
        start_outer = QVBoxLayout(start_page)
        start_outer.setContentsMargins(32, 32, 32, 32)
        start_outer.addStretch(1)

        start_card = QFrame()
        start_card.setObjectName("startCard")
        start_card.setMaximumWidth(520)
        card_shadow = QGraphicsDropShadowEffect(start_card)
        card_shadow.setBlurRadius(36)
        card_shadow.setOffset(0, 10)
        card_shadow.setColor(QColor(24, 31, 45, 34))
        start_card.setGraphicsEffect(card_shadow)
        card_lay = QVBoxLayout(start_card)
        card_lay.setContentsMargins(54, 46, 54, 44)
        card_lay.setSpacing(12)

        mark_row = QHBoxLayout()
        mark_row.addStretch(1)
        mark = QLabel("DO")
        mark.setObjectName("startMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(62, 62)
        mark_row.addWidget(mark)
        mark_row.addStretch(1)
        card_lay.addLayout(mark_row)

        title = QLabel("DO编辑器")
        title.setObjectName("startTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_lay.addWidget(title)

        subtitle = QLabel("轻量、专注的 PDF 阅读与编辑工具")
        subtitle.setObjectName("startSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_lay.addWidget(subtitle)
        card_lay.addSpacing(8)

        open_row = QHBoxLayout()
        open_row.addStretch(1)
        open_btn = QPushButton("打开文档")
        open_btn.setObjectName("startOpenButton")
        open_btn.setDefault(True)
        open_btn.clicked.connect(self.openRequested.emit)
        open_row.addWidget(open_btn)
        open_row.addStretch(1)
        card_lay.addLayout(open_row)

        hint = QLabel("支持 PDF、DOCX、DOC  ·  Ctrl+O 快速打开")
        hint.setObjectName("startHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_lay.addWidget(hint)

        card_row = QHBoxLayout()
        card_row.addStretch(1)
        card_row.addWidget(start_card)
        card_row.addStretch(1)
        start_outer.addLayout(card_row)
        start_outer.addStretch(1)

        self.workspace_stack = QStackedWidget()
        self.workspace_stack.addWidget(start_page)
        self.workspace_stack.addWidget(self.scroll)
        self.workspace_stack.setCurrentWidget(start_page)

        splitter = QSplitter()
        splitter.setObjectName("documentSplitter")
        splitter.setHandleWidth(1)
        splitter.addWidget(self.side_tabs)
        splitter.addWidget(self.workspace_stack)
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
        self.workspace_stack.setCurrentWidget(self.scroll)
        self._refresh()
        self._rebuild_thumbnails()
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
        self.workspace_stack.setCurrentIndex(0)
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
                backend.insert_text_auto(
                    page, fr, obj.get("text", ""),
                    fontsize=obj.get("fontsize", 12), color=rgb,
                    fontfamily=obj.get("fontfamily", ""),
                    bold=bool(obj.get("bold", False)),
                    italic=bool(obj.get("italic", False)))
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

    def _on_thumb_clicked(self, item):
        pno = item.data(Qt.ItemDataRole.UserRole)
        if pno is not None:
            self.show_page(int(pno))

    # ================= 搜索 / 复制 =================
    def search(self, text):
        """搜索全文，收集所有匹配并全部高亮，定位到第一个结果。"""
        self._search_text = text
        self._search_results = []
        if not text or self.doc is None:
            self.page_view.clear_search_highlights()
            return
        total = len(self.doc)
        start = self.page_view.current_page()
        all_map = {}
        for off in range(total):
            pno = (start + off) % total
            rects = self.doc[pno].search_for(text)
            if rects:
                all_map[pno] = rects
                for r in rects:
                    self._search_results.append((pno, r))
        if not self._search_results:
            self.page_view.clear_search_highlights()
            self.statusMessage.emit(f"未找到“{text}”", 3000)
            return
        # 全部匹配黄色高亮
        self.page_view.set_search_all(all_map)
        self._search_index = 0
        self._goto_search(0)

    def _goto_search(self, idx):
        n = len(self._search_results)
        if n == 0:
            return
        idx = idx % n
        self._search_index = idx
        pno, rect = self._search_results[idx]
        # 定位到具体匹配位置（显示在可视区中央），而非仅页面顶部
        self.scroll.verticalScrollBar().setValue(
            self.page_view.scroll_to_rect(pno, rect))
        self.page_view.set_search_current(pno, rect)
        self.statusMessage.emit(
            f"共 {n} 处匹配，第 {idx + 1} 处（第 {pno + 1} 页）", 0)

    def search_next(self):
        if self._search_results:
            self._goto_search(self._search_index + 1)

    def search_prev(self):
        if self._search_results:
            self._goto_search(self._search_index - 1)

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
            fmt = {"family": "", "size": 10, "color": QColor(0, 0, 0),
                   "bold": False, "italic": False}
            try:
                c = QPointF((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
                fmt = self._detect_format_at(page, c)
            except Exception:
                pass
            dlg = ReplaceTextDialog(self, old_text=old,
                                    default_size=int(round(fmt["size"])),
                                    default_family=fmt["family"],
                                    default_color=fmt["color"],
                                    default_bold=fmt["bold"],
                                    default_italic=fmt["italic"])
            if dlg.exec() == QDialog.DialogCode.Accepted:
                text, fontsize, color, fontfamily, bold, italic = dlg.result()
                if text.strip():
                    # 删除原文字
                    backend.redact_rect(self.doc[page], r)
                    # 创建可拖动的浮动文本对象（保存时烘焙进 PDF）
                    self._obj_counter += 1
                    fr = QRectF(r.x0, r.y0, max(40.0, r.x1 - r.x0),
                                max(20.0, r.y1 - r.y0))
                    self.objects.append({
                        "id": self._obj_counter, "page": page,
                        "rect": fr,
                        "text": text,
                        "color": QColor.fromRgbF(*color),
                        "fontsize": fontsize, "fontfamily": fontfamily,
                        "bold": bold, "italic": italic, "kind": "text",
                    })
                    self.modified = True
                    self.set_mode("view")
                    self._refresh()
                    self.page_view.select(self._obj_counter)
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

    def _detect_format_at(self, page, pt):
        """检测点击位置文字格式（字体/字号/颜色/粗细）。

        优先取同行左侧文字；同行左侧无字则取上一行最后一段。
        返回 {"family", "size", "color", "bold", "italic"}。
        """
        fmt = {"family": "", "size": 10, "color": QColor(0, 0, 0),
               "bold": False, "italic": False}
        try:
            p = self.doc[page]
            lines = []
            for block in p.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if spans:
                        lines.append(spans)
            if not lines:
                return fmt

            # 找 pt 所在行（按 y 范围）
            target_idx = None
            for i, spans in enumerate(lines):
                y0 = min(s["bbox"][1] for s in spans)
                y1 = max(s["bbox"][3] for s in spans)
                if y0 - 3 <= pt.y() <= y1 + 3:
                    target_idx = i
                    break
            if target_idx is None:
                target_idx = min(
                    range(len(lines)),
                    key=lambda i: abs(min(s["bbox"][1] for s in lines[i]) - pt.y()))
            target = lines[target_idx]

            # 同行左侧文字
            left = [s for s in target if s["bbox"][2] <= pt.x() + 2]
            if left:
                span = left[-1]
            elif target_idx > 0:
                span = lines[target_idx - 1][-1]   # 上一行最后一段
            else:
                span = target[0]

            fam = self._map_pdf_font(span.get("font", ""))
            if fam:
                fmt["family"] = fam
            fmt["size"] = round(span.get("size", 10), 1)
            c = span.get("color", 0) & 0xFFFFFF
            fmt["color"] = QColor((c >> 16) & 255, (c >> 8) & 255, c & 255)
            fmt["bold"] = bool(span.get("flags", 0) & 16)
            fmt["italic"] = bool(span.get("flags", 0) & 2)
        except Exception:
            pass
        return fmt

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
                                      QPushButton, QHBoxLayout, QCheckBox)
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
            init_bold = existing.get("bold", False)
            init_italic = existing.get("italic", False)
        else:
            wx = int(pt.x() * self.page_view._zoom)
            wy = int(self.page_view._offsets[page] + pt.y() * self.page_view._zoom)
            init_text = ""
            fmt = self._detect_format_at(page, pt)
            init_family = fmt["family"]
            init_size = int(round(fmt["size"]))
            cur_color = fmt["color"]
            init_bold = fmt["bold"]
            init_italic = fmt["italic"]

        box = QWidget(self.page_view)
        box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        box.setObjectName("inlineTextBar")
        box.setStyleSheet(
            "#inlineTextBar { background: #eceff3; border: 1px solid #c8cdd4;"
            " border-radius: 6px; }")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(6, 6, 6, 6)
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

        bold_check = QCheckBox(i18n.tr("bold"))
        bold_check.setChecked(init_bold)

        italic_check = QCheckBox(i18n.tr("italic"))
        italic_check.setChecked(init_italic)

        btn_ok = QPushButton("确定")
        btn_cancel = QPushButton("取消")
        lay.addWidget(edit, 1)
        lay.addWidget(font_combo)
        lay.addWidget(size_spin)
        lay.addWidget(btn_color)
        lay.addWidget(bold_check)
        lay.addWidget(italic_check)
        lay.addWidget(btn_ok)
        lay.addWidget(btn_cancel)
        box.setFixedWidth(760)
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
            bold = bold_check.isChecked()
            italic = italic_check.isChecked()
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
                existing["bold"] = bold
                existing["italic"] = italic
                self.modified = True
                self._refresh_objects()
                self.page_view.select(oid)
            else:
                self._add_text_object(text, page, pt, family, size, color, bold,
                                      italic, keep_mode=True)

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

    def _add_text_object(self, text, page, pt, fontfamily="", fontsize=12, color=None,
                         bold=False, italic=False, keep_mode=False):
        rect = self._measure_text_rect(text, fontfamily, fontsize, bold, italic)
        rect.moveTo(pt.x(), pt.y())
        self._obj_counter += 1
        self.objects.append({
            "id": self._obj_counter, "page": page,
            "rect": rect,
            "text": text, "color": color if color is not None else QColor(0, 0, 0),
            "fontsize": fontsize, "fontfamily": fontfamily, "bold": bold,
            "italic": italic, "kind": "text",
        })
        self.modified = True
        if not keep_mode:
            self.set_mode("view")
        self._refresh_objects()
        self.page_view.select(self._obj_counter)

    @staticmethod
    def _measure_text_rect(text, fontfamily, fontsize, bold, italic=False):
        """根据文字内容测量单行框大小（返回 PDF 坐标 QRectF）。"""
        from PySide6.QtGui import QFont, QFontMetrics
        f = QFont(fontfamily if fontfamily else "Microsoft YaHei UI")
        f.setPixelSize(max(10, int(fontsize)))
        f.setBold(bold)
        f.setItalic(italic)
        fm = QFontMetrics(f)
        w = fm.horizontalAdvance(text) + 12
        h = fm.height() + 6
        return QRectF(0, 0, max(30.0, float(w)), max(16.0, float(h)))

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
