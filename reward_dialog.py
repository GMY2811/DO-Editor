"""打赏作者弹窗：第 N 次启动（默认 6）展示赞赏码，用户可勾选"以后不再弹出"。"""
import os

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout)

import app_config as cfg
import i18n

_KEY = "reward_dismissed"
_COUNT_KEY = "reward_launch_count"

# 第几次启动开始弹出（>= 6 且未勾选"以后不再弹出"）。
SHOW_AT_LAUNCH = 6


def is_reward_dismissed():
    s = QSettings(cfg.ORG_NAME, cfg.APP_NAME)
    return bool(s.value(_KEY, False, type=bool))


def set_reward_dismissed(value=True):
    s = QSettings(cfg.ORG_NAME, cfg.APP_NAME)
    s.setValue(_KEY, bool(value))


def bump_launch_count():
    """每次软件启动调用一次，返回累计启动次数。
    勾选"以后不再弹出"后停止计数（不再增长）。"""
    s = QSettings(cfg.ORG_NAME, cfg.APP_NAME)
    if bool(s.value(_KEY, False, type=bool)):
        return int(s.value(_COUNT_KEY, 0, type=int))
    n = int(s.value(_COUNT_KEY, 0, type=int)) + 1
    s.setValue(_COUNT_KEY, n)
    return n


class RewardDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("reward_title"))
        # 不要系统模态，避免阻塞其它启动逻辑；软件已可见后才弹出。
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 28, 18)
        lay.setSpacing(10)

        title = QLabel(i18n.tr("reward_title"))
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.2)
        title.setFont(font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        msg = QLabel(i18n.tr("reward_message"))
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        msg.setObjectName("rewardMessage")
        lay.addWidget(msg)

        asset = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "assets", "reward_qr.png")
        pix = QPixmap(asset)
        if not pix.isNull():
            img = QLabel()
            img.setPixmap(pix.scaledToWidth(
                280, Qt.TransformationMode.SmoothTransformation))
            img.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img.setObjectName("rewardQrImage")
            lay.addWidget(img)
        else:
            err = QLabel(i18n.tr("reward_image_missing"))
            err.setAlignment(Qt.AlignmentFlag.AlignCenter)
            err.setObjectName("rewardMissingHint")
            lay.addWidget(err)

        self._dont_show = QCheckBox(i18n.tr("reward_dont_show"))
        self._dont_show.setObjectName("rewardDontShow")
        lay.addWidget(self._dont_show, 0, Qt.AlignmentFlag.AlignHCenter)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton(i18n.tr("reward_close"))
        close_btn.setObjectName("rewardCloseBtn")
        close_btn.setDefault(True)
        close_btn.setAutoDefault(True)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

    def accept(self):
        if self._dont_show.isChecked():
            set_reward_dismissed(True)
        super().accept()

    def reject(self):
        # ESC 关闭：不勾选"以后不再弹出"时，下次启动仍会出现。
        super().reject()