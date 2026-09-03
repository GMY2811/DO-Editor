"""单个文档的视图：连续滚动页面 + 缩略图侧栏 + 编辑逻辑。"""
import os
import re
import copy
import pymupdf
from PySide6.QtCore import (Qt, QSize, QRect, QRectF, QPointF, Signal,
                            QEvent, QTimer, QItemSelectionModel)
from PySide6.QtGui import (QIcon, QPixmap, QImage, QPainter, QColor, QPen,
                           QFont, QTransform, QKeySequence, QShortcut,
                           QCursor, QPageLayout)
from PySide6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QSplitter,
                               QScrollArea, QListWidget, QListWidgetItem,
                               QTabWidget, QStackedWidget, QFrame, QPushButton,
                               QLabel, QLineEdit, QFileDialog, QMessageBox,
                               QInputDialog, QApplication, QMenu, QColorDialog,
                               QGraphicsDropShadowEffect, QAbstractItemView,
                               QStyledItemDelegate, QStyleOptionViewItem, QStyle,
                               QTreeWidget, QTreeWidgetItem)
from PySide6.QtPrintSupport import QPrinter, QPrintDialog

import backend
import i18n
from page_view import PageView
from sign_dialog import (SignatureDialog, SignatureLibraryDialog,
                         SignatureFontComboBox, qimage_to_png_bytes)
from slide_show import SlideShowWindow

MODE_DEFS = [
    ("view",         "选择",     "view",  "select"),
    ("text_select",  "快捷复制", "rect",  "text_select"),
    ("replace_text", "修改文字", "point", "edit"),
    ("highlight",    "高亮",     "rect",  "highlight"),
    ("underline",    "下划线",   "rect",  "underline"),
    ("strikeout",    "删除线",   "rect",  "strikeout"),
    ("rect",         "矩形",     "rect",  "rect"),
    ("line",         "直线",     "line",  "line"),
    ("ink",          "手绘",     "ink",   "ink"),
    ("text",         "添加文字", "point", "text"),
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
    """添加水印对话框：文字/图片两种类型。
    文字：文字 + 字号 + 颜色 + 透明度 + 旋转 + 平铺；
    图片：图片文件 + 大小 + 透明度 + 旋转 + 平铺。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("add_watermark"))
        from PySide6.QtWidgets import (QPushButton, QHBoxLayout, QVBoxLayout,
                                      QSpinBox, QSlider, QCheckBox, QComboBox,
                                      QFileDialog, QToolButton)
        self._color = QColor(0.5, 0.5, 0.5)
        self._opacity = 0.3
        self._image_path = ""

        # 水印类型：0 文字 / 1 图片（下拉三角号由主题全局 QSS 提供）
        self._type_combo = QComboBox()
        self._type_combo.setObjectName("watermarkTypeCombo")
        self._type_combo.addItem(i18n.tr("watermark_type_text"))
        self._type_combo.addItem(i18n.tr("watermark_type_image"))
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        # 下拉三角号：QComboBox::down-arrow 图像在真实 Windows 窗口下不可靠，
        # 改用 QToolButton 子控件绝对定位在选择框内部右侧（Qt 原生 DownArrow）。
        self._type_combo.setStyleSheet(
            "QComboBox::drop-down { border: none; width: 0; }"
            "QComboBox { padding-right: 24px; }")
        self._type_arrow = QToolButton(self._type_combo)
        self._type_arrow.setObjectName("watermarkTypeArrow")
        self._type_arrow.setArrowType(Qt.ArrowType.DownArrow)
        self._type_arrow.setAutoRaise(True)
        self._type_arrow.setFixedSize(24, 24)
        self._type_arrow.setCursor(Qt.CursorShape.PointingHandCursor)
        self._type_arrow.clicked.connect(self._type_combo.showPopup)
        self._type_arrow.setToolTip(i18n.tr("watermark_type"))

        def _relocate_arrow():
            self._type_arrow.move(
                self._type_combo.width() - 26,
                (self._type_combo.height() - 24) // 2)
            self._type_arrow.raise_()

        self._type_combo.resizeEvent = lambda e: (
            QComboBox.resizeEvent(self._type_combo, e) or _relocate_arrow())
        _relocate_arrow()
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
        self._opacity_label = QLabel("30%")
        self._opacity_label.setObjectName("opacityValueLabel")
        self._opacity_label.setMinimumWidth(44)
        self._opacity_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._opacity_slider.valueChanged.connect(
            lambda v: self._opacity_label.setText(f"{v}%"))

        self._tiled_check = QCheckBox(i18n.tr("tiled"))
        self._tiled_check.setChecked(True)

        self._color_btn = QPushButton(i18n.tr("color"))
        self._color_btn.setFixedWidth(52)
        self._color_btn.clicked.connect(self._pick_color)
        self._style_color_btn()

        # 图片水印控件
        self._img_btn = QPushButton(i18n.tr("watermark_image"))
        self._img_btn.clicked.connect(self._pick_image)
        self._img_label = QLabel()
        self._img_label.setStyleSheet("color:#7a828c;")
        self._scale_spin = QSpinBox()
        self._scale_spin.setRange(5, 100)
        self._scale_spin.setValue(50)
        self._scale_spin.setSuffix(" %")

        btn_ok = QPushButton(i18n.tr("confirm"))
        btn_cancel = QPushButton(i18n.tr("cancel"))
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)

        row0 = QHBoxLayout()
        row0.addWidget(QLabel(i18n.tr("watermark_type")))
        row0.addWidget(self._type_combo)
        row0.addStretch(1)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel(i18n.tr("watermark_text")))
        row1.addWidget(self._text_edit, 1)
        self._img_row = QHBoxLayout()
        self._img_row.addWidget(QLabel(i18n.tr("watermark_image_label")))
        self._img_row.addWidget(self._img_btn)
        self._img_row.addWidget(self._img_label, 1)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel(i18n.tr("font_size")))
        row2.addWidget(self._size_spin)
        row2.addWidget(QLabel(i18n.tr("watermark_rotate")))
        row2.addWidget(self._rotate_spin)
        row2.addWidget(self._color_btn)
        self._scale_row = QHBoxLayout()
        self._scale_row.addWidget(QLabel(i18n.tr("watermark_scale")))
        self._scale_row.addWidget(self._scale_spin)
        self._scale_row.addStretch(1)
        row4 = QHBoxLayout()
        row4.addWidget(QLabel(i18n.tr("watermark_opacity")))
        row4.addWidget(self._opacity_slider, 1)
        row4.addWidget(self._opacity_label)
        row4.addWidget(self._tiled_check)
        row5 = QHBoxLayout()
        row5.addStretch(1)
        row5.addWidget(btn_ok)
        row5.addWidget(btn_cancel)

        lay = QVBoxLayout(self)
        lay.addLayout(row0)
        lay.addLayout(row1)
        self._img_widgets = (self._img_btn, self._img_label, self._scale_spin)
        self._img_layouts = [self._img_row, self._scale_row]
        lay.addLayout(self._img_row)
        lay.addLayout(row2)
        lay.addLayout(self._scale_row)
        lay.addLayout(row4)
        lay.addLayout(row5)
        self.resize(470, 220)
        self._on_type_changed(0)

    def _on_type_changed(self, idx):
        is_text = idx == 0
        self._text_edit.setVisible(is_text)
        self._size_spin.setVisible(is_text)
        self._color_btn.setVisible(is_text)
        for w in self._img_widgets:
            w.setVisible(not is_text)
        for lay in self._img_layouts:
            # 隐藏整个布局行
            for i in range(lay.count()):
                item = lay.itemAt(i)
                if item is not None and item.widget() is not None:
                    item.widget().setVisible(not is_text)

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self, i18n.tr("color"))
        if c.isValid():
            self._color = c
            self._style_color_btn()

    def _style_color_btn(self):
        self._color_btn.setStyleSheet(
            f"background:{self._color.name()};color:#ffffff;"
            f"border:1px solid #666;border-radius:4px;padding:2px 6px;")

    def _pick_image(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.tr("watermark_image"), "",
            i18n.tr("image_file_filter"))
        if path:
            self._image_path = path
            import os as _os
            self._img_label.setText(_os.path.basename(path))

    def result(self):
        if self._type_combo.currentIndex() == 1:
            return ("image", self._image_path,
                    self._scale_spin.value() / 100.0,
                    self._opacity_slider.value() / 100.0,
                    self._rotate_spin.value(), self._tiled_check.isChecked())
        return ("text", self._text_edit.text().strip(),
                self._size_spin.value(),
                (self._color.redF(), self._color.greenF(), self._color.blueF()),
                self._opacity_slider.value() / 100.0,
                self._rotate_spin.value(), self._tiled_check.isChecked())


class ThumbnailListWidget(QListWidget):
    """支持内部拖放并在落下后报告完整页面顺序的缩略图列表。"""
    orderChanged = Signal(object)

    def dragEnterEvent(self, event):
        # 内部拖放显式接受：避免个别环境显示"禁止"光标
        if event.source() is self:
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.source() is self:
            event.accept()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        # 仅处理本列表的内部拖放；外部拖放交给 Qt
        if event.source() is not self:
            super().dropEvent(event)
            return
        before = [
            self.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.count())
        ]
        selected = self.selectedItems()
        if len(selected) != 1:
            # 多选拖动：交给 Qt 原生
            super().dropEvent(event)
            after = [
                self.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.count())
            ]
            if event.isAccepted() and after != before:
                self.orderChanged.emit(after)
            return
        src_row = self.row(selected[0])
        if not (0 <= src_row < self.count()):
            return
        target_item = self.itemAt(event.position().toPoint())
        if target_item is None:
            target_row = self.count() - 1       # 拖到空白 → 末尾
        else:
            target_row = self.row(target_item)
        if target_row == src_row:
            return
        item = self.takeItem(src_row)
        if src_row < target_row:
            target_row -= 1                      # 移除后索引前移
        self.insertItem(max(0, min(target_row, self.count())), item)
        after = [
            self.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.count())
        ]
        if after != before:
            self.orderChanged.emit(after)
        event.acceptProposedAction()


class ThumbnailDelegate(QStyledItemDelegate):
    """将页码以半透明标签覆盖在缩略图底部。"""

    PAGE_BAND_COLOR = QColor(248, 250, 252, 112)
    PAGE_TEXT_COLOR = QColor(75, 85, 99, 255)  # 深灰 #4b5563

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
        font = painter.font()
        font.setPixelSize(max(14, min(18, round(actual.width() * 0.125))))
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        # 页码直接绘制，无底色无阴影
        text_rect = QRect(icon_rect.left(), icon_rect.bottom() - band_height + 1,
                          icon_rect.width(), band_height)
        painter.setPen(self.PAGE_TEXT_COLOR)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, page_number)
        painter.restore()


class DocumentView(QWidget):
    statusMessage = Signal(str, int)
    titleChanged = Signal(str)
    pageChanged = Signal(int, int)
    openRequested = Signal()
    securityChanged = Signal()
    undoAvailableChanged = Signal(bool)
    ocrRequested = Signal(int)
    pageOrientationChanged = Signal(float, float)   # (页面宽, 页面高)，供主窗口调整窗口方向

    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc = None
        self.file_path = None
        self.zoom = 1.4
        # 当前视图适配模式："width"=适合宽度 / "page"=整页 / None=手动缩放。
        # 「适合宽度」按钮据此在整页与适宽之间切换；手动缩放后回到 None，
        # 下次点击总是先进入适合宽度。
        self._fit_mode = None
        self.modified = False
        self.current_mode = "view"
        self.edit_color = QColor(200, 30, 30)
        self.objects = []
        self._obj_counter = 0
        self.pending_image_qimg = None
        self.pending_sign_qimg = None
        self.pending_sign_match_image_scale = False
        self.pending_paste_text = None
        self.pending_note_text = None
        self.mode_actions = {}
        self._editing_line = None    # 就地修改的 PDF 原文行 (page, QRectF)
        self._row_edit = None        # 就地行编辑 QLineEdit（无弹窗工具条）
        self._row_edit_meta = None   # {page, rect, text, fmt} 行编辑元数据
        self._row_focus_pending = False  # 失焦已提交过行编辑（供点击空白判定）
        self._inplace_edit = None   # 「文本」工具就地新增文字的 QLineEdit
        self._inplace_meta = None   # {page, pt, family, size, color, bold, italic}
        self._search_results = []
        self._search_index = 0
        self._source_encrypted = False
        self._security_mode = "none"
        self._security_options = None
        self._open_password = None
        self._auth_level = 0
        self._viewport_pan_last = None
        self._undo_stack = []
        self._undo_pdf_cache = None
        self._undo_limit = 20
        self._undo_memory_limit = 128 * 1024 * 1024
        # 窗口尺寸变化时的整页适配节流定时器（保持阅读区完整显示）。
        self._window_fit_timer = QTimer(self)
        self._window_fit_timer.setSingleShot(True)
        self._window_fit_timer.setInterval(150)
        self._window_fit_timer.timeout.connect(
            lambda: self.fit_width(preserve_position=True))
        self._last_viewport_w = 0
        self._last_viewport_h = 0
        # 主窗口按文档方向调整自身大小时置位，抑制随后的 resizeEvent 适宽，
        # 由主窗口在布局稳定后统一执行整页适配。
        self._suppress_resize_fit = False
        self._build_ui()

    # ================= UI =================
    def _build_ui(self):
        self.side_tabs = QTabWidget()
        self.side_tabs.setObjectName("sidePanel")
        # 高 DPI 下逻辑宽度会被成倍放大。首次打开使用紧凑宽度，之后
        # 允许用户拖动调整并在本次会话内记住该宽度。
        # 最小/默认宽度须能容纳「页面/目录」两个页签（各约 54px，合计 ~112px）。
        self._sidebar_default_width = 120
        self._sidebar_last_width = self._sidebar_default_width
        self.side_tabs.setMinimumWidth(130)
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
        # Qt 原生拖放排序（InternalMove + Snap 是原始可用配置）
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

        # ---- 目录页签（PDF 自带书签/大纲）----
        self._outline_page = QWidget()
        self._outline_page.setObjectName("outlinePage")
        outline_lay = QVBoxLayout(self._outline_page)
        outline_lay.setContentsMargins(4, 4, 4, 4)
        outline_lay.setSpacing(4)
        self.outline_tree = QTreeWidget()
        self.outline_tree.setObjectName("outlineTree")
        self.outline_tree.setHeaderHidden(True)
        self.outline_tree.setColumnCount(2)
        self.outline_tree.setColumnWidth(0, 96)
        self.outline_tree.setRootIsDecorated(True)
        self.outline_tree.setIndentation(10)
        self.outline_tree.setExpandsOnDoubleClick(False)
        self.outline_tree.itemClicked.connect(self._on_outline_clicked)
        self.outline_tree.itemDoubleClicked.connect(
            self._on_outline_double_clicked)
        outline_lay.addWidget(self.outline_tree, 1)
        self.outline_hint = QLabel(i18n.tr("outline_empty"))
        self.outline_hint.setObjectName("outlineHint")
        self.outline_hint.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.outline_hint.setWordWrap(True)
        outline_lay.addWidget(self.outline_hint)
        self.outline_hint.hide()
        self.side_tabs.addTab(self._outline_page, i18n.tr("outline"))
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
        # 禁止拖 splitter 时把侧边栏折叠到 0（否则侧边栏"消失"）
        self._splitter.setChildrenCollapsible(False)
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
            self._fit_page_after_sidebar_resize)
        self._splitter.splitterMoved.connect(
            lambda _pos, _index: self._schedule_content_fit())

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._splitter)

        self.page_view.rectSelected.connect(self._on_rect)
        self.page_view.lineSelected.connect(self._on_line)
        self.page_view.inkSelected.connect(self._on_ink)
        self.page_view.pointClicked.connect(self._on_point)
        self.page_view.textLineClicked.connect(self._on_text_line_clicked)
        self.page_view.objectChanged.connect(self._on_object_changed)
        self.page_view.objectSelected.connect(self._on_object_selected)
        self.page_view.objectDoubleClicked.connect(self._on_object_double_clicked)
        self.page_view.contextMenuRequested.connect(self._on_context_menu)
        self.page_view.panRequested.connect(self._pan_document)

        self.scroll.viewport().setMouseTracking(True)
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
        self._clear_undo_history()
        self.objects = []
        self._obj_counter = 0
        self.titleChanged.emit(os.path.basename(path))
        self.workspace_stack.setCurrentWidget(self.scroll)
        self._refresh()
        self._rebuild_thumbnails()
        self.fit_width()
        self.set_mode("view")
        self._load_outline()
        try:
            pw, ph = backend.page_size(doc, 0)
        except Exception:
            pw, ph = 595.0, 842.0
        self.pageOrientationChanged.emit(float(pw), float(ph))
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
        self.pending_sign_match_image_scale = False
        self.pending_paste_text = None
        self.pending_note_text = None
        self._source_encrypted = False
        self._security_mode = "none"
        self._security_options = None
        self._open_password = None
        self._auth_level = 0
        self._clear_undo_history()
        self.titleChanged.emit(i18n.tr("untitled"))
        self.page_view.set_document(None, 1.0, 1.0)
        self._viewport_pan_last = None
        self.scroll.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.thumb_list.clear()
        self.outline_tree.clear()
        self.outline_hint.show()
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
            # 保存后的当前状态成为新基准；撤销到任何历史状态都应重新
            # 标记为“未保存”，否则关闭标签页时不会提示用户保存。
            for state in self._undo_stack:
                state["modified"] = True
            self._undo_pdf_cache = None
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
        self.begin_undo_step()
        self._security_mode = "aes256"
        self._security_options = {
            "user_pw": user_pw,
            "owner_pw": owner_pw,
            "permissions": int(permissions),
        }
        self.modified = True
        self.securityChanged.emit()

    def remove_pdf_encryption(self):
        self.begin_undo_step()
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

    # ================= 撤销 =================
    @staticmethod
    def _clone_undo_value(value):
        """复制浮动编辑对象，显式处理 Qt 值类型以保持快照独立。"""
        if isinstance(value, QRectF):
            return QRectF(value)
        if isinstance(value, QPointF):
            return QPointF(value)
        if isinstance(value, QColor):
            return QColor(value)
        if isinstance(value, QImage):
            return value.copy()
        if isinstance(value, dict):
            return {k: DocumentView._clone_undo_value(v)
                    for k, v in value.items()}
        if isinstance(value, list):
            return [DocumentView._clone_undo_value(v) for v in value]
        if isinstance(value, tuple):
            return tuple(DocumentView._clone_undo_value(v) for v in value)
        try:
            return copy.deepcopy(value)
        except Exception:
            return value

    def _clear_undo_history(self):
        self._undo_stack = []
        self._undo_pdf_cache = None
        self.undoAvailableChanged.emit(False)

    def can_undo(self):
        return bool(self._undo_stack)

    def _snapshot_pdf(self):
        if self._undo_pdf_cache is None:
            # 保留原加密设置。这样撤销不会意外把受保护文档变成明文。
            self._undo_pdf_cache = self.doc.tobytes(
                garbage=3, deflate=True,
                encryption=pymupdf.PDF_ENCRYPT_KEEP)
        return self._undo_pdf_cache

    def _trim_undo_history(self):
        while len(self._undo_stack) > self._undo_limit:
            self._undo_stack.pop(0)
        while len(self._undo_stack) > 1:
            unique = {}
            for state in self._undo_stack:
                blob = state["pdf"]
                unique[id(blob)] = len(blob)
            if sum(unique.values()) <= self._undo_memory_limit:
                break
            self._undo_stack.pop(0)

    def begin_undo_step(self, document_change=False):
        """在一次内容修改前记录状态；返回是否成功记录。"""
        if self.doc is None:
            return False
        try:
            state = {
                "pdf": self._snapshot_pdf(),
                "objects": self._clone_undo_value(self.objects),
                "obj_counter": self._obj_counter,
                "modified": self.modified,
                "page": self.page_view.current_page(),
                "security_mode": self._security_mode,
                "security_options": self._clone_undo_value(
                    self._security_options),
                "source_encrypted": self._source_encrypted,
                "open_password": self._open_password,
                "auth_level": self._auth_level,
            }
        except Exception as exc:
            self.statusMessage.emit(f"无法记录撤销状态：{exc}", 4000)
            return False
        self._undo_stack.append(state)
        self._trim_undo_history()
        if document_change:
            # 后续操作会直接改写 PyMuPDF 文档，下一次快照必须重新生成。
            self._undo_pdf_cache = None
        self.undoAvailableChanged.emit(True)
        return True

    def undo(self):
        if not self._undo_stack or self.doc is None:
            self.statusMessage.emit(i18n.tr("nothing_to_undo"), 2000)
            return False
        state = self._undo_stack.pop()
        try:
            restored = pymupdf.open(stream=state["pdf"], filetype="pdf")
            password = state.get("open_password")
            if restored.needs_pass and password:
                restored.authenticate(password)
            self.doc.close()
            self.doc = restored
            self.objects = self._clone_undo_value(state["objects"])
            self._obj_counter = int(state["obj_counter"])
            self.modified = bool(state["modified"])
            self._security_mode = state["security_mode"]
            self._security_options = self._clone_undo_value(
                state["security_options"])
            self._source_encrypted = bool(state["source_encrypted"])
            self._open_password = password
            self._auth_level = int(state["auth_level"])
            self._undo_pdf_cache = state["pdf"]
            self.pending_image_qimg = None
            self.pending_sign_qimg = None
            self.pending_sign_match_image_scale = False
            self.pending_paste_text = None
            self.pending_note_text = None
            self._search_results = []
            self.page_view.clear_search_highlights()
            self._close_inline_editor()
            self.set_mode("view")
            self._refresh()
            self._rebuild_thumbnails()
            target = max(0, min(int(state["page"]), len(self.doc) - 1))
            self.show_page(target)
            self.thumb_list.setCurrentRow(target)
            self.pageChanged.emit(target, len(self.doc))
            self.securityChanged.emit()
            self.undoAvailableChanged.emit(bool(self._undo_stack))
            self.statusMessage.emit(i18n.tr("undo_done"), 2500)
            return True
        except Exception as exc:
            # 恢复失败时把快照放回，允许用户再次尝试且不丢历史。
            self._undo_stack.append(state)
            self.undoAvailableChanged.emit(True)
            QMessageBox.warning(self, i18n.tr("undo"),
                                f"{i18n.tr('undo_failed')}\n{exc}")
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
                embed = obj.get("embed")
                if embed:
                    # 修改原有 PDF 文字：用原字体（系统同族或原嵌入字体）
                    # 在原基线高度写回，观感与原文一致。
                    try:
                        self._bake_text_original_font(page, fr, obj, rgb)
                        continue
                    except Exception:
                        pass      # 原字体写回失败 → 回退 htmlbox
                backend.insert_text_auto(
                    page, fr, obj.get("text", ""),
                    fontsize=obj.get("fontsize", 12), color=rgb,
                    fontfamily=obj.get("fontfamily", ""),
                    bold=bool(obj.get("bold", False)),
                    italic=bool(obj.get("italic", False)))
            else:
                opacity = obj.get("opacity", 1.0)
                if opacity >= 1.0:
                    page.insert_image(fr, stream=obj["png"])
                else:
                    # PyMuPDF 的 alpha 参数是 int(0/1 有无透明)，不是透明度值；
                    # 把透明度固化到图像自身的 alpha 通道，保存/重开后依然生效。
                    from PIL import Image as _PILImage
                    from io import BytesIO as _BytesIO
                    _img = _PILImage.open(_BytesIO(obj["png"])).convert("RGBA")
                    _r, _g, _b, _a = _img.split()
                    _a = _a.point(lambda v: int(v * opacity))
                    _img = _PILImage.merge("RGBA", (_r, _g, _b, _a))
                    _buf = _BytesIO()
                    _img.save(_buf, format="PNG")
                    page.insert_image(fr, stream=_buf.getvalue())
        self.objects = []
        self._obj_counter = 0

    def _bake_text_original_font(self, page, fr, obj, rgb):
        """以原字体写回修改后的整行文字，保证字形/字族与文档其它行一致。

        embed 的 name 为注册名，file/buffer 为字体来源；基线取原行重建值，
        使新文字与原行处于同一垂直位置。文字只按单行从左往右排（不折行），
        宽度超出部分在保存时由调用方按字符数估算的对象宽度承担。

        字形兜底：若新文本含原字体没有的字形（典型：把西文行改成中文，
        Arial/Helvetica 等无中文字形，直接写回会渲染成方块），自动回退到
        系统中文全量字体（对象原字族 → 雅黑/宋体/黑体/等线/楷体/仿宋），
        保证保存后汉字正常显示；字号、颜色、基线保持不变。
        """
        text = obj.get("text", "")
        if not (text or "").strip():
            return
        embed = obj.get("embed") or {}
        fname = embed.get("name")
        if not fname:
            raise RuntimeError("no embed font name")
        # —— 字形覆盖检测：文本含非西文字符且原字体缺字形 → 换中文字体 ——
        if any(ord(ch) > 0x2E7F for ch in text if not ch.isspace()):
            try:
                fo = None
                if embed.get("file"):
                    fo = pymupdf.Font(fontfile=embed["file"])
                elif embed.get("buffer"):
                    fo = pymupdf.Font(fontbuffer=embed["buffer"])
                covered = fo is not None and self._font_covers(fo, text)
            except Exception:
                covered = False
            if not covered:
                fname, embed = self._fallback_cjk_font(obj, text)
        try:
            if embed.get("file"):
                page.insert_font(fontname=fname, fontfile=embed["file"])
            elif embed.get("buffer"):
                page.insert_font(fontname=fname, fontbuffer=embed["buffer"])
            else:
                raise RuntimeError("no embed font source")
        except Exception:
            # 同名资源可能已在页面注册（同一页多处同字体修改）
            fonts = page.get_fonts(full=True)
            if not any(f[3] == fname or fname in (f[3] or "") for f in fonts):
                raise
        size = max(4.0, float(obj.get("fontsize") or 10.0))
        base = obj.get("baseline")
        if base is None:
            base = fr.y1 - size * 0.15
        page.insert_text((fr.x0, float(base)), text, fontname=fname,
                         fontsize=size, color=rgb)

    @staticmethod
    def _font_covers(font, text):
        """字体是否含文本全部非空白字符的字形（用于写回前兜底检测）。"""
        try:
            for ch in text:
                if not ch.isspace() and not font.has_glyph(ord(ch)):
                    return False
            return True
        except Exception:
            return False

    def _fallback_cjk_font(self, obj, text):
        """为含中文的新文本挑选能覆盖全部字形的系统字体。

        依次尝试 对象原字族 → 微软雅黑 → 宋体 → 黑体 → 等线 → 楷体 →
        仿宋，返回 (注册名, embed dict)；全部不覆盖则抛错，由调用方回退
        htmlbox（内置 Droid Sans Fallback 仍能显示中文）。
        """
        import os as _os
        import re as _re
        fams = [obj.get("fontfamily") or "",
                "Microsoft YaHei", "SimSun", "SimHei",
                "DengXian", "KaiTi", "FangSong"]
        seen = set()
        for fam in fams:
            if not fam or fam in seen:
                continue
            seen.add(fam)
            p = self._system_font_file(fam)
            if not p:
                continue
            try:
                fo = pymupdf.Font(fontfile=p)
            except Exception:
                continue
            if not self._font_covers(fo, text):
                continue
            # 注册名加 fb 前缀，避免与原嵌入资源/字族名撞名
            clean = _re.sub(r"[^A-Za-z0-9]", "", fam)
            return "fb" + (clean or "cjk"), {"name": "fb" + clean, "file": p}
        raise RuntimeError("no font covers text glyphs")

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

    def start_slideshow(self):
        """从当前页开始全屏幻灯片放映。"""
        if self.doc is None:
            self.statusMessage.emit(i18n.tr("slideshow_open_first"), 0)
            return
        self._slide_window = SlideShowWindow(
            self.doc, self.page_view.current_page(), self.window())
        self._slide_window.closed.connect(self._on_slideshow_closed)
        self._slide_window.showFullScreen()
        self._slide_window.activateWindow()

    def _on_slideshow_closed(self):
        win = getattr(self, "_slide_window", None)
        if win is not None:
            win.closed.disconnect(self._on_slideshow_closed)
            self._slide_window = None

    def next_page(self):
        self.show_page(self.page_view.current_page() + 1)

    def prev_page(self):
        self.show_page(self.page_view.current_page() - 1)

    def zoom_in(self):
        self._fit_mode = None
        self._set_zoom(self.zoom * 1.25)

    def zoom_out(self):
        self._fit_mode = None
        self._set_zoom(self.zoom / 1.25)

    def fit_page(self, preserve_position=False):
        """整页适配：使当前页完整显示在阅读区（宽度和高度都约束）。
        页面顶部对齐视口顶部、底部填满视口，下一页完全在视口之外，
        既无底部空隙横条，也不会露出下一页内容。"""
        if self.doc is None:
            return
        self._fit_mode = "page"
        keep = self.page_view.current_page()
        page_offset = None
        if preserve_position:
            old_page_top = self.page_view.scroll_to_page(keep)
            old_scroll = self.scroll.verticalScrollBar().value()
            page_offset = max(0.0, old_scroll - old_page_top) / max(
                0.1, self.zoom)
        w, h = backend.page_size(self.doc, keep)
        vw = max(200, self.scroll.viewport().width() - 40)
        # 高度约束直接填满视口：页面底平齐视口底，下一页（在下方 18px
        # 间距处）完全位于视口之外，不露出、也无底部空隙带。
        vh = max(200, self.scroll.viewport().height())
        self._set_zoom(min(vw / w, vh / h), page_offset)

    def fit_width(self, preserve_position=False):
        if self.doc is None:
            return
        self._fit_mode = "width"
        keep = self.page_view.current_page()
        page_offset = None
        if preserve_position:
            old_page_top = self.page_view.scroll_to_page(keep)
            old_scroll = self.scroll.verticalScrollBar().value()
            page_offset = max(0.0, old_scroll - old_page_top) / max(
                0.1, self.zoom)
        # 以当前页宽度为准，保证「当前页在阅读区完整显示」。
        w, _h = backend.page_size(self.doc, keep)
        vw = max(200, self.scroll.viewport().width() - 40)
        self._set_zoom(vw / w, page_offset)

    def toggle_fit(self):
        """「适合宽度」按钮：整页显示与适合宽度之间来回切换。

        文档打开默认是适合宽度（_fit_mode="width"），首次点击切到整页，
        再次点击回到适合宽度；手动缩放后（_fit_mode=None）点击先适宽。
        """
        if self.doc is None:
            return
        if self._fit_mode == "width":
            self.fit_page()
        else:
            self.fit_width()

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
            # splitter 尺寸更新，保证页面最终按宽度完整显示。
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
        """节流侧边栏拖动触发的正文整页适配，兼顾实时反馈和渲染性能。"""
        if self.doc is None or self.side_tabs.isHidden():
            return
        if not self._sidebar_fit_timer.isActive():
            self._sidebar_fit_timer.start()

    def _fit_page_after_sidebar_resize(self):
        if self.doc is not None and not self.side_tabs.isHidden():
            self.fit_page(preserve_position=True)

    def resizeEvent(self, event):
        """窗口尺寸变化时整页适配（节流），保持当前页完整显示。
        宽、高任一方向变化都会触发，支持单独拖拽窗口边缘。"""
        super().resizeEvent(event)
        if self.doc is None or self._suppress_resize_fit:
            return
        new_w = self.scroll.viewport().width()
        new_h = self.scroll.viewport().height()
        if abs(new_w - self._last_viewport_w) >= 24 or \
                abs(new_h - self._last_viewport_h) >= 24:
            self._last_viewport_w = new_w
            self._last_viewport_h = new_h
            if not self._window_fit_timer.isActive():
                self._window_fit_timer.start()

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
        # 下限 40：侧边栏拖到最窄时缩略图仍可见（不消失）。
        icon_width = max(
            40, min(self._thumbnail_source_width, viewport_width - 14))
        icon_height = max(1, round(icon_width * self._thumbnail_aspect))
        grid_width = max(icon_width + 8, viewport_width)
        # 页码覆盖在缩略图内部，只需给选中框和项目上下留少量空间。
        grid_height = icon_height + 14

        return QSize(icon_width, icon_height), QSize(grid_width, grid_height)

    # ================= 侧边栏 =================
    def _rebuild_thumbnails(self):
        self.thumb_list.clear()
        self._thumb_batch = 0
        self._thumbnail_job_active = False
        if self.doc is None:
            return
        # 缩略图比例跟随文档方向：横向文档用矮缩略图，
        # 避免固定竖版比例导致横向页面上下留白、间距过大。
        if len(self.doc) > 0:
            try:
                p0 = self.doc[0]
                aspect = p0.rect.height / max(1.0, p0.rect.width)
                self._thumbnail_aspect = max(0.5, min(1.8, aspect))
            except Exception:
                self._thumbnail_aspect = 1.414
        self._update_thumbnail_layout()
        # 超大 PDF（数百页以上）一次性渲染所有缩略图会长时间冻结界面；
        # 改为分批生成，每批让出事件循环，缩略图逐渐出现。
        self._schedule_thumbnail_batch()

    def _schedule_thumbnail_batch(self):
        if getattr(self, "_thumbnail_job_active", False) or self.doc is None:
            return
        self._thumbnail_job_active = True
        QTimer.singleShot(0, self._render_thumbnail_batch)

    def _render_thumbnail_batch(self):
        self._thumbnail_job_active = False
        if self.doc is None or getattr(self, "_thumb_batch", 0) is None:
            return
        batch_size = 24
        start = self._thumb_batch
        end = min(start + batch_size, len(self.doc))
        for i in range(start, end):
            self._add_thumbnail_item(i)
        self._thumb_batch = end
        if end < len(self.doc):
            QTimer.singleShot(0, self._render_thumbnail_batch)

    def _add_thumbnail_item(self, i):
        try:
            page = self.doc[i]
        except Exception:
            return
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

    def _load_outline(self):
        """加载 PDF 自带大纲到侧边栏目录树。"""
        self.outline_tree.clear()
        if self.doc is None:
            self.outline_hint.show()
            return
        toc = backend.get_outline(self.doc)
        if not toc:
            self.outline_hint.show()
            return
        self.outline_hint.hide()
        parents = {}   # level -> QTreeWidgetItem
        for entry in toc:
            level, title, page = entry[0], entry[1], entry[2]
            item = QTreeWidgetItem([
                str(title), i18n.tr("outline_page").format(p=page + 1)])
            item.setData(0, Qt.ItemDataRole.UserRole, int(page))
            if level <= 1 or (level - 1) not in parents:
                self.outline_tree.addTopLevelItem(item)
            else:
                parents[level - 1].addChild(item)
            parents[level] = item
            for k in [k for k in parents if k > level]:
                del parents[k]
        self.outline_tree.expandAll()
        # 第 2 列（页码）右对齐
        header = self.outline_tree.header()
        header.setSectionResizeMode(0, header.ResizeMode.Stretch)
        header.setSectionResizeMode(1, header.ResizeMode.ResizeToContents)

    def _on_outline_clicked(self, item, _col):
        page = item.data(0, Qt.ItemDataRole.UserRole)
        if page is None or self.doc is None:
            return
        self.show_page(int(page))

    def _on_outline_double_clicked(self, item, _col):
        self._on_outline_clicked(item, _col)

    def _on_thumb_context_menu(self, pos):
        """缩略图右键菜单：空白处可添加 PDF；缩略图项支持删除。"""
        item = self.thumb_list.itemAt(pos)
        if item is None:
            # 空白处：仅提供"添加 PDF 文件"入口
            menu = QMenu(self.thumb_list)
            menu.addAction(i18n.tr("insert_pdf_file"),
                           self._on_add_pdf_empty)
            menu.exec(self.thumb_list.viewport().mapToGlobal(pos))
            return
        if self.doc is None:
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
        # 上移/下移一页（拖动排序的可靠替代入口）
        if len(pages) == 1:
            menu.addAction(i18n.tr("move_up"),
                           lambda checked=False: self._move_page(-1))
            menu.addAction(i18n.tr("move_down"),
                           lambda checked=False: self._move_page(1))
        # 在选中页之前插入另一个 PDF 的页面
        insert_at = min(pages)
        menu.addAction(
            i18n.tr("insert_pdf_file"),
            lambda checked=False, at=insert_at: self._on_thumb_insert_pdf(at))
        # 文档多时空白处难点到，缩略图项上也提供"插入到末尾"入口
        menu.addAction(
            i18n.tr("insert_pdf_to_end"),
            lambda checked=False: self._on_add_pdf_empty())
        menu.exec(self.thumb_list.viewport().mapToGlobal(pos))

    def _move_page(self, delta):
        """上移/下移当前选中页一页（单选时可用）。"""
        pages = self._selected_thumbnail_pages()
        if len(pages) != 1 or self.doc is None:
            return
        old = pages[0]
        new = old + delta
        if not (0 <= new < len(self.doc)):
            return
        order = list(range(len(self.doc)))
        order[old], order[new] = order[new], order[old]
        self._reorder_pages(order)

    def _on_add_pdf_empty(self):
        """侧边栏空白处右键：选择 PDF 插入到当前页之后。"""
        if self.doc is None:
            return
        at = len(self.doc)
        self._on_thumb_insert_pdf(at)

    def _on_thumb_insert_pdf(self, at_page):
        """选择 PDF 并插入到 at_page（0-based）之前。"""
        if self.doc is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.tr("insert_pdf_file"), "",
            "PDF 文件 (*.pdf)")
        if not path:
            return
        self.insert_pdf_pages(path, at_page)

    def insert_pdf_pages(self, path, at_page):
        """在 at_page（0-based）位置插入另一个 PDF 的全部页面。"""
        if self.doc is None:
            return False
        if not self._require_permission(pymupdf.PDF_PERM_MODIFY, "编辑文档"):
            return False
        at_page = max(0, min(at_page, len(self.doc)))
        try:
            src = backend.open_pdf(path)
        except Exception as e:
            QMessageBox.warning(self, i18n.tr("hint"),
                                f"无法打开 {path}\n{e}")
            return False
        with src:
            insert_count = len(src)
            if insert_count == 0:
                QMessageBox.information(self, i18n.tr("hint"),
                                        i18n.tr("insert_empty"))
                return False
            self.begin_undo_step(document_change=True)
            self.doc.insert_pdf(src, start_at=at_page)
        # 调整已有页面对象的页码
        shifted = []
        for obj in self.objects:
            if obj["page"] >= at_page:
                obj = dict(obj)
                obj["page"] = obj["page"] + insert_count
            shifted.append(obj)
        self.objects = shifted
        self.modified = True
        self._refresh()
        self._rebuild_thumbnails()
        self.show_page(at_page)
        self.statusMessage.emit(
            f"{i18n.tr('insert_done')} {insert_count} "
            f"{i18n.tr('insert_pages_hint')}", 3000)
        return True

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
        self.begin_undo_step(document_change=True)
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
            i18n.tr("paste_text_done").format(p=int(page) + 1), 3000)

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
        self.begin_undo_step()
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
            i18n.tr("note_added").format(p=page + 1), 4000)
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
            # 历史路径：拖框 + 对话框批量替换。当前「修改文字」已改为
            # 整页文字行框 + 就地编辑（_on_text_line_clicked），此分支备用。
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
                    self.begin_undo_step(document_change=True)
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
        self.begin_undo_step()
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
            self._begin_inplace_text(page, pt)
        elif m == "image" and self.pending_image_qimg is not None:
            self._add_object(self.pending_image_qimg, "image", page, pt, 160.0)
            self.pending_image_qimg = None
        elif m == "sign" and self.pending_sign_qimg is not None:
            base_width = (
                self._image_placement_width(self.pending_sign_qimg, page)
                if self.pending_sign_match_image_scale else 180.0)
            self._add_object(
                self.pending_sign_qimg, "signature", page, pt, base_width)
            self.pending_sign_qimg = None
            self.pending_sign_match_image_scale = False
        elif m == "note" and self.pending_note_text:
            self._add_note_at(self.pending_note_text, page, pt)
        elif m == "paste" and self.pending_paste_text:
            self._add_text_object(self.pending_paste_text, page, pt)
            self.pending_paste_text = None

    def _on_text_line_clicked(self, page, line):
        """「修改文字」整页框模式：点击一行 → 该行就地变成可编辑框。

        连续点行 = 先提交上一处再编辑下一处；点空白若刚由失焦提交过
        编辑则不重复提示。
        """
        if self.current_mode != "replace_text" or self.doc is None:
            return
        focus_done = self._row_focus_pending
        self._row_focus_pending = False
        was_editing = self._commit_row_edit(commit=True)
        if line is None:
            if not (was_editing or focus_done):
                self.statusMessage.emit(i18n.tr("replace_no_text"), 3000)
            return
        self._begin_row_edit(int(page), line)

    def _begin_row_edit(self, page, line):
        """在文字行原位置就地打开单行编辑框（无弹窗）。

        编辑器紧贴该行文字框，字号/颜色/字体还原原文样式；输入框中
        预填原行文字并全选，回车或点击其它处提交，Esc 取消。
        """
        if not self._require_permission(pymupdf.PDF_PERM_MODIFY, "编辑文档"):
            return
        from PySide6.QtWidgets import QLineEdit
        from PySide6.QtGui import QFont
        self._close_inline_editor()

        # 编辑框是页面画布的子控件：page_view 就是滚动内容本身
        # （整页高度），所以直接使用画布局部坐标即可随页面滚动与缩放。
        canvas = self.page_view
        zoom = canvas._zoom
        r = line["rect"]          # PDF 坐标
        wx = r.x() * zoom
        wy = canvas._offsets[page] + r.y() * zoom
        ww = r.width() * zoom
        wh = max(2.0, r.height() * zoom)

        fmt = line.get("fmt") or {}
        size = float(fmt.get("size") or 10.0)
        family = self._map_pdf_font(fmt.get("font", ""))
        if not family:
            family = "Microsoft YaHei"
        c = fmt.get("color") or (0, 0, 0)
        color = QColor(int(c[0]), int(c[1]), int(c[2]))
        bold = bool(fmt.get("bold", False))
        italic = bool(fmt.get("italic", False))
        luminance = (0.299 * color.red() + 0.587 * color.green() +
                     0.114 * color.blue())

        font_px = max(9.0, size * zoom * 1.08)
        box_h = max(wh + 4.0, font_px * 1.3 + 4.0)
        # 垂直：中心对齐该行文字框，避免字体替换引起的基线偏移
        center_y = wy + wh / 2.0
        by = int(center_y - box_h / 2.0)
        # 水平：从行首开始，宽度不小于原行框，短行放宽便于输入，
        # 但不超过页面右缘。
        bx = max(0, int(wx - 1))
        page_px_w = backend.page_size(self.doc, page)[0] * zoom
        avail_w = max(2.0, page_px_w - bx)
        box_w = max(ww + 6.0, min(180.0, avail_w))
        box_w = min(box_w, avail_w)

        edit = QLineEdit(str(line.get("text", "")), canvas)
        edit.setObjectName("rowEditInline")
        font = QFont(family)
        font.setPixelSize(int(round(font_px)))
        font.setBold(bold)
        font.setItalic(italic)
        edit.setFont(font)
        # 编辑器覆盖在页面上，采用近纸色半透明底 + 主题蓝细框，
        # 文字尽量沿用原颜色（过浅则压暗以保证在白底上可读）。
        text_color = color.name() if luminance > 225 else (
            "#1c1c1e" if luminance > 200 else color.name())
        edit.setStyleSheet(
            "QLineEdit#rowEditInline{"
            "background-color: rgba(255,255,255,0.92);"
            "border: 1px solid #0a84ff; border-radius: 2px;"
            "padding: 0 2px; color: %s;"
            "selection-background-color: #b6d7ff;"
            "selection-color: #101418;}" % text_color)
        edit.setGeometry(bx, by, int(box_w), int(box_h))
        edit.raise_()
        edit.show()
        edit.setFocus()
        edit.selectAll()
        edit.returnPressed.connect(self._finish_row_edit)
        edit.installEventFilter(self)
        self._row_edit = edit
        self._row_edit_meta = {
            "page": page,
            "rect": QRectF(r),
            "text": str(line.get("text", "")),
            "cx": float(line.get("cx", r.x() + r.width() / 2.0)),
            # 提交时直接复用点击命中行的格式与主 span 矩形，避免
            # 表格型文档中按 y 二次定位误中相邻行导致格式/颜色串行。
            "fmt": dict(line.get("fmt") or {}),
            "span_bbox": list(line.get("span_bbox") or
                              [r.x(), r.y(), r.right(), r.bottom()]),
        }

    def _finish_row_edit(self):
        """回车提交就地行编辑，并把键盘焦点还给画布。"""
        self._commit_row_edit(commit=True)
        if self.page_view is not None:
            self.page_view.setFocus()

    def _commit_row_edit(self, commit=True):
        """关闭就地行编辑框。commit=True 时把改动写回 PDF。

        返回是否曾处于行编辑状态（用于点击空白的提示决策）。
        """
        edit = self._row_edit
        if edit is None:
            return False
        meta = self._row_edit_meta or {}
        page = int(meta.get("page", 0))
        rect = meta.get("rect")
        new_text = edit.text()
        self._close_inline_editor()
        if not commit or rect is None:
            return True
        old_text = meta.get("text", "")
        if new_text == old_text:
            return True                     # 未改动，不产生撤销记录
        family = ""
        size = 10.0
        color = QColor(0, 0, 0)
        bold = italic = False
        embed = None
        baseline = None
        fmt = meta.get("fmt") or {}
        if fmt:
            # 主路径：直接使用点击命中行的格式（表格文档中同一水平带
            # 常有多行上下交叠，按 y 二次定位会误中相邻行，导致字号、
            # 颜色被串成其它行的值）。embed/baseline 由命中行主 span
            # 的字体与矩形重建，保证保存后观感与点击行一致。
            try:
                pdf_font = str(fmt.get("font") or "")
                family = (self._map_pdf_font(pdf_font) or
                          "Microsoft YaHei")
                size = round(float(fmt.get("size") or 10.0), 1)
                cc = fmt.get("color") or (0, 0, 0)
                color = QColor(int(cc[0]), int(cc[1]), int(cc[2]))
                bold = bool(fmt.get("bold", False))
                italic = bool(fmt.get("italic", False))
                sb = meta.get("span_bbox") or [
                    rect.x(), rect.y(), rect.right(), rect.bottom()]
                embed, baseline = self._prepare_row_embed(
                    self.doc[page], pdf_font, size, sb)
            except Exception:
                embed = None
                baseline = None
        else:
            try:
                # 兜底：meta 无 fmt（理论不会走到）→ 才按位置就近找行。
                p = self.doc[page]
                lines = []
                for block in p.get_text("dict").get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    lines.extend(block.get("lines", []) or [])
                cx = meta.get("cx", rect.center().x())
                target = None
                if lines:
                    cy = rect.center().y()
                    cands = []
                    for ln in lines:
                        b0 = ln.get("bbox")
                        if not b0:
                            continue
                        if (b0[1] - 2 <= cy <= b0[3] + 2):
                            cands.append(ln)
                    if not cands:
                        cands = [min(lines, key=lambda ln: abs(
                            (ln["bbox"][1] + ln["bbox"][3]) / 2.0 - cy))]
                    # 同带多行时按横坐标就近取真正被点击的行
                    target = min(cands, key=lambda ln: abs(
                        (ln["bbox"][0] + ln["bbox"][2]) / 2.0 - cx))
                if target is not None:
                    span = max(target["spans"],
                               key=lambda s: len(s.get("text", "")))
                    fam = self._map_pdf_font(span.get("font", ""))
                    family = fam or "Microsoft YaHei"
                    size = round(float(span.get("size", 10.0)), 1)
                    col = int(span.get("color", 0)) & 0xFFFFFF
                    color = QColor((col >> 16) & 255,
                                   (col >> 8) & 255, col & 255)
                    bold, italic = backend.font_style_flags(
                        span.get("font", ""), int(span.get("flags", 0)))
                    embed, baseline = self._prepare_row_embed(
                        p, span.get("font", ""), span.get("size", 10.0),
                        span.get("bbox"))
            except Exception:
                embed = None
                baseline = None
        self._commit_edited_line(page, rect, new_text, family, size,
                                 color, bold, italic, embed=embed,
                                 baseline=baseline)
        return True

    def _begin_inplace_text(self, page, pt):
        """「文本」工具点击处就地输入新文字（无弹窗工具条）。

        点击位置直接出现单行输入框，预置点击处文字格式；输入完后
        回车或点击页面其它处即在该处写入浮动文字对象，Esc 取消；
        保持 text 模式可连续在其它位置继续添加。
        """
        if not self._require_permission(pymupdf.PDF_PERM_MODIFY, "编辑文档"):
            return
        self._close_inline_editor()

        fmt = self._detect_format_at(page, pt)
        family = self._map_pdf_font(fmt.get("family", "")) or "Microsoft YaHei"
        size = float(fmt.get("size") or 10.0)
        color = fmt.get("color")
        if color is None or not isinstance(color, QColor):
            color = QColor(0, 0, 0)
        bold = bool(fmt.get("bold", False))
        italic = bool(fmt.get("italic", False))

        canvas = self.page_view
        zoom = canvas._zoom
        wx = pt.x() * zoom
        wy = canvas._offsets[page] + pt.y() * zoom

        font_px = max(9.0, size * zoom * 1.08)
        box_h = max(24.0, font_px * 1.35 + 4.0)
        page_px_w = backend.page_size(self.doc, page)[0] * zoom
        box_w = min(max(160.0, min(320.0, page_px_w - wx)), 460.0)
        if box_w <= 0:
            box_w = 320.0

        lum = (0.299 * color.red() + 0.587 * color.green() +
               0.114 * color.blue())
        text_color = color.name() if lum > 225 else (
            "#1c1c1e" if lum > 200 else color.name())
        style = (
            "QLineEdit#textEditInline{"
            "background-color: rgba(255,255,255,0.92);"
            "border: 1px dashed #0a84ff; border-radius: 2px;"
            "padding: 0 2px; color: %s;"
            "selection-background-color: #b6d7ff;"
            "selection-color: #101418;}" % text_color)

        edit = QLineEdit("", canvas)
        edit.setObjectName("textEditInline")
        font = QFont(family)
        font.setPixelSize(int(round(font_px)))
        font.setBold(bold)
        font.setItalic(italic)
        edit.setFont(font)
        edit.setStyleSheet(style)
        edit.setGeometry(int(wx), int(wy), int(box_w), int(box_h))
        edit.raise_()
        edit.show()
        edit.setFocus()
        edit.returnPressed.connect(self._finish_inplace_text)
        edit.installEventFilter(self)
        self._inplace_edit = edit
        self._inplace_meta = {
            "page": int(page),
            "pt": QPointF(pt),
            "family": family, "size": size, "color": color,
            "bold": bold, "italic": italic,
        }

    def _finish_inplace_text(self):
        """回车提交就地新增文字，并把键盘焦点还给画布。"""
        self._commit_inplace_text(commit=True)
        if self.page_view is not None:
            self.page_view.setFocus()

    def _commit_inplace_text(self, commit=True):
        """关闭就地新增文字输入框；commit=True 且有内容时写入文档。

        返回是否曾处于就地新增文字编辑状态。
        """
        edit = self._inplace_edit
        if edit is None:
            return False
        meta = self._inplace_meta or {}
        new_text = edit.text().strip()
        self._close_inline_editor()
        if commit and new_text:
            self._add_text_object(
                new_text, int(meta.get("page", 0)), meta["pt"],
                meta.get("family", ""), meta.get("size", 10.0),
                meta.get("color"), meta.get("bold", False),
                meta.get("italic", False), keep_mode=True)
        return True

    def _close_inline_editor(self):
        self._editing_line = None
        if getattr(self, "_row_edit", None) is not None:
            self._row_edit.deleteLater()
        self._row_edit = None
        self._row_edit_meta = None
        if getattr(self, "_inplace_edit", None) is not None:
            self._inplace_edit.deleteLater()
        self._inplace_edit = None
        self._inplace_meta = None
        if getattr(self, "_inline_box", None) is not None:
            self._inline_box.deleteLater()
        self._inline_box = None
        self._inline_edit = None

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
            fmt["bold"], fmt["italic"] = backend.font_style_flags(
                span.get("font", ""), int(span.get("flags", 0)))
        except Exception:
            pass
        return fmt

    @staticmethod
    def _map_pdf_font(pdf_font):
        """PDF 内部字体名 → 系统字体名（找不到则返回空串）。

        中文字体优先按「衬线/宋体系」与「无衬线/黑体系」归类到系统自带
        的等价字体，保证就地编辑写回与原文保持同一字族观感；识别不了时
        才返回空串由调用方兜底（雅黑）。英文全名中可能带子集前缀
        （如 ABCDEF+SimSun），统一用小写包含匹配。
        """
        low = (pdf_font or "").lower()
        if not low:
            return ""
        # ---- 西文等宽 / 无衬线 / 衬线 ----
        if any(k in low for k in ("courier", "consolas", "mono", "等宽")):
            return "Courier New"
        if any(k in low for k in ("arial", "helvetica", "helv", "liberationsans")):
            return "Arial"
        if any(k in low for k in ("times", "roman", "georgia", "garamond",
                                  "liberationserif")):
            return "Times New Roman"
        # ---- 楷体 / 仿宋（先于泛化宋体判断，避免被归成宋体）----
        if any(k in low for k in ("kaiti", "kai", "楷", "kaishu")):
            return "KaiTi"
        # ---- 仿宋（注意：不能用裸 "fang"，否则误命中苹方 PingFang）----
        if any(k in low for k in ("fangsong", "仿宋", "stfangsong", "fzfs")):
            return "FangSong"
        # ---- 宋体 / 明体等衬线中文字体 → SimSun ----
        if any(k in low for k in (
                "simsun", "songti", "song", "stsong", "songsc", "nssong",
                "uming", "ming", "sun", "batsong", "thsong", "书宋", "报宋",
                "宋", "fzsong", "fzss", "fzxbs", "dhyuan",
                "notoserif", "noto serif", "sourcehanserif", "source han serif",
                "思源宋", "serifcjk", "serif cjk", "serifsc", "stzhongsong",
                "华文中宋")):
            return "SimSun"
        # ---- 现代无衬线中文字体 → 微软雅黑（思源黑体/苹方/Noto/Droid/
        # 华文黑体/文泉驿等系统缺失，雅黑观感最接近，避免回退成粗重的 SimHei）
        if any(k in low for k in (
                "yahei", "msyh", "雅黑", "微软", "dengxian", "droid sans",
                "noto sans", "notosans", "sourcehansans", "思源黑",
                "pingfang", "stheiti", "heiti", "jhenghei", "jheng",
                "wqy", "wenquanyi", "sans cjk", "sanssc", "hansans",
                "malgun", "segoe ui", "兰亭黑", "方正兰亭", "华为", "harmonyos")):
            return "Microsoft YaHei"
        # ---- 传统粗黑体（SimHei/方正黑体等）----
        if any(k in low for k in ("simhei", "fzhei", "fzht", "方正黑", "黑体")):
            return "SimHei"
        return ""

    # 常见中文字体 → Windows 系统全量字体文件（保证写回字形覆盖全部字符）
    _SYSTEM_FONT_FILES = {
        "SimSun": r"C:\Windows\Fonts\simsun.ttc",
        "SimHei": r"C:\Windows\Fonts\simhei.ttf",
        "KaiTi": r"C:\Windows\Fonts\simkai.ttf",
        "FangSong": r"C:\Windows\Fonts\simfang.ttf",
        "Microsoft YaHei": r"C:\Windows\Fonts\msyh.ttc",
        "DengXian": r"C:\Windows\Fonts\deng.ttf",
        "Arial": r"C:\Windows\Fonts\arial.ttf",
        "Times New Roman": r"C:\Windows\Fonts\times.ttf",
        "Courier New": r"C:\Windows\Fonts\cour.ttf",
    }

    @staticmethod
    def _system_font_file(family):
        """映射字体族名 → 本机系统字体文件（存在才返回，否则 None）。"""
        import os as _os
        p = DocumentView._SYSTEM_FONT_FILES.get(family or "")
        if p and _os.path.exists(p):
            return p
        return None

    def _prepare_row_embed(self, page, span_font, span_size, span_bbox):
        """为写回行准备字体嵌入载荷与基线，保证保存后观感贴近原文。

        优先使用「系统同族全量字体文件」（字形覆盖全，用户改入新字符也有字形）；
        找不到系统同族时退回抽取原嵌入字体 buffer（可能是子集）。均失败返回 None。
        返回 (embed_dict | None, baseline_y)。embed 形如
        {"name": 注册名, "file": 系统路径} 或 {"name": 注册名, "buffer": 字节}。
        """
        try:
            import pymupdf as _pym
            size = float(span_size or 10.0)
            fam = self._map_pdf_font(span_font)
            fpath = self._system_font_file(fam)
            fo = None
            buf = None
            name = ""
            if fpath:
                name = fam
                try:
                    fo = _pym.Font(fontfile=fpath)
                except Exception:
                    fo = None
            else:
                # 无系统同族字体 → 尝试抽取原嵌入字体 buffer
                cleaned = re.sub(r"^[A-Fa-f0-9]{6}\+", "",
                                 (span_font or "")).strip()
                base = re.sub(r"[\s-]", "", cleaned).lower()
                for f in page.get_fonts(full=True):
                    cand = re.sub(r"[\s-]", "", (f[3] or "")).lower()
                    if not base or not cand:
                        continue
                    hit = (base in cand or cand in base or
                           cand.startswith(base) or base.startswith(cand))
                    if not hit:
                        continue
                    try:
                        _nm, _ext, _sub, buf = self.doc.extract_font(f[0])
                    except Exception:
                        buf = None
                    if buf:
                        name = cleaned or _nm or f"F{f[0]}"
                        try:
                            fo = _pym.Font(fontbuffer=buf)
                        except Exception:
                            fo = None
                        break
            asc = 0.86
            if fo is not None:
                try:
                    a = float(getattr(fo, "ascender", 0.86))
                    if 0.2 < a < 1.6:
                        asc = a
                except Exception:
                    pass
            bb = span_bbox or (0, 0, 0, 0)
            baseline = float(bb[1]) + asc * size
            if fpath:
                return {"name": name, "file": fpath}, baseline
            if buf:
                return {"name": name, "buffer": buf}, baseline
            return None, baseline
        except Exception:
            bb = span_bbox or (0, 0, 0, 0)
            size = float(span_size or 10.0)
            return None, float(bb[3]) - size * 0.15

    def _start_inline_text(self, page, pt, oid=None, line=None):
        """在页面位置显示 inline 文字输入框（字体/字号/颜色）。
        oid 非空 = 编辑既有浮动文字对象；line 非空 = 就地修改 PDF 原有文字行。"""
        if not self._require_permission(pymupdf.PDF_PERM_MODIFY, "编辑文档"):
            return
        from PySide6.QtWidgets import (QTextEdit, QFontComboBox, QSpinBox,
                                      QPushButton, QHBoxLayout, QVBoxLayout,
                                      QCheckBox)
        from PySide6.QtGui import QFont
        self._close_inline_editor()

        existing = None
        line_target = None
        zoom = self.page_view._zoom
        if oid is not None:
            existing = next((o for o in self.objects if o["id"] == oid), None)
        if existing is not None:
            wx = int(existing["rect"].x() * zoom)
            wy = int(self.page_view._offsets[page] +
                     existing["rect"].y() * zoom)
            init_text = existing.get("text", "")
            init_family = existing.get("fontfamily", "")
            init_size = existing.get("fontsize", 10)
            cur_color = existing.get("color") or QColor(self.edit_color)
            init_bold = existing.get("bold", False)
            init_italic = existing.get("italic", False)
        elif line is not None:
            # 就地编辑 PDF 原文字行：编辑条尽量对准点击行的视觉位置
            lr = line["rect"]
            line_target = (int(page), QRectF(lr))
            wx = int(lr.x() * zoom)
            lh = lr.height() * zoom
            wy = int(self.page_view._offsets[page] +
                     lr.y() * zoom + lh * 0.5 - 22)
            init_text = str(line.get("text", ""))
            fmt = self._detect_format_at(page, pt)
            init_family = fmt["family"] or ""
            init_size = int(round(fmt["size"]))
            cur_color = fmt["color"]
            init_bold = fmt["bold"]
            init_italic = fmt["italic"]
        else:
            wx = int(pt.x() * zoom)
            wy = int(self.page_view._offsets[page] + pt.y() * zoom)
            init_text = ""
            fmt = self._detect_format_at(page, pt)
            init_family = fmt["family"]
            init_size = int(round(fmt["size"]))
            cur_color = fmt["color"]
            init_bold = fmt["bold"]
            init_italic = fmt["italic"]
        self._editing_line = line_target

        # toolbar 父级 = 滚动视口，坐标用视口像素而非内容坐标：
        # 防止页面比窗口窄时 AlignCenter 把 toolbar 推到 page_view 之外被裁掉。
        box = QWidget(self.scroll.viewport())
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
        edit.setPlaceholderText(i18n.tr("replace_input_hint"))
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
        btn_color = QPushButton(i18n.tr("color_btn"))
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

        btn_ok = QPushButton(i18n.tr("confirm"))
        btn_ok.setObjectName("inlineTextOk")
        btn_ok.setDefault(True)
        btn_ok.setFixedWidth(68)
        btn_cancel = QPushButton(i18n.tr("cancel"))
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
        # 把内容坐标 (wx, wy) 换算成视口像素坐标，并按视口尺寸 clamp。
        # 当页面比窗口窄时，QScrollArea 居中对齐，page_view 之外有一段空白；
        # 若 box 还按内容坐标定位 + 父级 = page_view，超出 page_view 宽度的右半
        # 截会落在视口空白区里被裁掉。父级改为 viewport 后这里直接用视口像素。
        vp = self.scroll.viewport()
        h_off = self.scroll.horizontalScrollBar().value()
        v_off = self.scroll.verticalScrollBar().value()
        align_h = max(0, (vp.width() - self.page_view.width()) // 2)
        align_v = max(0, (vp.height() - self.page_view.height()) // 2)
        vp_x = int(wx) - h_off + align_h
        vp_y = int(wy) - v_off + align_v
        vp_w = max(100, vp.width())
        vp_h = max(100, vp.height())
        vp_x = max(4, min(vp_x, vp_w - box_w - 4))
        vp_y = max(4, min(vp_y, vp_h - box_h - 4))
        box.move(vp_x, vp_y)
        box.show()
        edit.setFocus()
        edit.selectAll()

        def on_ok():
            text = edit.text()
            family = font_combo.currentFont().family()
            size = size_spin.value()
            color = color_state["color"]
            bold = bold_check.isChecked()
            italic = italic_check.isChecked()
            target = line_target
            self._close_inline_editor()
            if not text.strip():
                if existing is not None:
                    self.delete_object(oid)
                elif target is not None:
                    self._commit_edited_line(
                        target[0], target[1], "", family, size,
                        color, bold, italic)
                return
            if existing is not None:
                self.begin_undo_step()
                existing["text"] = text
                existing["fontfamily"] = family
                existing["fontsize"] = size
                existing["color"] = color
                existing["bold"] = bold
                existing["italic"] = italic
                self.modified = True
                self._refresh_objects()
                self.page_view.select(oid)
            elif target is not None:
                self._commit_edited_line(
                    target[0], target[1], text, family, size,
                    color, bold, italic)
            else:
                self._add_text_object(text, page, pt, family, size, color, bold,
                                      italic, keep_mode=True)

        btn_ok.clicked.connect(on_ok)
        edit.returnPressed.connect(on_ok)
        edit.installEventFilter(self)
        btn_cancel.clicked.connect(self._close_inline_editor)
        self._inline_box = box
        self._inline_edit = edit
        self._inline_oid = oid

    def _commit_edited_line(self, page, rect, text, fontfamily, fontsize, color,
                            bold, italic, embed=None, baseline=None):
        """就地编辑结果写回 PDF：擦除原行文字，在相同位置叠加新文字浮层。

        embed/baseline 由 _prepare_row_embed 提供，用于保存时以原字体、
        原基线高度写回，保证最终 PDF 观感贴近原文；为空则走 htmlbox。
        """
        fr = pymupdf.Rect(rect.x(), rect.y(), rect.right(), rect.bottom())
        self.begin_undo_step(document_change=True)
        backend.redact_rect(self.doc[int(page)], fr)
        self.modified = True
        if not text.strip():
            self._refresh()
            self.statusMessage.emit(
                i18n.tr("replace_deleted").format(p=int(page) + 1), 3000)
            return
        self._obj_counter += 1
        # 新文字可能比原文更长：把对象矩形放宽到能容纳整行内容，
        # 否则保存（按矩形排版）时会把长句折成两行。按字符数估算宽度，
        # 东亚字约 1.0em、西文约 0.55em，与 Qt/PDF 设备无关，稳定可靠。
        size_pt = max(4.0, float(fontsize or 10.0))
        est_w = sum(
            size_pt if ord(ch) > 0x2E80 else size_pt * 0.55
            for ch in text) * 1.06 + 6.0
        obj_w = max(rect.width(), est_w)
        obj_h = max(rect.height(), size_pt * 1.3 + 2.0)
        self.objects.append({
            "id": self._obj_counter, "page": int(page),
            "rect": QRectF(rect.x(), rect.y(),
                           max(obj_w, 40.0), max(obj_h, 20.0)),
            "text": text,
            "color": color if color is not None else QColor(0, 0, 0),
            "fontsize": fontsize, "fontfamily": fontfamily,
            "bold": bold, "italic": italic, "kind": "text",
            "embed": embed, "baseline": baseline,
        })
        self._refresh()
        self.page_view.select(self._obj_counter)
        self.statusMessage.emit(
            i18n.tr("replace_done").format(p=int(page) + 1), 3000)

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

    def _add_object(self, img, kind, page, pt, base_w):
        aspect = img.height() / max(1, img.width())
        h = base_w * aspect
        self.begin_undo_step()
        self._obj_counter += 1
        self.objects.append({
            "id": self._obj_counter, "page": page,
            "rect": QRectF(pt.x(), pt.y(), base_w, h),
            "img": img, "png": qimage_to_png_bytes(img), "kind": kind,
            "opacity": 1.0,
        })
        self.modified = True
        self.set_mode("view")
        self._refresh_objects()
        self.page_view.select(self._obj_counter)

    def _add_text_object(self, text, page, pt, fontfamily="", fontsize=12, color=None,
                         bold=False, italic=False, keep_mode=False):
        rect = self._measure_text_rect(text, fontfamily, fontsize, bold, italic)
        rect.moveTo(pt.x(), pt.y())
        self.begin_undo_step()
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
        if self._find_object(oid) is None:
            return
        self.begin_undo_step()
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
        if obj.get("kind") == "image":
            self._edit_image_object(oid)
            return
        if obj.get("kind") != "text":
            return
        self._start_inline_text(
            obj["page"], QPointF(obj["rect"].x(), obj["rect"].y()), oid)

    def _edit_image_object(self, oid):
        from edit_image_dialog import EditImageDialog
        obj = self._find_object(oid)
        if obj is None or obj.get("kind") != "image":
            return
        initial_opacity = float(obj.get("opacity", 1.0))
        dlg = EditImageDialog(obj, self)

        def _live_apply(opacity):
            # 拖动透明度时直接在页面呈现效果（不落 undo，取消时回滚）
            obj["opacity"] = float(opacity)
            self.page_view.update()

        dlg.opacityChanged.connect(_live_apply)
        dlg.exec()
        res = dlg.result()
        if not res:
            # 取消：恢复初始透明度
            obj["opacity"] = initial_opacity
            self.page_view.update()
            return
        # ("ok", opacity)
        _, new_opacity = res
        self.begin_undo_step()
        obj["opacity"] = float(new_opacity)
        self.modified = True
        self.page_view.select(oid)
        self._refresh_objects()
        self.statusMessage.emit(i18n.tr("image_edited"), 3000)

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
            self.begin_undo_step()
            obj["text"] = text
            self.modified = True
            self.page_view.select(oid)
            self.statusMessage.emit(i18n.tr("note_updated"), 3000)

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
            self.begin_undo_step()
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
            self.begin_undo_step()
            obj["color"] = QColor(c)
            self.edit_color = QColor(c)
            self.modified = True
            self._refresh_objects()
            self.page_view.select(oid)
            self.statusMessage.emit("标注颜色已更新", 3000)

    def _refresh_objects(self):
        self.page_view.set_objects(self._objects_for_current_page())

    def _on_object_changed(self, oid, rect, old_rect=None):
        if not (self.permission_allowed(pymupdf.PDF_PERM_MODIFY) or
                self.permission_allowed(pymupdf.PDF_PERM_ANNOTATE)):
            self.statusMessage.emit("文档安全设置禁止移动或缩放对象", 4000)
            self._refresh_objects()
            return
        obj = self._find_object(oid)
        if obj is None:
            return
        new_rect = QRectF(rect)
        if old_rect is not None:
            old_rect = QRectF(old_rect)
            if old_rect == new_rect:
                return
            # PageView 与此处共享对象字典，鼠标拖动时对象已是新矩形。
            # 临时恢复旧值后记录，保证撤销回到拖动开始的位置。
            obj["rect"] = old_rect
            self.begin_undo_step()
        elif QRectF(obj["rect"]) != new_rect:
            self.begin_undo_step()
        obj["rect"] = new_rect
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
        self.pending_sign_match_image_scale = False
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
        self._viewport_pan_last = None
        self.scroll.viewport().setCursor(
            Qt.CursorShape.OpenHandCursor
            if key == "view" and self.doc is not None
            else Qt.CursorShape.ArrowCursor)
        if getattr(self, "_row_edit", None) is not None:
            # 行内就地编辑未提交时，切换模式/工具前先把改动写回 PDF，
            # 避免用户在另一行继续操作后丢失上一处修改。
            self._commit_row_edit(commit=True)
        if getattr(self, "_inplace_edit", None) is not None:
            # 「文本」工具就地输入未提交时，换工具/换模式前先写入文档。
            self._commit_inplace_text(commit=True)
        self._close_inline_editor()
        for k, act in self.mode_actions.items():
            act.setChecked(k == key)
        self.page_view.set_mode(MODE_VIEW[key])
        overlay = bool(key == "replace_text" and self.doc is not None)
        self.page_view.set_edit_overlay(overlay)
        if overlay:
            self.page_view.setCursor(Qt.CursorShape.IBeamCursor)
            self.statusMessage.emit(i18n.tr("replace_text_hint"), 6000)

    def _check_none(self):
        for act in self.mode_actions.values():
            act.setChecked(False)

    def apply_language(self):
        """同步文档视图中的静态文字，不重建文档或页面状态。"""
        self.side_tabs.setTabText(0, i18n.tr("pages"))
        self.side_tabs.setTabText(1, i18n.tr("outline"))
        self.outline_hint.setText(i18n.tr("outline_empty"))
        # 已打开文档的目录页码也包含本地化文字（例如 p. 2 / 第 2 页），
        # 切换语言时重新载入目录，避免树中继续保留旧语言。
        if self.doc is not None:
            self._load_outline()
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
                self.begin_undo_step()
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
            QMessageBox.warning(self, i18n.tr("hint"),
                                i18n.tr("image_read_failed"))
            return False
        if page is not None and pt is not None:
            self._add_object(img, "image", int(page), QPointF(pt), 160.0)
            self.statusMessage.emit(
                i18n.tr("image_inserted").format(p=int(page) + 1), 3000)
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
        width = self._image_placement_width(img, page)
        height = width * aspect
        x = page_rect.x0 + max(0.0, (page_rect.width - width) / 2)
        # 工具栏和菜单插入时置于页面上部中央，既醒目又留出页边距。
        top_margin = min(72.0, max(24.0, page_rect.height * 0.08))
        y = min(page_rect.y1 - height,
                page_rect.y0 + top_margin)
        return page, QPointF(x, y), width

    def _image_placement_width(self, img, page):
        """返回与“插入图片”一致的等比初始显示宽度。"""
        page = max(0, min(int(page), len(self.doc) - 1))
        page_rect = self.doc[page].rect
        aspect = img.height() / max(1, img.width())
        width = min(160.0, page_rect.width * 0.42)
        if aspect > 0:
            width = min(width, page_rect.height * 0.46 / aspect)
        return max(24.0, width)

    def start_sign(self):
        if not self._require_permission(pymupdf.PDF_PERM_ANNOTATE, "添加签名"):
            return
        dlg = SignatureDialog(self)
        if dlg.exec() != SignatureDialog.DialogCode.Accepted:
            return
        img = dlg.result_image()
        if img is None or img.isNull():
            return
        self._prepare_sign(img, match_image_scale=dlg.is_imported_image())

    def open_sign_lib(self):
        if not self._require_permission(pymupdf.PDF_PERM_ANNOTATE, "添加签名"):
            return
        dlg = SignatureLibraryDialog(self)
        if dlg.exec() != SignatureLibraryDialog.DialogCode.Accepted:
            return
        img = dlg.result_image()
        if img is None or img.isNull():
            return
        # 签名库保存原图；放入页面时采用与“插入图片”相同的等比缩放。
        self._prepare_sign(img, match_image_scale=True)

    def _prepare_sign(self, img, match_image_scale=False):
        self.pending_sign_qimg = img.copy()
        self.pending_sign_match_image_scale = bool(match_image_scale)
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
                prompt = i18n.tr("delete_page_confirm").format(n=pno + 1)
            else:
                prompt = i18n.tr("delete_selected_pages_confirm").format(
                    n=len(page_set))
            answer = QMessageBox.question(self, i18n.tr("delete_page"), prompt)
            if answer != QMessageBox.StandardButton.Yes:
                return False

        current = self.page_view.current_page()
        target = current - sum(1 for p in page_set if p < current)
        target = max(0, min(target, len(self.doc) - len(page_set) - 1))
        self.begin_undo_step(document_change=True)
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
    def _render_print_page(self, page_no, zoom, rot=0, want_gray=False, doc=None):
        """渲染单个 PDF 页为 QImage（打印用）。

        边长上限 2000px：避免超大位图在部分打印机驱动
        （如 EPSON GDI）下破坏打印流导致空白页。
        返回 RGB32 格式 QImage（驱动兼容性最好）。
        doc：外部 pymupdf Document（多文档拼版用）；默认当前 self.doc。
        """
        use_doc = doc if doc is not None else self.doc
        page = use_doc[page_no]
        pr_w = max(page.rect.width, page.rect.height)
        if pr_w * zoom > 2000:
            zoom *= 2000 / (pr_w * zoom)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom),
                              alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format.Format_RGB888).copy()
        img = img.convertToFormat(QImage.Format.Format_RGB32)
        if rot:
            img = img.transformed(QTransform().rotate(rot))
        if want_gray:
            img = img.convertToFormat(QImage.Format.Format_Grayscale8)
            img = img.convertToFormat(QImage.Format.Format_RGB32)
        return img

    def print_pdf(self):
        """打印：同一个文档的多页按 N 页/张 排版（N-up），预览同步。"""
        if self.doc is None:
            QMessageBox.information(self, i18n.tr("hint"),
                                    i18n.tr("need_open_pdf"))
            return
        if not self._require_permission(pymupdf.PDF_PERM_PRINT, i18n.tr("menu_print")):
            return
        from print_dialog import (PrintDialog, ALIGN_CENTER, ALIGN_TOP_CENTER,
                                  ALIGN_BOTTOM_CENTER, _nup_grid,
                                  SCALE_ACTUAL, SCALE_CUSTOM)
        dlg = PrintDialog(self.doc, self)
        if dlg.exec() != PrintDialog.DialogCode.Accepted:
            return
        printer = dlg.result_printer()
        if printer is None:
            return

        scale_mode = dlg.scale_mode()
        custom_scale = dlg.scale_percent()
        alignment = dlg.alignment()
        nup = dlg.pages_per_sheet()   # 每张纸页数：1/2/4
        rot = dlg.rotation()
        want_gray = dlg.grayscale()

        # 页面范围（自定义对话框决定）
        total = len(self.doc)
        if dlg.print_current_only():
            cur = max(0, self.page_view.current_page())
            from_page = to_page = min(cur, total - 1)
        elif dlg.custom_range():
            f, t = dlg.custom_range()
            from_page = max(0, f - 1)
            to_page = min(total - 1, t - 1)
        else:
            from_page, to_page = 0, total - 1
        pages = list(range(from_page, to_page + 1))
        if dlg.reverse_order():
            pages.reverse()
        copies = max(1, dlg.copies())
        all_pages = []
        for _ in range(copies):
            all_pages.extend(pages)
        if not all_pages:
            return

        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.critical(self, i18n.tr("hint"),
                                 i18n.tr("print_failed"))
            return
        try:
            page_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
            res = max(72, printer.resolution())
            cols, rows = _nup_grid(nup)
            cell_w = page_rect.width() / cols
            cell_h = page_rect.height() / rows

            placed = 0
            is_first_sheet = True
            for page_no in all_pages:
                # 每张纸的首个页面才 newPage（同一张纸内不 newPage）
                if placed == 0 and not is_first_sheet:
                    printer.newPage()
                is_first_sheet = False

                col = placed % cols
                row = placed // cols
                cell = QRectF(page_rect.x() + col * cell_w,
                              page_rect.y() + row * cell_h,
                              cell_w, cell_h)

                img = self._render_print_page(
                    page_no, res / 72.0, rot, want_gray)
                iw, ih = img.width(), img.height()

                # 缩放（多页时在单元格内生效）
                if scale_mode == SCALE_ACTUAL:
                    dw, dh = iw * 72.0 / res, ih * 72.0 / res
                elif scale_mode == SCALE_CUSTOM:
                    dw, dh = iw * 72.0 / res * custom_scale, \
                        ih * 72.0 / res * custom_scale
                else:
                    scale = min(cell.width() / iw, cell.height() / ih)
                    dw, dh = iw * scale, ih * scale

                # 位置：水平居中，垂直按选择对齐（单元格内）
                if alignment == ALIGN_TOP_CENTER:
                    x = cell.x() + (cell.width() - dw) / 2
                    y = cell.y()
                elif alignment == ALIGN_BOTTOM_CENTER:
                    x = cell.x() + (cell.width() - dw) / 2
                    y = cell.y() + cell.height() - dh
                else:
                    x = cell.x() + (cell.width() - dw) / 2
                    y = cell.y() + (cell.height() - dh) / 2

                # QPixmap int 重载：Windows GDI 兼容
                painter.drawPixmap(int(x), int(y), int(dw), int(dh),
                                   QPixmap.fromImage(img))

                placed += 1
                if placed >= nup:
                    placed = 0

            self.statusMessage.emit(i18n.tr("print_job_sent"), 3000)
        finally:
            painter.end()

    # ================= 事件过滤器 =================
    def _pan_document(self, delta):
        """按抓手拖动方向同步平移水平和垂直滚动条。"""
        if self.doc is None:
            return
        hbar = self.scroll.horizontalScrollBar()
        vbar = self.scroll.verticalScrollBar()
        hbar.setValue(hbar.value() - int(round(delta.x())))
        vbar.setValue(vbar.value() - int(round(delta.y())))

    def eventFilter(self, obj, event):
        if obj is getattr(self, "_row_edit", None):
            if event.type() == QEvent.Type.KeyPress and \
                    event.key() == Qt.Key.Key_Escape:
                # 就地行编辑：Esc 仅取消本次编辑，不写回
                self._commit_row_edit(commit=False)
                self.page_view.setFocus()
                return True
            if event.type() == QEvent.Type.FocusOut:
                # 点击页面其它处 / 其它行：把当前行改动提交写回；
                # 置位标记避免随后 textLineClicked(None) 重复提示。
                self._row_focus_pending = True
                self._commit_row_edit(commit=True)
                return False
        if obj is getattr(self, "_inline_edit", None):
            if event.type() == QEvent.Type.KeyPress and \
                    event.key() == Qt.Key.Key_Escape:
                # 就地编辑条内按 Esc 仅收起编辑条（不切回选择工具）
                self._close_inline_editor()
                return True
        if obj is getattr(self, "_inplace_edit", None):
            if event.type() == QEvent.Type.KeyPress and \
                    event.key() == Qt.Key.Key_Escape:
                # 「文本」工具就地输入：Esc 取消本次输入，不写入文档
                self._commit_inplace_text(commit=False)
                self.page_view.setFocus()
                return True
            if event.type() == QEvent.Type.FocusOut:
                # 点击页面其它处 / 切换工具：把就地输入的内容写入文档
                self._commit_inplace_text(commit=True)
                return False
        if obj is self.scroll.viewport():
            if event.type() == QEvent.Type.Wheel:
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    delta = event.angleDelta().y()
                    if delta > 0:
                        self.zoom_in()
                    else:
                        self.zoom_out()
                    return True
            elif event.type() == QEvent.Type.MouseButtonPress and \
                    event.button() == Qt.MouseButton.LeftButton and \
                    self.doc is not None and self.current_mode == "view":
                # PageView 之外的灰色边缘同样可以抓住拖动。
                self._viewport_pan_last = QPointF(event.globalPosition())
                self.scroll.viewport().setCursor(
                    Qt.CursorShape.ClosedHandCursor)
                return True
            elif event.type() == QEvent.Type.MouseMove and \
                    self._viewport_pan_last is not None:
                if not (event.buttons() & Qt.MouseButton.LeftButton):
                    self._viewport_pan_last = None
                    self.scroll.viewport().setCursor(
                        Qt.CursorShape.OpenHandCursor)
                    return True
                global_pos = QPointF(event.globalPosition())
                self._pan_document(global_pos - self._viewport_pan_last)
                self._viewport_pan_last = global_pos
                return True
            elif event.type() == QEvent.Type.MouseButtonRelease and \
                    event.button() == Qt.MouseButton.LeftButton and \
                    self._viewport_pan_last is not None:
                self._viewport_pan_last = None
                self.scroll.viewport().setCursor(
                    Qt.CursorShape.OpenHandCursor)
                return True
        return super().eventFilter(obj, event)
