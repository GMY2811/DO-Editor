"""DO编辑器界面主题：现代浅色 / 深色主题与系统主题检测。"""
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import Qt


LIGHT = r"""
QMainWindow, QDialog { background: #f6f6f8; color: #1d1d1f; }
QDialog#aboutDialog { background: #d7dbe1; border: 1px solid #c7ccd3; }
QWidget#aboutTitleBar { background: #f7f7f9; border: none; border-bottom: 1px solid #d9dde3; }
QWidget#aboutBody { background: #f6f6f8; border: none; }
QLabel#aboutTitleText { color: #1d1d1f; font-size: 11pt; font-weight: 600; }
QToolButton#aboutCloseButton { background: transparent; border: none; color: #3a3a3c; font-family: "Segoe UI"; font-size: 20px; padding: 0; }
QToolButton#aboutCloseButton:hover { background: #e5484d; color: #ffffff; }
QLabel#aboutInfo { color: #2c2c2e; }
QMainWindow::separator { background: transparent; width: 0; height: 0; }
QWidget { color: #2c2c2e; }
QWidget:disabled { color: #aeaeb2; }
QWidget#toolbarSeamCover { background: #f7f7f9; border: none; }
QMenuBar { background: #f7f7f9; border: none; padding: 3px 10px; }
QMenuBar::item { padding: 6px 11px; border-radius: 6px; color: #2c2c2e; font-weight: 500; }
QMenuBar::item:selected { background: #e7e7eb; color: #0066cc; }
QMenu { background: #ffffff; border: 1px solid #d2d2d7; border-radius: 0; padding: 6px; }
QMenu::item { padding: 7px 30px 7px 12px; border-radius: 0; color: #2c2c2e; }
QMenu::item:selected { background: #007aff; color: #ffffff; }
QMenu::item:disabled { color: #aeaeb2; }
QMenu::separator { height: 1px; background: #e5e5ea; margin: 5px 8px; }
QToolBar { background: #f7f7f9; border: none; border-bottom: 1px solid #f7f7f9; padding: 2px 26px 2px 6px; spacing: 2px; }
QToolBar#editToolBar { background: #f7f7f9; border-left: none; padding-left: 7px; }
QToolBar#toolbarEndSpacer { background: #f7f7f9; border-left: none; padding: 0; }
QToolBar#toolbarEndSpacer::handle { image: none; width: 0; margin: 0; padding: 0; }
QToolBar::separator { width: 1px; background: #d8d8dd; margin: 6px 5px; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 7px; padding: 4px 6px; color: #3a3a3c; }
QToolButton:hover { background: #e8e8ec; border-color: #d9d9de; color: #0066cc; }
QToolButton:pressed { background: #dcdcE1; }
QToolButton:checked { background: #dceeff; border-color: #a8d2ff; color: #0066cc; font-weight: 600; }
QToolBar#fileToolBar QToolButton, QToolBar#editToolBar QToolButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fafbfc, stop:0.55 #f6f7f9, stop:1 #f0f2f5); border: 1px solid #e4e7eb; border-top-color: #fcfcfd; border-bottom-color: #d9dde3; border-radius: 0; padding: 1px 3px; margin: 2px 2px 3px 2px; color: #4b5563; }
QToolBar#fileToolBar QToolButton:hover, QToolBar#editToolBar QToolButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fbfdff, stop:0.55 #f3f7fb, stop:1 #eaf1f8); border-color: #cddcea; border-top-color: #ffffff; border-bottom-color: #b9ccdd; color: #1769aa; }
QToolBar#fileToolBar QToolButton:pressed, QToolBar#editToolBar QToolButton:pressed { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #e6edf4, stop:1 #f2f5f8); border-color: #becddb; border-top-color: #afbfce; border-bottom-color: #d9e2ea; padding-top: 2px; padding-bottom: 0; }
QToolBar#fileToolBar QToolButton:checked, QToolBar#editToolBar QToolButton:checked { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f5f9fd, stop:0.5 #eaf2f9, stop:1 #ddeaf5); border-color: #bfd2e3; border-top-color: #ffffff; border-bottom-color: #9ebbd3; color: #17649f; font-weight: 600; }
QToolButton#qt_toolbar_ext_button { min-width: 0; max-width: 0; width: 0; padding: 0; margin: 0; border: none; }
QToolButton#toolbar_more_btn { background: transparent; border: none; border-radius: 0; color: #7b8796; font-size: 11px; font-weight: 600; padding: 0; margin: 0; }
QToolButton#toolbar_more_btn::menu-indicator { image: none; width: 0; height: 0; }
QToolButton#toolbar_more_btn:hover { background: #e8eef5; color: #0068c9; }
QToolButton#toolbar_more_btn:pressed { background: #dce8f4; color: #005eb8; }
QPushButton { min-height: 20px; background: #ffffff; color: #334155; border: 1px solid #d8e0ea; border-radius: 7px; padding: 6px 16px; }
QPushButton:hover { background: #f5f8fc; border-color: #b9c5d4; }
QPushButton:pressed { background: #e9eef5; }
QPushButton:default, QPushButton#primaryButton, QPushButton#startOpenButton, QToolButton#btn_search { background: #007aff; color: #ffffff; border: 1px solid #0071e3; font-weight: 600; }
QPushButton:default:hover, QPushButton#primaryButton:hover, QPushButton#startOpenButton:hover, QToolButton#btn_search:hover { background: #0071e3; border-color: #0068d1; }
QPushButton#startOpenButton { min-width: 128px; padding: 9px 22px; }
QToolButton#btn_search { border-radius: 7px; padding: 5px 12px; }
QToolButton#btn_search_prev, QToolButton#btn_search_next { background: #e5f2ff; border: 1px solid #a8d2ff; border-radius: 7px; color: #0071e3; font-size: 12px; font-weight: 700; padding: 0; }
QToolButton#btn_search_prev:hover, QToolButton#btn_search_next:hover { background: #007aff; border-color: #0068d1; color: #ffffff; }
QToolButton#btn_search_prev:pressed, QToolButton#btn_search_next:pressed { background: #0066cc; }
QToolButton#btn_search_next { margin-right: 8px; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QFontComboBox, QSpinBox, QDoubleSpinBox { background: #ffffff; color: #1d1d1f; border: 1px solid #c7c7cc; border-radius: 7px; padding: 5px 9px; selection-background-color: #b8d9ff; selection-color: #1d1d1f; }
QLineEdit:hover, QTextEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: #b9c5d4; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QFontComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #4f7cff; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #ffffff; border: 1px solid #d8e0ea; selection-background-color: #e7efff; }
QListWidget, QTreeWidget { background: #f6f6f8; border: none; outline: none; }
QListWidget::item { border-radius: 8px; margin: 4px 8px; padding: 5px; color: #64748b; }
QListWidget::item:hover, QTreeWidget::item:hover { background: #eef3f8; }
QListWidget::item:selected, QTreeWidget::item:selected { background: #dceeff; color: #0066cc; }
QTreeWidget::item { padding: 5px 3px; }
QTabWidget::pane { border: none; background: transparent; }
QTabBar { background: #ededf0; border: none; }
QTabBar::tab { background: transparent; color: #6e6e73; min-width: 92px; padding: 7px 18px; margin: 3px 2px; border: 1px solid transparent; border-radius: 8px; }
QTabBar::tab:selected { background: #ffffff; color: #0066cc; font-weight: 600; border: 1px solid #d2d2d7; }
QTabBar::tab:hover:!selected { background: #e1e1e5; color: #1d1d1f; }
QTabBar::close-button { margin-left: 6px; }
QStatusBar { background: #f7f7f9; border-top: 1px solid #e1e1e5; color: #6e6e73; padding: 3px 8px; }
QStatusBar::item { border: none; }
QStatusBar QLabel { color: #718096; padding: 0 6px; }
QScrollArea { border: none; background: #d9d9dd; }
QSplitter::handle { background: #e3e9f1; width: 1px; }
QSplitter::handle:hover { background: #9db7f4; }
QScrollBar:vertical { background: transparent; width: 12px; border: none; }
QScrollBar::handle:vertical { background: #b8c1ce; border-radius: 5px; min-height: 32px; margin: 2px 3px; }
QScrollBar::handle:vertical:hover { background: #929dab; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 12px; border: none; }
QScrollBar::handle:horizontal { background: #b8c1ce; border-radius: 5px; min-width: 32px; margin: 3px 2px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QWidget#startPage { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f8f8fa, stop:0.52 #f3f5f8, stop:1 #edf4fb); }
QFrame#startCard { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #fbfbfd); border: 1px solid #e0e0e5; border-radius: 22px; }
QLabel#startMark { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1b93ff, stop:1 #0066d6); color: #ffffff; border-radius: 14px; font-family: "Segoe UI"; font-size: 24px; font-weight: 700; }
QLabel#startTitle { color: #1d1d1f; font-size: 24px; font-weight: 700; }
QLabel#startSubtitle { color: #6e6e73; font-size: 13px; }
QLabel#startHint { color: #8e8e93; font-size: 12px; }
QCheckBox { spacing: 7px; color: #475569; }
QCheckBox::indicator { width: 16px; height: 16px; }
QSlider::groove:horizontal { height: 4px; background: #dfe5ed; border-radius: 2px; }
QSlider::handle:horizontal { width: 16px; height: 16px; margin: -6px 0; background: #3b6ef5; border-radius: 8px; }
QToolTip { background: #1f2937; color: #ffffff; border: none; padding: 5px 8px; }
QMessageBox, QInputDialog { background: #f8fafc; }
"""


DARK = r"""
QMainWindow, QDialog { background: #171b22; color: #dbe3ef; }
QDialog#aboutDialog { background: #343d4b; border: 1px solid #343d4b; }
QWidget#aboutTitleBar { background: #1d222b; border: none; border-bottom: 1px solid #343d4b; }
QWidget#aboutBody { background: #20262f; border: none; }
QLabel#aboutTitleText { color: #edf2f8; font-size: 11pt; font-weight: 600; }
QToolButton#aboutCloseButton { background: transparent; border: none; color: #d5deea; font-family: "Segoe UI"; font-size: 20px; padding: 0; }
QToolButton#aboutCloseButton:hover { background: #e5484d; color: #ffffff; }
QLabel#aboutInfo { color: #dbe3ef; }
QMainWindow::separator { background: transparent; width: 0; height: 0; }
QWidget { color: #d5deea; }
QWidget:disabled { color: #667085; }
QWidget#toolbarSeamCover { background: #1d222b; border: none; }
QMenuBar { background: #1d222b; border: none; padding: 3px 10px; }
QMenuBar::item { padding: 6px 11px; border-radius: 6px; color: #d5deea; font-weight: 500; }
QMenuBar::item:selected { background: #29354a; color: #8fb1ff; }
QMenu { background: #222833; border: 1px solid #343d4b; border-radius: 0; padding: 6px; }
QMenu::item { padding: 7px 30px 7px 12px; border-radius: 0; color: #d5deea; }
QMenu::item:selected { background: #30466f; color: #ffffff; }
QMenu::item:disabled { color: #667085; }
QMenu::separator { height: 1px; background: #343d4b; margin: 5px 8px; }
QToolBar { background: #1d222b; border: none; border-bottom: 1px solid #1d222b; padding: 2px 26px 2px 6px; spacing: 2px; }
QToolBar#editToolBar { background: #1d222b; border-left: none; padding-left: 8px; }
QToolBar#toolbarEndSpacer { background: #1d222b; border-left: none; padding: 0; }
QToolBar#toolbarEndSpacer::handle { image: none; width: 0; margin: 0; padding: 0; }
QToolBar::separator { width: 1px; background: #343d4b; margin: 5px 6px; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 4px 6px; color: #c9d3e2; }
QToolButton:hover { background: #29313d; border-color: #343e4d; }
QToolButton:pressed { background: #323b49; }
QToolButton:checked { background: #294579; border-color: #3f64a9; color: #ffffff; font-weight: 600; }
QToolBar#fileToolBar QToolButton, QToolBar#editToolBar QToolButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #303845, stop:0.5 #29313c, stop:1 #20262f); border: 1px solid #394454; border-top-color: #465162; border-bottom-color: #11161c; border-radius: 0; padding: 1px 3px; margin: 2px 2px 3px 2px; }
QToolBar#fileToolBar QToolButton:hover, QToolBar#editToolBar QToolButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3a4d65, stop:0.5 #30445b, stop:1 #26374a); border-color: #4c6d90; border-top-color: #6384a8; border-bottom-color: #172536; color: #ffffff; }
QToolBar#fileToolBar QToolButton:pressed, QToolBar#editToolBar QToolButton:pressed { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1b2938, stop:1 #31445a); border-color: #355777; border-top-color: #172332; border-bottom-color: #4a6887; padding-top: 2px; padding-bottom: 0; }
QToolBar#fileToolBar QToolButton:checked, QToolBar#editToolBar QToolButton:checked { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3f70ad, stop:0.52 #315f9b, stop:1 #234978); border-color: #4f7fb8; border-top-color: #6f98c7; border-bottom-color: #162f52; color: #ffffff; font-weight: 600; }
QToolButton#qt_toolbar_ext_button { min-width: 0; max-width: 0; width: 0; padding: 0; margin: 0; border: none; }
QToolButton#toolbar_more_btn { background: transparent; border: none; border-radius: 0; color: #8290a3; font-size: 11px; font-weight: 600; padding: 0; margin: 0; }
QToolButton#toolbar_more_btn::menu-indicator { image: none; width: 0; height: 0; }
QToolButton#toolbar_more_btn:hover { background: #29313d; color: #9fc9ff; }
QToolButton#toolbar_more_btn:pressed { background: #222a35; color: #ffffff; }
QPushButton { min-height: 20px; background: #252c36; color: #dbe3ef; border: 1px solid #3a4452; border-radius: 7px; padding: 6px 16px; }
QPushButton:hover { background: #2d3541; border-color: #526073; }
QPushButton:pressed { background: #343e4b; }
QPushButton:default, QPushButton#primaryButton, QPushButton#startOpenButton, QToolButton#btn_search { background: #4f7cff; color: #ffffff; border: 1px solid #4f7cff; font-weight: 600; }
QPushButton:default:hover, QPushButton#primaryButton:hover, QPushButton#startOpenButton:hover, QToolButton#btn_search:hover { background: #416be8; border-color: #416be8; }
QPushButton#startOpenButton { min-width: 128px; padding: 9px 22px; }
QToolButton#btn_search { border-radius: 7px; padding: 5px 12px; }
QToolButton#btn_search_prev, QToolButton#btn_search_next { background: #203b5b; border: 1px solid #356b9f; border-radius: 7px; color: #73b7ff; font-size: 12px; font-weight: 700; padding: 0; }
QToolButton#btn_search_prev:hover, QToolButton#btn_search_next:hover { background: #0a84ff; border-color: #409cff; color: #ffffff; }
QToolButton#btn_search_prev:pressed, QToolButton#btn_search_next:pressed { background: #0066cc; }
QToolButton#btn_search_next { margin-right: 8px; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QFontComboBox, QSpinBox, QDoubleSpinBox { background: #20262f; color: #e1e8f2; border: 1px solid #394352; border-radius: 7px; padding: 5px 9px; selection-background-color: #3f64a9; }
QLineEdit:hover, QTextEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: #526073; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QFontComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #6f94ff; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #222833; border: 1px solid #3a4452; selection-background-color: #30466f; }
QListWidget, QTreeWidget { background: #1b2028; border: none; outline: none; }
QListWidget::item { border-radius: 8px; margin: 4px 8px; padding: 5px; color: #9eabbd; }
QListWidget::item:hover, QTreeWidget::item:hover { background: #252d38; }
QListWidget::item:selected, QTreeWidget::item:selected { background: #294579; color: #ffffff; }
QTreeWidget::item { padding: 5px 3px; }
QTabWidget::pane { border: none; background: transparent; }
QTabBar::tab { background: #181d24; color: #8793a5; min-width: 92px; padding: 8px 18px; border: none; border-right: 1px solid #2b3340; }
QTabBar::tab:selected { background: #252c36; color: #ffffff; font-weight: 600; }
QTabBar::tab:hover:!selected { background: #212731; color: #d5deea; }
QTabBar::close-button { margin-left: 6px; }
QStatusBar { background: #1d222b; border-top: 1px solid #2b3340; color: #8793a5; padding: 3px 8px; }
QStatusBar::item { border: none; }
QStatusBar QLabel { color: #8793a5; padding: 0 6px; }
QScrollArea { border: none; background: #303640; }
QSplitter::handle { background: #303947; width: 1px; }
QSplitter::handle:hover { background: #4f72bd; }
QScrollBar:vertical { background: transparent; width: 12px; border: none; }
QScrollBar::handle:vertical { background: #505a68; border-radius: 5px; min-height: 32px; margin: 2px 3px; }
QScrollBar::handle:vertical:hover { background: #697585; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 12px; border: none; }
QScrollBar::handle:horizontal { background: #505a68; border-radius: 5px; min-width: 32px; margin: 3px 2px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QWidget#startPage { background: #20262e; }
QFrame#startCard { background: #252c36; border: 1px solid #343e4c; border-radius: 18px; }
QLabel#startMark { background: #4f7cff; color: #ffffff; border-radius: 14px; font-family: "Segoe UI"; font-size: 24px; font-weight: 700; }
QLabel#startTitle { color: #f2f5fa; font-size: 24px; font-weight: 700; }
QLabel#startSubtitle { color: #9aa8bb; font-size: 13px; }
QLabel#startHint { color: #748195; font-size: 12px; }
QCheckBox { spacing: 7px; color: #bdc8d8; }
QCheckBox::indicator { width: 16px; height: 16px; }
QSlider::groove:horizontal { height: 4px; background: #394352; border-radius: 2px; }
QSlider::handle:horizontal { width: 16px; height: 16px; margin: -6px 0; background: #4f7cff; border-radius: 8px; }
QToolTip { background: #f3f6fa; color: #1f2937; border: none; padding: 5px 8px; }
QMessageBox, QInputDialog { background: #20262f; }
"""


def system_is_dark():
    """检测系统是否处于深色模式（Qt 6.5+）。"""
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def qss_for(mode, dark_override=None):
    """根据主题模式返回 QSS 字符串。"""
    if mode == "dark":
        return DARK
    if mode == "system":
        if dark_override is not None:
            return DARK if dark_override else LIGHT
        return DARK if system_is_dark() else LIGHT
    return LIGHT


def is_dark(mode, dark_override=None):
    return qss_for(mode, dark_override) is DARK
