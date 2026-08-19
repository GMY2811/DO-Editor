"""单个文档的视图：连续滚动页面 + 缩略图侧栏 + 编辑逻辑。"""
import os
import pymupdf
from PySide6.QtCore import (Qt, QSize, QRect, QRectF, QPointF, Signal, QEvent,
                            QTimer, QItemSelectionModel)
from PySide6.QtGui import (QImage, QPixmap, QIcon, QColor, QPainter, QPen, QFont,
                           QShortcut, QKeySequence, QCursor)
from PySide6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QSplitter,
                               QScrollArea, QListWidget, QListWidgetItem,
                               QTabWidget, QStackedWidget, QFrame, QPushButton,
                               QLabel, QLineEdit, QFileDialog, QMessageBox,
                               QInputDialog, QApplication, QMenu, QColorDialog,
                               QGraphicsDropShadowEffect, QAbstractItemView,
                               QStyledItemDelegate, QStyleOptionViewItem, QStyle)
from PySide6.QtPrintSupport import QPrinter, QPrintDialog

import backend
import i18n
from page_view import PageView
from sign_dialog import (SignatureDialog, SignatureLibraryDialog,
                         SignatureFontComboBox, qimage_to_png_bytes)

MODE_DEFS = [
    ("view",         "选择",     "view",  "select"),
    ("text_select",  "快捷复制", "rect",  "text_select"),
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
ANNOTATION_OBJECT_KINDS = {
    "highlight", "underline", "strikeout", "rect", "line", "ink"
}


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

        self._font_combo = SignatureFontComboBox()
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


class ThumbnailListWidget(QListWidget):
    """支持内部拖放并在落下后报告完整页面顺序的缩略图列表。"""
    orderChanged = Signal(object)

    def dropEvent(self, event):
        before = [
            self.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.count())
        ]
        super().dropEvent(event)
        after = [
            self.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.count())
        ]
        if event.isAccepted() and after != before:
            self.orderChanged.emit(after)


class ThumbnailDelegate(QStyledItemDelegate):
    """将页码以半透明标签覆盖在缩略图底部。"""

    PAGE_BAND_COLOR = QColor(248, 250, 252, 112)
    PAGE_TEXT_COLOR = QColor(156, 163, 175, 255)

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        page_number = opt.text
        opt.text = ""
        opt.features &= ~QStyleOptionViewItem.ViewItemFeature.HasDisplay

        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem,
                          opt, painter, opt.widget)

        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if not isinstance(icon, QIcon) or icon.isNull() or not page_number:
            return
        actual = icon.actualSize(opt.decorationSize)
        icon_rect = QRect(
            opt.rect.center().x() - actual.width() // 2,
            opt.rect.center().y() - actual.height() // 2,
            actual.width(), actual.height())
        band_height = max(22, min(30, round(actual.height() * 0.18)))
        band_rect = QRect(icon_rect.left(), icon_rect.bottom() - band_height + 1,
                          icon_rect.width(), band_height)

        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.PAGE_BAND_COLOR)
        painter.drawRect(band_rect)
        font = painter.font()
        font.setPixelSize(max(14, min(18, round(actual.width() * 0.125))))
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(self.PAGE_TEXT_COLOR)
        painter.drawText(band_rect, Qt.AlignmentFlag.AlignCenter, page_number)
        painter.restore()


class DocumentView(QWidget):
    statusMessage = Signal(str, int)
    titleChanged = Signal(str)
    pageChanged = Signal(int, int)
    openRequested = Signal()
    securityChanged = Signal()
    ocrRequested = Signal(int)

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
        self.pending_note_text = None
        self.mode_actions = {}
        self._search_results = []
        self._search_index = 0
        self._source_encrypted = False
        self._security_mode = "none"
        self._security_options = None
        self._open_password = None
        self._auth_level = 0
        self._build_ui()

    # ================= UI =================
    def _build_ui(self):
        self.side_tabs = QTabWidget()
        self.side_tabs.setObjectName("sidePanel")
        # 高 DPI 下逻辑宽度会被成倍放大。首次打开使用紧凑宽度，之后
        # 允许用户拖动调整并在本次会话内记住该宽度。
        self._sidebar_default_width = 104
        self._sidebar_last_width = self._sidebar_default_width
        self.side_tabs.setMinimumWidth(88)
        self.side_tabs.setMaximumWidth(180)
        self.side_tabs.setVisible(False)

        self.thumb_list = ThumbnailListWidget()
        self.thumb_list.setObjectName("thumbnailList")
        self.thumb_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumb_list.setFlow(QListWidget.Flow.TopToBottom)
        self.thumb_list.setWrapping(False)
        self.thumb_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._thumbnail_aspect = 1.414
        self._thumbnail_source_width = 150
        self.thumb_list.setIconSize(QSize(64, 91))
        self.thumb_list.setGridSize(QSize(86, 105))
        self.thumb_list.setItemDelegate(ThumbnailDelegate(self.thumb_list))
        self.thumb_list.setMovement(QListWidget.Movement.Snap)
        self.thumb_list.setDragEnabled(True)
        self.thumb_list.setAcceptDrops(True)
        self.thumb_list.setDropIndicatorShown(True)
        self.thumb_list.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove)
        self.thumb_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.thumb_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.thumb_list.itemClicked.connect(self._on_thumb_clicked)
        self.thumb_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumb_list.customContextMenuRequested.connect(
            self._on_thumb_context_menu)
        self.thumb_list.orderChanged.connect(self._reorder_pages)
        self._thumb_delete_shortcut = QShortcut(
            QKeySequence(Qt.Key.Key_Delete), self.thumb_list)
        self._thumb_delete_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._thumb_delete_shortcut.activated.connect(
            self._delete_selected_thumbnails)

        self.side_tabs.addTab(self.thumb_list, i18n.tr("pages"))
        self.side_tabs.setTabBarAutoHide(True)

        self.page_view = PageView()
        self._content_delete_shortcut = QShortcut(
            QKeySequence(Qt.Key.Key_Delete), self.page_view)
        self._content_delete_shortcut.setContext(
            Qt.ShortcutContext.WidgetShortcut)
        self._content_delete_shortcut.activated.connect(self.delete_selected)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("documentScroll")
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
        mark = QLabel()
        mark.setObjectName("startAppIcon")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(86, 86)
        app_icon_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "app-icon.png")
        app_icon = QPixmap(app_icon_path)
        if not app_icon.isNull():
            mark.setPixmap(app_icon.scaled(
                82, 82, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        mark_row.addWidget(mark)
        mark_row.addStretch(1)
        card_lay.addLayout(mark_row)

        self.start_title = QLabel(i18n.tr("app_name"))
        self.start_title.setObjectName("startTitle")
        self.start_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_lay.addWidget(self.start_title)

        self.start_subtitle = QLabel(i18n.tr("about_summary"))
        self.start_subtitle.setObjectName("startSubtitle")
        self.start_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_lay.addWidget(self.start_subtitle)
        card_lay.addSpacing(8)

        open_row = QHBoxLayout()
        open_row.addStretch(1)
        self.start_open_btn = QPushButton(i18n.tr("start_open"))
        self.start_open_btn.setObjectName("startOpenButton")
        self.start_open_btn.setDefault(True)
        self.start_open_btn.clicked.connect(self.openRequested.emit)
        open_row.addWidget(self.start_open_btn)
        open_row.addStretch(1)
        card_lay.addLayout(open_row)

        self.start_hint = QLabel(i18n.tr("start_hint"))
        self.start_hint.setObjectName("startHint")
        self.start_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_lay.addWidget(self.start_hint)

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

        self._splitter = QSplitter()
        self._splitter.setObjectName("documentSplitter")
        self._splitter.setHandleWidth(1)
        self._splitter.addWidget(self.side_tabs)
        self._splitter.addWidget(self.workspace_stack)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.splitterMoved.connect(self._remember_sidebar_width)
        self._splitter.splitterMoved.connect(
            lambda _pos, _index: self._schedule_thumbnail_resize())
        self._sidebar_fit_timer = QTimer(self)
        self._sidebar_fit_timer.setSingleShot(True)
        self._sidebar_fit_timer.setInterval(32)
        self._sidebar_fit_timer.timeout.connect(
            self._fit_width_after_sidebar_resize)
        self._splitter.splitterMoved.connect(
            lambda _pos, _index: self._schedule_content_fit())

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._splitter)

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
    def load(self, path, password=None):
        try:
            doc = backend.open_pdf(path, password)
        except (backend.PdfPasswordRequired, backend.PdfPasswordInvalid):
            raise
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开该文件：\n{e}")
            return False
        if self.doc:
            self.doc.close()
        self.doc = doc
        self.file_path = path
        self.modified = False
        self._source_encrypted = bool(
            getattr(doc, "_do_was_encrypted", False))
        self._security_mode = "keep" if self._source_encrypted else "none"
        self._security_options = None
        self._open_password = password
        self._auth_level = int(getattr(doc, "_do_auth_level", 0))
        self.objects = []
        self._obj_counter = 0
        self.titleChanged.emit(os.path.basename(path))
        self.workspace_stack.setCurrentWidget(self.scroll)
        self._refresh()
        self._rebuild_thumbnails()
        self.fit_width()
        self.set_mode("view")
        self.securityChanged.emit()
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
        self.pending_note_text = None
        self._source_encrypted = False
        self._security_mode = "none"
        self._security_options = None
        self._open_password = None
        self._auth_level = 0
        self.titleChanged.emit(i18n.tr("untitled"))
        self.page_view.set_document(None, 1.0, 1.0)
        self.thumb_list.clear()
        self.workspace_stack.setCurrentIndex(0)
        self.pageChanged.emit(0, 0)
        self.securityChanged.emit()

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
            save_args = {"garbage": 3, "deflate": True}
            reopen_password = self._open_password
            if self._security_mode == "aes256":
                options = self._security_options or {}
                save_args.update({
                    "encryption": pymupdf.PDF_ENCRYPT_AES_256,
                    "owner_pw": options.get("owner_pw", ""),
                    "user_pw": options.get("user_pw", ""),
                    "permissions": int(options.get("permissions", 0)),
                })
                # 保存后按普通用户身份重开并立即执行权限限制。只有用户
                # 明确输入所有者密码打开文档时，才进入不受限管理模式。
                reopen_password = options.get("user_pw") or None
            elif self._security_mode == "keep":
                save_args["encryption"] = pymupdf.PDF_ENCRYPT_KEEP
            else:
                save_args["encryption"] = pymupdf.PDF_ENCRYPT_NONE
                reopen_password = None
            self.doc.save(tmp, **save_args)
            self.doc.close()
            os.replace(tmp, path)
            self.doc = backend.open_pdf(path, reopen_password)
            self.file_path = path
            self.modified = False
            self._source_encrypted = bool(
                getattr(self.doc, "_do_was_encrypted", False))
            self._security_mode = "keep" if self._source_encrypted else "none"
            self._security_options = None
            self._open_password = reopen_password
            self._auth_level = int(
                getattr(self.doc, "_do_auth_level", 0))
            self.titleChanged.emit(os.path.basename(path))
            self._refresh()
            self.securityChanged.emit()
            self.statusMessage.emit("已保存", 2000)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：\n{e}")

    def set_pdf_encryption(self, user_pw, owner_pw, permissions):
        self._security_mode = "aes256"
        self._security_options = {
            "user_pw": user_pw,
            "owner_pw": owner_pw,
            "permissions": int(permissions),
        }
        self.modified = True
        self.securityChanged.emit()

    def remove_pdf_encryption(self):
        self._security_mode = "none"
        self._security_options = None
        self.modified = True
        self.securityChanged.emit()

    def security_status(self):
        if self._security_mode == "aes256":
            return "pending_encrypt"
        if self._security_mode == "none" and self._source_encrypted:
            return "pending_remove"
        return "encrypted" if self._source_encrypted else "plain"

    def permission_allowed(self, permission):
        """执行 PDF 权限；所有者认证可管理全部功能。"""
        if self.doc is None:
            return False
        if self._auth_level & 4:
            return True
        if self._security_mode == "aes256" and self._security_options:
            permissions = int(self._security_options.get("permissions", 0))
            return bool(permissions & permission)
        if self._source_encrypted:
            return bool(int(self.doc.permissions) & permission)
        return True

    def _require_permission(self, permission, operation):
        if self.permission_allowed(permission):
            return True
        self.statusMessage.emit(f"文档安全设置禁止{operation}", 4000)
        return False

    def _bake_objects(self):
        for obj in self.objects:
            page = self.doc[obj["page"]]
            r = obj["rect"]
            fr = pymupdf.Rect(r.x(), r.y(), r.right(), r.bottom())
            kind = obj.get("kind")
            if kind == "note":
                c = obj.get("color")
                rgb = (c.redF(), c.greenF(), c.blueF()) if c else None
                backend.add_note(
                    page, (r.x(), r.y()), obj.get("text", ""), rgb)
            elif kind in ANNOTATION_OBJECT_KINDS:
                c = QColor(obj.get("color") or QColor(200, 30, 30))
                rgb = (c.redF(), c.greenF(), c.blueF())
                if kind == "highlight":
                    backend.add_highlight(page, fr, rgb)
                elif kind == "underline":
                    backend.add_underline(page, fr, rgb)
                elif kind == "strikeout":
                    backend.add_strikeout(page, fr, rgb)
                elif kind == "rect":
                    backend.add_rect(page, fr, rgb)
                else:
                    points = [
                        (r.x() + float(x) * r.width(),
                         r.y() + float(y) * r.height())
                        for x, y in obj.get("points", [])
                    ]
                    if kind == "line" and len(points) >= 2:
                        backend.add_line(page, points[0], points[-1], rgb)
                    elif kind == "ink" and len(points) >= 2:
                        backend.add_ink(page, points, rgb)
            elif kind == "text":
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
            item = self.thumb_list.item(pno)
            modifiers = QApplication.keyboardModifiers()
            preserve_multi = (
                len(self.thumb_list.selectedItems()) > 1 or
                bool(modifiers & (Qt.KeyboardModifier.ControlModifier |
                                  Qt.KeyboardModifier.ShiftModifier)))
            if item is not None and preserve_multi:
                self.thumb_list.setCurrentItem(
                    item, QItemSelectionModel.SelectionFlag.NoUpdate)
            else:
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

    def fit_width(self, preserve_position=False):
        if self.doc is None:
            return
        keep = self.page_view.current_page()
        page_offset = None
        if preserve_position:
            old_page_top = self.page_view.scroll_to_page(keep)
            old_scroll = self.scroll.verticalScrollBar().value()
            page_offset = max(0.0, old_scroll - old_page_top) / max(
                0.1, self.zoom)
        w, _h = backend.page_size(self.doc, 0)
        vw = max(200, self.scroll.viewport().width() - 40)
        self._set_zoom(vw / w, page_offset)

    def _set_zoom(self, z, page_offset=None):
        keep = self.page_view.current_page()
        self.zoom = max(0.1, min(10.0, z))
        self.page_view.set_zoom(self.zoom)
        self.page_view.set_objects(self._objects_for_current_page())
        if self.doc is not None:
            target = self.page_view.scroll_to_page(keep)
            if page_offset is not None:
                target += int(page_offset * self.zoom)
            self.scroll.verticalScrollBar().setValue(target)

    def toggle_sidebar(self):
        self.set_sidebar_visible(self.side_tabs.isHidden())

    def set_sidebar_visible(self, visible):
        """切换缩略图栏，并按变化后的文档视口重新适合宽度。"""
        visible = bool(visible)
        changed = (not self.side_tabs.isHidden()) != visible
        if not visible and not self.side_tabs.isHidden():
            self._sidebar_last_width = max(
                self.side_tabs.minimumWidth(), self.side_tabs.width())
        self.side_tabs.setVisible(visible)
        if visible:
            target = max(
                self.side_tabs.minimumWidth(),
                min(self.side_tabs.maximumWidth(), self._sidebar_last_width))
            self._set_sidebar_splitter_width(target)
            QTimer.singleShot(
                0, lambda w=target: self._set_sidebar_splitter_width(w))
            QTimer.singleShot(0, self._update_thumbnail_layout)
        if changed and self.doc is not None:
            # 0ms 处理当前布局，80ms 覆盖 Windows/高 DPI 下稍晚完成的
            # splitter 尺寸更新，保证页面最终使用真实剩余宽度。
            QTimer.singleShot(0, self.fit_width)
            QTimer.singleShot(80, self.fit_width)

    def _set_sidebar_splitter_width(self, width):
        if self.side_tabs.isHidden():
            return
        total = max(300, self._splitter.width())
        self._splitter.setSizes([int(width), max(200, total - int(width))])

    def _remember_sidebar_width(self, _pos, index):
        if index == 1 and not self.side_tabs.isHidden():
            width = self.side_tabs.width()
            if width >= self.side_tabs.minimumWidth():
                self._sidebar_last_width = min(
                    self.side_tabs.maximumWidth(), width)

    def _schedule_thumbnail_resize(self):
        """合并分割条拖动事件，避免连续拖动时重复刷新布局。"""
        if getattr(self, "_thumbnail_resize_pending", False):
            return
        self._thumbnail_resize_pending = True
        QTimer.singleShot(0, self._update_thumbnail_layout)

    def _schedule_content_fit(self):
        """节流侧边栏拖动触发的正文适宽，兼顾实时反馈和渲染性能。"""
        if self.doc is None or self.side_tabs.isHidden():
            return
        if not self._sidebar_fit_timer.isActive():
            self._sidebar_fit_timer.start()

    def _fit_width_after_sidebar_resize(self):
        if self.doc is not None and not self.side_tabs.isHidden():
            self.fit_width(preserve_position=True)

    def _update_thumbnail_layout(self):
        """按侧边栏实际可用宽度等比例调整缩略图和项目网格。"""
        self._thumbnail_resize_pending = False
        viewport_width = self.thumb_list.viewport().width()
        if viewport_width <= 0:
            viewport_width = self.side_tabs.width() - 2

        size, grid = self._thumbnail_layout_for_width(viewport_width)
        if self.thumb_list.iconSize() != size:
            self.thumb_list.setIconSize(size)
        if self.thumb_list.gridSize() != grid:
            self.thumb_list.setGridSize(grid)
        self.thumb_list.scheduleDelayedItemsLayout()

    def _thumbnail_layout_for_width(self, viewport_width):
        """返回指定可用宽度下的等比例缩略图尺寸与项目尺寸。"""

        # 为滚动条及左右留白预留空间；源图宽度也是清晰度上限。
        icon_width = max(
            52, min(self._thumbnail_source_width, viewport_width - 14))
        icon_height = max(1, round(icon_width * self._thumbnail_aspect))
        grid_width = max(icon_width + 8, viewport_width)
        # 页码覆盖在缩略图内部，只需给选中框和项目上下留少量空间。
        grid_height = icon_height + 14

        return QSize(icon_width, icon_height), QSize(grid_width, grid_height)

    # ================= 侧边栏 =================
    def _rebuild_thumbnails(self):
        self.thumb_list.clear()
        if self.doc is None:
            return
        self._update_thumbnail_layout()
        for i in range(len(self.doc)):
            page = self.doc[i]
            w = max(1.0, page.rect.width)
            h = max(1.0, page.rect.height)
            source_height = round(
                self._thumbnail_source_width * self._thumbnail_aspect)
            scale = min(self._thumbnail_source_width / w, source_height / h)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format.Format_RGB888).copy()
            # 明确为选中状态提供同一张原色图。若只传入普通 QIcon，
            # Windows/Qt 会自动生成带蓝色蒙层的 Selected pixmap。
            thumb_pixmap = QPixmap.fromImage(img)
            thumb_icon = QIcon()
            for mode in (QIcon.Mode.Normal, QIcon.Mode.Active,
                         QIcon.Mode.Selected):
                thumb_icon.addPixmap(
                    thumb_pixmap, mode, QIcon.State.Off)
                thumb_icon.addPixmap(
                    thumb_pixmap, mode, QIcon.State.On)
            item = QListWidgetItem(thumb_icon, f"{i + 1}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.thumb_list.addItem(item)

    def _on_thumb_clicked(self, item):
        pno = item.data(Qt.ItemDataRole.UserRole)
        if pno is not None:
            self.show_page(int(pno))

    def _on_thumb_context_menu(self, pos):
        """缩略图右键菜单：单选删除本页，多选删除所有选中页。"""
        item = self.thumb_list.itemAt(pos)
        if item is None or self.doc is None:
            return
        # 右键点到未选页时按常见文件列表行为改为仅选中该页；右键点到
        # 已选集合中的任一页则保留整个多选集合。
        if not item.isSelected():
            self.thumb_list.clearSelection()
            item.setSelected(True)
            self.thumb_list.setCurrentItem(item)
        pages = self._selected_thumbnail_pages()
        if not pages:
            return
        menu = QMenu(self.thumb_list)
        label = (i18n.tr("delete_this_page") if len(pages) == 1 else
                 i18n.tr("delete_selected_pages"))
        menu.addAction(label, lambda checked=False, p=pages: self.delete_pages(p))
        menu.exec(self.thumb_list.viewport().mapToGlobal(pos))

    def _selected_thumbnail_pages(self):
        """返回侧边栏中选中的零基页码。"""
        return sorted({
            int(selected.data(Qt.ItemDataRole.UserRole))
            for selected in self.thumb_list.selectedItems()
            if selected.data(Qt.ItemDataRole.UserRole) is not None
        })

    def _delete_selected_thumbnails(self, confirm=True):
        """Delete 键与右键菜单共用的侧边栏批量删除入口。"""
        pages = self._selected_thumbnail_pages()
        if not pages:
            current = self.thumb_list.currentItem()
            if current is not None:
                page = current.data(Qt.ItemDataRole.UserRole)
                if page is not None:
                    pages = [int(page)]
        if not pages:
            return False
        return self.delete_pages(pages, confirm=confirm)

    def _reorder_pages(self, order):
        """按缩略图的新顺序重排 PDF，并同步页面对象和当前页。"""
        if self.doc is None:
            return False
        order = [int(page) for page in order]
        expected = list(range(len(self.doc)))
        if len(order) != len(expected) or sorted(order) != expected:
            self._rebuild_thumbnails()
            return False
        if order == expected:
            return True
        if not self._require_permission(pymupdf.PDF_PERM_MODIFY, "调整页面顺序"):
            self._rebuild_thumbnails()
            return False

        old_current = self.page_view.current_page()
        old_to_new = {old_page: new_page
                      for new_page, old_page in enumerate(order)}
        try:
            self.doc.select(order)
        except Exception as exc:
            self._rebuild_thumbnails()
            QMessageBox.critical(
                self, i18n.tr("error"), f"无法调整页面顺序：\n{exc}")
            return False

        for obj in self.objects:
            obj["page"] = old_to_new.get(obj["page"], obj["page"])
        target = old_to_new.get(old_current, 0)
        self.modified = True
        self._refresh()
        self._rebuild_thumbnails()
        self.show_page(target)
        self.thumb_list.setCurrentRow(target)
        self.pageChanged.emit(target, len(self.doc))
        self.statusMessage.emit("页面顺序已调整", 3000)
        return True

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
        if not self._require_permission(pymupdf.PDF_PERM_COPY, "复制内容"):
            return
        pno = self.page_view.current_page()
        text = backend.extract_text(self.doc, pno)
        if text:
            QApplication.clipboard().setText(text)
            self.statusMessage.emit(
                f"已复制第 {pno + 1} 页全部文字（{len(text)} 字）", 3000)
        else:
            self.statusMessage.emit("当前页没有可复制的文字", 3000)

    def _paste_target(self, global_pos=None):
        """取得右键位置或当前鼠标位置，仅接受页面内容内的坐标。"""
        if self.doc is None:
            return None
        if global_pos is None:
            global_pos = QCursor.pos()
        local = self.page_view.mapFromGlobal(global_pos)
        if not self.page_view.rect().contains(local):
            return None
        return self.page_view.pdf_point_at(local)

    def paste_text(self, page=None, pt=None):
        """将剪贴板文字直接粘贴到给定位置或当前鼠标位置。"""
        if not self._require_permission(pymupdf.PDF_PERM_MODIFY, "编辑文档"):
            return
        text = QApplication.clipboard().text().strip()
        if not text:
            self.statusMessage.emit("剪贴板没有文字", 3000)
            return
        if page is None or pt is None:
            target = self._paste_target()
            if target is None:
                self.statusMessage.emit(
                    "请将鼠标光标移到页面上的粘贴起始位置", 4000)
                return
            page, pt = target
        self.pending_paste_text = None
        self._add_text_object(text, int(page), QPointF(pt))
        self.statusMessage.emit(
            f"已在第 {int(page) + 1} 页粘贴文字", 3000)

    def start_note(self, page=None, pt=None):
        """输入便笺内容；有坐标时直接添加，否则进入页面定位模式。"""
        if not self._require_permission(
                pymupdf.PDF_PERM_ANNOTATE, i18n.tr("annotation_title")):
            return False
        text, ok = QInputDialog.getMultiLineText(
            self, i18n.tr("annotation_title"), i18n.tr("annotation_prompt"))
        text = text.strip()
        if not ok or not text:
            return False
        if page is not None and pt is not None:
            return self._add_note_at(text, int(page), QPointF(pt))
        self.pending_note_text = text
        self.current_mode = "note"
        self._check_none()
        self.page_view.set_mode("point")
        self.statusMessage.emit(i18n.tr("annotation_place"), 6000)
        return True

    def _add_note_at(self, text, page, pt):
        """创建可移动便笺对象，保存时再写入 PDF 原生批注。"""
        if self.doc is None or not text.strip():
            return False
        if not self._require_permission(
                pymupdf.PDF_PERM_ANNOTATE, i18n.tr("annotation_title")):
            return False
        page = max(0, min(int(page), len(self.doc) - 1))
        page_rect = self.doc[page].rect
        marker_size = 16.0
        x = max(page_rect.x0, min(page_rect.x1 - marker_size, pt.x()))
        y = max(page_rect.y0, min(page_rect.y1 - marker_size, pt.y()))
        note_color = QColor("#ff9f0a")
        image = self._note_marker_image(note_color)
        self._obj_counter += 1
        self.objects.append({
            "id": self._obj_counter,
            "page": page,
            "rect": QRectF(x, y, marker_size, marker_size),
            "img": image,
            "kind": "note",
            "text": text.strip(),
            "color": note_color,
        })
        self.pending_note_text = None
        self.modified = True
        self.set_mode("view")
        self._refresh_objects()
        self.page_view.select(self._obj_counter)
        self.statusMessage.emit(
            f"已在第 {page + 1} 页添加批注，可拖动调整位置", 4000)
        return True

    @staticmethod
    def _note_marker_image(color):
        """生成简洁、高清的圆形批注标记。"""
        # 逻辑尺寸与页面中的实际显示尺寸一致，不再从 24px 缩小到 18px。
        dpr = 4
        logical = 16
        image = QImage(logical * dpr, logical * dpr,
                       QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 先在物理像素画布上按 DPR 放大绘制，结束后再标记 DPR。
        # 若提前 setDevicePixelRatio()，QPainter 已自动使用逻辑坐标，
        # 再 scale(dpr) 会重复放大并把图标裁切成右下角色块。
        painter.scale(dpr, dpr)
        fill = QColor(color) if QColor(color).isValid() else QColor("#ff9f0a")
        fill.setAlpha(255)
        # 备用位图与页面上的 Win10 扁平矢量图标保持一致。
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawEllipse(QRectF(1.0, 1.0, 14.0, 14.0))

        # 不依赖字体绘制信息符号，在任何 DPI 下都保持清晰。
        ink = QColor(255, 255, 255, 245)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ink)
        painter.drawEllipse(QRectF(7.2, 4.4, 1.6, 1.6))
        painter.setPen(QPen(ink, 1.65, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(8.0, 8.0), QPointF(8.0, 12.0))
        painter.end()
        image.setDevicePixelRatio(dpr)
        return image

    # ================= 编辑 =================
    def _edit_rgb(self):
        return (self.edit_color.redF(), self.edit_color.greenF(), self.edit_color.blueF())

    def _clamp_rect(self, page, r):
        pr = self.doc[page].rect
        return pymupdf.Rect(max(pr.x0, r.x0), max(pr.y0, r.y0),
                            min(pr.x1, r.x1), min(pr.y1, r.y1))

    def _on_rect(self, page, rect):
        if self.current_mode == "text_select":
            if not self._require_permission(pymupdf.PDF_PERM_COPY, "复制内容"):
                return
        elif self.current_mode == "replace_text":
            if not self._require_permission(pymupdf.PDF_PERM_MODIFY, "编辑文档"):
                return
        elif not self._require_permission(
                pymupdf.PDF_PERM_ANNOTATE, "添加批注"):
            return
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
        m = self.current_mode
        if m == "highlight":
            color = QColor("#ffd60a")
        elif m in ("underline", "strikeout", "rect"):
            color = QColor(self.edit_color)
        else:
            return
        self._add_annotation_object(
            m, page, QRectF(r.x0, r.y0, r.width, r.height), color)

    def _on_line(self, page, p1, p2):
        if not self._require_permission(pymupdf.PDF_PERM_ANNOTATE, "添加批注"):
            return
        if self.current_mode != "line":
            return
        self._add_annotation_object(
            "line", page, self._points_bounding_rect([p1, p2]),
            QColor(self.edit_color), [p1, p2])

    def _on_ink(self, page, points):
        if not self._require_permission(pymupdf.PDF_PERM_ANNOTATE, "添加批注"):
            return
        if self.current_mode != "ink":
            return
        if len(points) < 2:
            return
        self._add_annotation_object(
            "ink", page, self._points_bounding_rect(points),
            QColor(self.edit_color), points, width=2.0)

    @staticmethod
    def _points_bounding_rect(points):
        xs = [p.x() for p in points]
        ys = [p.y() for p in points]
        return QRectF(min(xs), min(ys), max(1.0, max(xs) - min(xs)),
                      max(1.0, max(ys) - min(ys)))

    def _add_annotation_object(self, kind, page, rect, color, points=None,
                               width=1.5):
        """创建保存前可选、可移动、可缩放的标注对象。"""
        rect = QRectF(rect).normalized()
        if rect.width() < 1.0:
            rect.setWidth(1.0)
        if rect.height() < 1.0:
            rect.setHeight(1.0)
        normalized_points = []
        if points:
            normalized_points = [
                ((p.x() - rect.x()) / rect.width(),
                 (p.y() - rect.y()) / rect.height())
                for p in points
            ]
        self._obj_counter += 1
        self.objects.append({
            "id": self._obj_counter,
            "page": int(page),
            "rect": rect,
            "kind": kind,
            "color": QColor(color),
            "width": float(width),
            "points": normalized_points,
        })
        self.modified = True
        self.set_mode("view")
        self._refresh_objects()
        self.page_view.select(self._obj_counter)
        self.statusMessage.emit(
            "标注已创建，可拖动或缩放，双击修改颜色，Delete 删除", 6000)

    def _on_point(self, page, pt):
        permission = (pymupdf.PDF_PERM_ANNOTATE
                      if self.current_mode in ("sign", "note") else
                      pymupdf.PDF_PERM_MODIFY)
        operation = ("添加签名" if self.current_mode == "sign" else
                     "添加批注" if self.current_mode == "note" else "编辑文档")
        if not self._require_permission(permission, operation):
            return
        m = self.current_mode
        if m == "text":
            self._start_inline_text(page, pt)
        elif m == "image" and self.pending_image_qimg is not None:
            self._add_object(self.pending_image_qimg, "image", page, pt, 160.0)
            self.pending_image_qimg = None
        elif m == "sign" and self.pending_sign_qimg is not None:
            self._add_object(self.pending_sign_qimg, "signature", page, pt, 180.0)
            self.pending_sign_qimg = None
        elif m == "note" and self.pending_note_text:
            self._add_note_at(self.pending_note_text, page, pt)
        elif m == "paste" and self.pending_paste_text:
            self._add_text_object(self.pending_paste_text, page, pt)
            self.pending_paste_text = None

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
        if not self._require_permission(pymupdf.PDF_PERM_MODIFY, "编辑文档"):
            return
        """在页面位置显示 inline 文字输入框（字体/字号/颜色），oid 非空则为编辑模式。"""
        from PySide6.QtWidgets import (QTextEdit, QFontComboBox, QSpinBox,
                                      QPushButton, QHBoxLayout, QVBoxLayout,
                                      QCheckBox)
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
        bar_shadow = QGraphicsDropShadowEffect(box)
        bar_shadow.setBlurRadius(22)
        bar_shadow.setOffset(0, 5)
        bar_shadow.setColor(QColor(0, 0, 0, 72))
        box.setGraphicsEffect(bar_shadow)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        input_row = QHBoxLayout()
        input_row.setSpacing(7)
        edit = QLineEdit(init_text)
        edit.setObjectName("inlineTextInput")
        edit.setPlaceholderText("输入文字")
        edit.setMinimumWidth(360)
        font_combo = SignatureFontComboBox()
        font_combo.setObjectName("inlineTextFont")
        font_combo.setFixedWidth(176)
        if init_family:
            font_combo.setCurrentFont(QFont(init_family))
        size_spin = QSpinBox()
        size_spin.setObjectName("inlineTextSize")
        size_spin.setRange(6, 72)
        size_spin.setValue(init_size)
        size_spin.setSuffix(" pt")
        size_spin.setFixedWidth(72)

        color_state = {"color": QColor(cur_color)}
        btn_color = QPushButton("颜色")
        btn_color.setObjectName("inlineTextColor")
        btn_color.setFixedWidth(62)
        btn_color.clicked.connect(lambda: self._pick_text_color(color_state, btn_color))
        self._style_color_btn(btn_color, color_state["color"])

        bold_check = QCheckBox(i18n.tr("bold"))
        bold_check.setObjectName("inlineTextToggle")
        bold_check.setChecked(init_bold)

        italic_check = QCheckBox(i18n.tr("italic"))
        italic_check.setObjectName("inlineTextToggle")
        italic_check.setChecked(init_italic)

        btn_ok = QPushButton("确定")
        btn_ok.setObjectName("inlineTextOk")
        btn_ok.setDefault(True)
        btn_ok.setFixedWidth(68)
        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("inlineTextCancel")
        btn_cancel.setFixedWidth(68)

        input_row.addWidget(edit, 1)
        input_row.addWidget(btn_ok)
        input_row.addWidget(btn_cancel)
        format_row = QHBoxLayout()
        format_row.setSpacing(7)
        format_row.addWidget(font_combo)
        format_row.addWidget(size_spin)
        format_row.addWidget(btn_color)
        format_row.addSpacing(4)
        format_row.addWidget(bold_check)
        format_row.addWidget(italic_check)
        format_row.addStretch(1)
        lay.addLayout(input_row)
        lay.addLayout(format_row)
        box.setFixedWidth(620)
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
        luminance = (0.299 * color.red() + 0.587 * color.green() +
                     0.114 * color.blue())
        text_color = "#111111" if luminance > 170 else "#ffffff"
        btn.setStyleSheet(
            f"background-color:{color.name()};color:{text_color};")

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
        if not (self.permission_allowed(pymupdf.PDF_PERM_MODIFY) or
                self.permission_allowed(pymupdf.PDF_PERM_ANNOTATE)):
            self.statusMessage.emit("文档安全设置禁止删除对象", 4000)
            return
        self.objects = [o for o in self.objects if o["id"] != oid]
        self.modified = True
        self._refresh_objects()
        self.page_view.update()

    def _on_object_double_clicked(self, oid):
        obj = self._find_object(oid)
        if obj is None:
            return
        if obj.get("kind") == "note":
            self._edit_note_object(oid)
            return
        if obj.get("kind") in ANNOTATION_OBJECT_KINDS:
            self._change_annotation_color(oid)
            return
        if obj.get("kind") != "text":
            return
        self._start_inline_text(
            obj["page"], QPointF(obj["rect"].x(), obj["rect"].y()), oid)

    def _edit_note_object(self, oid):
        obj = self._find_object(oid)
        if obj is None or obj.get("kind") != "note":
            return
        if not self._require_permission(
                pymupdf.PDF_PERM_ANNOTATE, i18n.tr("edit_annotation")):
            return
        text, ok = QInputDialog.getMultiLineText(
            self, i18n.tr("edit_annotation"), i18n.tr("annotation_prompt"),
            obj.get("text", ""))
        text = text.strip()
        if ok and text:
            obj["text"] = text
            self.modified = True
            self.page_view.select(oid)
            self.statusMessage.emit("批注内容已更新", 3000)

    def _edit_text_object(self, oid):
        obj = self._find_object(oid)
        if obj is None or obj.get("kind") != "text":
            return
        self._start_inline_text(
            obj["page"], QPointF(obj["rect"].x(), obj["rect"].y()), oid)

    def _change_text_color(self, oid):
        if not self._require_permission(pymupdf.PDF_PERM_MODIFY, "编辑文档"):
            return
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

    def _change_annotation_color(self, oid):
        if not self._require_permission(
                pymupdf.PDF_PERM_ANNOTATE, "修改批注"):
            return
        obj = self._find_object(oid)
        if obj is None or obj.get("kind") not in ANNOTATION_OBJECT_KINDS:
            return
        c = QColorDialog.getColor(obj.get("color") or QColor(self.edit_color),
                                  self, "选择标注颜色")
        if c.isValid():
            obj["color"] = QColor(c)
            self.edit_color = QColor(c)
            self.modified = True
            self._refresh_objects()
            self.page_view.select(oid)
            self.statusMessage.emit("标注颜色已更新", 3000)

    def _refresh_objects(self):
        self.page_view.set_objects(self._objects_for_current_page())

    def _on_object_changed(self, oid, rect):
        if not (self.permission_allowed(pymupdf.PDF_PERM_MODIFY) or
                self.permission_allowed(pymupdf.PDF_PERM_ANNOTATE)):
            self.statusMessage.emit("文档安全设置禁止移动或缩放对象", 4000)
            self._refresh_objects()
            return
        for o in self.objects:
            if o["id"] == oid:
                o["rect"] = rect
                break
        self.modified = True

    def _on_object_selected(self, oid):
        if oid is not None:
            obj = self._find_object(oid)
            if obj is not None and obj.get("kind") == "note":
                preview = obj.get("text", "").replace("\n", " ")
                if len(preview) > 40:
                    preview = preview[:40] + "…"
                self.statusMessage.emit(
                    f"批注：{preview}　拖动移动，双击编辑，Delete 删除", 7000)
            elif obj is not None and obj.get("kind") in ANNOTATION_OBJECT_KINDS:
                self.statusMessage.emit(
                    "拖动移动，拖动控制点缩放，双击改色，Delete 删除", 7000)
            else:
                self.statusMessage.emit(
                    "拖动移动，拖动角点缩放，Delete 删除", 6000)

    def delete_selected(self):
        self.delete_object(self.page_view.selected_id())

    def _on_context_menu(self, global_pos):
        menu = QMenu(self)
        oid = self.page_view.selected_id()
        sel_obj = self._find_object(oid) if oid is not None else None
        if self.doc is not None:
            can_copy = self.permission_allowed(pymupdf.PDF_PERM_COPY)
            can_modify = self.permission_allowed(pymupdf.PDF_PERM_MODIFY)
            can_annotate = self.permission_allowed(pymupdf.PDF_PERM_ANNOTATE)
            if self.page_view.has_selection():
                action = menu.addAction(
                    i18n.tr("copy_selected"), self.copy_selected_text)
                action.setEnabled(can_copy)
            action = menu.addAction(
                i18n.tr("select_text"), lambda: self.set_mode("text_select"))
            action.setEnabled(can_copy)
            action = menu.addAction(i18n.tr("copy_page"), self.copy_page_text)
            action.setEnabled(can_copy)
            target = self._paste_target(global_pos)
            action = menu.addAction(i18n.tr("paste_text"))
            if target is not None:
                page, point = target
                action.triggered.connect(
                    lambda _checked=False, p=page, pt=point:
                    self.paste_text(p, pt))
            action.setEnabled(can_modify)
            action = menu.addAction(i18n.tr("annotation"))
            if target is not None:
                page, point = target
                action.triggered.connect(
                    lambda _checked=False, p=page, pt=point:
                    self.start_note(p, pt))
            action.setEnabled(can_annotate)
            action = menu.addAction(i18n.tr("ocr_toolbar"))
            if target is not None:
                page, _point = target
                action.triggered.connect(
                    lambda _checked=False, p=page:
                    self.ocrRequested.emit(int(p)))
            action.setEnabled(can_copy and can_modify and target is not None)
            action = menu.addAction(i18n.tr("edit_color"), self.pick_edit_color)
            action.setEnabled(can_modify or can_annotate)
            action = menu.addAction(i18n.tr("image"))
            if target is not None:
                page, point = target
                action.triggered.connect(
                    lambda _checked=False, p=page, pt=point:
                    self.start_image(p, pt))
            action.setEnabled(can_modify and target is not None)
            menu.addSeparator()
        if sel_obj is not None:
            if sel_obj.get("kind") == "note":
                action = menu.addAction(
                    i18n.tr("edit_annotation"),
                    lambda: self._edit_note_object(oid))
                action.setEnabled(can_annotate)
                menu.addSeparator()
            elif sel_obj.get("kind") == "text":
                action = menu.addAction(
                    i18n.tr("edit_text"), lambda: self._edit_text_object(oid))
                action.setEnabled(can_modify)
                action = menu.addAction(
                    i18n.tr("change_color"), lambda: self._change_text_color(oid))
                action.setEnabled(can_modify)
                menu.addSeparator()
            elif sel_obj.get("kind") in ANNOTATION_OBJECT_KINDS:
                action = menu.addAction(
                    i18n.tr("change_color"),
                    lambda: self._change_annotation_color(oid))
                action.setEnabled(can_annotate)
                menu.addSeparator()
            action = menu.addAction(i18n.tr("delete_object"), self.delete_selected)
            action.setEnabled(can_modify or can_annotate)
        if self.pending_sign_qimg is not None or self.pending_image_qimg is not None \
                or self.pending_paste_text or self.pending_note_text:
            menu.addAction(i18n.tr("cancel_place"), self._cancel_placement)
        menu.addSeparator()
        menu.addAction(i18n.tr("fit_width2"), self.fit_width)
        if menu.actions():
            menu.exec(global_pos)

    def copy_selected_text(self):
        if not self._require_permission(pymupdf.PDF_PERM_COPY, "复制内容"):
            return
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
        self.pending_note_text = None
        self.set_mode("view")

    # ================= 模式 =================
    def set_mode(self, key):
        if key not in MODE_VIEW:
            key = "view"
        permission = None
        operation = "使用该功能"
        if key == "text_select":
            permission, operation = pymupdf.PDF_PERM_COPY, "复制内容"
        elif key in ("replace_text", "text"):
            permission, operation = pymupdf.PDF_PERM_MODIFY, "编辑文档"
        elif key in ("highlight", "underline", "strikeout", "rect", "line", "ink"):
            permission, operation = pymupdf.PDF_PERM_ANNOTATE, "添加批注"
        if permission is not None and not self._require_permission(
                permission, operation):
            key = "view"
        self.current_mode = key
        self._close_inline_editor()
        for k, act in self.mode_actions.items():
            act.setChecked(k == key)
        self.page_view.set_mode(MODE_VIEW[key])

    def _check_none(self):
        for act in self.mode_actions.values():
            act.setChecked(False)

    def apply_language(self):
        """同步文档视图中的静态文字，不重建文档或页面状态。"""
        self.side_tabs.setTabText(0, i18n.tr("pages"))
        self.start_title.setText(i18n.tr("app_name"))
        self.start_subtitle.setText(i18n.tr("about_summary"))
        self.start_open_btn.setText(i18n.tr("start_open"))
        self.start_hint.setText(i18n.tr("start_hint"))

    def pick_edit_color(self):
        c = QColorDialog.getColor(self.edit_color, self, "选择编辑颜色")
        if c.isValid():
            self.edit_color = QColor(c)
            oid = self.page_view.selected_id()
            obj = self._find_object(oid) if oid is not None else None
            if obj is not None and obj.get("kind") in ANNOTATION_OBJECT_KINDS:
                obj["color"] = QColor(c)
                self.modified = True
                self._refresh_objects()
                self.page_view.select(oid)

    # ================= 图片 / 签名 =================
    def start_image(self, page=None, pt=None):
        """选择图片后直接插入；未指定坐标时放在当前页面中央。"""
        if not self._require_permission(pymupdf.PDF_PERM_MODIFY, "编辑文档"):
            return False
        path, _ = QFileDialog.getOpenFileName(self, "选择图片", "",
                                              "图片 (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return False
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "提示", "无法读取该图片")
            return False
        if page is not None and pt is not None:
            self._add_object(img, "image", int(page), QPointF(pt), 160.0)
            self.statusMessage.emit(
                f"已在第 {int(page) + 1} 页插入图片", 3000)
            return True

        page, position, width = self._default_image_placement(img)
        self.pending_image_qimg = None
        self._add_object(img, "image", page, position, width)
        self.show_page(page)
        self.statusMessage.emit(
            f"图片已直接插入第 {page + 1} 页，可拖动或缩放调整", 4000)
        return True

    def _default_image_placement(self, img):
        """计算当前页面上部居中且不溢出的图片初始位置与宽度。"""
        page = max(0, min(self.page_view.current_page(), len(self.doc) - 1))
        page_rect = self.doc[page].rect
        aspect = img.height() / max(1, img.width())
        width = min(160.0, page_rect.width * 0.42)
        if aspect > 0:
            width = min(width, page_rect.height * 0.46 / aspect)
        width = max(24.0, width)
        height = width * aspect
        x = page_rect.x0 + max(0.0, (page_rect.width - width) / 2)
        # 工具栏和菜单插入时置于页面上部中央，既醒目又留出页边距。
        top_margin = min(72.0, max(24.0, page_rect.height * 0.08))
        y = min(page_rect.y1 - height,
                page_rect.y0 + top_margin)
        return page, QPointF(x, y), width

    def start_sign(self):
        if not self._require_permission(pymupdf.PDF_PERM_ANNOTATE, "添加签名"):
            return
        dlg = SignatureDialog(self)
        if dlg.exec() != SignatureDialog.DialogCode.Accepted:
            return
        img = dlg.result_image()
        if img is None or img.isNull():
            return
        self._prepare_sign(img)

    def open_sign_lib(self):
        if not self._require_permission(pymupdf.PDF_PERM_ANNOTATE, "添加签名"):
            return
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
        if self.doc is not None:
            self.delete_pages([self.page_view.current_page()])

    def delete_pages(self, pages, confirm=True):
        """一次删除一页或多页，并同步调整页面对象索引。"""
        if self.doc is None:
            return False
        if not self._require_permission(pymupdf.PDF_PERM_MODIFY, "编辑文档"):
            return False
        page_set = {
            int(p) for p in pages if 0 <= int(p) < len(self.doc)
        }
        if not page_set:
            return False
        if len(self.doc) - len(page_set) < 1:
            QMessageBox.information(self, i18n.tr("hint"),
                                    i18n.tr("keep_one_page"))
            return False
        if confirm:
            if len(page_set) == 1:
                pno = next(iter(page_set))
                prompt = f"确定删除第 {pno + 1} 页吗？"
            else:
                prompt = i18n.tr("delete_selected_pages_confirm").format(
                    n=len(page_set))
            answer = QMessageBox.question(self, i18n.tr("delete_page"), prompt)
            if answer != QMessageBox.StandardButton.Yes:
                return False

        current = self.page_view.current_page()
        target = current - sum(1 for p in page_set if p < current)
        target = max(0, min(target, len(self.doc) - len(page_set) - 1))
        for pno in sorted(page_set, reverse=True):
            self.doc.delete_page(pno)

        shifted_objects = []
        for obj in self.objects:
            old_page = obj["page"]
            if old_page in page_set:
                continue
            obj["page"] = old_page - sum(1 for p in page_set if p < old_page)
            shifted_objects.append(obj)
        self.objects = shifted_objects
        self.modified = True
        self._refresh()
        self._rebuild_thumbnails()
        self.show_page(target)
        self.thumb_list.setCurrentRow(target)
        self.pageChanged.emit(target, len(self.doc))
        return True

    # ================= 打印 =================
    def print_pdf(self):
        if self.doc is None:
            QMessageBox.information(self, "提示", "请先打开一个 PDF 文件")
            return
        if not self._require_permission(pymupdf.PDF_PERM_PRINT, "打印"):
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
