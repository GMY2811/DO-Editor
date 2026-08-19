"""手写签名画板、签名库（保存/调用）。"""
import os
import time
import i18n
from PySide6.QtCore import (Qt, QBuffer, QByteArray, QIODevice, QSize, QRectF,
                            QPointF)
from PySide6.QtGui import (QImage, QPainter, QPen, QColor, QPixmap, QIcon,
                           QFont, QPolygonF, QPalette)
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLabel, QFileDialog, QMessageBox,
                               QListWidget, QListWidgetItem, QInputDialog,
                               QSlider, QLineEdit, QSpinBox, QFontComboBox,
                               QCheckBox)


def qimage_to_png_bytes(image):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return bytes(ba)


def signatures_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "DO编辑器", "signatures")
    os.makedirs(d, exist_ok=True)
    return d


def list_signatures():
    """返回 [(名称, 完整路径)]"""
    d = signatures_dir()
    out = []
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if fn.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
            out.append((os.path.splitext(fn)[0], os.path.join(d, fn)))
    return out


def save_signature(png_bytes, name):
    path = os.path.join(signatures_dir(), name + ".png")
    with open(path, "wb") as f:
        f.write(png_bytes)
    return path


def delete_signature(path):
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def text_to_signature_image(text, font_size=30, color="#000000", bold=False,
                            italic=False, family=None):
    """把文字渲染成透明背景的签名图片（用于文字签名）。

    自动选择系统必有的字体（中文用黑体、英文用 Arial），避免乱码。
    """
    from PySide6.QtGui import QFont, QFontMetricsF, QFontDatabase
    db = QFontDatabase()
    if not family:
        has_cjk = any('\u4e00' <= c <= '\u9fff' for c in text)
        candidates = (["Microsoft YaHei UI", "Microsoft YaHei", "SimHei"]
                      if has_cjk else ["Segoe UI", "Arial"])
        family = next((name for name in candidates if name in db.families()),
                      db.systemFont(QFontDatabase.SystemFont.GeneralFont).family())
    if family not in db.families():
        family = db.systemFont(QFontDatabase.SystemFont.GeneralFont).family()
    f = QFont(family)
    # 界面显示“号”时按排版字号处理。此前用像素生成 12px 小图后再
    # 强制放大预览，会造成明显的模糊、膨胀和笔画粘连。
    f.setPointSize(int(font_size))
    f.setBold(bold)
    f.setItalic(italic)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    f.setStyleStrategy(
        QFont.StyleStrategy.PreferAntialias |
        QFont.StyleStrategy.NoSubpixelAntialias)
    fm = QFontMetricsF(f)
    r = fm.boundingRect(text)
    pad = 18
    w = max(60, int(r.width() + pad * 2 + 0.5))
    h = max(40, int(r.height() + pad * 2 + 0.5))
    # 透明签名以 3 倍物理分辨率绘制，并标记设备像素比。界面按原逻辑
    # 尺寸显示，但笔画拥有足够采样点，插入 PDF 后也不会出现朦胧锯齿。
    render_scale = 3.0
    img = QImage(int(w * render_scale), int(h * render_scale),
                 QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(render_scale)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setFont(f)
    p.setPen(QColor(color))
    # 画布物理尺寸是逻辑尺寸的 3 倍；设置 DPR 后 QPainter 使用逻辑
    # 坐标，不能再传入 img.rect() 的物理范围，否则文字会被居中绘制到
    # 可见区域之外，结果看起来像一张完全透明的空图。
    p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return img


def remove_default_signatures():
    """删除旧版本自动建立的默认文字签名模板。"""
    for name in ("BOSL TRUCKING", "Manager", "BOLF",
                 "dispatch@bosltruckinginc.com", "日期"):
        for n, path in list_signatures():
            if n == name:
                delete_signature(path)


class SignatureFontComboBox(QFontComboBox):
    """始终绘制清晰下拉箭头的字体选择框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("signatureFontCombo")
        # 隐藏可能缺失或随平台变化的原生箭头，统一由 paintEvent 绘制。
        self.setStyleSheet(
            "QFontComboBox::drop-down {"
            " border: none; width: 30px; }"
            "QFontComboBox::down-arrow { image: none; }"
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = self.palette().color(QPalette.ColorRole.Base)
        color = QColor("#3f9bec" if base.lightness() < 128 else "#176fb6")
        if not self.isEnabled():
            color.setAlpha(110)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        cx = self.width() - 15.0
        cy = self.height() / 2.0 + 1.0
        painter.drawPolygon(QPolygonF([
            QPointF(cx - 5.0, cy - 3.0),
            QPointF(cx + 5.0, cy - 3.0),
            QPointF(cx, cy + 3.0),
        ]))


class DrawingCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._lines = []
        self._current = []
        self._pen_width = 3
        self._pen_color = QColor(20, 20, 20)
        self.setMinimumSize(460, 200)
        self.setMouseTracking(True)

    def set_pen_width(self, w):
        self._pen_width = max(1, int(w))
        self.update()

    def set_pen_color(self, color):
        self._pen_color = QColor(color)
        self.update()

    def clear(self):
        self._lines = []
        self._current = []
        self.update()

    def has_content(self):
        return bool(self._lines) or bool(self._current)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._current = [e.position()]

    def mouseMoveEvent(self, e):
        if self._current:
            self._current.append(e.position())
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._current:
            self._lines.append(self._current)
            self._current = []
            self.update()

    def _pen(self):
        return QPen(self._pen_color, self._pen_width, Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.GlobalColor.white)
        p.setPen(self._pen())
        for line in self._lines:
            for i in range(len(line) - 1):
                p.drawLine(line[i], line[i + 1])
        for i in range(len(self._current) - 1):
            p.drawLine(self._current[i], self._current[i + 1])
        p.end()

    def render_image(self):
        img = QImage(self.size(), QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setPen(self._pen())
        for line in self._lines:
            for i in range(len(line) - 1):
                p.drawLine(line[i], line[i + 1])
        p.end()
        return img


class SignatureDialog(QDialog):
    """手写/导入签名，可保存到签名库。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("sign_title"))
        self._image = None
        self._canvas = DrawingCanvas()

        self._preview = QLabel("（可手写、导入图片，或输入文字生成签名）")
        self._preview.setObjectName("signaturePreview")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setFixedHeight(76)
        # 签名最终通常落在白色 PDF 页面上，因此预览始终使用纸张白底；
        # 透明 PNG 的黑色笔迹在深色主题下也能正确显示。
        self._preview.setStyleSheet(
            "QLabel#signaturePreview {"
            " background-color: #ffffff; color: #667085;"
            " border: 1px solid #cfd5de; padding: 6px; }"
        )

        # 文字签名输入（含字号设置）
        self._text_edit = QLineEdit()
        self._text_edit.setPlaceholderText(i18n.tr("text_sign_placeholder"))
        self._text_size = QSpinBox()
        self._text_size.setRange(12, 120)
        self._text_size.setValue(12)
        self._text_size.setSuffix(" 号")
        self._text_size.setToolTip("文字签名字号")
        btn_text = QPushButton(i18n.tr("gen_text_sign"))
        btn_text.clicked.connect(self._make_text_signature)
        text_row = QHBoxLayout()
        text_row.addWidget(QLabel(i18n.tr("text_sign") + "："))
        text_row.addWidget(self._text_edit)
        text_row.addWidget(self._text_size)
        text_row.addWidget(btn_text)

        # 字体样式单独成行，避免压缩文字输入框，并让格式选项一目了然。
        format_row = QHBoxLayout()
        format_row.addWidget(QLabel(i18n.tr("font_family")))
        self._font_combo = SignatureFontComboBox()
        self._font_combo.setToolTip(i18n.tr("font_family").rstrip("：: "))
        self._font_combo.setCurrentFont(QFont("Microsoft YaHei UI"))
        format_row.addWidget(self._font_combo, 1)
        self._bold_check = QCheckBox(i18n.tr("bold"))
        self._italic_check = QCheckBox(i18n.tr("italic"))
        format_row.addWidget(self._bold_check)
        format_row.addWidget(self._italic_check)

        btn_import = QPushButton(i18n.tr("import_image"))
        btn_clear = QPushButton(i18n.tr("clear"))
        btn_save = QPushButton(i18n.tr("save_to_lib"))
        btn_cancel = QPushButton(i18n.tr("cancel"))
        btn_ok = QPushButton(i18n.tr("confirm"))

        btn_import.clicked.connect(self._import)
        btn_clear.clicked.connect(self._clear_signature)
        btn_save.clicked.connect(self._save_to_library)
        btn_cancel.clicked.connect(self.reject)
        btn_ok.clicked.connect(self._confirm)

        row = QHBoxLayout()
        row.addWidget(btn_import)
        row.addWidget(btn_clear)
        row.addWidget(btn_save)
        row.addStretch(1)
        row.addWidget(btn_cancel)
        row.addWidget(btn_ok)

        # 笔触粗细 + 颜色
        pen_row = QHBoxLayout()
        pen_row.addWidget(QLabel("笔触粗细："))
        self._width_slider = QSlider(Qt.Orientation.Horizontal)
        self._width_slider.setRange(1, 14)
        self._width_slider.setValue(3)
        self._width_slider.setFixedWidth(160)
        self._width_label = QLabel("3")
        self._width_slider.valueChanged.connect(self._on_width_changed)
        pen_row.addWidget(self._width_slider)
        pen_row.addWidget(self._width_label)
        pen_row.addSpacing(16)
        pen_row.addWidget(QLabel("颜色："))
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(28, 28)
        self._color_btn.setStyleSheet("background:#141414;border:1px solid #999;border-radius:4px;")
        self._color_btn.clicked.connect(self._pick_color)
        pen_row.addWidget(self._color_btn)
        pen_row.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)
        lay.addLayout(text_row)
        lay.addLayout(format_row)
        lay.addWidget(self._canvas)
        lay.addLayout(pen_row)
        lay.addWidget(self._preview)
        lay.addLayout(row)
        self.setMinimumWidth(560)

    def _on_width_changed(self, v):
        self._canvas.set_pen_width(v)
        self._width_label.setText(str(v))

    def _pick_color(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(self._canvas._pen_color, self, "选择签名颜色")
        if c.isValid():
            self._canvas.set_pen_color(c)
            self._color_btn.setStyleSheet(
                f"background:{c.name()};border:1px solid #999;border-radius:4px;")

    def _make_text_signature(self):
        text = self._text_edit.text().strip()
        if not text:
            QMessageBox.information(self, "提示", "请先输入文字")
            return
        img = text_to_signature_image(
            text, font_size=self._text_size.value(),
            color=self._canvas._pen_color.name(),
            family=self._font_combo.currentFont().family(),
            bold=self._bold_check.isChecked(),
            italic=self._italic_check.isChecked())
        self._image = img
        self._canvas.clear()
        self._show_preview(img)

    def _show_preview(self, img):
        """清晰显示签名：小图保持原始尺寸，只对过大的图片做缩小。"""
        pm = QPixmap.fromImage(img)
        available = QSize(max(80, self._preview.width() - 16),
                          max(32, self._preview.height() - 16))
        logical_size = pm.deviceIndependentSize()
        if (logical_size.width() > available.width() or
                logical_size.height() > available.height()):
            dpr = pm.devicePixelRatio()
            pm = pm.scaled(
                QSize(int(available.width() * dpr),
                      int(available.height() * dpr)),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
        self._preview.setPixmap(pm)

    def _clear_signature(self):
        self._image = None
        self._canvas.clear()
        self._preview.setPixmap(QPixmap())
        self._preview.setText("（可手写、导入图片，或输入文字生成签名）")

    def _current_image(self):
        if self._image is not None:
            return self._image
        if self._canvas.has_content():
            return self._canvas.render_image()
        return None

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择签名图片", "", "图片 (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "提示", "无法读取该图片")
            return
        self._image = img
        self._show_preview(img)

    def _save_to_library(self):
        img = self._current_image()
        if img is None:
            QMessageBox.information(self, "提示", "请先手写签名或导入图片")
            return
        name, ok = QInputDialog.getText(self, "保存签名", "签名名称：")
        if not ok or not name.strip():
            return
        save_signature(qimage_to_png_bytes(img), name.strip())
        self.status_hint = f"已保存签名「{name.strip()}」"
        QMessageBox.information(self, "完成", f"签名「{name.strip()}」已保存到签名库")

    def _confirm(self):
        img = self._current_image()
        if img is None:
            QMessageBox.information(self, "提示", "请先手写签名或导入图片")
            return
        self._image = img
        self.accept()

    def result_image(self):
        return self._image


class SignatureLibraryDialog(QDialog):
    """从签名库选择签名。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("签名库")
        self._image = None
        self._list = QListWidget()
        self._list.setObjectName("signatureLibraryList")
        # 签名图片大多是透明底黑色笔迹。展示区使用与 PDF 页面接近的
        # 浅色纸张背景，避免深色主题下黑色签名不可见。
        self._list.setStyleSheet(
            "QListWidget#signatureLibraryList {"
            " background: #f3f5f8; color: #344054;"
            " border: 1px solid #d7dce4; outline: none; }"
            "QListWidget#signatureLibraryList::item {"
            " color: #344054; margin: 4px; padding: 4px;"
            " border: 1px solid transparent; }"
            "QListWidget#signatureLibraryList::item:hover {"
            " background: #e8f1fb; border-color: #bfd7ef; }"
            "QListWidget#signatureLibraryList::item:selected {"
            " background: #d7eaff; color: #075fa9;"
            " border-color: #83b8eb; }"
        )
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setIconSize(QSize(110, 60))
        self._list.setGridSize(QSize(140, 100))
        self._list.setMovement(QListWidget.Movement.Static)

        items = list_signatures()
        for name, path in items:
            img = QImage(path)
            if img.isNull():
                continue
            item = QListWidgetItem(QIcon(self._signature_thumbnail(img)), name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self._list.addItem(item)

        btn_del = QPushButton("删除选中")
        btn_cancel = QPushButton("取消")
        btn_ok = QPushButton("使用")
        btn_del.clicked.connect(self._delete_selected)
        btn_cancel.clicked.connect(self.reject)
        btn_ok.clicked.connect(self._confirm)
        self._list.itemDoubleClicked.connect(lambda _i: self._confirm())

        row = QHBoxLayout()
        row.addWidget(btn_del)
        row.addStretch(1)
        row.addWidget(btn_cancel)
        row.addWidget(btn_ok)

        lay = QVBoxLayout(self)
        lay.addWidget(self._list)
        lay.addLayout(row)
        self.resize(420, 320)

    @staticmethod
    def _signature_thumbnail(img):
        """把透明签名合成到白色纸张缩略图，选择状态下仍清晰可见。"""
        size = QSize(110, 60)
        thumb = QPixmap(size)
        thumb.fill(QColor("#ffffff"))
        painter = QPainter(thumb)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#d3d8e0"), 1))
        painter.drawRect(0, 0, size.width() - 1, size.height() - 1)
        scaled = QPixmap.fromImage(img).scaled(
            QSize(98, 48), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        x = (size.width() - scaled.width()) // 2
        y = (size.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.end()
        return thumb

    def _delete_selected(self):
        item = self._list.currentItem()
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if delete_signature(path):
            self._list.takeItem(self._list.row(item))

    def _confirm(self):
        item = self._list.currentItem()
        if item is None:
            QMessageBox.information(self, "提示", "请选择一个签名")
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "提示", "无法读取该签名")
            return
        self._image = img
        self.accept()

    def result_image(self):
        return self._image
