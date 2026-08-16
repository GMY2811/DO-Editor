"""DO阅读器 界面主题：浅色 / 深色两套 QSS + 系统主题检测。"""
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import Qt


LIGHT = """
* { font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif; font-size: 13px; }
QMainWindow, QDialog { background: #f4f5f7; }
QMenuBar { background: #ffffff; border-bottom: 1px solid #e8eaed; padding: 2px 8px; }
QMenuBar::item { padding: 6px 12px; border-radius: 7px; color: #374151; }
QMenuBar::item:selected { background: #eef2ff; color: #2563eb; }
QMenu { background: #ffffff; border: 1px solid #e8eaed; border-radius: 10px; padding: 5px; }
QMenu::item { padding: 7px 26px 7px 14px; border-radius: 7px; color: #374151; }
QMenu::item:selected { background: #eef2ff; color: #2563eb; }
QMenu::separator { height: 1px; background: #e8eaed; margin: 5px 8px; }
QToolBar { background: #ffffff; border: none; border-bottom: 1px solid #e8eaed; padding: 5px 10px; spacing: 3px; }
QToolBar::separator { width: 1px; background: #e8eaed; margin: 5px 7px; }
QToolButton { background: transparent; border: none; border-radius: 8px; padding: 6px 9px; color: #374151; }
QToolButton:hover { background: #eef0f3; }
QToolButton:pressed { background: #e2e5ea; }
QToolButton:checked { background: #2563eb; color: #ffffff; }
QToolButton#qt_toolbar_ext_button { background: #eef2ff; border: 1px solid #c7d2fe; border-radius: 6px; color: #2563eb; font-weight: bold; min-width: 18px; padding: 0 4px; }
QToolButton#qt_toolbar_ext_button:hover { background: #dbeafe; }
QPushButton { background: #2563eb; color: #ffffff; border: none; border-radius: 8px; padding: 7px 18px; font-weight: 500; }
QPushButton:hover { background: #1d4ed8; }
QPushButton:pressed { background: #1e40af; }
QLineEdit { background: #ffffff; border: 1px solid #d7dbe0; border-radius: 8px; padding: 6px 10px; color: #111827; }
QLineEdit:focus { border: 1px solid #2563eb; }
QListWidget { background: #fafbfc; border: none; border-right: 1px solid #e8eaed; outline: none; }
QListWidget::item { border-radius: 8px; margin: 4px 8px; padding: 4px; color: #6b7280; }
QListWidget::item:selected { background: #eef2ff; color: #2563eb; }
QStatusBar { background: #ffffff; border-top: 1px solid #e8eaed; color: #6b7280; }
QStatusBar QLabel { color: #6b7280; }
QScrollArea { border: none; background: #5b6066; }
QScrollBar:vertical { background: #f4f5f7; width: 12px; border: none; }
QScrollBar::handle:vertical { background: #c6cbd2; border-radius: 6px; min-height: 30px; margin: 2px; }
QScrollBar::handle:vertical:hover { background: #aab0b9; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #f4f5f7; height: 12px; border: none; }
QScrollBar::handle:horizontal { background: #c6cbd2; border-radius: 6px; min-width: 30px; margin: 2px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QMessageBox, QInputDialog { background: #ffffff; }
QLabel { color: #374151; }
QSlider::groove:horizontal { height: 4px; background: #e2e5ea; border-radius: 2px; }
QSlider::handle:horizontal { width: 16px; height: 16px; margin: -6px 0; background: #2563eb; border-radius: 8px; }
"""


DARK = """
* { font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif; font-size: 13px; }
QMainWindow, QDialog { background: #2c2c2c; }
QMenuBar { background: #323232; border-bottom: 1px solid #444; padding: 2px 8px; }
QMenuBar::item { padding: 6px 12px; border-radius: 4px; color: #d6d6d6; }
QMenuBar::item:selected { background: #444; color: #ffffff; }
QMenu { background: #3c3c3c; border: 1px solid #555; border-radius: 6px; padding: 5px; }
QMenu::item { padding: 7px 26px 7px 14px; border-radius: 4px; color: #d6d6d6; }
QMenu::item:selected { background: #4b9cf0; color: #ffffff; }
QMenu::separator { height: 1px; background: #555; margin: 5px 8px; }
QToolBar { background: #323232; border: none; border-bottom: 1px solid #444; padding: 4px 8px; spacing: 3px; }
QToolBar::separator { width: 1px; background: #4a4a4a; margin: 5px 7px; }
QToolButton { background: transparent; border: none; border-radius: 4px; padding: 6px 9px; color: #d6d6d6; }
QToolButton:hover { background: #444; }
QToolButton:pressed { background: #4a4a4a; }
QToolButton:checked { background: #4b9cf0; color: #ffffff; }
QToolButton#qt_toolbar_ext_button { background: #3a3f44; border: 1px solid #4b9cf0; border-radius: 6px; color: #4b9cf0; font-weight: bold; min-width: 18px; padding: 0 4px; }
QToolButton#qt_toolbar_ext_button:hover { background: #444a50; }
QPushButton { background: #4b9cf0; color: #ffffff; border: none; border-radius: 4px; padding: 7px 18px; font-weight: 500; }
QPushButton:hover { background: #3f8ae0; }
QPushButton:pressed { background: #3578c8; }
QLineEdit { background: #2c2c2c; border: 1px solid #4a4a4a; border-radius: 4px; padding: 6px 10px; color: #e5e5e5; }
QLineEdit:focus { border: 1px solid #4b9cf0; }
QListWidget { background: #2c2c2c; border: none; border-right: 1px solid #444; outline: none; }
QListWidget::item { border-radius: 4px; margin: 3px 6px; padding: 4px; color: #c0c0c0; }
QListWidget::item:selected { background: #4b9cf0; color: #ffffff; }
QTreeWidget { background: #2c2c2c; border: none; color: #d0d0d0; outline: none; }
QTreeWidget::item { padding: 3px 2px; }
QTreeWidget::item:selected { background: #4b9cf0; color: #ffffff; }
QStatusBar { background: #323232; border-top: 1px solid #444; color: #b0b0b0; }
QStatusBar QLabel { color: #b0b0b0; }
QScrollArea { border: none; background: #525659; }
QScrollBar:vertical { background: #2c2c2c; width: 12px; border: none; }
QScrollBar::handle:vertical { background: #555; border-radius: 6px; min-height: 30px; margin: 2px; }
QScrollBar::handle:vertical:hover { background: #666; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #2c2c2c; height: 12px; border: none; }
QScrollBar::handle:horizontal { background: #555; border-radius: 6px; min-width: 30px; margin: 2px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QMessageBox, QInputDialog { background: #3c3c3c; }
QLabel { color: #d6d6d6; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: #2c2c2c; color: #b0b0b0; padding: 7px 16px; border: none; border-right: 1px solid #444; }
QTabBar::tab:selected { background: #525659; color: #ffffff; }
QTabBar::tab:hover { color: #ffffff; }
QSlider::groove:horizontal { height: 4px; background: #4a4a4a; border-radius: 2px; }
QSlider::handle:horizontal { width: 16px; height: 16px; margin: -6px 0; background: #4b9cf0; border-radius: 8px; }
"""


def system_is_dark():
    """检测系统是否处于深色模式（Qt 6.5+）。"""
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def qss_for(mode, dark_override=None):
    """根据主题模式返回 QSS 字符串。mode: 'light' / 'dark' / 'system'。"""
    if mode == "dark":
        return DARK
    if mode == "system":
        if dark_override is not None:
            return DARK if dark_override else LIGHT
        return DARK if system_is_dark() else LIGHT
    return LIGHT


def is_dark(mode, dark_override=None):
    return qss_for(mode, dark_override) is DARK
