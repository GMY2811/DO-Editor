"""编辑已插入图片的对话框：仅调整透明度。
透明度拖动时通过 opacityChanged 信号实时同步到文档页面。"""
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QSlider, QVBoxLayout, QFormLayout)

import i18n


class EditImageDialog(QDialog):
    """编辑已插入图片：仅透明度。"""

    # 透明度实时变化（0-1），调用方在文档页面上同步呈现
    opacityChanged = Signal(float)

    def __init__(self, obj, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("edit_image"))
        self._obj = obj
        self._opacity = float(obj.get("opacity", 1.0))

        form = QFormLayout()

        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(5, 100)
        self._opacity_slider.setValue(int(round(self._opacity * 100)))
        self._opacity_label = QLabel(f"{self._opacity_slider.value()}%")
        self._opacity_label.setMinimumWidth(44)
        self._opacity_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self._opacity_slider, 1)
        opacity_row.addWidget(self._opacity_label)
        form.addRow(i18n.tr("watermark_opacity"), opacity_row)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(btns)
        self.resize(320, 120)

    def _on_opacity_changed(self, v):
        self._opacity_label.setText(f"{v}%")
        # 实时同步到文档页面（由调用方连接）
        self.opacityChanged.emit(v / 100.0)

    def result(self):  # override 返回最终值
        if self._result_code != QDialog.DialogCode.Accepted:
            return None   # 取消
        return ("ok", self._opacity_slider.value() / 100.0)

    def done(self, r):
        self._result_code = r
        super().done(r)