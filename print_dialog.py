"""打印对话框（简洁版）：打印机/范围/份数/缩放/位置/方向/纸张/每张页数 + 右侧预览。"""
from PySide6.QtCore import Qt, QSize, QSizeF, QRectF
from PySide6.QtGui import QImage, QPixmap, QPageLayout, QPageSize, QPainter, QPen, QColor
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QDialogButtonBox,
                               QGroupBox, QHBoxLayout, QLabel, QPushButton, QRadioButton,
                               QSpinBox, QVBoxLayout, QWidget,
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
    "B5": QPageSize(QPageSize.PageSizeId.B5),
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


class PrintDialog(QDialog):
    """打印设置：打印机/范围/份数/缩放/位置/方向/纸张/每张页数 + 右侧预览。"""

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("print_dialog_title"))
        self._doc = doc
        self._total = len(doc) if doc is not None else 0
        self._printer = None
        self._preview_page = 1
        self._printers = [p for p in QPrinterInfo.availablePrinters()
                          if not p.isNull()]

        # 右侧预览标签（先建，后续信号可能立即触发刷新）
        self._preview_label = QLabel()
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumSize(330, 430)
        self._preview_label.setStyleSheet(
            "background:#e9eaee; border:1px solid #c5c6cb; border-radius:4px;")

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
            self._refresh_preview)
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
            rb.toggled.connect(self._refresh_preview)
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
            rb.toggled.connect(self._refresh_preview)
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
            rb.toggled.connect(self._refresh_preview)
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
            rb.toggled.connect(self._refresh_preview)
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
            self._paper_combo.addItem(name, name)
        self._paper_combo.setCurrentText("A4")
        for rb in (self._rb_portrait, self._rb_landscape, self._rb_auto):
            rb.toggled.connect(self._refresh_preview)
        self._paper_combo.currentTextChanged.connect(self._refresh_preview)
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
            rb.toggled.connect(self._refresh_preview)
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

        # 刷新预览：所有设置变化
        for w in (self._printer_combo, self._paper_combo,
                  self._from_spin, self._to_spin, self._copy_spin,
                  self._scale_spin):
            if isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._refresh_preview)
            else:
                w.valueChanged.connect(self._refresh_preview)
        for rb in (self._rb_all, self._rb_current, self._rb_pages,
                   self._rb_fit, self._rb_actual, self._rb_custom,
                   self._rb_pos_center, self._rb_pos_top, self._rb_pos_bottom,
                   self._rb_portrait, self._rb_landscape, self._rb_auto,
                   self._rb_pps1, self._rb_pps2, self._rb_pps4):
            rb.toggled.connect(self._refresh_preview)
        self._refresh_preview()

    # ---------- 交互 ----------
    def _on_pages_toggled(self, checked):
        self._from_spin.setEnabled(checked)
        self._to_spin.setEnabled(checked)

    def _on_scale_toggled(self, checked):
        self._scale_spin.setEnabled(self._rb_custom.isChecked())
        self._refresh_preview()

    def _navigate(self, delta):
        if self._total == 0:
            return
        # N-up 时按"一张纸"翻页（_preview_page = 纸张序号）
        sheets = max(1, -(-self._total // max(1, self.pages_per_sheet())))
        self._preview_page = max(1, min(sheets, self._preview_page + delta))
        self._refresh_preview()

    def _total_sheets(self):
        n = max(1, self.pages_per_sheet())
        return max(1, -(-self._total // n))

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
        # 自动方向：跟随当前预览页（所见即所得）
        if self._doc is not None and self._total > 0:
            try:
                pno = min(max(self._preview_page, 1), self._total) - 1
                p = self._doc[pno]
                return p.rect.width > p.rect.height
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
    def _refresh_preview(self, *_):
        if self._doc is None or self._total == 0:
            self._preview_label.clear()
            return
        try:
            import pymupdf
            # 每张页数网格
            n = self.pages_per_sheet()
            # 预览页 = 纸张序号：本张纸第一页 = (序号-1)*n
            pno = min((self._preview_page - 1) * n, self._total - 1)
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
            if n > 1:
                # N-up 网格引导线：蓝色虚线，清晰标识每张纸的页格
                p.setPen(QPen(QColor("#3b8cff"), 1.5, Qt.PenStyle.DashLine))
                for c in range(1, cols):
                    x0 = margin + int(c * paper_w / cols)
                    p.drawLine(x0, margin, x0, margin + paper_h)
                for r in range(1, rows):
                    y0 = margin + int(r * paper_h / rows)
                    p.drawLine(margin, y0, margin + paper_w, y0)
            mode = self.scale_mode()
            pct = self.scale_percent()
            rot = self.rotation()
            want_gray = self.grayscale()

            def _render_page_img(pg):
                zoom = 1.4
                pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom),
                                    alpha=False)
                im = QImage(pix.samples, pix.width, pix.height, pix.stride,
                            QImage.Format.Format_RGB888).copy()
                if rot:
                    from PySide6.QtGui import QTransform
                    im = im.transformed(QTransform().rotate(rot))
                if want_gray:
                    im = im.convertToFormat(QImage.Format.Format_Grayscale8)
                    im = im.convertToFormat(QImage.Format.Format_RGB32)
                return im

            if n > 1:
                # 多页：从当前预览页起依次渲染 n 页填满各格
                cell_w = paper_w / cols
                cell_h = paper_h / rows
                for cell_idx in range(n):
                    pg_no = pno + cell_idx
                    if pg_no >= self._total:
                        break   # 文档没有更多页：剩余格子留空（不重复）
                    img_c = _render_page_img(self._doc[pg_no])
                    iw, ih = img_c.width(), img_c.height()
                    actual_w = iw / 1.4 * 1.6
                    actual_h = ih / 1.4 * 1.6
                    if mode == SCALE_ACTUAL:
                        dw, dh = actual_w, actual_h
                    elif mode == SCALE_CUSTOM:
                        dw, dh = actual_w * pct, actual_h * pct
                    else:
                        s = min(cell_w * 0.9 / iw, cell_h * 0.9 / ih)
                        dw, dh = iw * s, ih * s
                    pos = self.position()
                    if pos == POS_TOP_CENTER:
                        x, y = (cell_w - dw) / 2, 6
                    elif pos == POS_BOTTOM_CENTER:
                        x, y = (cell_w - dw) / 2, cell_h - dh - 6
                    else:
                        x, y = (cell_w - dw) / 2, (cell_h - dh) / 2
                    col = cell_idx % cols
                    row = cell_idx // cols
                    p.drawImage(QRectF(margin + col * cell_w + x,
                                       margin + row * cell_h + y,
                                       dw, dh), img_c)
            else:
                # 单页模式
                img = _render_page_img(self._doc[pno])
                iw, ih = img.width(), img.height()
                actual_w = iw / 1.4 * 1.6
                actual_h = ih / 1.4 * 1.6
                if mode == SCALE_ACTUAL:
                    dw, dh = actual_w, actual_h
                elif mode == SCALE_CUSTOM:
                    dw, dh = actual_w * pct, actual_h * pct
                else:
                    s = min(paper_w * 0.9 / iw, paper_h * 0.9 / ih)
                    dw, dh = iw * s, ih * s
                pos = self.position()
                if pos == POS_TOP_CENTER:
                    x, y = (paper_w - dw) / 2, 10
                elif pos == POS_BOTTOM_CENTER:
                    x, y = (paper_w - dw) / 2, paper_h - dh - 10
                else:
                    x, y = (paper_w - dw) / 2, (paper_h - dh) / 2
                p.drawImage(QRectF(margin + x, margin + y, dw, dh), img)
            p.end()
            self._preview_label.setPixmap(paper_pix.scaled(
                QSize(340, 460), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
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
                              f"{int(self.scale_percent()*100)}%")
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
            import sys as _sys
            print(f"[print-preview] {type(_e).__name__}: {_e}", file=_sys.stderr)
            self._preview_label.clear()

    # ---------- 结果 ----------
    def result_printer(self):
        """返回完整配置的 QPrinter（取消返回 None）。

        应用自定义对话框的全部设置（打印机/纸张/方向/份数），
        打印时直接输出，无需再次调出系统打印对话框。
        """
        if int(self._result_code) != int(QDialog.DialogCode.Accepted):
            return None
        if self._printer is None:
            self._printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            name = self._printer_combo.currentData()
            if name:
                self._printer.setPrinterName(name)
            self._printer.setCopyCount(self.copies())
            self._printer.setPageSize(PAPERS[self.paper_name()])
            if self.paper_landscape():
                self._printer.setPageOrientation(
                    QPageLayout.Orientation.Landscape)
            else:
                self._printer.setPageOrientation(
                    QPageLayout.Orientation.Portrait)
        return self._printer

    def done(self, r):
        self._result_code = r
        super().done(r)