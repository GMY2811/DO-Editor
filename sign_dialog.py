"""手写签名画板、签名库（保存/调用）。"""
import os
import time
import i18n
from PySide6.QtCore import Qt, QBuffer, QByteArray, QIODevice, QSize
from PySide6.QtGui import QImage, QPainter, QPen, QColor, QPixmap, QIcon
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLabel, QFileDialog, QMessageBox,
                               QListWidget, QListWidgetItem, QInputDialog,
                               QSlider, QLineEdit, QSpinBox)


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
                            family=None):
    """把文字渲染成透明背景的签名图片（用于文字签名）。

    自动选择系统必有的字体（中文用黑体、英文用 Arial），避免乱码。
    """
    from PySide6.QtGui import QFont, QFontMetrics, QFontDatabase
    db = QFontDatabase()
    if not family:
        has_cjk = any('\u4e00' <= c <= '\u9fff' for c in text)
        family = "SimHei" if has_cjk else "Arial"
    if family not in db.families():
        family = "Arial"
    f = QFont(family)
    f.setPixelSize(int(font_size))
    f.setBold(bold)
    fm = QFontMetrics(f)
    r = fm.boundingRect(text)
    pad = 18
    w = max(60, r.width() + pad * 2)
    h = max(40, r.height() + pad * 2)
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return img


def remove_default_signatures():
    """删除旧版本自动建立的默认文字签名模板。"""
    for name in ("BOSL TRUCKING", "Manager", "BOLF",
                 "dispatch@bosltruckinginc.com", "日期"):
        for n, path in list_signatures():
            if n == name:
                delete_signature(path)


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
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumHeight(64)

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

        btn_import = QPushButton(i18n.tr("import_image"))
        btn_clear = QPushButton(i18n.tr("clear"))
        btn_save = QPushButton(i18n.tr("save_to_lib"))
        btn_cancel = QPushButton(i18n.tr("cancel"))
        btn_ok = QPushButton(i18n.tr("confirm"))

        btn_import.clicked.connect(self._import)
        btn_clear.clicked.connect(self._canvas.clear)
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
        lay.addLayout(text_row)
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
        img = text_to_signature_image(text, font_size=self._text_size.value(),
                                      bold=True)
        self._image = img
        self._canvas.clear()
        pm = QPixmap.fromImage(img).scaledToWidth(
            220, Qt.TransformationMode.SmoothTransformation)
        self._preview.setPixmap(pm)

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
        pm = QPixmap.fromImage(img).scaledToWidth(
            220, Qt.TransformationMode.SmoothTransformation)
        self._preview.setPixmap(pm)

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
            item = QListWidgetItem(QIcon(QPixmap.fromImage(img)), name)
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
