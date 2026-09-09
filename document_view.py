"""单个文档的视图：连续滚动页面 + 缩略图侧栏 + 编辑逻辑。"""
import os
import re
import copy
import time
import errno
import pymupdf
from PySide6.QtCore import (Qt, QSize, QRect, QRectF, QPointF, Signal,
                            QEvent, QTimer, QItemSelectionModel)
from PySide6.QtGui import (QIcon, QPixmap, QImage, QPainter, QColor, QPen,
                           QFont, QTransform, QKeySequence, QShortcut,
                           QCursor, QTextCursor)
from PySide6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QSplitter,
                               QScrollArea, QListWidget, QListWidgetItem,
                               QTabWidget, QStackedWidget, QFrame, QPushButton,
                               QLabel, QLineEdit, QFileDialog, QMessageBox,
                               QInputDialog, QApplication, QMenu, QColorDialog,
                               QGraphicsDropShadowEffect, QAbstractItemView,
                               QStyledItemDelegate, QStyleOptionViewItem, QStyle,
                               QTreeWidget, QTreeWidgetItem)
from PySide6.QtPrintSupport import QPrinter

import backend
import i18n
from page_view import PageView
from rich_text import (RichEditBox, PdfRowEditBox, merge_runs, runs_text, single_run,
                       runs_all_same_style, _qt_safe_family)
from sign_dialog import (SignatureDialog, SignatureLibraryDialog,
                         SignatureFontComboBox, qimage_to_png_bytes)
from slide_show import SlideShowWindow

# ---- 诊断后门（仅 DO_LIVE_DIAG=1 时启用）：记录 live 写回每段字体决策，
# 并自动保存编辑中的 PDF 快照，供"方块/变大"类问题做字形级取证 ----
def _live_diag_dir(meta):
    if not (meta and isinstance(meta, dict)):
        return None
    d = meta.get("_diag")
    if d and os.path.isdir(d.get("dir", "")):
        return d
    if not os.environ.get("DO_LIVE_DIAG"):
        return None
    try:
        di = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "_live_diag")
        os.makedirs(di, exist_ok=True)
        d = {"dir": di, "seq": 0}
        meta["_diag"] = d
        # 清掉旧日志
        open(os.path.join(di, "_live_diag.log"), "w",
             encoding="utf-8").write("=== live diag %s ===\n"
                                     % time.strftime("%H:%M:%S"))
        return d
    except Exception:
        return None


def _live_diag_log(meta, line):
    d = _live_diag_dir(meta)
    if not d:
        return
    try:
        with open(os.path.join(d["dir"], "_live_diag.log"), "a",
                  encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _live_diag_snap(doc, meta, tag):
    d = _live_diag_dir(meta)
    if not d:
        return
    try:
        d["seq"] += 1
        path = os.path.join(d["dir"], "step_%03d_%s.pdf"
                            % (d["seq"], tag))
        with open(path, "wb") as f:
            f.write(doc.tobytes())
    except Exception:
        pass

MODE_DEFS = [
    ("view",         "选择",     "view",  "select"),
    ("text_select",  "快捷复制", "rect",  "text_select"),
    # 内部键名为兼容旧设置继续使用 replace_text；界面统一称“编辑模式”。
    ("replace_text", "编辑模式", "point", "edit"),
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
                                      QHBoxLayout, QCheckBox)
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

    def __init__(self, parent=None, record=None):
        super().__init__(parent)
        self._record = record or None
        self.setWindowTitle(i18n.tr(
            "modify_watermark" if record else "add_watermark"))
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
        if record:
            self._load_record(record)
        else:
            self._on_type_changed(0)

    def _load_record(self, record):
        kind = record.get("kind", "text")
        # 无法从外部结构确定类型时，以可编辑的文字水印作为安全默认值。
        is_image = kind == "image"
        self._type_combo.setCurrentIndex(1 if is_image else 0)
        if record.get("text"):
            self._text_edit.setText(str(record["text"]))
        self._size_spin.setValue(max(
            self._size_spin.minimum(), min(self._size_spin.maximum(),
            int(round(float(record.get("fontsize", 50)))))))
        color = record.get("color")
        if isinstance(color, (list, tuple)) and len(color) >= 3:
            self._color = QColor.fromRgbF(
                float(color[0]), float(color[1]), float(color[2]))
            self._style_color_btn()
        self._opacity_slider.setValue(max(
            5, min(100, int(round(float(record.get("opacity", 0.3)) * 100)))))
        self._rotate_spin.setValue(max(
            0, min(360, int(round(float(record.get("rotate", 45)))))))
        self._tiled_check.setChecked(bool(record.get("tiled", True)))
        self._scale_spin.setValue(max(
            5, min(100, int(round(float(record.get("scale", 0.5)) * 100)))))
        if is_image:
            self._img_label.setText(
                str(record.get("image_name") or i18n.tr("watermark_embedded_image")))
        self._on_type_changed(self._type_combo.currentIndex())

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
        self._row_edit = None        # 就地行编辑 QLineEdit（无弹窗工具条）
        self._row_edit_meta = None   # {page, rect, text, fmt} 行编辑元数据
        self._row_live_busy = False  # 行编辑 live 写回重入保护
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
            self._on_window_fit_timeout)
        # 就地编辑（行/新增文字/对象文字）期间收到窗口尺寸变化：自动适宽
        # 会缩放整页并令透明编辑层与 PDF 行脱位（Acrobat 编辑中从不缩放
        # 页面），因此改为挂起，待编辑框关闭后再补一次适配。
        self._fit_after_edit = False
        self._fit_after_edit_mode = "width"
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
        self.page_view.objectRotated.connect(self._on_object_rotated)
        self.page_view.pdfImageChanged.connect(self._on_pdf_image_changed)
        self.page_view.pdfImageRotated.connect(self._on_pdf_image_rotated)
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
        self._load_native_annotations()
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

    @staticmethod
    def _atomic_replace(src, dst, max_retries=4):
        """把 src 原子替换到 dst。

        Windows 上 os.replace 经常因为目标文件正被另一个进程持有读/写
        句柄（PDF 阅读器/浏览器内嵌预览/AV 扫描/OneDrive 同步等）而抛
        ``WinError 5 (ERROR_ACCESS_DENIED)`` / ``PermissionError``。
        这种占用通常是临时的——其他进程在亚秒级时间内完成读取或索引后
        会释放句柄——所以用短退避重试几次大多能成功。最大 4 次退避
        0.15+0.3+0.6+1.2 ≈ 2.25s；其他错误（路径不存在等）立即抛。
        """
        delays = (0.0, 0.15, 0.3, 0.6, 1.2)[: max_retries + 1]
        last_err = None
        for delay in delays:
            if delay:
                time.sleep(delay)
            try:
                os.replace(src, dst)
                return
            except (PermissionError, OSError) as e:
                last_err = e
                winerr = getattr(e, "winerror", None)
                errno_code = getattr(e, "errno", None) or e.errno
                # 仅对 AccessDenied (winerror 5 / errno EACCES|EPERM)
                # 继续重试；其他错误立即抛出，避免无意义延迟。
                if winerr != 5 and errno_code not in (
                        errno.EACCES, errno.EPERM):
                    break
        assert last_err is not None
        raise last_err

    def save(self):
        if self.doc is None:
            return False
        if self.file_path:
            return self._save_to(self.file_path)
        else:
            return self.save_as()

    def save_as(self):
        if self.doc is None:
            return False
        path, _ = QFileDialog.getSaveFileName(self, "另存为", "未命名.pdf",
                                              "PDF 文件 (*.pdf)")
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        return self._save_to(path)

    def _save_to(self, path):
        try:
            # 就地编辑未提交时先写回文档：点工具栏保存按钮会先触发编辑框
            # 失焦提交，但 Ctrl+S 快捷键保存时编辑框不失焦——这里统一兜底，
            # 保证保存不丢失行内修改/就地新增的文字。
            if getattr(self, "_row_edit", None) is not None:
                self._commit_row_edit(commit=True)
            if getattr(self, "_inplace_edit", None) is not None:
                self._commit_inplace_text(commit=True)
            self._bake_objects()
            # 保存前子集化嵌入字体：把保存时新嵌入的系统全量字体（雅黑
            # ttc 约 20MB，仅原文档字形兜底时才嵌入）裁成只含本档实际用到
            # 的字形，避免输出文件暴涨数十倍、压缩写盘拖慢保存。实测单个
            # 大字体 subset 约 40ms，收益远大于开销；失败则跳过（保正确）。
            try:
                self.doc.subset_fonts()
            except Exception:
                pass
            tmp = path + ".tmp"
            recover = path + ".recover.pdf"
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
            try:
                self._atomic_replace(tmp, path)
            except OSError as e:
                # 保存到目标失败。此刻 self.doc 已被 close（写临时文件后
                # 必须先释放句柄才能替换目标）。若放任不管，self.doc 就
                # 永远停在“已关闭”状态——视图层任何重绘/鼠标移动都会因
                # 访问已关闭文档抛 ValueError: document closed 而崩溃。
                # 因此必须立刻把文档恢复到可用状态：
                #   1) 把 tmp 改名为 path + ".recover.pdf"（doc 未占用
                #      tmp，rename 几乎必然成功）作为新载体；
                #   2) 从该文件重新打开文档——内含用户最新修改，不丢数据；
                #   3) 使用固定恢复名，二次失败会覆盖同名旧备份，不积累
                #      垃圾；且下次保存写的是新的 .tmp，不会与 doc 自身
                #      打开的文件冲突（PyMuPDF 禁止 save 到自身文件）。
                restored = False
                try:
                    if os.path.exists(recover):
                        os.remove(recover)  # doc 已 close，旧备份句柄已释放
                except OSError:
                    pass
                try:
                    os.replace(tmp, recover)
                    self.doc = backend.open_pdf(recover, reopen_password)
                    self._load_native_annotations()
                    restored = True
                except Exception:
                    # rename 极罕见失败（如 AV 恰好扫到 tmp）：退而直接从
                    # tmp 打开，宁可下次保存前再处理也不让 doc 停在 closed。
                    try:
                        self.doc = backend.open_pdf(tmp, reopen_password)
                        self._load_native_annotations()
                        restored = True
                    except Exception:
                        self.doc = None
                if restored:
                    self._undo_pdf_cache = None
                    # 视图层仍指向旧（已 closed）doc 对象：立即重绑到
                    # 恢复的新文档，避免 paintEvent 等访问旧对象。
                    self._refresh()
                else:
                    try:
                        if os.path.exists(tmp):
                            os.remove(tmp)
                    except OSError:
                        pass
                hint = ""
                winerr = getattr(e, "winerror", None)
                errno_code = getattr(e, "errno", None) or e.errno
                if winerr == 5 or errno_code in (errno.EACCES, errno.EPERM):
                    hint = ("\n\n可能原因：目标文件正被其他程序占用。"
                            "\n请关闭占用该 PDF 的程序（PDF 阅读器、"
                            "浏览器内嵌预览、OneDrive/坚果云等网盘同步、"
                            "防病毒软件等），再重新保存。")
                elif "系统找不到指定的文件" in str(e) or "No such file" in str(e):
                    hint = "\n\n可能原因：目标目录不存在或无写入权限。"
                backup_note = (f"\n\n您这次的修改没有丢失，已安全保留在：\n"
                               f"{recover if restored else tmp}") if restored else ""
                raise RuntimeError(
                    f"保存失败：{e}{backup_note}{hint}") from e
            self.doc = backend.open_pdf(path, reopen_password)
            self._load_native_annotations()
            # 本次保存成功：清理此前保存失败遗留的 .recover.pdf 备份。
            # （其句柄已在本次 doc.save 后的 close 中释放，可安全删除。）
            try:
                if os.path.exists(recover):
                    os.remove(recover)
            except OSError:
                pass
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
            # 保存成功即退出就地文本编辑型工具状态（修改文字/添加文字），
            # 自动回到选择模式——无需再手动按 Esc 退出编辑状态。
            if self.current_mode in ("replace_text", "text"):
                self.set_mode("view")
            return True
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：\n{e}")
            return False

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
                # 编辑中的文档不能压缩 / 重排 xref：MuPDF 的字体缓存仍引用
                # 原编号，下一次 TextWriter 写入会把字形引用到其他对象。
                # 对象整理只在保存并立即重新打开文档时进行。
                garbage=0, deflate=True,
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
            # 保存后从 PDF 重新载入的原生批注只是一个可交互代理；其内容
            # 已经存在于 PDF 中，不能再次写入，否则每保存一次就会复制一份。
            if obj.get("native_proxy"):
                continue
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
                runs = obj.get("runs")
                if runs and not runs_all_same_style(runs):
                    # 字符级混排对象：逐段按 span 写回，保留局部粗斜/颜色/字体
                    backend.insert_rich_text_auto(page, fr, runs)
                    continue
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
                image_bytes = obj["png"]
                angle = float(obj.get("rotation", 0.0))
                if abs(angle) > 1e-7:
                    # 保存前的图片/签名以透明画布旋转后写入其外接矩形；
                    # 页面显示尺寸与编辑模式预览一致，任意角度均可保存。
                    rotated = obj["img"].transformed(
                        QTransform().rotate(angle),
                        Qt.TransformationMode.SmoothTransformation)
                    image_bytes = qimage_to_png_bytes(rotated)
                    rad = __import__("math").radians(angle)
                    new_w = abs(r.width() * __import__("math").cos(rad)) + \
                        abs(r.height() * __import__("math").sin(rad))
                    new_h = abs(r.width() * __import__("math").sin(rad)) + \
                        abs(r.height() * __import__("math").cos(rad))
                    center = r.center()
                    fr = pymupdf.Rect(center.x() - new_w / 2,
                                      center.y() - new_h / 2,
                                      center.x() + new_w / 2,
                                      center.y() + new_h / 2)
                opacity = obj.get("opacity", 1.0)
                if opacity >= 1.0:
                    page.insert_image(fr, stream=image_bytes)
                else:
                    # PyMuPDF 的 alpha 参数是 int(0/1 有无透明)，不是透明度值；
                    # 把透明度固化到图像自身的 alpha 通道，保存/重开后依然生效。
                    from PIL import Image as _PILImage
                    from io import BytesIO as _BytesIO
                    _img = _PILImage.open(_BytesIO(image_bytes)).convert("RGBA")
                    _r, _g, _b, _a = _img.split()
                    _a = _a.point(lambda v: int(v * opacity))
                    _img = _PILImage.merge("RGBA", (_r, _g, _b, _a))
                    _buf = _BytesIO()
                    _img.save(_buf, format="PNG")
                    page.insert_image(fr, stream=_buf.getvalue())
        self.objects = []
        self._obj_counter = 0

    @staticmethod
    def _annotation_color(annot, fallback):
        """读取 PDF 批注颜色并转换为 Qt 颜色。"""
        try:
            values = (annot.colors or {}).get("stroke") or []
            if len(values) == 1:
                gray = max(0.0, min(1.0, float(values[0])))
                return QColor.fromRgbF(gray, gray, gray)
            if len(values) >= 3:
                return QColor.fromRgbF(
                    max(0.0, min(1.0, float(values[0]))),
                    max(0.0, min(1.0, float(values[1]))),
                    max(0.0, min(1.0, float(values[2]))))
        except Exception:
            pass
        return QColor(fallback)

    @staticmethod
    def _normalized_annotation_points(points, rect):
        if not points or rect.width() <= 0 or rect.height() <= 0:
            return []
        return [((float(p[0]) - rect.x()) / rect.width(),
                 (float(p[1]) - rect.y()) / rect.height())
                for p in points]

    def _load_native_annotations(self):
        """把 PDF 原生批注恢复成可选、可编辑的界面代理对象。

        页面本身仍负责绘制原生外观，代理只负责命中和后续操作。因此既
        不改变第三方 PDF 的批注外观，也不会在第二次保存时产生重复项。
        """
        self.objects = []
        self._obj_counter = 0
        if self.doc is None:
            return
        kinds = {
            pymupdf.PDF_ANNOT_TEXT: "note",
            pymupdf.PDF_ANNOT_HIGHLIGHT: "highlight",
            pymupdf.PDF_ANNOT_UNDERLINE: "underline",
            pymupdf.PDF_ANNOT_STRIKE_OUT: "strikeout",
            pymupdf.PDF_ANNOT_SQUARE: "rect",
            pymupdf.PDF_ANNOT_LINE: "line",
            pymupdf.PDF_ANNOT_INK: "ink",
        }
        for pno in range(len(self.doc)):
            page = self.doc[pno]
            try:
                annotations = list(page.annots() or [])
            except Exception:
                continue
            for annot in annotations:
                kind = kinds.get(int(annot.type[0]))
                if kind is None:
                    continue
                ar = annot.rect
                rect = QRectF(ar.x0, ar.y0, ar.width, ar.height)
                vertices = annot.vertices
                raw_points = []
                if kind in ("highlight", "underline", "strikeout") and vertices:
                    # 标记批注的外接 rect 含 MuPDF 外观留白；用四边形顶点
                    # 恢复用户原先框选的文字区域，移动后再次保存不会变大。
                    flat = list(vertices)
                    xs = [float(p[0]) for p in flat]
                    ys = [float(p[1]) for p in flat]
                    rect = QRectF(min(xs), min(ys),
                                  max(1.0, max(xs) - min(xs)),
                                  max(1.0, max(ys) - min(ys)))
                elif kind == "line" and vertices:
                    raw_points = list(vertices)
                elif kind == "ink" and vertices:
                    # 本编辑器创建的墨迹是一条 stroke；第三方多 stroke 墨迹
                    # 仍保留在 PDF 中，代理使用第一条进行命中和整体变换。
                    first = vertices[0] if isinstance(vertices[0], list) else vertices
                    raw_points = list(first)
                self._obj_counter += 1
                fallback = "#ff9f0a" if kind == "note" else (
                    "#ffd400" if kind == "highlight" else "#c81e1e")
                obj = {
                    "id": self._obj_counter,
                    "page": pno,
                    "rect": rect,
                    "kind": kind,
                    "color": self._annotation_color(annot, fallback),
                    "width": float((annot.border or {}).get("width", 1.5) or 1.5),
                    "points": self._normalized_annotation_points(raw_points, rect),
                    "native_proxy": True,
                    "native_xref": int(annot.xref),
                }
                if kind == "note":
                    obj["text"] = str((annot.info or {}).get("content", ""))
                    obj["img"] = self._note_marker_image(obj["color"])
                self.objects.append(obj)

    def _detach_native_annotation(self, obj):
        """删除代理对应的原生批注，使对象回到保存前的可绘制状态。"""
        xref = obj.get("native_xref")
        if not obj.get("native_proxy") or not xref or self.doc is None:
            return False
        try:
            page = self.doc[int(obj["page"])]
            annot = page.load_annot(int(xref))
            if annot is not None:
                page.delete_annot(annot)
        except Exception:
            return False
        obj.pop("native_proxy", None)
        obj.pop("native_xref", None)
        self._undo_pdf_cache = None
        return True

    def _bake_text_original_font(self, page, fr, obj, rgb):
        """以原字体写回修改后的整行文字，保证字形/字族与文档其它行一致。

        embed 的 name 为注册名，file/buffer 为字体来源；基线取原行重建值，
        使新文字与原行处于同一垂直位置。文字只按单行从左往右排（不折行），
        宽度超出部分在保存时由调用方按字符数估算的对象宽度承担。

        字形兜底：若新文本含所选字体没有的字形——典型场景包括把西文行改成
        中文（Arial/Helvetica 无中文字形）、或嵌入子集字体缺少改入的字符
        （如中文字体子集缺西文字母）——直接写回会渲染成方块，此时自动回退到
        系统全量字体（对象原字族 → 雅黑/宋体/黑体/等线/楷体/仿宋），保证保存
        后汉字/字母均正常显示；字号、颜色、基线保持不变，粗斜样式由所选
        变体字体文件承载。
        """
        text = obj.get("text", "")
        if not (text or "").strip():
            return
        embed = obj.get("embed") or {}
        fname = embed.get("name")
        if not fname:
            raise RuntimeError("no embed font name")
        # 注册名必须为纯字母数字；历史 embed 可能带空格/连字符
        # （如 "Microsoft Ya Hei"），直接 insert_font 会抛异常导致
        # 保存静默回退 htmlbox——这里统一清理。
        import re as _re2
        fname = _re2.sub(r"[^A-Za-z0-9]", "", fname) or "font"
        # —— 字形覆盖检测：文本含任一原字体没有的字形 → 换全量系统字体 ——
        # 不做“仅中文才检测”的门限：西文行、混排、嵌入子集缺字形同样会
        # 在保存后变方块，必须对全部非空白字符逐一校验。
        # 性能：Font(fontfile=…) 解析系统 TTC 很贵（雅黑 ~100-180ms），
        # 按来源(file 路径 / buffer 内容)缓存 Font，同一来源只解析一次；
        # insert_font 重复同名注册 PyMuPDF 内部已缓存(实测 0.1ms)。
        # buffer 来源沿用对象中已选好的嵌入字体；子集的 has_glyph
        # 不能直接用于判断覆盖情况。系统 file 来源照常校验字形。
        if embed.get("buffer"):
            covered = True
        else:
            try:
                fo = self._cached_embed_font(embed)
                covered = fo is not None and self._font_covers(fo, text)
            except Exception:
                covered = False
        if not covered:
            fname, embed = self._fallback_cjk_font(obj, text)
        # 页面若已注册同名资源，多半是原 PDF 嵌入的 CID/TrueType 子集
        # (只含原文档用过的字形)；直接复用会把新字形映射成 \x00 豆腐。
        # 用页内唯一名强制注册新的全量字体，保证新文本字形可用。
        # get_fonts(full=True) 元组: (xref, ext, type, basefont, name, ...),
        # 第 4 项 (f[3]) 是带子集前缀的 basefont, 第 5 项 (f[4]) 才是
        # insert_font 时使用的资源名, 与 fname 直接比较必须用 f[4]。
        if any((f[4] or "") == fname for f in page.get_fonts(full=True)):
            self._bake_font_seq = getattr(self, "_bake_font_seq", 0) + 1
            fname = f"{fname}{self._bake_font_seq}"
        try:
            if embed.get("file"):
                page.insert_font(fontname=fname, fontfile=embed["file"])
            elif embed.get("buffer"):
                page.insert_font(fontname=fname, fontbuffer=embed["buffer"])
            else:
                raise RuntimeError("no embed font source")
        except Exception:
            # 唯一名仍撞名(极少见); 留作最后兜底. 同样用 f[4] 资源名比较.
            fonts = page.get_fonts(full=True)
            if not any((f[4] or "") == fname for f in fonts):
                raise
        size = max(4.0, float(obj.get("fontsize") or 10.0))
        base = obj.get("baseline")
        if base is None:
            # 新增文字对象的 rect.y0 就是用户点击并在画布预览时看到的
            # 文字行顶部。旧实现从包含额外上下留白的 rect.y1 反推基线，
            # 保存后字形会随文本框高度整体下沉。PDF 字体的 span bbox 顶部
            # 等于 baseline - ascender * fontsize，因此按实际写入字体的升部
            # 指标从 rect.y0 计算基线，保存前后的行顶位置即可保持一致。
            try:
                font_metrics = self._cached_embed_font(embed)
                ascender = float(font_metrics.ascender)
                if not (0.5 <= ascender <= 2.0):
                    raise ValueError("invalid font ascender")
            except Exception:
                # 主流 PDF 字体升部约为 0.8~1.1 em；只有字体指标不可读时
                # 才使用保守值，仍不能再依赖带 UI 留白的对象框底部。
                ascender = 1.0
            base = fr.y0 + size * ascender
        # 中文斜体：Windows 中文字体通常没有斜体变体文件，字体选择
        # 可能仍返回正体；直接写回会丢失对象的斜体样式。
        # 含 CJK 的斜体改用 morph 错切合成：斜切随字形写入 content
        # stream，保存/重开/其它阅读器都保持倾斜，与 backend 里添加文字
        # 的 CJK 斜体合成同参数同观感。
        if bool(obj.get("italic", False)) and any(
                backend._is_cjk_char(c) for c in text):
            self._bake_skew_italic(page, fr, text, fname, size, base, rgb)
            return
        page.insert_text((fr.x0, float(base)), text, fontname=fname,
                         fontsize=size, color=rgb)

    def _bake_skew_italic(self, page, fr, text, fname, size, base, rgb):
        """用目标字体 + morph 错切矩阵把整行文字合成斜体写回。

        参数与 backend._draw_italic_cjk_segments 的 CJK 段一致
        （tan(-14°)≈-0.2493，与常规拉丁斜体字面倾斜量匹配），保证
        “修改原行”与“添加文字”两条保存路径的汉字斜体观感统一。
        整行同一字体一次插入，无需分段推进光标。
        """
        tan_a = 0.2493   # tan(14°), 合成右倾 italic; 与 backend._draw_italic_cjk_segments
                          # 同符号, 保证「修改原行」与「添加文字」两条保存路径斜体
                          # 方向在主流 PDF 阅读器(Adobe/Edge/Chrome/Sumatra)一致
        pivot = pymupdf.Point(float(fr.x0), float(base))
        skew = pymupdf.Matrix(1, 0, tan_a, 1, 0, 0)
        page.insert_text((float(fr.x0), float(base)), text,
                         fontname=fname, fontsize=size, color=rgb,
                         morph=(pivot, skew))

    # 字体来源 → 解析出的 Font 缓存。系统 TTC(雅黑 msyh.ttc ~20MB)解析要
    # 100-180ms, 覆盖检测每次重建会拖慢整份文档保存。Font 对象只读、与
    # 具体 document 无关, 可按来源全局复用。缓存至多保留 24 个(文档字体
    # 数量有限), 超出清空防止长时间会话内存膨胀。
    _embed_font_cache = {}
    _EMBED_FONT_CACHE_MAX = 24

    @classmethod
    def _cached_embed_font(cls, embed):
        """按 file 路径 / buffer 内容返回解析过的 Font(无来源返回 None)。"""
        src = embed.get("file") if embed.get("file") else embed.get("buffer")
        if not src:
            return None
        key = ("f", src) if embed.get("file") else ("b", src)
        cache = cls._embed_font_cache
        fo = cache.get(key)
        if fo is None:
            try:
                fo = (pymupdf.Font(fontfile=src) if key[0] == "f"
                      else pymupdf.Font(fontbuffer=src))
            except Exception:
                fo = None
            cache[key] = fo
            if len(cache) > cls._EMBED_FONT_CACHE_MAX:
                # 只清不删热点键: 整体重建会丢当前键, 先清再补回
                cache.clear()
                cache[key] = fo
        return fo

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
        bold = bool(obj.get("bold", False))
        italic = bool(obj.get("italic", False))
        fams = [obj.get("fontfamily") or "",
                "Microsoft YaHei", "SimSun", "SimHei",
                "DengXian", "KaiTi", "FangSong"]
        seen = set()
        for fam in fams:
            if not fam or fam in seen:
                continue
            seen.add(fam)
            p = self._system_font_file(fam, bold=bold, italic=italic)
            if not p:
                continue
            try:
                fo = self._cached_embed_font({"file": p})
            except Exception:
                fo = None
            if fo is None or not self._font_covers(fo, text):
                continue
            # 注册名加 fb 前缀，避免与原嵌入资源/字族名撞名
            clean = _re.sub(r"[^A-Za-z0-9]", "", fam)
            suffix = self._style_suffix(bold, italic)
            return "fb" + (clean or "cjk") + suffix, {
                "name": "fb" + (clean or "cjk") + suffix, "file": p}
        raise RuntimeError("no font covers text glyphs")

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
        if self.doc is None or self.side_tabs.isHidden():
            return
        if self._inline_edit_active():
            self._fit_after_edit = True
            self._fit_after_edit_mode = "page"
            return
        self.fit_page(preserve_position=True)

    # ---------------- 就地编辑期间的缩放保护 ----------------
    def _inline_edit_active(self):
        """是否有就地编辑框开着（行文字/新增文字/对象文字）。

        这些编辑框以画布 _zoom 坐标锚定在 PDF 行/点上，编辑过程中页面被
        重新缩放会让框与文档内容脱位。窗口自动适宽等触发必须挂起，等编辑
        结束（提交/取消）后再补做，保证所见即所得不闪跳。
        """
        return (getattr(self, "_row_edit", None) is not None
                or getattr(self, "_inplace_edit", None) is not None
                or getattr(self, "_obj_edit", None) is not None)

    def _on_window_fit_timeout(self):
        if self._inline_edit_active():
            # 正在就地编辑：挂起适宽，编辑结束后由 _close_inline_editor 补跑
            self._fit_after_edit = True
            self._fit_after_edit_mode = "width"
            return
        self.fit_width(preserve_position=True)

    def _flush_fit_after_edit(self):
        """编辑框关闭后若曾有挂起的适宽请求，补做一次。"""
        if not self._fit_after_edit:
            return
        self._fit_after_edit = False
        mode = self._fit_after_edit_mode or "width"
        self._fit_after_edit_mode = "width"
        if self.doc is None or self._inline_edit_active():
            return
        if mode == "page":
            self.fit_page(preserve_position=True)
        else:
            self.fit_width(preserve_position=True)

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
        if self.doc is None or getattr(self.doc, "is_closed", False):
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
        # doc 可能在批次渲染期间被替换/关闭（如另存替换文档、关标签），
        # 用 is_closed 兜底，避免访问已关闭文档抛 document closed。
        if (self.doc is None
                or getattr(self.doc, "is_closed", False)
                or getattr(self, "_thumb_batch", 0) is None):
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
        # 粘贴内容在保存前仍是浮动文字对象：立即进入统一编辑层并保持
        # 选中，用户可以继续移动、双击编辑或删除；保存时才烘焙进 PDF。
        self._add_text_object(text, int(page), QPointF(pt), keep_mode=True)
        pasted_oid = self._obj_counter
        self.set_mode("replace_text")
        self.page_view.select(pasted_oid)
        self.statusMessage.emit(
            i18n.tr("paste_text_done").format(p=int(page) + 1) +
            "；保存前可直接拖动", 4000)

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
        # 从“修改文字”进入放置工具时必须先关闭整页文字编辑覆盖层；
        # 否则页面点击会被 textLineClicked 截获，便笺/签名都无法落下。
        self.set_mode("view")
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
            self._add_text_object(
                self.pending_paste_text, page, pt, keep_mode=True)
            pasted_oid = self._obj_counter
            self.pending_paste_text = None
            self.set_mode("replace_text")
            self.page_view.select(pasted_oid)

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
            self._selected_pdf_content = None
            self.page_view.set_edit_selection()
            if not (was_editing or focus_done):
                self.statusMessage.emit(i18n.tr("replace_no_text"), 3000)
            return
        if line.get("kind") == "image" and line.get("record"):
            # Acrobat“编辑 PDF”：单击独立图片对象后直接选中，Delete 删除。
            self._selected_pdf_content = dict(line["record"])
            self.page_view.set_edit_selection(
                int(page), line["rect"], self._selected_pdf_content)
            self.page_view.setFocus()
            if line.get("double_click"):
                self._replace_selected_pdf_image(
                    self._selected_pdf_content, line["rect"])
                return
            self.statusMessage.emit(
                "已选中图片对象；可移动、缩放、旋转，双击替换或 Delete 删除",
                7000)
            return
        self._selected_pdf_content = None
        self.page_view.set_edit_selection()
        self._begin_row_edit(int(page), line)


    def _begin_row_edit(self, page, line):
        """在文字行原位置就地打开单行富文本编辑框（无弹窗）。

        编辑器紧贴该行文字框，按行内各 span 的字体/字号/颜色/粗斜预填
        （保留行内原本的字符级格式差异），光标定位到鼠标点击的字符处；
        框内可拖动选中部分字符 → 右键「格式设置」只改选中字符，实现
        字符级混排。回车或点击其它处提交，Esc 取消。
        """
        if not self._require_permission(pymupdf.PDF_PERM_MODIFY, "编辑文档"):
            return
        from PySide6.QtGui import QTextCursor
        self._close_inline_editor()

        # 先判断所点文字是否恰好属于一个独立内容流。对这类对象直接在
        # 原流中替换 Tj 字符串，完整保留字体资源、Tm 旋转矩阵、灰度和
        # 透明度；删除则清空该流。全程不做 redaction，所以下层正文不受
        # 影响。这是用户样本和 Acrobat 编辑行为的关键路径。
        isolated_record = backend.find_isolated_text_object(
            self.doc, int(page), str(line.get("text", "")),
            [line["rect"].left(), line["rect"].top(),
             line["rect"].right(), line["rect"].bottom()])
        # 单一 span 优先直接改原内容流中的字形代码。这样不需要重嵌字体，
        # 自定义/商业字体也能原样保留字号、颜色、粗斜和文字矩阵。
        source_spans = [s for s in (line.get("spans") or [])
                        if str(s.get("text", ""))]
        direct_record = None
        if (len(source_spans) == 1 and
                str(source_spans[0].get("text", "")) == str(line.get("text", ""))):
            direct_record = backend.find_direct_text_object(
                self.doc, int(page), str(line.get("text", "")),
                [line["rect"].left(), line["rect"].top(),
                 line["rect"].right(), line["rect"].bottom()],
                source_spans[0].get("font", ""))

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
        family = self._row_font_family(page, fmt.get("font", ""))
        if not family:
            # 兜底按行文本内容：含 CJK 走 SimSun（中文默认衬线），
            # 纯西文走 Arial；不强行塞雅黑，否则会让西文无衬线行变
            # 中文字形观感（"字体/排列格式"全怪）。
            _text = line.get("text", "") or ""
            _has_cjk = any(
                ('一' <= ch <= '鿿') or
                ('぀' <= ch <= 'ヿ') or
                ('가' <= ch <= '힯')
                for ch in _text)
            family = "SimSun" if _has_cjk else "Arial"
        c = fmt.get("color") or (0, 0, 0)
        color = QColor(int(c[0]), int(c[1]), int(c[2]))
        bold = bool(fmt.get("bold", False))
        italic = bool(fmt.get("italic", False))
        luminance = (0.299 * color.red() + 0.587 * color.green() +
                     0.114 * color.blue())

        # 编辑框字号与页面渲染严格一致：页面位图与覆盖层文字均按
        # fontsize*zoom 逻辑像素显示（page_view 以 _zoom 缩放渲染），
        # 此处不再乘额外放大系数，避免框内文字比原文偏大变形。
        font_px = max(9.0, size * zoom)

        # 编辑框几何：完全紧贴 PDF line bbox（Acrobat 选中块 = 原文字宽，
        # 无空白 padding），宽度不强制拉至 180（短行拉成长白条是用户看到
        # "变大"的核心来源之一）。垂直与行顶对齐，字形 ink 顶与 PDF 行顶
        # 同位，邻行 baseline 不因框高而错位。
        bx = max(0, int(wx))
        by = int(wy)
        page_px_w = backend.page_size(self.doc, page)[0] * zoom
        avail_w = max(2.0, page_px_w - bx)
        box_h = wh
        box_w = max(ww, 2.0)
        box_w = min(box_w, avail_w)

        # 初始富文本：按行内各 span 预填（行内原本有混排时保留原样），
        # 仅当行无 span 明细时才退化为单段整行格式。
        init_runs = []
        for s in (line.get("spans") or []):
            st = str(s.get("text", ""))
            if not st:
                continue
            fam = self._row_font_family(page, s.get("font", "")) or family
            sc = s.get("color") or c
            init_runs.append({
                "text": st, "family": fam,
                "size": float(s.get("size") or size),
                "color": QColor(int(sc[0]), int(sc[1]), int(sc[2])),
                "bold": bool(s.get("bold", bold)),
                "italic": bool(s.get("italic", italic)),
            })
        if not init_runs:
            init_runs = single_run(
                str(line.get("text", "")), family, size, color, bold, italic)

        edit = PdfRowEditBox(canvas)
        edit.setObjectName("rowEditInline")
        edit.set_scale(zoom)
        # 控件级字体像素与页面一致（用于 Qt 内部布局/光标定位）
        from PySide6.QtGui import QFont as _QFont
        _wf = _QFont(family)
        _wf.setPixelSize(int(round(font_px)))
        _wf.setBold(bold)
        _wf.setItalic(italic)
        edit.setFont(_wf)
        # ================== Acrobat 就地方案（MuPDF 单引擎） ==================
        # 点击进入编辑的瞬间**不做任何像素/文档改动**：PDF 原字形原样显示。
        # 编辑框只是完全透明的「输入 + 光标 + 选区」层——框内文字字色透明，
        # 真正的新文字不在这里渲染！用户实际输入/删除/改样式的那一刻，
        # contentsChanged → 把整行文本 redact+insert **直接写回内存 PDF**
        # （原字体子集/系统同族、原字号、原基线），再仅重渲染该行区域位图。
        # 于是编辑行文字与页面其它行出自**同一个 MuPDF/FreeType 引擎**，
        # 同字体同字号同基线，彻底消除 Qt/DirectWrite 与 MuPDF 双引擎造成
        # 的"放大/挪动/字体不一致"。光标闪烁由 Qt 画在透明层上，点哪改哪。
        init_text_color = color.name() if luminance > 225 else (
            "#1c1c1e" if luminance > 200 else color.name())
        # 选中态绝不能把字形画出来：框内文字本就透明（字形由下方 MuPDF
        # 贴片唯一渲染），若 Qt 用 selection-color 重画选中字形，会叠在
        # PDF 字形上出现"变大/变形/方块"。选中只画半透明浅蓝高亮（与
        # Acrobat 一致：高亮底下仍是 PDF 原字形），字形永不二次绘制。
        edit.setStyleSheet(
            "QTextEdit#rowEditInline{"
            "background-color: transparent;"
            "border: none;"
            "padding: 0px; margin: 0px;"
            "color: " + init_text_color + ";"
            "selection-background-color: rgba(0,110,220,35%);"
            "selection-color: transparent;}")
        edit.set_runs(init_runs)
        edit.set_text_visible(False)      # 框内文字透明：视觉只看 PDF 引擎
        # 用文档理想宽度（实际渲染文字宽）兜底框宽：避免 PDF line bbox ww
        # 小于真实文字宽（如含混排 span）时把后段字裁掉；并防止光标
        # 滚动后字符被顶出可视区。
        ideal_w = edit.document().idealWidth()
        box_w = max(box_w, ideal_w + 2.0)
        box_w = min(box_w, avail_w)
        edit.setGeometry(bx, by, int(box_w), int(box_h))
        ranges = line.get("char_x") or []
        edit.set_pdf_layout(str(line.get("text", "")),
                            [(a * zoom - bx, b * zoom - bx) for a, b in ranges],
                            wy - by, wy - by + wh)
        edit.raise_()
        edit.show()
        edit.setFocus()
        # 点击进入不默认全选：光标定位到鼠标点击处的字符，便于点哪改哪。
        # 鼠标不在框内（键盘/程序触发）则把光标放到行尾，避免误替换整行。
        click_pos = (QPointF(float(line["cx"]) * zoom - bx, wh / 2)
                     if "cx" in line else edit.mapFromGlobal(QCursor.pos()))
        cur = edit.textCursor()
        if QRectF(edit.rect()).contains(QPointF(click_pos)):
            cur = edit.cursorForPosition(click_pos)
        else:
            cur.movePosition(QTextCursor.MoveOperation.End)
        edit.setTextCursor(cur)
        edit.sync_typing_format_from_cursor()
        # 内容/样式变化（含 IME 提交、格式对话框应用）→ live 写回 PDF
        edit.document().contentsChanged.connect(
            self._on_row_edit_contents_changed)
        edit.submitRequested.connect(self._finish_row_edit)
        edit.installEventFilter(self)
        self._row_edit = edit
        self._row_edit_meta = {
            "page": page,
            "rect": QRectF(r),
            # 擦除区 = 字符级并集（不含字体上下行），避免 redact 越界吞掉
            # 相邻行文字；行 bbox 在行距紧凑时与邻行交叠，不能直接用来擦除。
            "erase": list(line.get("erase")) if line.get("erase") else
                     [r.x(), r.y(), r.right(), r.bottom()],
            "text": str(line.get("text", "")),
            "origin": line.get("origin"),     # (x,y) 行首字符基线原点
            "char_x": line.get("char_x"),     # 每字符(x0,x1)顺序表（供前缀保留）
            "cx": float(line.get("cx", r.x() + r.width() / 2.0)),
            # 提交时直接复用点击命中行的格式与主 span 矩形，避免
            # 表格型文档中按 y 二次定位误中相邻行导致格式/颜色串行。
            "fmt": dict(line.get("fmt") or {}),
            "span_bbox": list(line.get("span_bbox") or
                              [r.x(), r.y(), r.right(), r.bottom()]),
            # 行内各 span 原始明细（PDF 字体/字号/粗斜），live 写回时
            # 优先复用对应 span 的嵌入子集字体
            "spans": list(line.get("spans") or []),
            # 初始富文本（行内原有样式），用于判定用户是否改了格式
            "init_runs": init_runs,
            # ========== live 会话状态（Acrobat 直写 PDF） ==========
            "live": False,     # 本会话是否已改动内存 PDF
            "undo": False,     # 会话级 undo 快照是否已记录
            "written": False,  # PDF 该行当前内容是否为本次会话写入
            "last_key": None,  # 上次 live 的 runs 指纹（防重入/防空转）
            "last_span": None, # 上次写入内容占用的 PDF 区域 [x0,y0,x1,y1]
            "fseq": 0,         # 字体注册名去重序号
            "isolated_record": isolated_record,
            "direct_record": direct_record,
            "format_revision": int(getattr(edit, "_format_revision", 0)),
        }
        # 连接后补记初始指纹：跳过 setTextCursor/sync_typing_format_from_cursor
        # 可能触发的一次空 contentsChanged tick（内容未变则 live 不空跑）。
        try:
            self._row_live_busy = False
            meta0 = self._row_edit_meta
            meta0["last_key"] = self._row_fingerprint(init_runs)
        except Exception:
            pass
        if isolated_record is not None:
            # 独立对象按 Acrobat 对象语义进入：首击选中全部文字，直接输入
            # 即替换，Delete/Backspace 即删除；无需再进“水印管理器”。
            edit.selectAll()
            self.statusMessage.emit(
                "已选中独立文字对象；直接输入可替换，Delete 可删除", 6000)
        # 该行进入就地编辑：立即从整页蓝框/hover 模式摘除（不改任何像素，
        # 原字形继续由 PDF 位图显示；直到用户真正输入才 live 写回）
        canvas.set_inline_rect(page, QRectF(r))

    @staticmethod
    def _row_fingerprint(runs):
        """整行富文本 runs 的指纹：文本 + 样式逐段拼接，内容/格式变化
        都会改变指纹（仅移动光标不会），用于 live 写回去重。"""
        parts = []
        for r in merge_runs(runs):
            c = r.get("color")
            if isinstance(c, QColor):
                cr, cg, cb = c.red(), c.green(), c.blue()
            else:
                cr = cg = cb = 0
            parts.append("|".join([
                str(r.get("text", "")),
                str(r.get("family") or ""),
                str(round(float(r.get("size") or 12.0), 2)),
                str(cr), str(cg), str(cb),
                "B" if r.get("bold") else "-",
                "I" if r.get("italic") else "-",
            ]))
        return "\x1f".join(parts)

    # ------------------------------------------------------------------
    # live 写回：把编辑框当前内容实时写进内存 PDF（MuPDF 单引擎）
    # ------------------------------------------------------------------

    def _on_row_edit_contents_changed(self):
        """行编辑框内容/格式变化 → 整行 redact+insert 写回内存 PDF。

        Acrobat 式就地编辑：键盘输入（含 IME 提交）、删除、粘贴、右键
        格式修改都会触发本回调，编辑行文字始终由 MuPDF 引擎渲染，与
        页面其它行完全一致。
        """
        if getattr(self, "_row_live_busy", False):
            return
        edit = self._row_edit
        meta = self._row_edit_meta
        if edit is None or meta is None or self.doc is None:
            return
        try:
            runs = merge_runs(edit.to_runs())
        except Exception:
            return
        key = self._row_fingerprint(runs)
        if key == meta.get("last_key"):
            return
        meta["last_key"] = key
        self._row_live_busy = True
        try:
            self._row_live_write(runs)
        except Exception as exc:
            import traceback as _tb
            _tb.print_exc()
            self.statusMessage.emit(f"就地更新失败：{exc}", 4000)
        finally:
            self._row_live_busy = False

    def _row_live_geom(self, meta):
        """live 写回几何：x 起点/基线取原行首字符 origin，兜底字形区。"""
        er = meta.get("erase") or [0.0, 0.0, 0.0, 0.0]
        og = meta.get("origin")
        if og and len(og) == 2:
            x0 = float(og[0])
            base = float(og[1])
        else:
            x0 = float(er[0])
            base = float(er[3]) - max(1.0, (float(er[3]) - float(er[1])) * 0.15)
        return x0, base, float(er[1]), float(er[3])

    def _sync_row_layout_from_pdf(self, edit, meta, text):
        """原位内容流写回后，用 PDF 的真实逐字边界刷新点击/光标映射。

        direct / isolated 路径只替换原内容流，不经过下方重排分支；旧代码
        因而一直保留编辑开始时的 ``char_x``。插入字符后 PDF 已正确变长，
        但编辑框仍只有旧字符数个命中区，后续点击会落到错误字符。这里以
        原行起点和基线为锚，从 rawdict 中选回刚写入的同一行，并同步其
        每字符 bbox、编辑框尺寸和纵向命中带。
        """
        if not isinstance(edit, PdfRowEditBox) or self.doc is None:
            return False
        pno = int(meta.get("page", -1))
        if pno < 0 or pno >= len(self.doc):
            return False
        x0, base_y, old_top, old_bottom = self._row_live_geom(meta)
        candidates = []
        try:
            raw = self.doc[pno].get_text("rawdict")
            for block in raw.get("blocks", []):
                for line in block.get("lines", []):
                    chars = [char for span in line.get("spans", [])
                             for char in span.get("chars", [])]
                    if not chars or "".join(str(c.get("c", ""))
                                             for c in chars) != text:
                        continue
                    origin = chars[0].get("origin") or (chars[0]["bbox"][0],
                                                         base_y)
                    score = abs(float(origin[0]) - x0) + \
                        4.0 * abs(float(origin[1]) - base_y)
                    candidates.append((score, chars))
        except Exception:
            return False
        if not candidates:
            return False
        chars = min(candidates, key=lambda item: item[0])[1]
        if len(chars) != len(text):
            return False

        ranges = [(float(c["bbox"][0]), float(c["bbox"][2])) for c in chars]
        ink_top = min(float(c["bbox"][1]) for c in chars)
        ink_bottom = max(float(c["bbox"][3]) for c in chars)
        top = min(old_top, ink_top)
        bottom = max(old_bottom, ink_bottom)
        pv = self.page_view
        if pv is None:
            return False
        zoom = pv._zoom
        origin_x = min(x0, float(meta["rect"].left()), ranges[0][0])
        bx = int(origin_x * zoom)
        by = int(pv._offsets[pno] + top * zoom)
        right = max(ranges[-1][1], float(meta["rect"].right())) * zoom
        page_right = backend.page_size(self.doc, pno)[0] * zoom
        edit.setGeometry(
            bx, by, max(2, int(min(page_right, right + 4.0) - bx)),
            max(2, int((bottom - top) * zoom) + 2))
        edit.set_pdf_layout(
            text, [(left * zoom - bx, right * zoom - bx)
                   for left, right in ranges],
            (ink_top - top) * zoom, (ink_bottom - top) * zoom,
            x0 * zoom - bx)
        meta["last_span"] = [ranges[0][0], top, ranges[-1][1], bottom]
        return True



    def _partition_chars_for_glyph(self, family, text):
        """按字符族把 text 拆成连续段，每段对应一个字体候选。

        Acrobat 语义：原行字符（无 CJK / 无超 ASCII）不应因新增字符被强制
        替换成字号/度量更大的字体（如 MicrosoftYaHei）而视觉放大。本函数
        原字体包含字形时保留原字族；仅将缺失的 CJK/扩展字符交给备用
        字体，避免把宋体或西文统一替换成雅黑。"""
        if not text:
            return []
        result = []
        cur_buf = ''
        cur_fam = None
        font_file = self._system_font_file(family)
        source_font = self._cached_embed_font({"file": font_file}) if font_file else None
        for ch in text:
            if (backend._is_cjk_char(ch) or ord(ch) > 0x7E) and not self._font_covers(source_font, ch):
                ch_fam = "Microsoft YaHei"
            else:
                ch_fam = family or "Arial"
            if cur_fam is None:
                cur_fam = ch_fam
            if ch_fam != cur_fam and cur_buf:
                result.append((cur_buf, cur_fam))
                cur_buf = ""
                cur_fam = ch_fam
            cur_buf += ch
        if cur_buf:
            result.append((cur_buf, cur_fam))
        return result

    def _row_live_choose_font(self, page, family, size, bold, italic, text,
                              meta=None):
        """为指定子段文本选择并注册写回字体。

        本函数接受任意子段（不必是整段 run），并按
        子段文本的内容评估候选字体，避免把原字符无差别换成大度量的 fallback
        字体。流程：1) 尝试原行嵌入子集（仅当子段字符全在原字符集合内，避免
        换字体污染原字符外观）→ 2) 系统同族候选链 → 3) 内置 china-s/helv。
        """
        text = text or ""
        has_cjk = any(backend._is_cjk_char(c) for c in text)
        # 原文使用 PDF 标准字体时直接沿用，避免同名字体替换后的字面差异。
        builtin_fonts = {"Helvetica": "helv", "Helvetica-Bold": "hebo",
                         "Helvetica-Oblique": "heit", "Helvetica-BoldOblique": "hebi",
                         "Times-Roman": "tiro", "Times-Bold": "tibo",
                         "Times-Italic": "tiit", "Times-BoldItalic": "tibi",
                         "Courier": "cour", "Courier-Bold": "cobo",
                         "Courier-Oblique": "coit", "Courier-BoldOblique": "cobi",
                         "Heiti": "china-s"}
        for span in (meta or {}).get("spans", []):
            name = builtin_fonts.get(span.get("font"))
            if (name and self._map_pdf_font(span.get("font")) == family
                    and bool(span.get("bold")) == bold
                    and bool(span.get("italic")) == italic):
                font = pymupdf.Font(name)
                # 字体含有字形不代表 insert_text 的单字节编码能表达它。
                # Helvetica/Times 的箭头、希腊字母等必须走 Unicode 字体写入。
                encodable = (all(ord(ch) <= 0xFFFF for ch in text) if name == "china-s"
                             else all(ord(ch) < 128 for ch in text))
                if encodable and self._font_covers(font, text):
                    return {"name": name, "embed": {"name": name, "builtin": True},
                            "fo": font}
        embed = None
        fo = None
        # 1. 复用原行嵌入子集：仅当子段字符全是原字符（字符级别校验，不破坏原外观）
        if meta is not None:
            orig_text = meta.get("text") or ""
            try:
                only_orig_chars = all(
                    c.isspace() or (c in orig_text) for c in text)
            except Exception:
                only_orig_chars = False
            if only_orig_chars:
                for s in (meta.get("spans") or []):
                    pf = str(s.get("font") or "")
                    if not pf:
                        continue
                    if ((self._map_pdf_font(pf) or "").lower() !=
                            (family or "").lower()):
                        continue
                    buf, raw, ftype = self._extract_embed_buffer(page, pf)
                    if not buf:
                        continue
                    try:
                        fo0 = pymupdf.Font(fontbuffer=buf)
                    except Exception:
                        fo0 = None
                    if fo0 is None:
                        continue
                    if self._subset_covers(fo0, ftype, text, orig_text):
                        clean = re.sub(r"^[A-Za-z]{6}\+", "",
                                       (raw or "")).strip()
                        nm = re.sub(r"[^A-Za-z0-9]", "", clean) or "font"
                        embed = {"name": nm, "buffer": buf}
                        fo = fo0
                        break
        # 2. 候选链：按 sub_text 文本脚本（ASCII/CJK）选字体
        if embed is None:
            embed = self._live_candidate_embed(family, text, bold, italic)
        # 3. 内置兜底
        if embed is None or not embed.get("name"):
            if has_cjk or any(
                    ord(c) > 0x7E for c in text if not c.isspace()):
                embed = {"name": "china-s", "builtin": True}
            else:
                embed = {"name": "helv", "builtin": True}
        # 取 fo
        if fo is None:
            try:
                if not embed.get("builtin"):
                    fo = self._cached_embed_font(embed)
                else:
                    fo = pymupdf.Font(embed["name"])
            except Exception:
                fo = None
        # 注册到页面（幂等）：避免 redact 清掉资源后引用失效
        name = embed.get("name") or "font"
        if not embed.get("builtin"):
            reg_name = "L" + re.sub(r"[^A-Za-z0-9]", "", name) or "Lfont"
            try:
                have = {f[4] or "" for f in page.get_fonts(full=True)}
                if reg_name not in have:
                    if embed.get("file"):
                        page.insert_font(fontname=reg_name,
                                         fontfile=embed["file"])
                    elif embed.get("buffer"):
                        page.insert_font(fontname=reg_name,
                                         fontbuffer=embed["buffer"])
                name = reg_name
            except Exception:
                # 重名冲突：换序号名
                try:
                    meta_seq = meta if isinstance(meta, dict) else {}
                    meta_seq["fseq"] = int(meta_seq.get("fseq", 0)) + 1
                    reg_name = f"L{int(meta_seq['fseq'])}"
                    have = {f[4] or "" for f in page.get_fonts(full=True)}
                    if reg_name not in have:
                        if embed.get("file"):
                            page.insert_font(fontname=reg_name,
                                             fontfile=embed["file"])
                        elif embed.get("buffer"):
                            page.insert_font(fontname=reg_name,
                                             fontbuffer=embed["buffer"])
                    name = reg_name
                except Exception:
                    # 实在不行回落内置
                    reg_name = "china-s" if has_cjk else "helv"
                    embed = {"name": reg_name, "builtin": True}
                    try:
                        fo = pymupdf.Font(reg_name)
                    except Exception:
                        fo = None
                    name = reg_name
        return {"name": name, "embed": embed, "fo": fo}

    def _live_candidate_embed(self, family, text, bold, italic):
        """候选链按「字形覆盖」挑选能渲染 text 的系统字体文件 embed。

        原字族系统字体若覆盖不全（少见汉字/符号等），按文本脚本遍历通用
        大字库，返回首个 has_glyph 全中的文件；全都不中返回 None（由调用
        方落内置 china-s/helv 万国码兜底）。
        """
        has_cjk = any(backend._is_cjk_char(c) for c in (text or ""))
        fams = [family or ""]
        fams += (["Microsoft YaHei", "SimSun", "SimHei", "DengXian",
                  "KaiTi", "FangSong"] if has_cjk else
                 ["Arial", "Times New Roman", "Segoe UI", "Calibri",
                  "Cambria", "Microsoft YaHei"])
        seen = set()
        for fam in fams:
            fam = (fam or "").strip()
            if not fam or fam in seen:
                continue
            seen.add(fam)
            p = self._system_font_file(fam, bold=bold, italic=italic)
            if not p:
                continue
            try:
                fo = self._cached_embed_font({"file": p})
            except Exception:
                fo = None
            if fo is None or not self._font_covers(fo, text):
                continue
            clean = re.sub(r"[^A-Za-z0-9]", "", fam) or "cjk"
            return {"name": "fb" + clean +
                    self._style_suffix(bold, italic), "file": p}
        return None


    def _row_live_write(self, runs):
        """把整行当前 runs 写入内存 PDF（Acrobat 式前缀保真）。

        与简单"整行 redact + 重写"不同：这里先求新文本与原行文本的公共
        前缀，**没有改动的原字符（连同其原嵌入字体渲染）原位保留、绝不
        重排**，只 redact 第一个改动字符之后到当前写入右端的区域，并从
        改动点续写。这样原字符不可能因替换字体（Arial/YaHei 的拉丁字形
        比原 CIDFont 更宽）而"同行整体变大"。
        """
        meta = self._row_edit_meta
        if meta is None:
            return
        pno = int(meta.get("page", -1))
        if pno < 0 or pno >= len(self.doc):
            return
        page = self.doc[pno]
        pv = self.page_view
        x0, base_y, y_top, y_bot = self._row_live_geom(meta)
        text = runs_text(runs)
        _live_diag_dir(meta)
        _live_diag_log(meta, "> write text=%r" % text)
        # Qt 框内文字保持透明（防格式编辑把 alpha 改回出现双引擎叠字）
        edit = getattr(self, "_row_edit", None)
        format_changed = bool(
            edit is not None and
            int(getattr(edit, "_format_revision", 0)) >
            int(meta.get("format_revision", 0)))
        if edit is not None:
            try:
                edit.set_text_visible(False)
            except Exception:
                pass
        # 首写 undo 快照（会话级一步）：后续每键都改 doc，绝不逐键入栈
        if not meta.get("undo"):
            if self.begin_undo_step(document_change=True):
                meta["undo"] = True
        isolated = meta.get("isolated_record")
        direct = meta.get("direct_record")
        if format_changed:
            # direct / isolated 的原位路径只改字符编码，刻意保留 Tf / rg 等
            # 原格式操作符；继续走它会让字号、颜色、粗斜体“点击后没反应”。
            # 格式一旦改变，本编辑会话永久切换到下方富文本分段写回路径。
            meta["direct_record"] = None
            meta["isolated_record"] = None
            direct = None
            isolated = None
        if direct is not None:
            # 原 PDF 字体的 ToUnicode 反向编码路径：只替换 Tj/TJ 数据，
            # 所有格式操作符保持逐字节不变。
            if not backend.replace_direct_text_object(self.doc, direct, text):
                # 例如 Albany / Helvetica 子集没有中文字形。旧逻辑只拒绝
                # 本次写入，而编辑框仍保留汉字，于是后续英文也因整段包含
                # 该汉字而持续失败。现在先恢复会话开始时的原内容流，再
                # 永久切换到下方“保留原前缀 + 缺字段兼容字体”路径。
                try:
                    self.doc.update_stream(
                        int(direct["stream_xref"]),
                        bytes(direct["source_stream"]))
                except Exception:
                    self.statusMessage.emit(
                        "原字体缺少所输入字符，且无法切换兼容字体", 5000)
                    return str(meta.get("text") or "")
                meta["direct_record"] = None
                # 同一对象即使也被识别为独立文字流，此刻仍应采用按字符
                # 分字体的通用路径，否则又会被原对象编码限制拦住。
                meta["isolated_record"] = None
                direct = None
                isolated = None
                meta["written"] = False
                meta["last_span"] = None
                meta["preserved_prefix"] = len(str(meta.get("text") or ""))
                self.statusMessage.emit(
                    "原字体不含该字形，改动部分已自动使用兼容字体", 5000)
            else:
                meta["written"] = True
                meta["live"] = True
                meta["last_span"] = list(meta.get("erase") or
                                         [0.0, 0.0, 0.0, 0.0])
                self._sync_row_layout_from_pdf(edit, meta, text)
                self.modified = True
                if pv is not None:
                    pv._images.pop(pno, None)
                    pv._render_page(pno)
                    pv.set_inline_rect(pno, meta["rect"])
                    pv.update()
                return text
        if isolated is not None:
            # 独立对象的安全路径：原位改内容流，不使用会擦到下层正文的
            # redaction。原模板保存在 record 中，所以删空后继续输入仍可恢复。
            if not backend.replace_isolated_text_object(self.doc, isolated, text):
                self.statusMessage.emit(
                    "该对象使用了当前字体无法原位编码的字符；未改动原文", 5000)
                return str(meta.get("text") or "")
            meta["written"] = True
            meta["live"] = True
            meta["last_span"] = list(meta.get("erase") or
                                     [0.0, 0.0, 0.0, 0.0])
            self._sync_row_layout_from_pdf(edit, meta, text)
            self.modified = True
            # 旋转对象替换后的边界可能改变；整页重渲染可避免旧字形残影。
            if pv is not None:
                pv._images.pop(pno, None)
                pv._render_page(pno)
                pv.set_inline_rect(pno, meta["rect"])
                pv.update()
            return text
        # 只有文字和样式都未改、且此前从未被擦除的原字符才能保留。
        # 已重写的区域不能再次当成原文；否则把 X 改回 A 时会跳过写回。
        orig_text = str(meta.get("text") or "")
        char_x = meta.get("char_x")
        keep = 0
        if isinstance(char_x, list) and len(char_x) == len(orig_text):
            limit = min(len(orig_text), len(text),
                        meta.get("preserved_prefix", len(orig_text)))
            def styled_chars(items):
                for run in items:
                    style = self._row_fingerprint([dict(run, text="_")])
                    for ch in str(run.get("text") or ""):
                        yield ch, style
            original_chars = list(styled_chars(meta.get("init_runs") or []))
            current_chars = list(styled_chars(runs))
            limit = min(limit, len(original_chars), len(current_chars))
            while keep < limit and original_chars[keep] == current_chars[keep]:
                keep += 1
        else:
            char_x = None
        meta["preserved_prefix"] = keep
        # 写入起点：
        #  - keep 已到原行尾（追加/行尾修改）→ 原行尾右缘续写；
        #  - keep 停在行中（中间插入/替换/删除）→ 被改首字符原左缘续写；
        #  - char_x 不可用（退路）→ 行首 x0（整行重排旧行为）。
        er = meta.get("erase") or [0, 0, 0, 0]
        if char_x and orig_text:
            if keep >= len(orig_text):
                write_x0 = float(char_x[-1][1])
                orig_right = write_x0
            else:
                write_x0 = float(char_x[keep][0])
                orig_right = float(char_x[-1][1])
        else:
            write_x0 = x0
            orig_right = max(float(er[2]), x0)
        ls = meta.get("last_span")
        prev_right = (float(ls[2]) if (meta.get("written") and ls)
                      else orig_right)
        red_x1 = max(orig_right, prev_right, write_x0 + 1.0)
        tail = text[keep:]
        live_ranges = list((char_x or [])[:keep])
        _live_diag_log(meta, "  keep=%d write_x0=%.1f red_x1=%.1f base_y=%.1f y_top=%.1f y_bot=%.1f char_x_ok=%s"
                       % (keep, write_x0, red_x1, base_y, y_top, y_bot,
                          isinstance(char_x, list)))
        # —— 擦除 [write_x0, red_x1]（前缀 keep 个原字符不在区内，不被擦）——
        fr_line = pymupdf.Rect(x0, y_top - 2.0, max(red_x1 + 2.0, x0 + 2.0),
                               y_bot + 2.0)
        backend.redact_line_safe(
            page, fr_line,
            erase_rect=pymupdf.Rect(write_x0 - 0.2, y_top,
                                    red_x1 + 0.2, y_bot))
        if tail.strip():
            # —— 从改动点续写 tail（混排时各段字体/字号/颜色/粗斜独立）——
            # 先按字符族拆分子段（ASCII / CJK 各选最优字体），避免原行
            # ASCII 被 CJK fallback 大字库整行替换造成视觉放大。
            x = write_x0
            for r in self._slice_runs(runs, keep):
                seg = str(r.get("text") or "")
                if not seg:
                    continue
                size = max(1.0, float(r.get("size") or 10.0))
                cc = r.get("color")
                if isinstance(cc, QColor):
                    rgb = (cc.redF(), cc.greenF(), cc.blueF())
                else:
                    rgb = (0.0, 0.0, 0.0)
                bold = bool(r.get("bold"))
                italic = bool(r.get("italic"))
                requested_family = str(r.get("family") or "").strip()
                # _map_pdf_font 负责 PDF 内部别名；用户从系统字体框选择的
                # 正常字族（Candara、Corbel 等）未必在别名表中，必须原样
                # 交给系统字体文件解析，不能静默降级成 Arial。
                family_hint = (self._map_pdf_font(requested_family)
                               or requested_family or "Arial")
                sub_segments = self._partition_chars_for_glyph(
                    family_hint, seg)
                if not sub_segments:
                    sub_segments = [(seg, family_hint)]
                for sub_text, sub_fam in sub_segments:
                    ent = self._row_live_choose_font(
                        page, sub_fam, size, bold, italic, sub_text, meta)
                    _live_diag_log(
                        meta, "    seg=%r fam=%r -> name=%r builtin=%s"
                        % (sub_text, sub_fam,
                           (ent or {}).get("name"),
                           bool((ent or {}).get("embed", {}).get("builtin"))))
                    # 采用原字体或同族完整字体；缺字时才使用兜底字体。
                    use_name = ent["name"]
                    use_fo = ent["fo"]
                    builtin = bool(ent["embed"].get("builtin"))
                    _live_diag_log(
                        meta, "    -> use_font=%r"
                        % use_name)
                    # 使用写入 PDF 的同一字体度量，逐字记录光标和命中位置。
                    next_x = x
                    for ch in sub_text:
                        # Font.text_length 对内置 CJK 字体的 ASCII 返回半宽，
                        # insert_text 却按全宽写入；get_text_length 与写入一致。
                        advance = (pymupdf.get_text_length(ch, fontname=use_name, fontsize=size)
                                   if builtin else use_fo.text_length(ch, size))
                        live_ranges.append((next_x, next_x + advance))
                        next_x += advance
                    if not sub_text.strip():
                        x = next_x
                        continue
                    try:
                        if not builtin:
                            # TextWriter 直接使用已验证的完整字体对象，避免沿用
                            # 页面中旧的 CID 资源映射而写出方块。
                            writer = pymupdf.TextWriter(page.rect)
                            writer.append((x, base_y), sub_text, font=use_fo, fontsize=size)
                            morph = None
                            if italic and not use_fo.is_italic:
                                morph = (pymupdf.Point(x, base_y),
                                         pymupdf.Matrix(1, 0, 0.2493, 1, 0, 0))
                            writer.write_text(page, color=rgb, morph=morph)
                        elif italic and any(
                                backend._is_cjk_char(c) for c in sub_text):
                            pivot = pymupdf.Point(x, base_y)
                            skew = pymupdf.Matrix(1, 0, 0.2493, 1, 0, 0)
                            page.insert_text((x, base_y), sub_text,
                                             fontname=use_name,
                                             fontsize=size, color=rgb,
                                             morph=(pivot, skew))
                        else:
                            page.insert_text((x, base_y), sub_text,
                                             fontname=use_name,
                                             fontsize=size, color=rgb)
                    except Exception as _e:
                        import traceback as _tb
                        _live_diag_log(meta,
                                       "    !! insert_text EXC %r: %s"
                                       % (_e, _tb.format_exc().replace("\n",
                                                                        " | ")))
                    x = next_x
            x_end = x
        else:
            x_end = write_x0
            for ch in tail:
                advance = pymupdf.Font("helv").text_length(ch, 10.0)
                live_ranges.append((x_end, x_end + advance))
                x_end += advance
        meta["written"] = True
        meta["live"] = True
        # 行高带：保留原字形 y 带并外扩容纳上行/下行
        max_size = max((float(r.get("size") or 10.0) for r in runs),
                       default=10.0)
        top = min(y_top, base_y - max(y_bot - y_top, max_size * 1.5))
        bot = max(y_bot, base_y + max((y_bot - y_top) * 0.4, max_size * 0.5))
        if ls:
            # 缩小字号时也重绘上一次大字占用的区域，避免留下旧字像素。
            top = min(top, float(ls[1]))
            bot = max(bot, float(ls[3]))
        span = [write_x0 - 0.5, top,
                max(x_end, red_x1) + 0.5, bot]
        meta["last_span"] = span
        if isinstance(edit, PdfRowEditBox):
            # 保持控件与画布坐标一致；向右输入后扩展命中区，避免 Qt 内部
            # 滚动或旧框宽把后半行的鼠标事件送到页面上。
            zoom = pv._zoom
            origin_x = min(x0, float(meta["rect"].left()))
            bx = int(origin_x * zoom)
            by = int(pv._offsets[pno] + top * zoom)
            right = max(x_end, float(meta["rect"].right())) * zoom
            page_right = backend.page_size(self.doc, pno)[0] * zoom
            edit.setGeometry(bx, by, max(2, int(min(page_right, right + 4) - bx)),
                             max(2, int((bot - top) * zoom) + 2))
            edit.set_pdf_layout(text,
                                [(a * zoom - bx, b * zoom - bx) for a, b in live_ranges],
                                (y_top - top) * zoom, (y_bot - top) * zoom,
                                write_x0 * zoom - bx)
        self.modified = True
        _live_diag_snap(self.doc, meta, "write")
        # 仅重渲染改动区域（前缀原字符不变无需重绘）
        if pv is not None:
            r = QRectF(max(0.0, write_x0 - 1.0), top,
                       max(x_end, red_x1) - write_x0 + 2.0,
                       bot - top)
            pv.set_inline_rect(pno, r)     # 该行持续摘除蓝框
            pv.rerender_page_region(pno, r, pad=2.0)
        return text

    @staticmethod
    def _slice_runs(runs, skip):
        """跳过整行 runs 的前 skip 个字符，返回剩余 run 列表（用于只重排
        keep 之后的部分；分界只可能出现在一个 run 内）。"""
        out = []
        n = skip
        for r in runs:
            seg = str(r.get("text") or "")
            if n <= 0:
                out.append(r)
                continue
            if n >= len(seg):
                n -= len(seg)
                continue
            r2 = dict(r)
            r2["text"] = seg[n:]
            out.append(r2)
            n = 0
        return out

    def _commit_row_edit(self, commit=True):
        """关闭就地行编辑。

        Acrobat 式：编辑过程中文本已实时写入内存 PDF。commit=True 时
        该行即最终结果（无需再生成浮层对象/Qt 重排），undo 栈保留会话
        级快照供 Ctrl+Z 整行撤销；commit=False（Esc/取消）时若文档已被
        本会话改写，用会话级快照整体还原。

        返回是否曾处于行编辑状态（用于点击空白的提示决策）。
        """
        edit = self._row_edit
        if edit is None:
            return False
        meta = self._row_edit_meta or {}
        live = bool(meta.get("live"))
        was_live = live
        if not commit and live:
            # 取消：文档已被会话改写 → 用会话前快照还原（undo 弹栈恢复）
            self.undo()
            return True
        # 提交或未改动：结束编辑框（清理 excl/缓存）
        if not live:
            pno = int(meta.get("page", -1))
            if pno >= 0 and self.page_view is not None:
                # 无任何改动：还原该行蓝框（可再次点击编辑）
                pass
        self._close_inline_editor()
        _live_diag_snap(self.doc, meta, "commit")
        if commit and was_live:
            # 行内容已直接写在 doc 中：失效该页文字缓存，确保再次点击
            # 该行/文字选择基于新文本重新解析
            pno = int(meta.get("page", -1))
            if self.page_view is not None:
                self.page_view.invalidate_text_cache(pno if pno >= 0 else None)
            if self.doc is not None:
                self.modified = True
        return was_live or edit is not None

    def _finish_row_edit(self):
        """回车提交就地行编辑，并把键盘焦点还给画布。"""
        self._commit_row_edit(commit=True)
        if self.page_view is not None:
            self.page_view.setFocus()

    def _begin_inplace_text(self, page, pt):
        """「文本」工具点击处就地输入新文字（无弹窗工具条）。

        点击位置直接出现单行富文本输入框，预置点击处文字格式（可选中
        部分字符后右键「格式设置」实现字符级混排）；输入完后回车或点击
        页面其它处即在该处写入浮动文字对象，Esc 取消；保持 text 模式可
        连续在其它位置继续添加。
        """
        if not self._require_permission(pymupdf.PDF_PERM_MODIFY, "编辑文档"):
            return
        self._close_inline_editor()

        fmt = self._detect_format_at(page, pt)
        # _detect_format_at 已把 PDF 字体别名/嵌入字体解析成真实字族；这里
        # 不能再次只走静态映射，否则 Candara 等系统字体会被误降级为雅黑。
        family = str(fmt.get("family", "") or "Microsoft YaHei")
        display_family = _qt_safe_family(family)
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
            "QTextEdit#textEditInline{"
            "background-color: rgba(255,255,255,0.92);"
            "border: 1px dashed #0a84ff; border-radius: 2px;"
            "padding: 0 2px; color: %s;"
            "selection-background-color: #b6d7ff;"
            "selection-color: #101418;}" % text_color)

        edit = RichEditBox(canvas)
        edit.setObjectName("textEditInline")
        edit.set_scale(zoom * 1.08)
        edit.set_default_format({
            "family": family, "size": size, "color": color,
            "bold": bold, "italic": italic,
        })
        # 控件本身也用兜底后的 QFont：保证光标/系统弹出与空文档默认
        # 字符样式都用一个真实可绘制的字体，避免 Qt 在未定义字族上输出豆腐。
        # QFont 预览可使用当前 Qt 后端可解析的兜底字体，但编辑元数据和
        # runs 始终保留 PDF 的真实逻辑字族，保存时据此寻找字体文件。
        base_qfont = QFont(display_family)
        base_qfont.setPointSizeF(max(1.0, float(size)))
        if bold:
            base_qfont.setBold(True)
        if italic:
            base_qfont.setItalic(True)
        edit.setFont(base_qfont)
        edit.setStyleSheet(style)
        edit.setGeometry(int(wx), int(wy), int(box_w), int(box_h))
        edit.raise_()
        edit.show()
        edit.setFocus()
        edit.submitRequested.connect(self._finish_inplace_text)
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
        runs = self._trim_runs(edit.to_runs())
        new_text = runs_text(runs)
        self._close_inline_editor()
        created_oid = None
        if commit and new_text.strip():
            if runs and len(runs) > 1:
                self._add_text_object(
                    new_text, int(meta.get("page", 0)), meta["pt"],
                    runs=runs, keep_mode=True)
            else:
                r0 = runs[0] if runs else {}
                self._add_text_object(
                    new_text, int(meta.get("page", 0)), meta["pt"],
                    (r0.get("family") or meta.get("family", "")),
                    (r0.get("size") or meta.get("size", 10.0)),
                    (r0.get("color") if isinstance(r0.get("color"), QColor)
                     else meta.get("color")),
                    r0.get("bold", meta.get("bold", False)),
                    r0.get("italic", meta.get("italic", False)),
                    keep_mode=True)
            created_oid = self._obj_counter
        if created_oid is not None:
            # 新增文字提交后立即交给统一的对象编辑层，保持选中，用户无需
            # 再切换工具即可直接移动、双击编辑或删除。
            self.set_mode("replace_text")
            self.page_view.select(created_oid)
        return True

    def _close_inline_editor(self):
        if getattr(self, "_row_edit", None) is not None:
            self._row_edit.deleteLater()
        self._row_edit = None
        self._row_edit_meta = None
        if getattr(self, "_inplace_edit", None) is not None:
            self._inplace_edit.deleteLater()
        self._inplace_edit = None
        self._inplace_meta = None
        if getattr(self, "_obj_edit", None) is not None:
            self._obj_edit.deleteLater()
        self._obj_edit = None
        self._obj_edit_oid = None
        # 就地编辑结束 → 该行恢复整页框模式下的蓝框（仍可再次点击编辑）
        pv = getattr(self, "page_view", None)
        if pv is not None:
            pv.set_inline_rect(-1, None)
        # 编辑期间挂起的窗口适宽在此补做（此刻编辑器已全部关闭）
        self._flush_fit_after_edit()

    def _detect_format_at(self, page, pt):
        """检测点击位置文字格式（字体/字号/颜色/粗细）。

        严格按“同行前方文字 → 上一行 → 下一行”的优先级继承；三者
        都不存在时才使用默认格式。
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
                    spans = [s for s in line.get("spans", [])
                             if str(s.get("text", "")) and s.get("bbox")]
                    if spans:
                        spans.sort(key=lambda s: (float(s["bbox"][0]),
                                                  float(s["bbox"][1])))
                        lines.append({
                            "spans": spans,
                            "x0": min(float(s["bbox"][0]) for s in spans),
                            "x1": max(float(s["bbox"][2]) for s in spans),
                            "y0": min(float(s["bbox"][1]) for s in spans),
                            "y1": max(float(s["bbox"][3]) for s in spans),
                            "base": float(next(
                                (s.get("origin", (0, s["bbox"][3]))[1]
                                 for s in spans if s.get("origin")),
                                max(float(s["bbox"][3]) for s in spans))),
                        })
            if not lines:
                return fmt
            lines.sort(key=lambda ln: ((ln["y0"] + ln["y1"]) / 2.0,
                                       ln["x0"]))
            py = float(pt.y())
            px = float(pt.x())
            same = [ln for ln in lines if ln["y0"] - 3.0 <= py <=
                    ln["y1"] + 3.0]
            span = None
            if same:
                left = [s for ln in same for s in ln["spans"]
                        if float(s["bbox"][0]) < px + 0.01]
                if left:
                    span = max(left, key=lambda s: float(s["bbox"][2]))

            anchor_y = (min(same, key=lambda ln: abs(ln["base"] - py))["base"]
                        if same else py)
            if span is None:
                previous = [ln for ln in lines if ln["base"] < anchor_y - 0.5]
                if previous:
                    prev_base = max(ln["base"] for ln in previous)
                    prev_spans = [s for ln in previous
                                  if abs(ln["base"] - prev_base) <= 0.5
                                  for s in ln["spans"]]
                    span = max(prev_spans, key=lambda s: float(s["bbox"][2]))
            if span is None:
                following = [ln for ln in lines if ln["base"] > anchor_y + 0.5]
                if following:
                    next_base = min(ln["base"] for ln in following)
                    next_spans = [s for ln in following
                                  if abs(ln["base"] - next_base) <= 0.5
                                  for s in ln["spans"]]
                    span = min(next_spans, key=lambda s: float(s["bbox"][0]))
            if span is None:
                return fmt

            pdf_font = str(span.get("font", "") or "")
            fam = self._row_font_family(page, pdf_font)
            if not fam:
                candidate = re.sub(r"^[A-Za-z]{6}\+", "", pdf_font).strip()
                candidate = re.sub(
                    r"(?:[-, ](?:Regular|Bold|Italic|BoldItalic|MT))+$",
                    "", candidate, flags=re.IGNORECASE).strip()
                fam = candidate or self._map_pdf_font(pdf_font)
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

    def _row_font_family(self, pno, pdf_font):
        """CIDFont+F3 等资源别名不是真实字族，从嵌入字体名称表解析。"""
        family = self._map_pdf_font(pdf_font)
        if family:
            return family
        buf, raw_name, _ = self._extract_embed_buffer(self.doc[pno], pdf_font)
        if buf:
            try:
                embedded = pymupdf.Font(fontbuffer=buf).name
                mapped = self._map_pdf_font(embedded)
                if mapped:
                    return mapped
            except Exception:
                pass
            # 未列入系统映射表的嵌入字体（例如 Albany WT J）也必须保留
            # 真实名称，不能静默回退 Arial。直接内容流编辑会继续使用原字体。
            name = re.sub(r"^[A-Za-z]{6}\+", "",
                          raw_name or pdf_font or "").strip()
            if name:
                return name
        return ""

    @staticmethod
    def _map_pdf_font(pdf_font):
        """PDF 内部字体名 → 系统字体名（找不到则返回空串）。

        中文字体优先按「衬线/宋体系」与「无衬线/黑体系」归类到系统自带
        的等价字体；系统本就有的字体（DengXian/SimSun/SimHei/微软雅黑
        等）严格透传不归类，否则会被错误映射到观感完全不同的字体（最
        严重的例子：DengXian → 雅黑会让合同正文普遍视觉"放大"）。
        PyMuPDF 对嵌入子集字体名字段已经去掉子集前缀（如
        `BCDGEE+DengXian` 直接显示为 `DengXian`），无需再处理。
        """
        low = (pdf_font or "").lower()
        if not low:
            return ""
        if "calibri" in low:
            return "Calibri"
        if "cambria" in low:
            return "Cambria"
        # ---- 西文等宽 ----
        if any(k in low for k in ("courier", "consolas", "mono", "等宽")):
            return "Courier New"
        # ---- 西文无衬线（含 Nimbus Sans/Arial/Helvetica）----
        if any(k in low for k in ("helvetica", "helv", "arial",
                                  "arialmt", "nimbus sans", "liberationsans")):
            return "Arial"
        # ---- 西文衬线 ----
        if any(k in low for k in ("times", "roman", "georgia", "garamond",
                                  "liberationserif", "nimbus roman")):
            return "Times New Roman"
        # ---- 楷体 / 仿宋（先于泛化宋体判断，避免被归成宋体）----
        if any(k in low for k in ("kaiti", "kai", "楷", "kaishu")):
            return "KaiTi"
        # ---- 仿宋（注意：不能用裸 "fang"，否则误命中苹方 PingFang）----
        if any(k in low for k in ("fangsong", "仿宋", "stfangsong", "fzfs")):
            return "FangSong"
        # ---- 系统中文字体严格透传（不能与雅黑段混）----
        # DengXian(等线) 是合同等正文中常用细体无衬线，系统自带；
        # 错映射到雅黑会让字形粗一截、字面宽一截，视觉"放大"主因。
        if "dengxian" in low or "等线" in low:
            return "DengXian"
        # ---- 传统粗黑体（SimHei/方正黑体等）----
        if any(k in low for k in ("simhei", "fzhei", "fzht", "方正黑", "黑体")):
            return "SimHei"
        # ---- 宋体 / 明体等衬线中文字体 → SimSun ----
        if any(k in low for k in (
                "simsun", "nssim", "simsun-extb",
                "songti", "stsong", "songsc", "nssong",
                "uming", "ming", "batsong", "thsong", "书宋", "报宋",
                "fzsong", "fzss", "fzxbs", "dhyuan",
                "notoserif", "noto serif", "sourcehanserif", "source han serif",
                "思源宋", "serifcjk", "serif cjk", "serifsc", "stzhongsong",
                "华文中宋")):
            return "SimSun"
        # ---- 现代无衬线中文字体 → 微软雅黑（思源黑/苹方/Noto/Droid Sans
        # Fallback/文泉驿等系统缺失，雅黑观感最接近；不要在此段放进
        # dengxian/heiti/宋体类，会被误命中）----
        if any(k in low for k in (
                "yahei", "msyh", "雅黑", "微软",
                "droid sans fallback", "sourcehansans", "思源黑",
                "pingfang", "stheiti", "jhenghei", "jheng",
                "wqy", "wenquanyi", "sans cjk", "sanssc", "hansans",
                "malgun", "segoe ui", "兰亭黑", "方正兰亭", "华为", "harmonyos")):
            return "Microsoft YaHei"
        # ---- MuPDF 对未嵌入中文字体的 fallback 归一化（合同 PDF 验证：
        # 'Heiti' 在 MuPDF 实际渲染为无衬线 Droid Sans Fallback）----
        if "heiti" in low:
            return "Microsoft YaHei"
        # ---- PyMuPDF 内置 CJK 字体名（极罕见 BaseFont 透出场景；PyMuPDF
        # 文本提取层通常已归一化为 Heiti，仅当透出时命中）----
        if any(k in low for k in ("china-ss", "chinass", "中黑", "hei-gbk")):
            return "SimHei"
        if any(k in low for k in ("china-s", "chinas", "stsong-lite")):
            return "SimSun"
        if any(k in low for k in ("china-ts", "chinats", "china-ks",
                                  "chinaks", "kaiti-sc")):
            return "KaiTi"
        if any(k in low for k in ("china-fs", "chinafs")):
            return "FangSong"
        return ""

    # 常见字体 → Windows 系统全量字体文件（按常规/粗/斜/粗斜四档）。
    # 保证写回字形覆盖全部字符，同时粗斜样式有对应的变体字体文件，
    # 否则 PDF 写回时会丢失原文的粗体/斜体观感。中文多数字体无斜体
    # 变体文件（系统不提供），斜体档回退常规；粗宋体用黑体近似。
    _SYSTEM_FONT_FILES = {
        "SimSun": {"": r"C:\Windows\Fonts\simsun.ttc",
                   "B": r"C:\Windows\Fonts\simhei.ttf",
                   "I": r"C:\Windows\Fonts\simsun.ttc",
                   "BI": r"C:\Windows\Fonts\simhei.ttf"},
        "SimHei": {"": r"C:\Windows\Fonts\simhei.ttf",
                   "B": r"C:\Windows\Fonts\simhei.ttf",
                   "I": r"C:\Windows\Fonts\simhei.ttf",
                   "BI": r"C:\Windows\Fonts\simhei.ttf"},
        "KaiTi": {"": r"C:\Windows\Fonts\simkai.ttf",
                  "B": r"C:\Windows\Fonts\simkai.ttf",
                  "I": r"C:\Windows\Fonts\simkai.ttf",
                  "BI": r"C:\Windows\Fonts\simkai.ttf"},
        "FangSong": {"": r"C:\Windows\Fonts\simfang.ttf",
                     "B": r"C:\Windows\Fonts\simfang.ttf",
                     "I": r"C:\Windows\Fonts\simfang.ttf",
                     "BI": r"C:\Windows\Fonts\simfang.ttf"},
        "Microsoft YaHei": {"": r"C:\Windows\Fonts\msyh.ttc",
                            "B": r"C:\Windows\Fonts\msyhbd.ttc",
                            "I": r"C:\Windows\Fonts\msyh.ttc",
                            "BI": r"C:\Windows\Fonts\msyhbd.ttc"},
        "DengXian": {"": r"C:\Windows\Fonts\deng.ttf",
                     "B": r"C:\Windows\Fonts\dengb.ttf",
                     "I": r"C:\Windows\Fonts\deng.ttf",
                     "BI": r"C:\Windows\Fonts\dengb.ttf"},
        "Arial": {"": r"C:\Windows\Fonts\arial.ttf",
                  "B": r"C:\Windows\Fonts\arialbd.ttf",
                  "I": r"C:\Windows\Fonts\ariali.ttf",
                  "BI": r"C:\Windows\Fonts\arialbi.ttf"},
        "Times New Roman": {"": r"C:\Windows\Fonts\times.ttf",
                            "B": r"C:\Windows\Fonts\timesbd.ttf",
                            "I": r"C:\Windows\Fonts\timesi.ttf",
                            "BI": r"C:\Windows\Fonts\timesbi.ttf"},
        "Segoe UI": {"": r"C:\Windows\Fonts\segoeui.ttf",
                     "B": r"C:\Windows\Fonts\segoeuib.ttf",
                     "I": r"C:\Windows\Fonts\segoeuii.ttf",
                     "BI": r"C:\Windows\Fonts\segoeuiz.ttf"},
        "Calibri": {"": r"C:\Windows\Fonts\calibri.ttf",
                    "B": r"C:\Windows\Fonts\calibrib.ttf",
                    "I": r"C:\Windows\Fonts\calibrii.ttf",
                    "BI": r"C:\Windows\Fonts\calibriz.ttf"},
        "Cambria": {"": r"C:\Windows\Fonts\cambria.ttc",
                    "B": r"C:\Windows\Fonts\cambriab.ttf",
                    "I": r"C:\Windows\Fonts\cambriai.ttf",
                    "BI": r"C:\Windows\Fonts\cambriaz.ttf"},
        "Courier New": {"": r"C:\Windows\Fonts\cour.ttf",
                        "B": r"C:\Windows\Fonts\courbd.ttf",
                        "I": r"C:\Windows\Fonts\couri.ttf",
                        "BI": r"C:\Windows\Fonts\courbi.ttf"},
    }
    _WINDOWS_FONT_REGISTRY = None

    @staticmethod
    def _style_suffix(bold, italic):
        """粗斜组合 → 字体变体档位后缀（无样式为 ''）。"""
        if bold and italic:
            return "BI"
        if bold:
            return "B"
        if italic:
            return "I"
        return ""

    @classmethod
    def _system_font_file(cls, family, bold=False, italic=False):
        """映射字体族名 → 本机系统字体文件（含粗斜变体，缺失回退常规）。

        返回 None 表示系统无对应字体文件。
        """
        import os as _os
        family = (family or "").strip()
        variants = cls._SYSTEM_FONT_FILES.get(family) or {}
        key = cls._style_suffix(bold, italic)
        p = variants.get(key) or variants.get("")
        if p and _os.path.exists(p):
            return p
        # QFontComboBox 会列出所有已安装字体，而静态表只覆盖常用字体。
        # 从 Windows 字体注册表按字族及粗斜体档解析实际文件，确保选择
        # Candara / Corbel / Comic Sans 等字体时不会无提示回退为 Arial。
        if cls._WINDOWS_FONT_REGISTRY is None:
            records = {}
            try:
                import re as _re
                import winreg as _winreg
                roots = [
                    (_winreg.HKEY_LOCAL_MACHINE,
                     r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
                    (_winreg.HKEY_CURRENT_USER,
                     r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
                ]
                suffixes = [
                    (" bold italic", "BI"), (" bold oblique", "BI"),
                    (" semibold italic", "BI"), (" semibold", "B"),
                    (" bold", "B"), (" italic", "I"), (" oblique", "I"),
                    (" regular", ""),
                ]
                for root, subkey in roots:
                    try:
                        key_handle = _winreg.OpenKey(root, subkey)
                    except OSError:
                        continue
                    try:
                        index = 0
                        while True:
                            try:
                                label, value, _kind = _winreg.EnumValue(
                                    key_handle, index)
                                index += 1
                            except OSError:
                                break
                            if not isinstance(value, str) or not value:
                                continue
                            label = _re.sub(r"\s*\([^)]*\)\s*$", "", label).strip()
                            style = ""
                            lowered = label.casefold()
                            for suffix, candidate in suffixes:
                                if lowered.endswith(suffix):
                                    label = label[:-len(suffix)].strip()
                                    style = candidate
                                    break
                            path = (value if _os.path.isabs(value) else
                                    _os.path.join(_os.environ.get(
                                        "WINDIR", r"C:\Windows"), "Fonts", value))
                            if not _os.path.exists(path):
                                continue
                            for name in _re.split(r"\s*&\s*", label):
                                normalized = _re.sub(r"\s+", " ", name).strip().casefold()
                                if normalized:
                                    records.setdefault(normalized, {})[style] = path
                    finally:
                        _winreg.CloseKey(key_handle)
            except Exception:
                records = {}
            cls._WINDOWS_FONT_REGISTRY = records
        import re as _re
        normalized_family = _re.sub(r"\s+", " ", family).strip().casefold()
        dynamic = (cls._WINDOWS_FONT_REGISTRY or {}).get(normalized_family) or {}
        p = dynamic.get(key) or dynamic.get("")
        if p and _os.path.exists(p):
            return p
        return None

    def _embed_for_style(self, family, size, bold, italic):
        """按「系统字体族 + 粗斜档」生成写回 embed（全量变体字体文件）。

        就地编辑产生的浮层对象带“原行样式”的 embed；用户在格式条里把
        字族/字号/粗斜改成新值后，旧 embed 仍指向原样式的字体文件，
        保存烘焙（_bake_text_original_font）会用旧字体直写，导致新斜体/
        粗细被忽略。此处按新样式重建 embed；系统无该族/变体文件时返回
        None（调用方改走 htmlbox，其粗斜由内置变体字体承载同样生效）。
        """
        import os as _os
        import re as _re
        try:
            fpath = self._system_font_file(
                family or "", bold=bold, italic=italic)
            if not fpath or not _os.path.exists(fpath):
                return None
            clean = _re.sub(r"[^A-Za-z0-9]", "", family or "") or "txt"
            suffix = self._style_suffix(bold, italic)
            name = clean + suffix
            return {"name": name, "file": fpath}
        except Exception:
            return None

    def _sync_embed_after_restyle(self, obj, family, size, bold, italic):
        """浮层文本对象被改过样式后，同步其 embed 指向新样式字体。

        仅当 obj 已带 embed（即“就地编辑原 PDF 行”产生的对象）且样式相对
        原值确有变化时处理：能重建系统变体字体 embed 就重建；不能则移除
        embed 让保存走 htmlbox（避免继续用旧字体忽略用户设置）。返回
        True 表示 embed 已被更新/移除。
        """
        if not obj.get("embed"):
            return False
        fam_changed = (family or "") != (obj.get("fontfamily") or "")
        size_changed = float(size) != float(obj.get("fontsize") or 0)
        bold_changed = bool(bold) != bool(obj.get("bold"))
        italic_changed = bool(italic) != bool(obj.get("italic"))
        if not (fam_changed or size_changed or bold_changed
                or italic_changed):
            return False
        # 中文斜体：保存烘焙时用 morph 错切合成（正体字形即可承载），
        # 无需换斜体字体档。字族/字号/粗细都没变、仅勾选斜体时保留原
        # embed（多为原行小子集字体），避免重建 20MB 级系统字体拖慢
        # 保存并使输出文件膨胀。
        if italic_changed and not (fam_changed or size_changed
                                   or bold_changed) and italic:
            try:
                txt = str(obj.get("text") or "")
                if any(backend._is_cjk_char(c) for c in txt):
                    return True
            except Exception:
                pass
        new_embed = self._embed_for_style(family, size, bold, italic)
        if new_embed is not None:
            obj["embed"] = new_embed
            obj["baseline"] = None
        else:
            obj.pop("embed", None)
            obj.pop("baseline", None)
        return True


    def _extract_embed_buffer(self, page, span_font):
        """按字体名从页面资源中抽取原嵌入字体的 buffer。

        返回 (buffer|None, 原始字体名|'', 字体类型|'')。内置/未嵌入/
        Type3 字体（xref 不可抽取）返回 (None, '', '')，由调用方回退
        系统字体。字体类型用于区分 CID(Type0) 子集——PyMuPDF 的
        Font(fontbuffer=) 对 Type0 子集 has_glyph 恒 False，字形覆盖
        须改用原行文本启发式判定。
        """
        try:
            cleaned = re.sub(r"^[A-Za-z]{6}\+", "",
                             (span_font or "")).strip()
            base = re.sub(r"[\s-]", "", cleaned).lower()
            if not base:
                return None, "", ""
            for f in page.get_fonts(full=True):
                cand = re.sub(r"[\s-]", "", (f[3] or "")).lower()
                if not cand:
                    continue
                hit = (base in cand or cand in base or
                       cand.startswith(base) or base.startswith(cand))
                if not hit:
                    continue
                try:
                    _nm, _ext, _sub, buf = self.doc.extract_font(f[0])
                except Exception:
                    continue
                if buf:
                    return (buf, (cleaned or _nm or (f[3] or "")),
                            str(f[2] or _sub or ""))
        except Exception:
            pass
        return None, "", ""

    def _subset_covers(self, fo, font_type, text, orig_text):
        """原嵌入子集字体能否覆盖待写文本全部字形。

        CID(Type0) 子集：恒不放行。PyMuPDF 的 Font(fontbuffer=) 对 Type0
        子集 has_glyph 恒 False；且 subnet 后 FontFile2 丢失 Unicode cmap，
        insert_font 重嵌会全部映射为 \x00/豆腐（实测渲染非白采样仅 169 点），
        因此中文等 CID 子集一律回退系统全量字体（嵌入后由保存时
        subset_fonts 裁成小子集，文件不膨胀）。
        非 Type0（TrueType/Type1 简单子集）：has_glyph 可靠，直接判定。
        """
        txt = (text or "").strip()
        if not txt:
            return True
        low = (font_type or "").lower()
        if "type0" in low or "cid" in low:
            return False
        try:
            return all(fo.has_glyph(ord(c)) for c in txt
                       if not c.isspace())
        except Exception:
            return False


    def _update_text_object(self, oid, runs):
        """编辑条确定：用富文本 runs 更新既有文本对象。

        多段（字符级混排）→ 对象带 runs、去掉 embed 走逐段写回；
        单段 → 回到单一格式对象，样式相对原值有变时同步重建 embed。
        """
        obj = self._find_object(oid)
        if obj is None:
            return
        runs = merge_runs(runs)
        text = runs_text(runs)
        if not text.strip():
            self.delete_object(oid)
            return
        r0 = runs[0] if runs else {}
        family = r0.get("family") or obj.get("fontfamily", "")
        size = float(r0.get("size") or obj.get("fontsize") or 10)
        color = (r0.get("color") if isinstance(r0.get("color"), QColor)
                 else obj.get("color") or QColor(0, 0, 0))
        bold = bool(r0.get("bold", obj.get("bold", False)))
        italic = bool(r0.get("italic", obj.get("italic", False)))
        if len(runs) > 1:
            # 字符级混排：保存逐段写回，放弃单一原字体 embed
            self.begin_undo_step()
            obj["text"] = text
            obj["fontfamily"] = family
            obj["fontsize"] = size
            obj["color"] = QColor(color)
            obj["bold"] = bold
            obj["italic"] = italic
            obj["runs"] = runs
            obj.pop("embed", None)
            obj.pop("baseline", None)
        else:
            # 单段整条改过样式 → 让 embed 跟随新样式（否则保存会沿用
            # 旧 embed 的原行字体文件，丢失用户新设的斜体/粗细/字体）。
            # 注意：须先于字段覆盖调用，_sync 用对象原值判断样式是否变化。
            self._sync_embed_after_restyle(obj, family, size, bold, italic)
            self.begin_undo_step()
            obj["text"] = text
            obj["fontfamily"] = family
            obj["fontsize"] = size
            obj["color"] = QColor(color)
            obj["bold"] = bold
            obj["italic"] = italic
            obj.pop("runs", None)
        # 文字变长时自动加宽对象，避免保存排版折行
        new_w = max(obj["rect"].width(), self._est_runs_width(runs))
        obj["rect"].setWidth(new_w)
        self.modified = True
        self._refresh_objects()
        self.page_view.select(oid)


    @staticmethod
    def _est_runs_width(runs):
        """按各段字号估算混排 runs 的总宽度（PDF pt，字符级近似）。

        与单行估算同思路：东亚字约 1.0em、西文约 0.55em，按段字号累加，
        不依赖系统字体度量，避免与保存排版宽度不一致导致折行。
        """
        total = 0.0
        for r in (runs or []):
            size = max(4.0, float(r.get("size") or 10.0))
            for ch in r.get("text", ""):
                total += size if ord(ch) > 0x2E80 else size * 0.55
        return total * 1.06 + 6.0

    @staticmethod
    def _trim_runs(runs):
        """去掉混排 runs 首尾的空白（首段去左侧、末段去右侧）。"""
        runs = merge_runs(runs)
        if not runs:
            return []
        runs[0]["text"] = (runs[0]["text"] or "").lstrip()
        runs[-1]["text"] = (runs[-1]["text"] or "").rstrip()
        return merge_runs(runs)

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
        # 图片和签名创建后统一进入编辑模式，随后才允许移动、缩放、
        # 替换或删除；阅读/选择模式不再承担对象编辑职责。
        self.set_mode("replace_text")
        self._refresh_objects()
        self.page_view.select(self._obj_counter)

    def _add_text_object(self, text, page, pt, fontfamily="", fontsize=12, color=None,
                         bold=False, italic=False, keep_mode=False, runs=None):
        if runs:
            runs = merge_runs(runs)
            text = runs_text(runs)
            if runs:
                r0 = runs[0]
                fontfamily = r0.get("family") or fontfamily
                fontsize = r0.get("size") or fontsize
                color = r0.get("color") if isinstance(
                    r0.get("color"), QColor) else color
                bold = bool(r0.get("bold"))
                italic = bool(r0.get("italic"))
            if len(runs) > 1:
                rect = QRectF(0, 0, self._est_runs_width(runs),
                              max(16.0, float(fontsize or 12.0) * 1.35 + 6.0))
            else:
                runs = None    # 单段统一格式 → 与既有对象模型一致
        if not runs:
            rect = self._measure_text_rect(text, fontfamily, fontsize,
                                           bold, italic)
        rect.moveTo(pt.x(), pt.y())
        self.begin_undo_step()
        self._obj_counter += 1
        obj = {
            "id": self._obj_counter, "page": page,
            "rect": rect,
            "text": text, "color": color if color is not None else QColor(0, 0, 0),
            "fontsize": fontsize, "fontfamily": fontfamily, "bold": bold,
            "italic": italic, "kind": "text",
        }
        if runs and len(runs) > 1:
            obj["runs"] = runs
        else:
            # “添加文字”过去只保存 fontfamily 字符串，烘焙时 generic
            # HTML 路径会把它压成 serif / sans-serif / monospace，导致用户
            # 选中的具体字体在保存后失效。单样式新文字直接携带对应系统
            # 字体文件，与修改既有文字的字体保真路径保持一致。
            embed = self._embed_for_style(
                fontfamily, fontsize, bool(bold), bool(italic))
            if embed:
                obj["embed"] = embed
        self.objects.append(obj)
        self.modified = True
        if not keep_mode:
            self.set_mode("view")
        self._refresh_objects()
        self.page_view.select(self._obj_counter)

    @staticmethod
    def _measure_text_rect(text, fontfamily, fontsize, bold, italic=False):
        """根据文字内容测量单行框大小（返回 PDF 坐标 QRectF）。"""
        from PySide6.QtGui import QFont, QFontMetrics
        f = QFont(_qt_safe_family(fontfamily or "Microsoft YaHei UI"))
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
        obj = self._find_object(oid)
        if obj is None:
            return
        native = bool(obj.get("native_proxy"))
        if not self.begin_undo_step(document_change=native):
            return
        detached = self._detach_native_annotation(obj) if native else False
        self.objects = [o for o in self.objects if o["id"] != oid]
        self.modified = True
        if detached:
            self._refresh()
        else:
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
        self._edit_text_object(oid)

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
            native = bool(obj.get("native_proxy"))
            if not self.begin_undo_step(document_change=native):
                return
            detached = self._detach_native_annotation(obj) if native else False
            obj["text"] = text
            self.modified = True
            if detached:
                self._refresh()
            self.page_view.select(oid)
            self.statusMessage.emit(i18n.tr("note_updated"), 3000)

    def _edit_text_object(self, oid):
        """就地编辑既有文字对象（双击对象 / 对象右键「编辑文字」共用）。

        不再弹大编辑条：直接在对象原位置打开就地富文本编辑框，按对象
        现有样式（runs 混排或单一格式）预填；框内拖动选中字符后右键
        「格式编辑…」可弹出独立模块做字符级局部修改。回车/失焦提交，
        Esc 取消。
        """
        if not self._require_permission(pymupdf.PDF_PERM_MODIFY, "编辑文档"):
            return
        obj = self._find_object(oid)
        if obj is None or obj.get("kind") != "text":
            return
        self._close_inline_editor()
        from PySide6.QtGui import QFont as _QFont
        canvas = self.page_view
        zoom = canvas._zoom
        page = int(obj.get("page", 0))
        r = obj["rect"]
        wx = r.x() * zoom
        wy = canvas._offsets[page] + r.y() * zoom
        ww = r.width() * zoom
        wh = max(2.0, r.height() * zoom)

        runs = merge_runs(obj.get("runs")) if obj.get("runs") else None
        if not runs:
            runs = single_run(
                str(obj.get("text", "")), obj.get("fontfamily", ""),
                float(obj.get("fontsize") or 10.0),
                (obj.get("color") if isinstance(obj.get("color"), QColor)
                 else QColor(self.edit_color)),
                bool(obj.get("bold", False)),
                bool(obj.get("italic", False)))
        r0 = runs[0]
        size = float(r0.get("size") or 10.0)
        color = (r0.get("color") if isinstance(r0.get("color"), QColor)
                 else QColor(self.edit_color))
        # 与 _begin_inplace_text/页面绘制一致：对象 runs 的字族可能来自
        # PDF 嵌入子集名（"Nimbus Sans Regular" 等），必须安全化为系统已
        # 安装族名，否则编辑框 QFont 解析空族名 → 输入/选中字符全方块。
        family = _qt_safe_family(
            r0.get("family") or "Microsoft YaHei")
        lum = (0.299 * color.red() + 0.587 * color.green() +
               0.114 * color.blue())
        text_color = color.name() if lum > 225 else (
            "#1c1c1e" if lum > 200 else color.name())

        font_px = max(9.0, size * zoom)
        box_h = max(wh + 4.0, font_px * 1.35 + 4.0)
        center_y = wy + wh / 2.0
        by = int(center_y - box_h / 2.0)
        bx = max(0, int(wx - 1))
        page_px_w = backend.page_size(self.doc, page)[0] * zoom
        avail_w = max(2.0, page_px_w - bx)
        est_px = self._est_runs_width(runs) * zoom
        box_w = max(ww + 6.0, min(est_px + 14.0, avail_w))
        box_w = min(box_w, avail_w)

        edit = RichEditBox(canvas)
        edit.setObjectName("objEditInline")
        edit.set_scale(zoom)
        _wf = _QFont(family)
        _wf.setPixelSize(int(round(font_px)))
        _wf.setBold(bool(r0.get("bold", False)))
        _wf.setItalic(bool(r0.get("italic", False)))
        edit.setFont(_wf)
        # 编辑器覆盖在页面上，采用近纸色半透明底 + 主题蓝细框，文字
        # 颜色由 runs 各自字符格式决定，此处仅作兜底。
        edit.setStyleSheet(
            "QTextEdit#objEditInline{"
            "background-color: rgba(255,255,255,0.94);"
            "border: 1px solid #0a84ff; border-radius: 2px;"
            "padding: 0 2px; color: %s;"
            "selection-background-color: #b6d7ff;"
            "selection-color: #101418;}" % text_color)
        edit.set_runs(runs)
        edit.setGeometry(bx, by, int(box_w), int(box_h))
        edit.raise_()
        edit.show()
        edit.setFocus()
        # 光标定位到鼠标双击处的字符（点哪改哪）；鼠标不在框内
        # （键盘/程序触发）则放到文字末尾，避免误覆盖整段。
        click_pos = edit.mapFromGlobal(QCursor.pos())
        cur = edit.textCursor()
        if edit.rect().contains(click_pos):
            cur = edit.cursorForPosition(click_pos)
        else:
            cur.movePosition(QTextCursor.MoveOperation.End)
        edit.setTextCursor(cur)
        edit.sync_typing_format_from_cursor()
        edit.submitRequested.connect(self._finish_object_edit)
        edit.installEventFilter(self)
        self._obj_edit = edit
        self._obj_edit_oid = oid

    def _finish_object_edit(self):
        """回车提交就地对象编辑，并把键盘焦点还给画布。"""
        self._commit_object_edit(commit=True)
        if self.page_view is not None:
            self.page_view.setFocus()

    def _commit_object_edit(self, commit=True):
        """关闭就地对象编辑框。commit=True 且有改动时更新对象。

        返回是否曾处于就地对象编辑状态。
        """
        edit = getattr(self, "_obj_edit", None)
        if edit is None:
            return False
        oid = getattr(self, "_obj_edit_oid", None)
        runs = merge_runs(edit.to_runs())
        self._close_inline_editor()
        if not commit or oid is None:
            return True
        obj = self._find_object(oid)
        if obj is None:
            return True
        text = runs_text(runs)
        if not text.strip():
            self.delete_object(oid)
            return True
        if self._runs_same_as_object(obj, runs):
            return True            # 未改动，不产生撤销记录
        self._update_text_object(oid, runs)
        return True

    @staticmethod
    def _runs_same_as_object(obj, runs):
        """就地编辑前后内容/样式是否一致（用于跳过无改动提交）。"""
        from rich_text import _style_key
        obj_runs = merge_runs(obj.get("runs")) if obj.get("runs") else None
        if not obj_runs:
            obj_runs = single_run(
                str(obj.get("text", "")), obj.get("fontfamily", ""),
                float(obj.get("fontsize") or 10.0),
                (obj.get("color") if isinstance(obj.get("color"), QColor)
                 else QColor(0, 0, 0)),
                bool(obj.get("bold", False)),
                bool(obj.get("italic", False)))
        kb = [_style_key(r) for r in obj_runs]
        ka = [_style_key(r) for r in runs]
        return ka == kb

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
            native = bool(obj.get("native_proxy"))
            if not self.begin_undo_step(document_change=native):
                return
            detached = self._detach_native_annotation(obj) if native else False
            obj["color"] = QColor(c)
            self.edit_color = QColor(c)
            self.modified = True
            if detached:
                self._refresh()
            else:
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
        native = bool(obj.get("native_proxy"))
        detached = False
        if old_rect is not None:
            old_rect = QRectF(old_rect)
            if old_rect == new_rect:
                return
            # PageView 与此处共享对象字典，鼠标拖动时对象已是新矩形。
            # 临时恢复旧值后记录，保证撤销回到拖动开始的位置。
            obj["rect"] = old_rect
            if not self.begin_undo_step(document_change=native):
                self._refresh_objects()
                return
            detached = self._detach_native_annotation(obj) if native else False
        elif QRectF(obj["rect"]) != new_rect:
            if not self.begin_undo_step(document_change=native):
                return
            detached = self._detach_native_annotation(obj) if native else False
        elif native:
            # 某些调用方与 PageView 共享对象字典，进入此处时 rect 已经是
            # 新值；原生批注仍需脱离，否则保存后会恢复到旧位置。
            if not self.begin_undo_step(document_change=True):
                return
            detached = self._detach_native_annotation(obj)
        obj["rect"] = new_rect
        self.modified = True
        if detached:
            self._refresh()
            self.page_view.select(oid)

    def _on_object_rotated(self, oid, rotation, old_rotation):
        """提交保存前图片/签名的一次旋转，并合并为一个撤销步骤。"""
        obj = self._find_object(oid)
        if obj is None or obj.get("kind") not in ("image", "signature"):
            return
        obj["rotation"] = float(old_rotation)
        if not self.begin_undo_step():
            self._refresh_objects()
            return
        obj["rotation"] = float(rotation)
        self.modified = True
        self._refresh_objects()
        self.page_view.select(oid)
        self.statusMessage.emit("对象已旋转，可按 Ctrl+Z 撤销", 3500)

    def _on_object_selected(self, oid):
        obj = self._find_object(oid) if oid is not None else None
        reading_annotation = (
            self.current_mode == "view" and obj is not None and
            obj.get("kind") in ({"note"} | ANNOTATION_OBJECT_KINDS))
        if self.current_mode != "replace_text" and not reading_annotation:
            return
        if oid is not None:
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
                    "拖动移动，控制点缩放，上方圆点旋转，Delete 删除", 6000)

    def delete_selected(self):
        record = getattr(self, "_selected_pdf_content", None)
        oid = self.page_view.selected_id()
        selected_obj = self._find_object(oid) if oid is not None else None
        reading_annotation = (
            self.current_mode == "view" and selected_obj is not None and
            selected_obj.get("kind") in ({"note"} | ANNOTATION_OBJECT_KINDS))
        # 阅读模式只允许删除批注；图片、签名、文字和 PDF 图片仍必须进入
        # 编辑模式。页面缩略图有独立删除入口，不受这里影响。
        if self.current_mode != "replace_text" and not reading_annotation:
            if record is not None or oid is not None:
                return
        if record is not None:
            if not self._require_permission(pymupdf.PDF_PERM_MODIFY, "编辑文档"):
                return
            if not self.begin_undo_step(document_change=True):
                return
            if (record.get("kind") == "image"):
                removed = backend.remove_pdf_image_object(self.doc, record)
            else:
                removed = bool(backend.remove_watermark(self.doc, record))
            if not removed:
                self.undo()
                self.statusMessage.emit("无法安全删除该对象", 3500)
                return
            pages = list(record.get("pages") or [record.get("page", 0)])
            self._selected_pdf_content = None
            self.modified = True
            self.page_view.set_edit_selection()
            for pno in pages:
                self.page_view.invalidate_text_cache(int(pno))
                self.page_view._images.pop(int(pno), None)
                self.page_view._render_page(int(pno))
            self.page_view.update()
            self.statusMessage.emit("对象已删除，可按 Ctrl+Z 撤销", 3500)
            return
        self.delete_object(oid)

    def _on_pdf_image_changed(self, page, rect, old_rect):
        """提交编辑模式中 PDF 图片/已保存签名的一次移动或自由缩放。"""
        record = getattr(self, "_selected_pdf_content", None)
        if (record is None or record.get("kind") != "image" or
                int(record.get("page", -1)) != int(page)):
            self.page_view.set_edit_selection(int(page), old_rect)
            return
        if not self._require_permission(pymupdf.PDF_PERM_MODIFY, "编辑文档"):
            self.page_view.set_edit_selection(int(page), old_rect)
            return
        moved_or_resized = QRectF(rect) != QRectF(old_rect)
        if not moved_or_resized:
            self.page_view.set_edit_selection(int(page), old_rect)
            return
        if not self.begin_undo_step(document_change=True):
            self.page_view.set_edit_selection(int(page), old_rect)
            return
        size_changed = (abs(float(rect.width() - old_rect.width())) > 1e-7 or
                        abs(float(rect.height() - old_rect.height())) > 1e-7)
        if size_changed:
            changed = backend.resize_pdf_image_object(
                self.doc, record,
                [rect.left(), rect.top(), rect.right(), rect.bottom()])
        else:
            dx = float(rect.x() - old_rect.x())
            dy = float(rect.y() - old_rect.y())
            changed = backend.move_pdf_image_object(self.doc, record, dx, dy)
        if not changed:
            self.undo()
            self.statusMessage.emit("无法安全移动或缩放该图片对象", 3500)
            return
        pno = int(page)
        self.modified = True
        self.page_view.invalidate_text_cache(pno)
        self.page_view._images.pop(pno, None)
        self.page_view._render_page(pno)
        # 重新枚举以取得 PDF 引擎计算后的精确 bbox/变换，便于连续拖动。
        fresh = next((item for item in backend.isolated_image_objects(
            self.doc, pno) if item.get("id") == record.get("id")), None)
        if fresh is not None:
            self._selected_pdf_content = fresh
            rr = fresh.get("rect") or record.get("rect")
            rect = QRectF(float(rr[0]), float(rr[1]),
                          float(rr[2]) - float(rr[0]),
                          float(rr[3]) - float(rr[1]))
        self.page_view.set_edit_selection(pno, rect, self._selected_pdf_content)
        self.page_view.setFocus()
        self.statusMessage.emit(
            "图片已缩放，可按 Ctrl+Z 撤销" if size_changed else
            "图片已挪动，可按 Ctrl+Z 撤销", 3500)

    def _on_pdf_image_rotated(self, page, degrees):
        """提交编辑模式中 PDF 图片/已保存签名的任意角度旋转。"""
        record = getattr(self, "_selected_pdf_content", None)
        if (record is None or record.get("kind") != "image" or
                int(record.get("page", -1)) != int(page)):
            return
        if not self._require_permission(pymupdf.PDF_PERM_MODIFY, "编辑文档"):
            return
        if abs(float(degrees)) < 1e-5:
            return
        if not self.begin_undo_step(document_change=True):
            return
        if not backend.rotate_pdf_image_object(self.doc, record, degrees):
            self.undo()
            self.statusMessage.emit("无法安全旋转该图片对象", 3500)
            return
        pno = int(page)
        self.modified = True
        self.page_view.invalidate_text_cache(pno)
        self.page_view._images.pop(pno, None)
        self.page_view._render_page(pno)
        fresh = next((item for item in backend.isolated_image_objects(
            self.doc, pno) if item.get("id") == record.get("id")), None)
        if fresh is not None:
            self._selected_pdf_content = fresh
            rr = fresh.get("rect") or record.get("rect")
        else:
            rr = record.get("rect")
        rect = QRectF(float(rr[0]), float(rr[1]),
                      float(rr[2]) - float(rr[0]),
                      float(rr[3]) - float(rr[1]))
        self.page_view.set_edit_selection(pno, rect, self._selected_pdf_content)
        self.page_view.setFocus()
        self.statusMessage.emit("图片已旋转，可按 Ctrl+Z 撤销", 3500)

    def _replace_selected_pdf_image(self, record, rect):
        """替换“修改文字”模式选中的独立 PDF 图片对象。"""
        if not self._require_permission(pymupdf.PDF_PERM_MODIFY, "编辑文档"):
            return False
        path, _ = QFileDialog.getOpenFileName(
            self, "替换图片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return False
        preview = QImage(path)
        if preview.isNull():
            QMessageBox.warning(self, "替换图片", "无法读取所选图片。")
            return False
        try:
            with open(path, "rb") as stream:
                image_bytes = stream.read()
        except OSError as exc:
            QMessageBox.warning(self, "替换图片", f"无法读取所选图片：\n{exc}")
            return False
        if not self.begin_undo_step(document_change=True):
            return False
        if not backend.replace_isolated_image_object(
                self.doc, record, image_bytes):
            self.undo()
            QMessageBox.warning(self, "替换图片", "无法安全替换该图片对象。")
            return False
        pno = int(record.get("page", 0))
        self.modified = True
        self._selected_pdf_content = record
        self.page_view.invalidate_text_cache(pno)
        self.page_view._images.pop(pno, None)
        self.page_view._render_page(pno)
        self.page_view.set_edit_selection(pno, rect, self._selected_pdf_content)
        self.page_view.setFocus()
        self.statusMessage.emit("图片已替换，原缩放、旋转和透明度保持不变", 4500)
        return True

    def _on_context_menu(self, global_pos):
        menu = self._build_context_menu(global_pos)
        if menu.actions():
            menu.exec(global_pos)

    def _build_context_menu(self, global_pos):
        """构建右键菜单(不弹出)。抽出以便测试直接断言菜单项；text 对象
        右键已去掉「编辑文字/更改颜色」入口(编辑走双击就地编辑、改色走
        编辑框内「格式编辑…」)，批注对象保留「更改颜色」。"""
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
            action = menu.addAction(i18n.tr("image"))
            if target is not None:
                page, point = target
                action.triggered.connect(
                    lambda _checked=False, p=page, pt=point:
                    self.start_image(p, pt))
            action.setEnabled(can_modify and target is not None)
            menu.addSeparator()
        editing = self.current_mode == "replace_text"
        annotation_interaction = (
            self.current_mode == "view" and sel_obj is not None and
            sel_obj.get("kind") in ({"note"} | ANNOTATION_OBJECT_KINDS))
        if (editing or annotation_interaction) and sel_obj is not None:
            if sel_obj.get("kind") == "note":
                action = menu.addAction(
                    i18n.tr("edit_annotation"),
                    lambda: self._edit_note_object(oid))
                action.setEnabled(can_annotate)
                menu.addSeparator()
            elif sel_obj.get("kind") in ANNOTATION_OBJECT_KINDS:
                action = menu.addAction(
                    i18n.tr("change_color"),
                    lambda: self._change_annotation_color(oid))
                action.setEnabled(can_annotate)
                menu.addSeparator()
            action = menu.addAction(i18n.tr("delete_object"), self.delete_selected)
            action.setEnabled(can_modify or can_annotate)
        pdf_record = getattr(self, "_selected_pdf_content", None)
        if (editing and pdf_record is not None and
                pdf_record.get("kind") == "image"):
            action = menu.addAction(
                "替换图片", lambda: self._replace_selected_pdf_image(
                    pdf_record, self.page_view._edit_selected[1]))
            action.setEnabled(can_modify)
            action = menu.addAction(i18n.tr("delete_object"), self.delete_selected)
            action.setEnabled(can_modify)
        if self.pending_sign_qimg is not None or self.pending_image_qimg is not None \
                or self.pending_paste_text or self.pending_note_text:
            menu.addAction(i18n.tr("cancel_place"), self._cancel_placement)
        menu.addSeparator()
        menu.addAction(i18n.tr("fit_width2"), self.fit_width)
        return menu

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
        self._selected_pdf_content = None
        self.page_view.set_edit_selection()
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
        # 签名设计与签名库共用此入口。先通过正式模式切换退出“修改文字”
        # 覆盖层并提交可能尚未失焦的行内编辑，再进入点击放置状态。
        self.set_mode("view")
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

        保留请求的分辨率；驱动的位图尺寸限制由输出时分块处理。
        返回 RGB32 格式 QImage（驱动兼容性最好）。
        doc：外部 pymupdf Document（多文档拼版用）；默认当前 self.doc。
        """
        use_doc = doc if doc is not None else self.doc
        page = use_doc[page_no]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csRGB,
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

    @staticmethod
    def _print_target_size(page_rect, cell, resolution, scale_mode,
                           custom_scale=1.0, rotation=0):
        from print_dialog import print_target_size
        return print_target_size(page_rect, cell, resolution, scale_mode,
                                 custom_scale, rotation)

    @staticmethod
    def _draw_print_image(painter, target, image):
        # 保持高分辨率，将单次发送给 GDI 的位图控制在 2000px 内。
        # 相邻块共用浮点边界，避免整数截断产生缝隙。
        for top in range(0, image.height(), 2000):
            for left in range(0, image.width(), 2000):
                width = min(2000, image.width() - left)
                height = min(2000, image.height() - top)
                rect = QRectF(target.x() + left * target.width() / image.width(),
                              target.y() + top * target.height() / image.height(),
                              width * target.width() / image.width(),
                              height * target.height() / image.height())
                painter.drawImage(rect, image.copy(left, top, width, height))

    def print_pdf(self):
        """打印：同一个文档的多页按 N 页/张 排版（N-up），预览同步。"""
        if self.doc is None:
            QMessageBox.information(self, i18n.tr("hint"),
                                    i18n.tr("need_open_pdf"))
            return
        if not self._require_permission(pymupdf.PDF_PERM_PRINT, i18n.tr("menu_print")):
            return
        from print_dialog import (PrintDialog, ALIGN_TOP_CENTER,
                                  ALIGN_BOTTOM_CENTER, _nup_grid)
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

        # 预览与打印使用同一页码列表。
        pages = dlg.selected_pages()
        if dlg.reverse_order():
            pages.reverse()
        copies = max(1, dlg.copies())
        if not pages:
            return
        all_pages = []
        for _ in range(copies):
            all_pages.extend(pages)
            # 每份从新纸开始，不能拼到上一份末页的空白格里。
            all_pages.extend([None] * ((-len(pages)) % nup))
        if not all_pages:
            return

        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.critical(self, i18n.tr("hint"),
                                 i18n.tr("print_failed"))
            return
        try:
            page_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
            # 非 fullPage 模式下，QPainter 原点已经位于可打印区域左上角。
            # pageRect 的物理纸张边距不能再次加到绘制坐标上。
            if not printer.fullPage():
                page_rect.moveTo(0, 0)
            res = max(72, printer.resolution())
            cols, rows = _nup_grid(nup)
            cell_w = page_rect.width() / cols
            cell_h = page_rect.height() / rows

            placed = 0
            is_first_sheet = True
            for page_no in all_pages:
                # 每张纸的首个页面才 newPage（同一张纸内不 newPage）
                if placed == 0 and not is_first_sheet:
                    if not printer.newPage():
                        QMessageBox.critical(self, i18n.tr('hint'), i18n.tr('print_failed'))
                        return
                is_first_sheet = False

                if page_no is None:
                    placed = (placed + 1) % nup
                    continue

                col = placed % cols
                row = placed // cols
                cell = QRectF(page_rect.x() + col * cell_w,
                              page_rect.y() + row * cell_h,
                              cell_w, cell_h)

                source_rect = self.doc[page_no].rect
                dw, dh = self._print_target_size(
                    source_rect, cell, res, scale_mode, custom_scale, rot)
                source_width = (source_rect.height if rot % 180
                                else source_rect.width)
                # 按纸上实际尺寸提供最高 600 DPI 的细节，避免 N-up
                # 浪费内存，也避免自定义放大时仍使用低分辨率原图。
                zoom = dw / source_width * min(res, 600) / res
                img = self._render_print_page(page_no, zoom, rot, want_gray)

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

                painter.save()
                painter.setClipRect(cell)
                self._draw_print_image(painter, QRectF(x, y, dw, dh), img)
                painter.restore()

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
                if getattr(obj, "_suppress_focusout", 0) > 0:
                    # 正在弹出右键格式菜单：失焦交给菜单，不提交不关闭
                    return False
                # 点击页面其它处 / 其它行：把当前行改动提交写回；
                # 置位标记避免随后 textLineClicked(None) 重复提示。
                self._row_focus_pending = True
                self._commit_row_edit(commit=True)
                return False
        if obj is getattr(self, "_obj_edit", None):
            if event.type() == QEvent.Type.KeyPress and \
                    event.key() == Qt.Key.Key_Escape:
                # 就地对象编辑：Esc 仅取消本次编辑，不写回
                self._commit_object_edit(commit=False)
                self.page_view.setFocus()
                return True
            if event.type() == QEvent.Type.FocusOut:
                if getattr(obj, "_suppress_focusout", 0) > 0:
                    # 正在弹右键菜单/格式编辑对话框：失焦交给弹窗，
                    # 不提交不关闭，保证确认后改动仍落在原编辑框上。
                    return False
                # 点击页面其它处：把对象改动提交写回
                self._commit_object_edit(commit=True)
                return False
        if obj is getattr(self, "_inplace_edit", None):
            if event.type() == QEvent.Type.KeyPress and \
                    event.key() == Qt.Key.Key_Escape:
                # 「文本」工具就地输入：Esc 取消本次输入，不写入文档
                self._commit_inplace_text(commit=False)
                self.page_view.setFocus()
                return True
            if event.type() == QEvent.Type.FocusOut:
                if getattr(obj, "_suppress_focusout", 0) > 0:
                    return False
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
