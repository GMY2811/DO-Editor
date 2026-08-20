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
QLabel#aboutAppIcon { background: #ffffff; border: 1px solid #e1e1e5; border-radius: 16px; }
QLabel#aboutAppName { color: #1d1d1f; font-size: 19px; font-weight: 700; }
QLabel#aboutVersion { color: #6e6e73; font-size: 12px; }
QLabel#aboutSummary { color: #6e6e73; font-size: 12px; }
QFrame#aboutDivider { background: #dedee3; border: none; }
QWidget#aboutDetails { background: #ffffff; border: 1px solid #e1e1e5; border-radius: 10px; }
QLabel#aboutMetaLabel { color: #8e8e93; font-size: 12px; }
QLabel#aboutMetaValue { color: #2c2c2e; font-size: 12px; font-weight: 500; }
QLabel#aboutCopyright { color: #8e8e93; font-size: 11px; }
QMainWindow::separator { background: transparent; width: 0; height: 0; }
QWidget { color: #2c2c2e; }
QWidget:disabled { color: #aeaeb2; }
QWidget#toolbarSeamCover { background: #f7f7f9; border: none; }
QMenuBar { background: #f7f7f9; border: none; padding: 1px 10px; }
QMenuBar::item { padding: 4px 10px; border-radius: 5px; color: #2c2c2e; font-weight: 500; }
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
QToolButton#toolbar_more_btn { background: transparent; border: none; border-radius: 5px; padding: 0; margin: 0; }
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
QToolButton#btn_search_prev, QToolButton#btn_search_next { background: #e4eef8; border: 1px solid #b7cee3; border-radius: 7px; color: #176fb6; font-size: 12px; font-weight: 700; padding: 0; }
QToolButton#btn_search_prev:hover, QToolButton#btn_search_next:hover { background: #007aff; border-color: #0068d1; color: #ffffff; }
QToolButton#btn_search_prev:pressed, QToolButton#btn_search_next:pressed { background: #0066cc; }
QWidget#searchNavSpacer { background: transparent; border: none; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QFontComboBox, QSpinBox, QDoubleSpinBox { background: #ffffff; color: #1d1d1f; border: 1px solid #c7c7cc; border-radius: 7px; padding: 5px 9px; selection-background-color: #b8d9ff; selection-color: #1d1d1f; }
QLineEdit:hover, QTextEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: #b9c5d4; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QFontComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #4f7cff; }
QWidget#inlineTextBar { background: #fbfbfd; border: 1px solid #c7c7cc; border-radius: 12px; }
QWidget#inlineTextBar QLineEdit, QWidget#inlineTextBar QFontComboBox, QWidget#inlineTextBar QSpinBox { min-height: 28px; background: #ffffff; border: 1px solid #d1d1d6; border-radius: 7px; padding: 3px 8px; color: #1d1d1f; }
QWidget#inlineTextBar QLineEdit:focus, QWidget#inlineTextBar QFontComboBox:focus, QWidget#inlineTextBar QSpinBox:focus { border-color: #007aff; }
QWidget#inlineTextBar QPushButton { min-height: 28px; padding: 3px 10px; border-radius: 7px; }
QWidget#inlineTextBar QPushButton#inlineTextOk { background: #007aff; color: #ffffff; border: 1px solid #0071e3; font-weight: 600; }
QWidget#inlineTextBar QPushButton#inlineTextOk:hover { background: #0071e3; }
QWidget#inlineTextBar QPushButton#inlineTextCancel { background: #f1f1f4; color: #3a3a3c; border: 1px solid #d1d1d6; }
QWidget#inlineTextBar QPushButton#inlineTextCancel:hover { background: #e5e5ea; }
QWidget#inlineTextBar QPushButton#inlineTextColor { border: 2px solid #ffffff; }
QWidget#inlineTextBar QCheckBox#inlineTextToggle { color: #3a3a3c; spacing: 6px; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #ffffff; border: 1px solid #d8e0ea; selection-background-color: #e7efff; }
QListWidget, QTreeWidget { background: #f6f6f8; border: none; outline: none; }
QListWidget::item { border-radius: 8px; margin: 4px 8px; padding: 5px; color: #64748b; }
QListWidget::item:hover, QTreeWidget::item:hover { background: #eef3f8; }
QListWidget::item:selected, QTreeWidget::item:selected { background: #dceeff; color: #0066cc; }
QTreeWidget::item { padding: 5px 3px; }
QTabWidget::pane { border: none; background: transparent; }
QTabBar { background: #ededf0; border: none; outline: none; }
QTabBar::tab { background: transparent; color: #6e6e73; font-size: 8pt; min-width: 62px; min-height: 16px; max-height: 16px; padding: 0 6px; margin: 1px 2px; border: 1px solid transparent; border-radius: 5px; }
QTabBar::tab:selected { background: #ffffff; color: #0066cc; font-weight: 600; border: 1px solid #d2d2d7; }
QTabBar::tab:hover:!selected { background: #e1e1e5; color: #1d1d1f; }
QTabWidget#sidePanel QTabBar::tab { min-width: 40px; padding: 0 4px; }
QToolButton#tabCloseButton { background: transparent; border: none; border-radius: 4px; padding: 0; margin: 0; }
QToolButton#tabCloseButton:hover { background: #e3e8ee; }
QToolButton#tabCloseButton:pressed { background: #d6dde5; }
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
QListWidget#thumbnailList QScrollBar:vertical { background: transparent; width: 7px; border: none; margin: 0; }
QListWidget#thumbnailList QScrollBar::handle:vertical { background: #aeb8c5; border-radius: 2px; min-height: 28px; margin: 2px; }
QListWidget#thumbnailList QScrollBar::handle:vertical:hover { background: #7f8b99; }
QListWidget#thumbnailList QScrollBar::add-line:vertical, QListWidget#thumbnailList QScrollBar::sub-line:vertical { height: 0; }
QListWidget#thumbnailList QScrollBar::add-page:vertical, QListWidget#thumbnailList QScrollBar::sub-page:vertical { background: transparent; }
QListWidget#thumbnailList { outline: none; show-decoration-selected: 0; selection-background-color: transparent; }
QListWidget#thumbnailList::item { background: transparent; border: 1px solid transparent; border-radius: 0; margin: 3px 5px; padding: 1px 4px; color: #5f6b78; }
QListWidget#thumbnailList::item:hover { background: #edf2f7; border-color: #d8e1ea; color: #344252; }
QListWidget#thumbnailList::item:selected { background: #e7f1fb; border-color: #78aee3; color: #1769aa; }
QListWidget#thumbnailList::item:selected:active { background: #e1eefb; border-color: #5c9bd8; color: #0f5f9f; }
QScrollArea#documentScroll QScrollBar:vertical { background: transparent; width: 9px; border: none; margin: 0; }
QScrollArea#documentScroll QScrollBar::handle:vertical { background: #aeb6c0; border: none; border-radius: 2px; min-height: 42px; margin: 2px; }
QScrollArea#documentScroll QScrollBar::handle:vertical:hover { background: #7f8995; }
QScrollArea#documentScroll QScrollBar::handle:vertical:pressed { background: #667482; }
QScrollArea#documentScroll QScrollBar::add-line:vertical, QScrollArea#documentScroll QScrollBar::sub-line:vertical { width: 0; height: 0; background: transparent; border: none; }
QScrollArea#documentScroll QScrollBar::add-page:vertical, QScrollArea#documentScroll QScrollBar::sub-page:vertical { background: transparent; }
QScrollArea#documentScroll QScrollBar::up-arrow:vertical, QScrollArea#documentScroll QScrollBar::down-arrow:vertical { image: none; width: 0; height: 0; }
QScrollBar:horizontal { background: transparent; height: 12px; border: none; }
QScrollBar::handle:horizontal { background: #b8c1ce; border-radius: 5px; min-width: 32px; margin: 3px 2px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QWidget#startPage { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f8f8fa, stop:0.52 #f3f5f8, stop:1 #edf4fb); }
QFrame#startCard { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #fbfbfd); border: 1px solid #e0e0e5; border-radius: 22px; }
QLabel#startAppIcon { background: transparent; border: none; padding: 0; }
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
QMainWindow, QDialog { background: #1c1c1e; color: #f5f5f7; }
QDialog#aboutDialog { background: #3a3a3c; border: 1px solid #3a3a3c; }
QWidget#aboutTitleBar { background: #242426; border: none; border-bottom: 1px solid #3a3a3c; }
QWidget#aboutBody { background: #1c1c1e; border: none; }
QLabel#aboutTitleText { color: #f5f5f7; font-size: 11pt; font-weight: 600; }
QToolButton#aboutCloseButton { background: transparent; border: none; color: #d1d1d6; font-family: "Segoe UI"; font-size: 20px; padding: 0; }
QToolButton#aboutCloseButton:hover { background: #e5484d; color: #ffffff; }
QLabel#aboutInfo { color: #f5f5f7; }
QLabel#aboutAppIcon { background: #2c2c2e; border: 1px solid #48484a; border-radius: 16px; }
QLabel#aboutAppName { color: #f5f5f7; font-size: 19px; font-weight: 700; }
QLabel#aboutVersion { color: #a1a1a6; font-size: 12px; }
QLabel#aboutSummary { color: #a1a1a6; font-size: 12px; }
QFrame#aboutDivider { background: #38383a; border: none; }
QWidget#aboutDetails { background: #2c2c2e; border: 1px solid #3a3a3c; border-radius: 10px; }
QLabel#aboutMetaLabel { color: #8e8e93; font-size: 12px; }
QLabel#aboutMetaValue { color: #f2f2f7; font-size: 12px; font-weight: 500; }
QLabel#aboutCopyright { color: #8e8e93; font-size: 11px; }
QMainWindow::separator { background: transparent; width: 0; height: 0; }
QWidget { color: #d1d1d6; }
QWidget:disabled { color: #636366; }
QWidget#toolbarSeamCover { background: #242426; border: none; }
QMenuBar { background: #242426; border: none; padding: 1px 10px; }
QMenuBar::item { padding: 4px 10px; border-radius: 5px; color: #d1d1d6; font-weight: 500; }
QMenuBar::item:selected { background: #3a3a3c; color: #64a8ff; }
QMenu { background: #2c2c2e; border: 1px solid #48484a; border-radius: 0; padding: 6px; }
QMenu::item { padding: 7px 30px 7px 12px; border-radius: 0; color: #f2f2f7; }
QMenu::item:selected { background: #0a84ff; color: #ffffff; }
QMenu::item:disabled { color: #636366; }
QMenu::separator { height: 1px; background: #48484a; margin: 5px 8px; }
QToolBar { background: #242426; border: none; border-bottom: 1px solid #242426; padding: 2px 26px 2px 6px; spacing: 2px; }
QToolBar#editToolBar { background: #242426; border-left: none; padding-left: 8px; }
QToolBar#toolbarEndSpacer { background: #242426; border-left: none; padding: 0; }
QToolBar#toolbarEndSpacer::handle { image: none; width: 0; margin: 0; padding: 0; }
QToolBar::separator { width: 1px; background: #48484a; margin: 5px 6px; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 4px 6px; color: #d1d1d6; }
QToolButton:hover { background: #363638; border-color: #48484a; }
QToolButton:pressed { background: #424245; }
QToolButton:checked { background: #0a5fad; border-color: #0a84ff; color: #ffffff; font-weight: 600; }
QToolBar#fileToolBar QToolButton, QToolBar#editToolBar QToolButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3a3a3c, stop:0.52 #343436, stop:1 #2c2c2e); border: 1px solid #48484a; border-top-color: #545456; border-bottom-color: #1c1c1e; border-radius: 0; padding: 1px 3px; margin: 2px 2px 3px 2px; color: #d1d1d6; }
QToolBar#fileToolBar QToolButton:hover, QToolBar#editToolBar QToolButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #48484a, stop:0.52 #404042, stop:1 #363638); border-color: #636366; border-top-color: #6b6b70; border-bottom-color: #242426; color: #ffffff; }
QToolBar#fileToolBar QToolButton:pressed, QToolBar#editToolBar QToolButton:pressed { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #29292b, stop:1 #3a3a3c); border-color: #3a3a3c; border-top-color: #202022; border-bottom-color: #545456; padding-top: 2px; padding-bottom: 0; }
QToolBar#fileToolBar QToolButton:checked, QToolBar#editToolBar QToolButton:checked { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #238cff, stop:0.52 #0a78e8, stop:1 #0060bf); border-color: #409cff; border-top-color: #64b0ff; border-bottom-color: #004f9e; color: #ffffff; font-weight: 600; }
QToolButton#qt_toolbar_ext_button { min-width: 0; max-width: 0; width: 0; padding: 0; margin: 0; border: none; }
QToolButton#toolbar_more_btn { background: transparent; border: none; border-radius: 5px; padding: 0; margin: 0; }
QToolButton#toolbar_more_btn::menu-indicator { image: none; width: 0; height: 0; }
QToolButton#toolbar_more_btn:hover { background: #363638; color: #64a8ff; }
QToolButton#toolbar_more_btn:pressed { background: #424245; color: #ffffff; }
QPushButton { min-height: 20px; background: #2c2c2e; color: #f2f2f7; border: 1px solid #48484a; border-radius: 7px; padding: 6px 16px; }
QPushButton:hover { background: #3a3a3c; border-color: #636366; }
QPushButton:pressed { background: #48484a; }
QPushButton:default, QPushButton#primaryButton, QPushButton#startOpenButton, QToolButton#btn_search { background: #0a84ff; color: #ffffff; border: 1px solid #0a84ff; font-weight: 600; }
QPushButton:default:hover, QPushButton#primaryButton:hover, QPushButton#startOpenButton:hover, QToolButton#btn_search:hover { background: #0077ed; border-color: #0077ed; }
QPushButton#startOpenButton { min-width: 128px; padding: 9px 22px; }
QToolButton#btn_search { border-radius: 7px; padding: 5px 12px; }
QToolButton#btn_search_prev, QToolButton#btn_search_next { background: #303740; border: 1px solid #4b5b6a; border-radius: 7px; color: #7fc0ff; font-size: 12px; font-weight: 700; padding: 0; }
QToolButton#btn_search_prev:hover, QToolButton#btn_search_next:hover { background: #0a84ff; border-color: #409cff; color: #ffffff; }
QToolButton#btn_search_prev:pressed, QToolButton#btn_search_next:pressed { background: #0066cc; }
QWidget#searchNavSpacer { background: transparent; border: none; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QFontComboBox, QSpinBox, QDoubleSpinBox { background: #2c2c2e; color: #f2f2f7; border: 1px solid #48484a; border-radius: 7px; padding: 5px 9px; selection-background-color: #0a5fad; }
QLineEdit:hover, QTextEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: #636366; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QFontComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #0a84ff; }
QWidget#inlineTextBar { background: #2c2c2e; border: 1px solid #545456; border-radius: 12px; }
QWidget#inlineTextBar QLineEdit, QWidget#inlineTextBar QFontComboBox, QWidget#inlineTextBar QSpinBox { min-height: 28px; background: #1c1c1e; border: 1px solid #48484a; border-radius: 7px; padding: 3px 8px; color: #f2f2f7; }
QWidget#inlineTextBar QLineEdit:focus, QWidget#inlineTextBar QFontComboBox:focus, QWidget#inlineTextBar QSpinBox:focus { border-color: #0a84ff; }
QWidget#inlineTextBar QPushButton { min-height: 28px; padding: 3px 10px; border-radius: 7px; }
QWidget#inlineTextBar QPushButton#inlineTextOk { background: #0a84ff; color: #ffffff; border: 1px solid #409cff; font-weight: 600; }
QWidget#inlineTextBar QPushButton#inlineTextOk:hover { background: #0077ed; }
QWidget#inlineTextBar QPushButton#inlineTextCancel { background: #3a3a3c; color: #f2f2f7; border: 1px solid #545456; }
QWidget#inlineTextBar QPushButton#inlineTextCancel:hover { background: #48484a; }
QWidget#inlineTextBar QPushButton#inlineTextColor { border: 2px solid #636366; }
QWidget#inlineTextBar QCheckBox#inlineTextToggle { color: #d1d1d6; spacing: 6px; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #2c2c2e; border: 1px solid #48484a; selection-background-color: #0a5fad; }
QListWidget, QTreeWidget { background: #1c1c1e; border: none; outline: none; }
QListWidget::item { border-radius: 8px; margin: 4px 8px; padding: 5px; color: #a1a1a6; }
QListWidget::item:hover, QTreeWidget::item:hover { background: #2c2c2e; }
QListWidget::item:selected, QTreeWidget::item:selected { background: #0a5fad; color: #ffffff; }
QTreeWidget::item { padding: 5px 3px; }
QTabWidget::pane { border: none; background: transparent; }
QTabBar { background: #1c1c1e; border: none; outline: none; }
QTabBar::tab { background: transparent; color: #8e8e93; font-size: 8pt; min-width: 62px; min-height: 16px; max-height: 16px; padding: 0 6px; margin: 1px 2px; border: 1px solid transparent; border-radius: 5px; }
QTabBar::tab:selected { background: #2c2c2e; color: #ffffff; font-weight: 600; border: 1px solid #48484a; }
QTabBar::tab:hover:!selected { background: #242426; color: #d1d1d6; }
QTabWidget#sidePanel QTabBar::tab { min-width: 40px; padding: 0 4px; }
QToolButton#tabCloseButton { background: transparent; border: none; border-radius: 4px; padding: 0; margin: 0; }
QToolButton#tabCloseButton:hover { background: #363b42; }
QToolButton#tabCloseButton:pressed { background: #40464e; }
QStatusBar { background: #242426; border-top: 1px solid #38383a; color: #8e8e93; padding: 3px 8px; }
QStatusBar::item { border: none; }
QStatusBar QLabel { color: #8e8e93; padding: 0 6px; }
QScrollArea { border: none; background: #323234; }
QSplitter::handle { background: #38383a; width: 1px; }
QSplitter::handle:hover { background: #0a84ff; }
QScrollBar:vertical { background: transparent; width: 12px; border: none; }
QScrollBar::handle:vertical { background: #545456; border-radius: 5px; min-height: 32px; margin: 2px 3px; }
QScrollBar::handle:vertical:hover { background: #6b6b70; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QListWidget#thumbnailList QScrollBar:vertical { background: transparent; width: 7px; border: none; margin: 0; }
QListWidget#thumbnailList QScrollBar::handle:vertical { background: #555b64; border-radius: 2px; min-height: 28px; margin: 2px; }
QListWidget#thumbnailList QScrollBar::handle:vertical:hover { background: #77808b; }
QListWidget#thumbnailList QScrollBar::add-line:vertical, QListWidget#thumbnailList QScrollBar::sub-line:vertical { height: 0; }
QListWidget#thumbnailList QScrollBar::add-page:vertical, QListWidget#thumbnailList QScrollBar::sub-page:vertical { background: transparent; }
QListWidget#thumbnailList { outline: none; show-decoration-selected: 0; selection-background-color: transparent; }
QListWidget#thumbnailList::item { background: transparent; border: 1px solid transparent; border-radius: 0; margin: 3px 5px; padding: 1px 4px; color: #aeb5bf; }
QListWidget#thumbnailList::item:hover { background: #262b31; border-color: #3a4652; color: #e3e6ea; }
QListWidget#thumbnailList::item:selected { background: #2a3542; border-color: #4f91d2; color: #f3f6fa; }
QListWidget#thumbnailList::item:selected:active { background: #2d3b49; border-color: #68a5df; color: #ffffff; }
QScrollArea#documentScroll QScrollBar:vertical { background: transparent; width: 9px; border: none; margin: 0; }
QScrollArea#documentScroll QScrollBar::handle:vertical { background: #5e646d; border: none; border-radius: 2px; min-height: 42px; margin: 2px; }
QScrollArea#documentScroll QScrollBar::handle:vertical:hover { background: #808994; }
QScrollArea#documentScroll QScrollBar::handle:vertical:pressed { background: #9aa4af; }
QScrollArea#documentScroll QScrollBar::add-line:vertical, QScrollArea#documentScroll QScrollBar::sub-line:vertical { width: 0; height: 0; background: transparent; border: none; }
QScrollArea#documentScroll QScrollBar::add-page:vertical, QScrollArea#documentScroll QScrollBar::sub-page:vertical { background: transparent; }
QScrollArea#documentScroll QScrollBar::up-arrow:vertical, QScrollArea#documentScroll QScrollBar::down-arrow:vertical { image: none; width: 0; height: 0; }
QScrollBar:horizontal { background: transparent; height: 12px; border: none; }
QScrollBar::handle:horizontal { background: #545456; border-radius: 5px; min-width: 32px; margin: 3px 2px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QWidget#startPage { background: #1c1c1e; }
QFrame#startCard { background: #2c2c2e; border: 1px solid #3a3a3c; border-radius: 18px; }
QLabel#startAppIcon { background: transparent; border: none; padding: 0; }
QLabel#startTitle { color: #f5f5f7; font-size: 24px; font-weight: 700; }
QLabel#startSubtitle { color: #a1a1a6; font-size: 13px; }
QLabel#startHint { color: #8e8e93; font-size: 12px; }
QCheckBox { spacing: 7px; color: #d1d1d6; }
QCheckBox::indicator { width: 16px; height: 16px; }
QSlider::groove:horizontal { height: 4px; background: #48484a; border-radius: 2px; }
QSlider::handle:horizontal { width: 16px; height: 16px; margin: -6px 0; background: #0a84ff; border-radius: 8px; }
QToolTip { background: #f5f5f7; color: #1d1d1f; border: none; padding: 5px 8px; }
QMessageBox, QInputDialog { background: #2c2c2e; }
"""

# 最后追加的配色层用于统一主要界面的色彩关系。保留前面的控件尺寸、
# 字体和布局规则，仅覆盖颜色与状态层级，减少大面积灰色带来的沉闷感。
LIGHT += r"""
QMainWindow, QDialog { background: #f5f6f8; color: #202124; }
QMainWindow::separator { width: 0; height: 0; background: transparent; }
QWidget { color: #343438; }
QWidget:disabled { color: #a3a3a8; }
QWidget#toolbarSeamCover, QMenuBar, QToolBar, QToolBar#editToolBar,
QToolBar#toolbarEndSpacer { background: #f0f2f5; }
QMenuBar { background: #eef1f5; padding: 1px 10px; }
QMenuBar::item { padding: 4px 10px; color: #3f4650; }
QToolBar#fileToolBar { padding: 2px 0 2px 6px; spacing: 0; }
QToolBar#editToolBar { padding: 2px 26px 2px 0; spacing: 0; }
QToolBar::handle { image: none; width: 0; margin: 0; padding: 0; }
QWidget#toolbarSeamCover {
    background: #f0f2f5;
    border: none;
}
QMenuBar::item { color: #343438; }
QMenuBar::item:selected { background: #e8eef7; color: #0668c8; }
QMenu { background: #ffffff; border-color: #d1d1d6; }
QMenu::item { color: #2c2c2e; }
QMenu::item:selected { background: #087bf0; color: #ffffff; }
QMenu::separator { background: #e5e5ea; }
QToolBar#fileToolBar QToolButton, QToolBar#editToolBar QToolButton {
    background: #f7f8fa;
    border: none;
    margin: 2px 0 3px 0;
    color: #42474f;
}
QToolBar#fileToolBar QToolButton:hover, QToolBar#editToolBar QToolButton:hover {
    background: #e4ebf3; border: none; color: #1769aa;
}
QToolBar#fileToolBar QToolButton:pressed, QToolBar#editToolBar QToolButton:pressed {
    background: #d9e4ef; border: none;
    padding-top: 1px; padding-bottom: 1px;
}
QToolBar#fileToolBar QToolButton:checked, QToolBar#editToolBar QToolButton:checked {
    background: #dce9f6; border: none; color: #155f9d;
    font-weight: 600;
}
QPushButton { background: #ffffff; color: #343438; border-color: #d1d1d6; }
QPushButton:hover { background: #f4f7fb; border-color: #b8c9da; }
QPushButton:default, QPushButton#primaryButton, QPushButton#startOpenButton,
QToolButton#btn_search { background: #087bf0; border-color: #0874e2; color: #ffffff; }
QPushButton:default:hover, QPushButton#primaryButton:hover,
QPushButton#startOpenButton:hover, QToolButton#btn_search:hover {
    background: #006ee6; border-color: #0067d8;
}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QFontComboBox,
QSpinBox, QDoubleSpinBox { background: #ffffff; color: #1f1f22; border-color: #c7c7cc; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
QFontComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #2685df; }
QWidget#inlineTextBar { background: #fafafd; border-color: #c7c7cc; }
QWidget#inlineTextBar QLineEdit, QWidget#inlineTextBar QFontComboBox,
QWidget#inlineTextBar QSpinBox { background: #ffffff; border-color: #c7c7cc; }
QTabBar { background: #e7ebf0; }
QTabBar::tab { color: #6e6e73; }
QTabBar::tab:selected { background: #f8fafc; color: #1769aa; border-color: #d2d9e2; }
QTabBar::tab:hover:!selected { background: #dce3eb; color: #303741; }
QStatusBar { background: #f8f8fa; border-top-color: #dedee3; color: #6e6e73; }
QListWidget, QTreeWidget { background: #f5f5f7; }
QListWidget::item:hover, QTreeWidget::item:hover { background: #e9edf2; }
QListWidget::item:selected, QTreeWidget::item:selected { background: #dcecff; color: #0864bc; }
QScrollArea { background: #dde1e6; }
QWidget#startPage { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
    stop:0 #f8f9fb, stop:0.52 #f3f5f8, stop:1 #eaf0f6); }
QFrame#startCard { background: #ffffff; border-color: #dedee3; }
QLabel#startTitle { color: #1f1f22; }
QLabel#startSubtitle { color: #6e6e73; }
QLabel#startHint { color: #8e8e93; }
QDialog#aboutDialog { background: #e1e1e5; border-color: #c7c7cc; }
QWidget#aboutTitleBar { background: #f8f8fa; border-bottom-color: #dedee3; }
QWidget#aboutBody { background: #f5f5f7; }
QWidget#aboutDetails { background: #ffffff; border-color: #dedee3; }
QLabel#noteHoverPreview {
    background: #ffffff;
    color: #27364a;
    border: 1px solid #cbd8e6;
    border-radius: 8px;
    padding: 8px 10px;
}
"""

DARK += r"""
QMainWindow, QDialog { background: #1d1e21; color: #f2f2f4; }
QMainWindow::separator { width: 0; height: 0; background: transparent; }
QWidget { color: #d7d7dc; }
QWidget:disabled { color: #68686d; }
QWidget#toolbarSeamCover, QMenuBar, QToolBar, QToolBar#editToolBar,
QToolBar#toolbarEndSpacer { background: #232529; }
QMenuBar { background: #202226; padding: 1px 10px; }
QMenuBar::item { padding: 4px 10px; color: #d2d6dc; }
QToolBar#fileToolBar { padding: 2px 0 2px 6px; spacing: 0; }
QToolBar#editToolBar { padding: 2px 26px 2px 0; spacing: 0; }
QToolBar::handle { image: none; width: 0; margin: 0; padding: 0; }
QWidget#toolbarSeamCover {
    background: #232529;
    border: none;
}
QMenuBar::item { color: #d7d7dc; }
QMenuBar::item:selected { background: #38383d; color: #72b4ff; }
QMenu { background: #2b2b2f; border-color: #4a4a4f; }
QMenu::item { color: #f0f0f3; }
QMenu::item:selected { background: #147bd1; color: #ffffff; }
QMenu::separator { background: #48484d; }
QToolBar#fileToolBar QToolButton, QToolBar#editToolBar QToolButton {
    background: #292b2f;
    border: none;
    margin: 2px 0 3px 0;
    color: #d7d9de;
}
QToolBar#fileToolBar QToolButton:hover, QToolBar#editToolBar QToolButton:hover {
    background: #343a42; border: none; color: #f4f5f7;
}
QToolBar#fileToolBar QToolButton:pressed, QToolBar#editToolBar QToolButton:pressed {
    background: #2c333b; border: none;
    padding-top: 1px; padding-bottom: 1px;
}
QToolBar#fileToolBar QToolButton:checked, QToolBar#editToolBar QToolButton:checked {
    background: #30465b; border: none; color: #f2f5f8;
    font-weight: 600;
}
QPushButton { background: #2d2d31; color: #f2f2f7; border-color: #4a4a4f; }
QPushButton:hover { background: #3a3a3f; border-color: #626268; }
QPushButton:default, QPushButton#primaryButton, QPushButton#startOpenButton,
QToolButton#btn_search { background: #1687e8; border-color: #3598ed; color: #ffffff; }
QPushButton:default:hover, QPushButton#primaryButton:hover,
QPushButton#startOpenButton:hover, QToolButton#btn_search:hover {
    background: #0b78d6; border-color: #45a0ed;
}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QFontComboBox,
QSpinBox, QDoubleSpinBox { background: #29292d; color: #f2f2f7; border-color: #4a4a4f; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
QFontComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #3f9bec; }
QWidget#inlineTextBar { background: #2b2b2f; border-color: #505056; }
QWidget#inlineTextBar QLineEdit, QWidget#inlineTextBar QFontComboBox,
QWidget#inlineTextBar QSpinBox { background: #202023; border-color: #48484d; }
QTabBar { background: #1d1f23; }
QTabBar::tab { color: #989fa9; }
QTabBar::tab:selected { background: #2b3036; color: #f3f5f7; border-color: #40464e; }
QTabBar::tab:hover:!selected { background: #272b30; color: #dce0e5; }
QStatusBar { background: #252529; border-top-color: #3a3a3f; color: #949499; }
QListWidget, QTreeWidget { background: #1d1d20; }
QListWidget::item:hover, QTreeWidget::item:hover { background: #2c2c30; }
QListWidget::item:selected, QTreeWidget::item:selected { background: #126ab1; color: #ffffff; }
QScrollArea { background: #292b30; }
QWidget#startPage { background: #202226; }
QFrame#startCard { background: #2b2b2f; border-color: #444449; }
QLabel#startTitle { color: #f5f5f7; }
QLabel#startSubtitle { color: #a6a6ab; }
QLabel#startHint { color: #85858a; }
QDialog#aboutDialog { background: #38383d; border-color: #48484d; }
QWidget#aboutTitleBar { background: #252529; border-bottom-color: #3f3f44; }
QWidget#aboutBody { background: #1c1c1e; }
QWidget#aboutDetails { background: #2b2b2f; border-color: #444449; }
QLabel#noteHoverPreview {
    background: #2b313a;
    color: #f4f7fb;
    border: 1px solid #4a586a;
    border-radius: 8px;
    padding: 8px 10px;
}
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
