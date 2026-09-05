"""打印对话框（简洁版）：打印机/范围/份数/缩放/位置/方向/纸张/每张页数 + 右侧预览。"""
from collections import OrderedDict
from PySide6.QtCore import Qt, QSize, QSizeF, QRectF, QTimer
from PySide6.QtGui import QImage, QPixmap, QPageLayout, QPageSize, QPainter, QPen, QColor
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QDialogButtonBox,
                               QGroupBox, QHBoxLayout, QLabel, QPushButton, QRadioButton,
                               QSpinBox, QVBoxLayout, QWidget, QMessageBox, QSizePolicy,
                               QGridLayout)

import i18n

# 缩放
SCALE_FIT = 0
SCALE_ACTUAL = 1
SCALE_CUSTOM = 2

# 位置
POS_CENTER = "center"          # 居中
POS_TOP_CENTER = "top_center"  # 靠上居中
POS_BOTTOM_CENTER = "bottom_center"  # 靠下居中

# 纸张（QPageSize 对象）
PAPERS = {
    "A4": QPageSize(QPageSize.PageSizeId.A4),
    "A3": QPageSize(QPageSize.PageSizeId.A3),
    "A5": QPageSize(QPageSize.PageSizeId.A5),
    "B5": QPageSize(QPageSize.PageSizeId.JisB5),
    "B5 (ISO)": QPageSize(QPageSize.PageSizeId.B5),
    "Letter": QPageSize(QPageSize.PageSizeId.Letter),
    "Legal": QPageSize(QPageSize.PageSizeId.Legal),
}


# 位置（兼容别名，print_pdf 引用）
ALIGN_CENTER = POS_CENTER
ALIGN_TOP_CENTER = POS_TOP_CENTER
ALIGN_BOTTOM_CENTER = POS_BOTTOM_CENTER


def _nup_grid(nup):
    """N-up 网格：1→1x1, 2→2x1, 4→2x2。"""
    if nup == 4:
        return 2, 2
    if nup == 2:
        return 2, 1
    return 1, 1


def print_target_size(page_rect, cell, resolution, scale_mode,
                      custom_scale=1.0, rotation=0):
    """预览和打印共用的尺寸计算：PDF 点数转换为输出设备坐标。"""
    width, height = page_rect.width, page_rect.height
    if rotation % 180:
        width, height = height, width
    if scale_mode == SCALE_ACTUAL:
        scale = resolution / 72.0
    elif scale_mode == SCALE_CUSTOM:
        scale = resolution / 72.0 * custom_scale
    else:
        scale = min(cell.width() / width, cell.height() / height)
    return width * scale, height * scale


class PrintDialog(QDialog):
    """打印设置：打印机/范围/份数/缩放/位置/方向/纸张/每张页数 + 右侧预览。"""

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self._preview_ready = False
        self._preview_images = OrderedDict()
        self._preview_layouts = {}
        self._configured_printers = {}
        self._supported_papers = {}
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(80)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self.setWindowTitle(i18n.tr("print_dialog_title"))
        self._doc = doc
        self._total = len(doc) if doc is not None else 0
        self._printer = None
        self._preview_page = 1
        view = getattr(parent, 'page_view', None)
        self._current_page = max(0, view.current_page()) if view is not None else 0
        self._printers = [p for p in QPrinterInfo.availablePrinters()
                          if not p.isNull()]

        # 右侧预览标签（先建，后续信号可能立即触发刷新）
        self._preview_label = QLabel()
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumSize(330, 430)
        self._preview_label.setWordWrap(True)
        self._preview_label.setTextFormat(Qt.TextFormat.PlainText)
        self._preview_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                          QSizePolicy.Policy.Expanding)
        self._preview_label.setStyleSheet(
            "background:#e9eaee; color:#30343b; font-size:11pt; "
            "border:1px solid #c5c6cb; border-radius:4px;")

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(14)

        # ============ 左侧设置（紧凑 GridLayout，分组） ============
        left = QVBoxLayout()
        left.setSpacing(8)
        left.setContentsMargins(0, 0, 0, 0)

        settings_box = QGroupBox(i18n.tr("print_settings"))
        grid = QGridLayout(settings_box)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setContentsMargins(10, 8, 10, 10)
        grid.setColumnStretch(1, 1)
        # 不强制列宽：label 紧贴控件，宽度由内容自适应（防遮挡）

        # 行 0: 打印机
        grid.addWidget(QLabel(i18n.tr("print_printer")), 0, 0)
        self._printer_combo = QComboBox()
        self._printer_combo.setMinimumWidth(150)
        for p in self._printers:
            self._printer_combo.addItem(p.printerName(), p.printerName())
        if self._printers:
            self._printer_combo.setCurrentIndex(0)
        self._printer_combo.currentIndexChanged.connect(
            self._schedule_preview)
        grid.addWidget(self._printer_combo, 0, 1, 1, 2)

        # 行 1: 范围（radio + 起止页 同一行）
        grid.addWidget(QLabel(i18n.tr("print_range")), 1, 0)
        self._range_group = QButtonGroup(self)
        self._rb_all = QRadioButton(i18n.tr("print_all")); self._rb_all.setChecked(True)
        self._rb_current = QRadioButton(i18n.tr("print_current"))
        self._rb_pages = QRadioButton(i18n.tr("print_pages"))
        self._from_spin = QSpinBox(); self._from_spin.setRange(1, max(1, self._total)); self._from_spin.setValue(1)
        self._to_spin = QSpinBox(); self._to_spin.setRange(1, max(1, self._total)); self._to_spin.setValue(self._total or 1)
        rg = QHBoxLayout(); rg.setSpacing(8); rg.setContentsMargins(0,0,0,0)
        for rb in (self._rb_all, self._rb_current, self._rb_pages):
            self._range_group.addButton(rb)
            rg.addWidget(rb)
        rg.addSpacing(4)
        rg.addWidget(self._from_spin)
        rg.addWidget(QLabel("-"))
        rg.addWidget(self._to_spin)
        rg.addStretch(1)
        rgw = QWidget(); rgw.setLayout(rg)
        grid.addWidget(rgw, 1, 1, 1, 2)
        for rb in (self._rb_all, self._rb_current, self._rb_pages):
            rb.toggled.connect(self._on_pages_toggled)
        self._on_pages_toggled(self._rb_pages.isChecked())

        # 行 2: 份数
        grid.addWidget(QLabel(i18n.tr("print_copies")), 2, 0)
        self._copy_spin = QSpinBox()
        self._copy_spin.setRange(1, 99); self._copy_spin.setValue(1)
        grid.addWidget(self._copy_spin, 2, 1)

        # 行 3: 颜色
        grid.addWidget(QLabel(i18n.tr("print_color_mode")), 3, 0)
        self._color_group = QButtonGroup(self)
        self._rb_color = QRadioButton(i18n.tr("print_color_color")); self._rb_color.setChecked(True)
        self._rb_gray = QRadioButton(i18n.tr("print_color_gray"))
        for rb in (self._rb_color, self._rb_gray):
            self._color_group.addButton(rb)
            rb.toggled.connect(self._schedule_preview)
        cg = QHBoxLayout(); cg.setSpacing(12); cg.setContentsMargins(0,0,0,0)
        cg.addWidget(self._rb_color); cg.addWidget(self._rb_gray); cg.addStretch(1)
        cgw = QWidget(); cgw.setLayout(cg)
        grid.addWidget(cgw, 3, 1, 1, 2)

        # 行 4: 缩放（radio + 自定义 %）
        grid.addWidget(QLabel(i18n.tr("print_scale_mode")), 4, 0)
        self._scale_group = QButtonGroup(self)
        self._rb_fit = QRadioButton(i18n.tr("scale_fit")); self._rb_fit.setChecked(True)
        self._rb_actual = QRadioButton(i18n.tr("scale_actual"))
        self._rb_custom = QRadioButton(i18n.tr("scale_custom"))
        for rb in (self._rb_fit, self._rb_actual, self._rb_custom):
            self._scale_group.addButton(rb)
        self._scale_spin = QSpinBox()
        self._scale_spin.setRange(10, 400); self._scale_spin.setSuffix(" %"); self._scale_spin.setValue(100)
        self._scale_spin.setEnabled(False)
        srg = QHBoxLayout(); srg.setSpacing(8); srg.setContentsMargins(0,0,0,0)
        srg.addWidget(self._rb_fit); srg.addWidget(self._rb_actual)
        srg.addWidget(self._rb_custom); srg.addSpacing(4); srg.addWidget(self._scale_spin)
        srg.addStretch(1)
        srgw = QWidget(); srgw.setLayout(srg)
        grid.addWidget(srgw, 4, 1, 1, 2)
        for rb in (self._rb_fit, self._rb_actual, self._rb_custom):
            rb.toggled.connect(self._on_scale_toggled)

        # 行 5: 位置
        grid.addWidget(QLabel(i18n.tr("print_position")), 5, 0)
        self._pos_group = QButtonGroup(self)
        self._rb_pos_center = QRadioButton(i18n.tr("position_center")); self._rb_pos_center.setChecked(True)
        self._rb_pos_top = QRadioButton(i18n.tr("position_top_center"))
        self._rb_pos_bottom = QRadioButton(i18n.tr("position_bottom_center"))
        for rb in (self._rb_pos_center, self._rb_pos_top, self._rb_pos_bottom):
            self._pos_group.addButton(rb)
            rb.toggled.connect(self._schedule_preview)
        pg = QHBoxLayout(); pg.setSpacing(10); pg.setContentsMargins(0,0,0,0)
        for rb in (self._rb_pos_center, self._rb_pos_top, self._rb_pos_bottom):
            pg.addWidget(rb)
        pg.addStretch(1)
        pgw = QWidget(); pgw.setLayout(pg)
        grid.addWidget(pgw, 5, 1, 1, 2)

        # 行 6: 旋转
        grid.addWidget(QLabel(i18n.tr("print_rotate")), 6, 0)
        self._rot_group = QButtonGroup(self)
        self._rot_btns = {}
        for deg, label in ((0, "0°"), (90, "90°"), (180, "180°"), (270, "270°")):
            rb = QRadioButton(label)
            self._rot_btns[deg] = rb
            self._rot_group.addButton(rb)
            rb.toggled.connect(self._schedule_preview)
        self._rot_btns[0].setChecked(True)
        rog = QHBoxLayout(); rog.setSpacing(10); rog.setContentsMargins(0,0,0,0)
        for deg in (0, 90, 180, 270):
            rog.addWidget(self._rot_btns[deg])
        rog.addStretch(1)
        rogw = QWidget(); rogw.setLayout(rog)
        grid.addWidget(rogw, 6, 1, 1, 2)

        # 行 7: 方向
        grid.addWidget(QLabel(i18n.tr("print_orientation")), 7, 0)
        self._orient_group = QButtonGroup(self)
        self._rb_portrait = QRadioButton(i18n.tr("print_orient_portrait"))
        self._rb_landscape = QRadioButton(i18n.tr("print_orient_landscape"))
        self._rb_auto = QRadioButton(i18n.tr("print_orient_auto"))
        self._rb_auto.setChecked(True)
        for rb in (self._rb_portrait, self._rb_landscape, self._rb_auto):
            self._orient_group.addButton(rb)
            rb.toggled.connect(self._schedule_preview)
        oo = QHBoxLayout(); oo.setSpacing(10); oo.setContentsMargins(0,0,0,0)
        for rb in (self._rb_portrait, self._rb_landscape, self._rb_auto):
            oo.addWidget(rb)
        oo.addStretch(1)
        oow = QWidget(); oow.setLayout(oo)
        grid.addWidget(oow, 7, 1, 1, 2)

        # 行 8: 纸张
        grid.addWidget(QLabel(i18n.tr("print_paper_label")), 8, 0)
        self._paper_combo = QComboBox()
        for name in PAPERS.keys():
            label = {'B5': 'B5 (JIS · 182 × 257 mm)',
                     'B5 (ISO)': 'B5 (ISO · 176 × 250 mm)'}.get(name, name)
            self._paper_combo.addItem(label, name)
        self._paper_combo.setCurrentText("A4")
        self._paper_combo.currentTextChanged.connect(self._schedule_preview)
        grid.addWidget(self._paper_combo, 8, 1, 1, 2)

        # 行 9: 每张纸页数（三个 radio 放同一行，避免网格重叠）
        grid.addWidget(QLabel(i18n.tr("print_pages_per_sheet")), 9, 0)
        self._pps_group = QButtonGroup(self)
        self._rb_pps1 = QRadioButton(i18n.tr("print_pps_1"))
        self._rb_pps2 = QRadioButton(i18n.tr("print_pps_2"))
        self._rb_pps4 = QRadioButton(i18n.tr("print_pps_4"))
        self._rb_pps1.setChecked(True)
        ppsg = QHBoxLayout(); ppsg.setSpacing(12); ppsg.setContentsMargins(0,0,0,0)
        for rb in (self._rb_pps1, self._rb_pps2, self._rb_pps4):
            self._pps_group.addButton(rb)
            ppsg.addWidget(rb)
            rb.toggled.connect(self._schedule_preview)
        ppsg.addStretch(1)
        ppsgw = QWidget(); ppsgw.setLayout(ppsg)
        grid.addWidget(ppsgw, 9, 1, 1, 2)

        left.addWidget(settings_box)

        # 按钮行
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText(i18n.tr("print"))
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.tr("cancel"))
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        left.addWidget(btns)

        root.addLayout(left, 1)

        # ============ 右侧预览 ============
        right = QVBoxLayout()
        right.setSpacing(5)
        # 标题 + 位置/缩放指示
        title_row = QHBoxLayout()
        self._preview_title = QLabel(i18n.tr("print_preview_title"))
        self._preview_title.setStyleSheet("font-weight:700; font-size:11pt;")
        self._pos_badge = QLabel("")
        self._pos_badge.setStyleSheet(
            "background:#0a84ff; color:#ffffff; border-radius:3px;"
            "padding:2px 8px; font-weight:600;")
        title_row.addWidget(self._preview_title)
        title_row.addStretch(1)
        title_row.addWidget(self._pos_badge)
        right.addLayout(title_row)
        self._scale_badge = QLabel("")
        self._scale_badge.setStyleSheet(
            "color:#555555; padding:0 2px;")
        right.addWidget(self._scale_badge)
        # 预览图（已在 __init__ 开头创建）
        right.addWidget(self._preview_label, 1)
        # 翻页
        nav_row = QHBoxLayout()
        prev_btn = QPushButton("<")
        next_btn = QPushButton(">")
        prev_btn.clicked.connect(lambda: self._navigate(-1))
        next_btn.clicked.connect(lambda: self._navigate(1))
        self._page_label = QLabel("")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_row.addStretch(1)
        nav_row.addWidget(self._page_label)
        nav_row.addWidget(prev_btn)
        nav_row.addWidget(next_btn)
        right.addLayout(nav_row)
        # 纸张信息
        self._paper_info_label = QLabel("")
        self._paper_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._paper_info_label.setStyleSheet(
            "color:#888888; font-size:9pt;")
        right.addWidget(self._paper_info_label)
        root.addLayout(right, 1)

        self.setMinimumWidth(880)
        self.resize(780, 580)

        # 其余控件已在创建时连接；这里只补齐页码和百分比输入。
        for w in (self._from_spin, self._to_spin, self._scale_spin):
            w.valueChanged.connect(self._schedule_preview)
        for rb in (self._rb_all, self._rb_current, self._rb_pages):
            rb.toggled.connect(self._schedule_preview)
        self._preview_ready = True
        self._schedule_preview()

    # ---------- 交互 ----------
    def _on_pages_toggled(self, checked):
        self._from_spin.setEnabled(checked)
        self._to_spin.setEnabled(checked)

    def _on_scale_toggled(self, checked):
        self._scale_spin.setEnabled(self._rb_custom.isChecked())
        self._schedule_preview()

    def _navigate(self, delta):
        if self._total == 0:
            return
        # N-up 时按"一张纸"翻页（_preview_page = 纸张序号）
        sheets = self._total_sheets()
        self._preview_page = max(1, min(sheets, self._preview_page + delta))
        self._schedule_preview()

    def _total_sheets(self):
        n = max(1, self.pages_per_sheet())
        return max(1, -(-len(self.selected_pages()) // n))

    def selected_pages(self):
        if not self._total:
            return []
        if self.print_current_only():
            return [min(self._current_page, self._total - 1)]
        limits = self.custom_range()
        if limits:
            first, last = limits
            return list(range(max(0, first - 1), min(self._total, last)))
        return list(range(self._total))

    # ---------- 取值 ----------
    def print_current_only(self):
        return self._rb_current.isChecked()

    def custom_range(self):
        if self._rb_pages.isChecked():
            return (self._from_spin.value(), self._to_spin.value())
        return None

    def copies(self):
        return self._copy_spin.value()

    def scale_mode(self):
        if self._rb_actual.isChecked():
            return SCALE_ACTUAL
        if self._rb_custom.isChecked():
            return SCALE_CUSTOM
        return SCALE_FIT

    def scale_percent(self):
        return self._scale_spin.value() / 100.0

    def position(self):
        if self._rb_pos_top.isChecked():
            return POS_TOP_CENTER
        if self._rb_pos_bottom.isChecked():
            return POS_BOTTOM_CENTER
        return POS_CENTER

    def alignment(self):
        return self.position()

    def reverse_order(self):
        return False

    def grayscale(self):
        return self._rb_gray.isChecked()

    def pages_per_sheet(self):
        if self._rb_pps2.isChecked():
            return 2
        if self._rb_pps4.isChecked():
            return 4
        return 1

    def rotation(self):
        for deg, rb in self._rot_btns.items():
            if rb.isChecked():
                return deg
        return 0

    def paper_name(self):
        return self._paper_combo.currentData() or "A4"

    def _first_page_landscape(self):
        # 整个任务统一使用所选首个页面的方向，浏览预览不会改变输出方向。
        if self._doc is not None and self._total > 0:
            try:
                pno = (self.selected_pages() or [0])[0]
                p = self._doc[pno]
                landscape = p.rect.width > p.rect.height
                return not landscape if self.rotation() % 180 else landscape
            except Exception:
                pass
        return False

    def paper_landscape(self):
        if self._rb_portrait.isChecked():
            return False
        if self._rb_landscape.isChecked():
            return True
        return self._first_page_landscape()

    def paper_size(self):
        size = PAPERS[self.paper_name()].size(QPageSize.Unit.Point)
        if self.paper_landscape():
            return QSizeF(size.height(), size.width())
        return QSizeF(size.width(), size.height())

    # ---------- 预览 ----------
    def _schedule_preview(self, *_):
        if self._preview_ready:
            self._preview_timer.start()

    def _preview_image(self, page, rotation, gray):
        import pymupdf
        from PySide6.QtGui import QTransform
        key = (page.number, rotation, gray)
        if key in self._preview_images:
            self._preview_images.move_to_end(key)
            return self._preview_images[key]
        # 仅预览限制像素大小，实际打印仍走独立的 600 DPI 渲染路径。
        zoom = min(1.4, 1400 / max(page.rect.width, page.rect.height))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom),
                              colorspace=pymupdf.csRGB, alpha=False)
        image = QImage(pix.samples, pix.width, pix.height, pix.stride,
                       QImage.Format.Format_RGB888).copy()
        if rotation:
            image = image.transformed(QTransform().rotate(rotation))
        if gray:
            image = image.convertToFormat(QImage.Format.Format_Grayscale8)
        self._preview_images[key] = image
        while len(self._preview_images) > 8:
            self._preview_images.popitem(last=False)
        return image

    def _refresh_preview(self, *_):
        self._preview_timer.stop()
        if not self._preview_ready:
            return
        if self._doc is None or self._total == 0:
            self._preview_label.clear()
            return
        try:
            import pymupdf
            # 每张页数网格
            n = self.pages_per_sheet()
            # 预览页 = 纸张序号：本张纸第一页 = (序号-1)*n
            self._preview_page = min(self._preview_page, self._total_sheets())
            pages = self.selected_pages()
            start = (self._preview_page - 1) * n
            if n == 4:
                cols, rows = 2, 2
            elif n == 2:
                cols, rows = 2, 1
            else:
                cols, rows = 1, 1
            # 纸张画布：四周统一充足留白 + 均匀环绕阴影 + 白纸 + 细边框
            paper_pts = self.paper_size()
            paper_w = int(paper_pts.width() * 1.6)
            paper_h = int(paper_pts.height() * 1.6)
            margin = 26
            canvas_w = paper_w + margin * 2
            canvas_h = paper_h + margin * 2
            paper_pix = QPixmap(canvas_w, canvas_h)
            paper_pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(paper_pix)
            # 四周均匀阴影（环绕纸张，无方向偏移）
            p.fillRect(margin - 3, margin - 3, paper_w + 6, paper_h + 6,
                       QColor(0, 0, 0, 30))
            # 纸张本体（白底 + 细边框）
            p.fillRect(margin, margin, paper_w, paper_h, Qt.GlobalColor.white)
            p.setPen(QPen(QColor("#8a8a90"), 1.5))
            p.drawRect(margin, margin, paper_w, paper_h)
            mode = self.scale_mode()
            pct = self.scale_percent()
            rot = self.rotation()
            want_gray = self.grayscale()

            # 预览与打印采用同一个驱动配置，按真实可打印区域排版。
            layout_key = (self._printer_combo.currentData(), self.paper_name(),
                          self.paper_landscape())
            if layout_key not in self._preview_layouts:
                preview_printer = self._configured_printer()
                self._preview_layouts[layout_key] = QRectF(
                    preview_printer.pageLayout().paintRect(QPageLayout.Unit.Point))
            printable = self._preview_layouts[layout_key]
            preview_scale = 1.6
            cell_w = printable.width() * preview_scale / cols
            cell_h = printable.height() * preview_scale / rows
            for cell_idx in range(n):
                if start + cell_idx >= len(pages):
                    break
                pg_no = pages[start + cell_idx]
                page = self._doc[pg_no]
                img = self._preview_image(page, rot, want_gray)
                col, row = cell_idx % cols, cell_idx // cols
                cell = QRectF(margin + printable.x() * preview_scale + col * cell_w,
                              margin + printable.y() * preview_scale + row * cell_h,
                              cell_w, cell_h)
                dw, dh = print_target_size(page.rect, cell, 72 * preview_scale,
                                           mode, pct, rot)
                x = cell.x() + (cell.width() - dw) / 2
                pos = self.position()
                if pos == POS_TOP_CENTER:
                    y = cell.y()
                elif pos == POS_BOTTOM_CENTER:
                    y = cell.bottom() - dh
                else:
                    y = cell.y() + (cell.height() - dh) / 2
                p.save()
                p.setClipRect(cell)
                p.drawImage(QRectF(x, y, dw, dh), img)
                p.restore()
            p.end()
            dpr = self._preview_label.devicePixelRatioF()
            preview = paper_pix.scaled(
                QSize(round(340 * dpr), round(460 * dpr)),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            if n > 1:
                # 在最终设备像素上绘制提示线，避免整图缩小把横竖线采样
                # 成不同粗细；最后叠加也避免被各页的白底遮住。
                sx, sy = preview.width() / canvas_w, preview.height() / canvas_h
                left = (margin + printable.x() * preview_scale) * sx
                top = (margin + printable.y() * preview_scale) * sy
                width = printable.width() * preview_scale * sx
                height = printable.height() * preview_scale * sy
                guide = QPainter(preview)
                pen = QPen(QColor("#3b8cff"), max(1, round(dpr)),
                           Qt.PenStyle.DashLine)
                pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                guide.setPen(pen)
                guide.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                for col in range(1, cols):
                    x = round(left + col * width / cols)
                    guide.drawLine(x, round(top), x, round(top + height))
                for row in range(1, rows):
                    y = round(top + row * height / rows)
                    guide.drawLine(round(left), y, round(left + width), y)
                guide.end()
            preview.setDevicePixelRatio(dpr)
            self._preview_label.setMargin(0)
            self._preview_label.setPixmap(preview)
            # 引导信息
            pos = self.position()
            if pos == POS_TOP_CENTER:
                pos_name = i18n.tr("position_top_center")
            elif pos == POS_BOTTOM_CENTER:
                pos_name = i18n.tr("position_bottom_center")
            else:
                pos_name = i18n.tr("position_center")
            self._pos_badge.setText(
                f"{i18n.tr('print_pos_label')} {pos_name}")
            mode = self.scale_mode()
            if mode == SCALE_ACTUAL:
                scale_name = i18n.tr("scale_actual")
            elif mode == SCALE_CUSTOM:
                scale_name = (f"{i18n.tr('scale_custom')} "
                              f"{self._scale_spin.value()}%")
            else:
                scale_name = i18n.tr("scale_fit")
            nup = self.pages_per_sheet()
            if nup > 1:
                scale_name += f"  ·  {nup} {i18n.tr('print_pps_suffix')}"
            # 方向徽标（纵向/横向）
            if self.paper_landscape():
                orient_name = i18n.tr("orientation_landscape")
            else:
                orient_name = i18n.tr("orientation_portrait")
            scale_name += f"  ·  {i18n.tr('print_orient_label')} {orient_name}"
            self._scale_badge.setText(
                f"{i18n.tr('print_scale_label')} {scale_name}")
            self._page_label.setText(
                f"{i18n.tr('print_preview_page_label')} "
                f"{self._preview_page} / {self._total_sheets()}")
            self._paper_info_label.setText(
                f"{i18n.tr('print_paper_label')} {self.paper_name()}  ·  "
                f"{paper_pts.width()/72*2.54:.1f} × {paper_pts.height()/72*2.54:.1f} cm")
        except Exception as _e:
            if 'p' in locals() and p.isActive():
                p.end()
            import sys as _sys
            print(f"[print-preview] {type(_e).__name__}: {_e}", file=_sys.stderr)
            self._preview_label.clear()
            self._preview_label.setMargin(20)
            self._preview_label.setText(str(_e))

    # ---------- 结果 ----------
    def result_printer(self):
        """返回完整配置的 QPrinter（取消返回 None）。

        应用自定义对话框的全部设置（打印机/纸张/方向/份数），
        打印时直接输出，无需再次调出系统打印对话框。
        """
        if int(self._result_code) != int(QDialog.DialogCode.Accepted):
            return None
        if not self.selected_pages():
            QMessageBox.warning(self, i18n.tr('hint'), i18n.tr('print_invalid_range'))
            return None
        try:
            self._printer = self._configured_printer()
        except ValueError as exc:
            QMessageBox.warning(self, i18n.tr('hint'), str(exc))
            return None
        return self._printer

    def _configured_printer(self):
        """预览和输出均通过此处配置纸张、方向、驱动和可打印边距。"""
        name = self._printer_combo.currentData()
        printer = self._configured_printers.get(name)
        if printer is None:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            if name:
                printer.setPrinterName(name)
            # 份数由 print_pdf 逐份排版，驱动不能再次复制。
            printer.setCopyCount(1)
            info = QPrinterInfo(printer)
            self._supported_papers[name] = info.supportedPageSizes()
            supported = info.supportedResolutions()
            candidates = [dpi for dpi in supported if dpi > 0]
            if candidates:
                preferred = [dpi for dpi in candidates if dpi >= 600]
                printer.setResolution(min(preferred) if preferred else max(candidates))
            self._configured_printers[name] = printer
        requested = PAPERS[self.paper_name()]
        supported_papers = self._supported_papers.get(name, [])
        # Windows 驱动可能对不支持的纸张也返回设置成功，须先核对规格。
        if supported_papers and not any(size.isEquivalentTo(requested)
                                        for size in supported_papers):
            raise ValueError(i18n.tr('print_paper_unsupported').format(
                paper=self._paper_combo.currentText()))
        if not printer.setPageSize(requested):
            raise ValueError(i18n.tr('print_paper_rejected').format(paper=self.paper_name()))
        if not printer.pageLayout().pageSize().isEquivalentTo(requested):
            raise ValueError(i18n.tr('print_paper_mismatch'))
        if self.paper_landscape():
            printer.setPageOrientation(
                QPageLayout.Orientation.Landscape)
        else:
            printer.setPageOrientation(
                QPageLayout.Orientation.Portrait)
        printer.setFullPage(False)
        return printer

    def done(self, r):
        self._preview_timer.stop()
        self._result_code = r
        super().done(r)
