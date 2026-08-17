"""DO编辑器 主窗口：多标签页 + 工具栏 + 主题。"""
import os
import sys
import json
import ctypes
from PySide6.QtCore import Qt, QSize, QSettings, QEvent, Signal, QTimer, QThread
from PySide6.QtGui import (QAction, QKeySequence, QActionGroup, QGuiApplication,
                           QColor, QFont, QIcon, QShortcut, QPainter)
from PySide6.QtWidgets import (QMainWindow, QDialog, QTabWidget, QToolBar,
                               QLabel, QLineEdit, QFileDialog, QMessageBox,
                               QApplication, QToolButton, QInputDialog, QMenu,
                               QProxyStyle, QStyle, QWidget, QVBoxLayout,
                               QHBoxLayout, QPushButton)

import backend
import app_config as cfg
import theme
import icons
import i18n
from document_view import DocumentView, MODE_DEFS


class ToolbarProxyStyle(QProxyStyle):
    """隐藏工具栏原生溢出入口，改用统一主题的自定义菜单。"""

    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PixelMetric.PM_ToolBarExtensionExtent:
            return 0
        return super().pixelMetric(metric, option, widget)


class SortableToolBar(QToolBar):
    """支持拖动按钮调整顺序的工具栏；按钮溢出时自动显示 >> 下拉框。"""

    orderChanged = Signal()

    def __init__(self, title, parent=None):
        super().__init__(title, parent)
        self._overflow_style = ToolbarProxyStyle()
        self.setStyle(self._overflow_style)
        # 工具按钮仍可在栏内拖动排序，无需显示系统工具栏拖动手柄。
        self.setMovable(False)
        self._drag_action = None
        self._drag_start = None
        self._dragging = False

    def showEvent(self, event):
        super().showEvent(event)
        self._install_button_filters()

    def actionEvent(self, event):
        super().actionEvent(event)
        QTimer.singleShot(0, self._install_button_filters)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._install_button_filters)

    def paintEvent(self, event):
        super().paintEvent(event)
        # 覆盖部分 Windows/Qt 样式强制绘制的工具栏底边高光。
        dark = theme.is_dark(getattr(self.window(), "theme_mode", "system"))
        painter = QPainter(self)
        color = QColor("#1d222b" if dark else "#f7f7f9")
        painter.fillRect(0, 0, self.width(), 2, color)
        painter.fillRect(0, max(0, self.height() - 2), self.width(), 2, color)

    def _install_button_filters(self):
        for btn in self.findChildren(QToolButton):
            if btn.objectName() == "qt_toolbar_ext_button":
                btn.setFixedWidth(0)
                btn.hide()
                continue
            # 工具栏自身使用 ToolbarProxyStyle 隐藏原生溢出入口。Qt 在
            # QAction 重排时新建的按钮会错误继承该代理样式，导致背景、
            # 边框、边距和高度全部丢失；按钮必须使用应用主题样式。
            app = QApplication.instance()
            if app is not None and \
                    btn.style().metaObject().className() == "ToolbarProxyStyle":
                btn.setStyle(app.style())
            # QAction 调整位置后，Qt 可能重建对应的 QToolButton。显式同步
            # 工具栏外观，避免新按钮退回系统默认的图标/文字排列与字体。
            btn.setToolButtonStyle(self.toolButtonStyle())
            btn.setIconSize(self.iconSize())
            btn.setFont(self.font())
            btn.ensurePolished()
            btn.updateGeometry()
            try:
                btn.removeEventFilter(self)
            except Exception:
                pass
            btn.installEventFilter(self)

    def eventFilter(self, obj, event):
        if isinstance(obj, QToolButton):
            t = event.type()
            if t == QEvent.Type.MouseButtonPress and \
                    event.button() == Qt.MouseButton.LeftButton:
                pos = self.mapFromGlobal(event.globalPosition().toPoint())
                self._drag_action = self.actionAt(pos)
                self._drag_start = event.globalPosition().toPoint()
                self._dragging = False
            elif t == QEvent.Type.MouseMove and self._drag_action is not None:
                gp = event.globalPosition().toPoint()
                if (gp - self._drag_start).manhattanLength() > 8:
                    self._dragging = True
                    # QToolButton 已经收到按下事件；进入排序拖动后立即解除
                    # 按压外观，防止松开事件被过滤时按钮一直呈现凹陷状态。
                    obj.setDown(False)
                    obj.update()
                    return True
            elif t == QEvent.Type.MouseButtonRelease:
                was_drag = self._dragging
                drag_action = self._drag_action
                target = None
                if was_drag and drag_action is not None:
                    pos = self.mapFromGlobal(event.globalPosition().toPoint())
                    target = self.actionAt(pos)
                self._drag_action = None
                self._drag_start = None
                self._dragging = False
                if was_drag:
                    # 先让 QToolButton 正常处理 MouseButtonRelease，彻底清除
                    # pressed/hover/grab 状态；下一轮事件循环再移动 QAction。
                    if target is not None and target is not drag_action \
                            and not target.isSeparator():
                        QTimer.singleShot(
                            0, lambda a=drag_action, t=target:
                            self._finish_action_move(a, t))
                    return False
        return super().eventFilter(obj, event)

    def _finish_action_move(self, action, target):
        """鼠标释放完成后移动操作，并统一刷新新旧按钮外观。"""
        if action not in self.actions() or target not in self.actions():
            return
        self.insertAction(target, action)
        self.orderChanged.emit()
        self._install_button_filters()
        button = self.widgetForAction(action)
        if button is not None:
            button.setDown(False)
            button.clearFocus()
            button.update()
        if self.layout() is not None:
            self.layout().invalidate()
        self.updateGeometry()
        self.update()


class DialogTitleBar(QWidget):
    """随应用主题绘制、支持拖动的对话框标题栏。"""

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)


class AboutDialog(QDialog):
    """自绘标题栏的“关于”窗口，避免 Windows 原生标题栏主题失步。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aboutDialog")
        self.setWindowTitle(f"关于 {cfg.APP_NAME}")
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.setFixedWidth(430)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        title_bar = DialogTitleBar(self)
        title_bar.setObjectName("aboutTitleBar")
        title_bar.setFixedHeight(48)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(12, 0, 8, 0)
        title_layout.setSpacing(9)

        icon_label = QLabel(title_bar)
        icon_label.setObjectName("aboutTitleIcon")
        icon_label.setFixedSize(26, 26)
        icon_label.setPixmap(self.windowIcon().pixmap(24, 24))
        icon_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        title_layout.addWidget(icon_label)

        title_label = QLabel(f"关于 {cfg.APP_NAME}", title_bar)
        title_label.setObjectName("aboutTitleText")
        title_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        title_layout.addWidget(title_label, 1)

        close_button = QToolButton(title_bar)
        close_button.setObjectName("aboutCloseButton")
        close_button.setText("×")
        close_button.setToolTip("关闭")
        close_button.setFixedSize(34, 32)
        close_button.clicked.connect(self.reject)
        title_layout.addWidget(close_button)
        outer.addWidget(title_bar)

        body = QWidget(self)
        body.setObjectName("aboutBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(28, 22, 28, 20)
        body_layout.setSpacing(18)

        info = QLabel(body)
        info.setObjectName("aboutInfo")
        info.setTextFormat(Qt.TextFormat.RichText)
        info.setText(
            f"<h3>{cfg.APP_NAME}</h3>"
            f"<p>版本 {cfg.APP_VERSION}</p>"
            f"<p>开发者：{cfg.DEVELOPER}<br>邮箱：{cfg.DEVELOPER_EMAIL}</p>"
            f"<p>基于 PySide6 + PyMuPDF 构建</p>"
            f"<p>{cfg.COPYRIGHT}</p>")
        body_layout.addWidget(info)

        ok_button = QPushButton("OK", body)
        ok_button.setObjectName("primaryButton")
        ok_button.setDefault(True)
        ok_button.setFixedWidth(94)
        ok_button.clicked.connect(self.accept)
        body_layout.addWidget(
            ok_button, 0, Qt.AlignmentFlag.AlignRight)
        outer.addWidget(body)


class WordConvertWorker(QThread):
    """后台线程把 Word 文档转为 PDF，避免阻塞主界面。"""

    converted = Signal(str)   # 转换后的 PDF 路径
    failed = Signal(str)      # 错误信息

    def __init__(self, src_path, parent=None):
        super().__init__(parent)
        self.src_path = src_path

    def run(self):
        try:
            pdf = backend.word_to_pdf(self.src_path)
            self.converted.emit(pdf)
        except Exception as e:
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(cfg.APP_NAME)
        self.resize(1280, 820)
        self.setMinimumSize(940, 640)
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.settings = QSettings(cfg.ORG_NAME, cfg.APP_NAME)
        self.theme_mode = self.settings.value("theme", cfg.DEFAULT_THEME, type=str)
        i18n.set_lang(self.settings.value("language", "zh"))
        self._icon_color = icons.icon_color_for_dark(theme.is_dark(self.theme_mode))
        self._word_workers = []

        self._build_tabs()
        self._build_actions()
        self._build_toolbars()
        self._build_menus()
        self._apply_ui_fonts()
        self._build_statusbar()
        self._apply_theme()

        self._new_tab()

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self._escape_to_select)
        QShortcut(QKeySequence(Qt.Key.Key_F11), self, self.toggle_fullscreen)
        QShortcut(QKeySequence.StandardKey.Copy, self, self._copy_shortcut)
        QShortcut(QKeySequence.StandardKey.Paste, self, self._paste_shortcut)
        QShortcut(QKeySequence.StandardKey.Find, self, self._focus_search)

        QGuiApplication.styleHints().colorSchemeChanged.connect(
            self._on_system_theme_changed)

    # ================= 标签页 =================
    def _build_tabs(self):
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

    def current_view(self):
        return self.tabs.currentWidget()

    def _new_tab(self):
        view = DocumentView()
        view.openRequested.connect(self.open_pdf)
        view.statusMessage.connect(self._on_status)
        view.titleChanged.connect(lambda t, v=view: self._update_tab_title(v, t))
        view.pageChanged.connect(self._on_page_changed)
        idx = self.tabs.addTab(view, "未命名")
        self.tabs.setCurrentIndex(idx)
        self._sync_mode_buttons(view)
        return view

    def _update_tab_title(self, view, title):
        idx = self.tabs.indexOf(view)
        if idx >= 0:
            self.tabs.setTabText(idx, title)
            if view is self.current_view():
                self.setWindowTitle(f"{cfg.APP_NAME} — {title}")

    def _on_tab_changed(self, idx):
        view = self.tabs.widget(idx)
        if view:
            self._sync_mode_buttons(view)
            if view.file_path:
                self.setWindowTitle(f"{cfg.APP_NAME} — {os.path.basename(view.file_path)}")
            else:
                self.setWindowTitle(cfg.APP_NAME)

    def _sync_mode_buttons(self, view):
        for k, act in self.mode_actions.items():
            act.setChecked(k == view.current_mode)

    def _on_status(self, msg, timeout):
        self.statusBar().showMessage(msg, timeout)

    def _on_page_changed(self, pno, total):
        if total > 0:
            self.page_label.setText(f"第 {pno + 1} / {total} 页")
        else:
            self.page_label.setText("")

    def _close_tab(self, idx):
        view = self.tabs.widget(idx)
        if view is None:
            return
        if view.modified:
            r = self._ask_save(i18n.tr("unsaved_changes"))
            if r == "save":
                view.save()
            elif r == "cancel":
                return
        if self.tabs.count() <= 1:
            view.close_doc()
            self._update_tab_title(view, "未命名")
            self._on_page_changed(0, 0)
        else:
            self.tabs.removeTab(idx)
            view.deleteLater()

    # ================= 动作 =================
    def _build_actions(self):
        a = self.act = {}
        self._icon_key_of = {}

        def mk(key, ikey, text, **kw):
            act = QAction(i18n.tr(key, text), self, **kw)
            act.setProperty("do_key", key)
            if ikey:
                act.setIcon(icons.get(ikey, self._icon_color))
                self._icon_key_of[act] = ikey
            a[key] = act
            return act

        mk("open", "open", "打开", shortcut=QKeySequence.StandardKey.Open,
           triggered=self.open_pdf)
        mk("save", "save", "保存", shortcut=QKeySequence.StandardKey.Save,
           triggered=lambda: self.current_view().save())
        mk("save_as", None, "另存为", shortcut="Ctrl+Shift+S",
           triggered=lambda: self.current_view().save_as())
        mk("print", "print", "打印", shortcut=QKeySequence.StandardKey.Print,
           triggered=lambda: self.current_view().print_pdf())
        mk("close", None, "关闭标签页", shortcut="Ctrl+W",
           triggered=lambda: self._close_tab(self.tabs.currentIndex()))

        mk("zoom_in", "zoom_in", "放大", shortcut=QKeySequence.StandardKey.ZoomIn,
           triggered=lambda: self.current_view().zoom_in())
        mk("zoom_out", "zoom_out", "缩小", shortcut=QKeySequence.StandardKey.ZoomOut,
           triggered=lambda: self.current_view().zoom_out())
        mk("fit_width", "fit_width", "适合宽度",
           triggered=lambda: self.current_view().fit_width())
        mk("sidebar", "sidebar", "侧边栏", triggered=self._toggle_sidebar)

        mk("delete_page", "trash", "删除当前页",
           triggered=lambda: self.current_view().delete_current_page())
        mk("merge", "merge", "合并 PDF", triggered=self.merge_pdfs)
        mk("split_every", "split", "每 N 页拆分", triggered=self.split_every_n)
        mk("split_ranges", None, "按页码范围拆分", triggered=self.split_by_ranges)
        mk("extract", None, "提取指定页", triggered=self.extract_pages)
        mk("watermark", "watermark", "添加水印", triggered=self.add_watermark)
        mk("copy_all", None, "复制本页全部文字",
           triggered=lambda: self.current_view().copy_page_text())
        mk("image", "image", "插入图片",
           triggered=lambda: self.current_view().start_image())
        mk("edit_color", "color", "编辑颜色", triggered=self._pick_color)
        mk("sign", "sign", "手写签名",
           triggered=lambda: self.current_view().start_sign())
        mk("sign_lib", "library", "签名库",
           triggered=lambda: self.current_view().open_sign_lib())
        mk("fullscreen", None, "全屏", triggered=self.toggle_fullscreen)
        mk("about", None, "关于", triggered=self.about)

        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        mk("theme_light", None, "浅色", checkable=True,
           triggered=lambda: self.set_theme("light"))
        mk("theme_dark", None, "深色", checkable=True,
           triggered=lambda: self.set_theme("dark"))
        mk("theme_system", None, "跟随系统", checkable=True,
           triggered=lambda: self.set_theme("system"))
        for k in ("theme_light", "theme_dark", "theme_system"):
            self.theme_group.addAction(a[k])

        self.mode_actions = {}
        for key, label, _vm, ikey in MODE_DEFS:
            act = QAction(icons.get(ikey, self._icon_color), i18n.tr(key, label),
                          self, checkable=True,
                          triggered=lambda checked=False, k=key: self._trigger_mode(k))
            act.setToolTip(i18n.tr(key, label))
            act.setProperty("do_key", key)
            self._icon_key_of[act] = ikey
            self.mode_actions[key] = act

    def _trigger_mode(self, key):
        view = self.current_view()
        if view:
            view.set_mode(key)
        for k, act in self.mode_actions.items():
            act.setChecked(k == key)

    def _escape_to_select(self):
        self._trigger_mode("view")

    def _copy_shortcut(self):
        view = self.current_view()
        if view:
            view.copy_selected_or_page()

    def _paste_shortcut(self):
        view = self.current_view()
        if view:
            view.paste_text()

    # ================= 工具栏 =================
    def _build_toolbars(self):
        default_file = ["save", "fit_width", "sidebar", "merge", "split_every",
                        "watermark"]
        default_edit = [k for k, _l, _vm, _i in MODE_DEFS[1:]] + \
                       ["edit_color", "image", "sign", "sign_lib", "delete_page"]
        saved_raw = self.settings.value("toolbar_order", None)
        saved = None
        if saved_raw:
            try:
                saved = json.loads(saved_raw)
            except Exception:
                saved = None

        # 第一行：文件/工具
        self.tb1 = SortableToolBar("文件", self)
        self.tb1.setObjectName("fileToolBar")
        self.tb1.setIconSize(QSize(16, 16))
        self.tb1.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.tb1.orderChanged.connect(self._toolbar_order_changed)
        self.addToolBar(self.tb1)
        file_order = list((saved.get("file") if saved else None) or default_file)
        for key in default_file:  # 补齐默认顺序里新增的按钮
            if key not in file_order:
                file_order.append(key)
        for key in file_order:
            if key in self.act:
                self.tb1.addAction(self.act[key])

        # 第二行：编辑
        self.tb2 = SortableToolBar("编辑", self)
        self.tb2.setObjectName("editToolBar")
        self.tb2.setIconSize(QSize(16, 16))
        self.tb2.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.tb2.orderChanged.connect(self._toolbar_order_changed)
        self.addToolBar(self.tb2)
        edit_order = list((saved.get("edit") if saved else None) or default_edit)
        for key in default_edit:  # 补齐默认顺序里新增的按钮
            if key not in edit_order:
                if key == "edit_color" and "image" in edit_order:
                    edit_order.insert(edit_order.index("image"), key)
                else:
                    edit_order.append(key)
        for key in edit_order:
            if key in self.mode_actions:
                self.tb2.addAction(self.mode_actions[key])
            elif key in self.act:
                self.tb2.addAction(self.act[key])

        # QMainWindow 会在相邻工具栏之间强制绘制一条竖向分隔边；使用与
        # 主题同色的无交互覆盖层消除突兀竖线，不影响按钮拖动排序。
        self.toolbar_seam_cover = QWidget(self)
        self.toolbar_seam_cover.setObjectName("toolbarSeamCover")
        self.toolbar_seam_cover.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.toolbar_seam_cover.setFixedWidth(4)

        # 独立溢出入口使用普通 QMenu，确保菜单背景与当前主题同步。
        self.more_tools_menu = QMenu(self)
        self.more_tools_menu.setObjectName("toolbarOverflowMenu")
        self.more_tools_menu.aboutToShow.connect(self._refresh_more_tools_menu)

        self.more_tools_btn = QToolButton(self.tb2)
        self.more_tools_btn.setObjectName("toolbar_more_btn")
        self.more_tools_btn.setText("▾")
        self.more_tools_btn.setToolTip("更多工具")
        self.more_tools_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_tools_btn.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_tools_btn.setMenu(self.more_tools_menu)
        self.more_tools_btn.setAutoRaise(True)
        self.more_tools_btn.setFixedSize(24, 24)
        self.more_tools_btn.hide()
        self._more_visibility_pending = False

    @staticmethod
    def _action_is_visible(toolbar, action):
        widget = toolbar.widgetForAction(action)
        if widget is None or not widget.isVisible():
            return False
        return toolbar.rect().contains(widget.geometry())

    def _refresh_more_tools_menu(self):
        """仅列出当前宽度下未显示在工具栏里的操作。"""
        self.more_tools_menu.clear()
        hidden_file = [
            action for action in self.tb1.actions()
            if not action.isSeparator() and action.property("do_key") and
            not self._action_is_visible(self.tb1, action)
        ]
        hidden_edit = [
            action for action in self.tb2.actions()
            if not action.isSeparator() and action.property("do_key") and
            not self._action_is_visible(self.tb2, action)
        ]
        for action in hidden_file:
            self.more_tools_menu.addAction(action)
        if hidden_file and hidden_edit:
            self.more_tools_menu.addSeparator()
        for action in hidden_edit:
            self.more_tools_menu.addAction(action)

    def _schedule_more_tools_visibility(self):
        if not hasattr(self, "more_tools_btn"):
            return
        if self._more_visibility_pending:
            return
        self._more_visibility_pending = True
        self.more_tools_btn.hide()
        # 先释放倒三角的预留区域，判断工具本身是否真的发生溢出。
        self.tb2.setContentsMargins(0, 0, 0, 0)
        QTimer.singleShot(0, self._finish_more_tools_visibility)

    def _finish_more_tools_visibility(self):
        self._more_visibility_pending = False
        if not self.isVisible():
            return
        actions = [
            (self.tb1, action) for action in self.tb1.actions()
            if not action.isSeparator() and action.property("do_key")
        ]
        actions.extend(
            (self.tb2, action) for action in self.tb2.actions()
            if not action.isSeparator() and action.property("do_key")
        )
        overflow = any(
            not self._action_is_visible(toolbar, action)
            for toolbar, action in actions
        )
        if overflow:
            # 为倒三角留出独立区域，避免覆盖最右侧仍可见的功能按钮。
            self.tb2.setContentsMargins(0, 0, 40, 0)
            x = max(0, self.tb2.width() - self.more_tools_btn.width() - 5)
            y = max(0, (self.tb2.height() - self.more_tools_btn.height()) // 2)
            self.more_tools_btn.move(x, y)
            self.more_tools_btn.raise_()
        else:
            self.tb2.setContentsMargins(0, 0, 0, 0)
        self.more_tools_btn.setVisible(overflow)
        # 内容边距变化会让 Qt 再次尝试显示原生溢出条，必须在布局完成后
        # 再隐藏一次，避免倒三角左侧出现细竖条。
        self.tb2._install_button_filters()
        QTimer.singleShot(0, self.tb2._install_button_filters)

    def _position_toolbar_seam_cover(self):
        if not hasattr(self, "toolbar_seam_cover"):
            return
        geo = self.tb2.geometry()
        self.toolbar_seam_cover.setGeometry(
            max(0, geo.x() - 2), geo.y(), 4, geo.height())
        self.toolbar_seam_cover.setVisible(self.tb2.isVisible())
        self.toolbar_seam_cover.raise_()
    def _apply_ui_fonts(self):
        """为菜单和工具栏设置清晰的独立字号与字重。"""
        menu_font = QFont("Microsoft YaHei UI")
        menu_font.setPointSizeF(10.0)
        menu_font.setWeight(QFont.Weight.Medium)
        menu_font.setHintingPreference(
            QFont.HintingPreference.PreferVerticalHinting)
        menu_font.setStyleStrategy(
            QFont.StyleStrategy.PreferAntialias |
            QFont.StyleStrategy.NoSubpixelAntialias)
        menu_font.setKerning(True)
        self.menuBar().setFont(menu_font)
        for menu in (self._m_file, self._m_edit, self._m_tools, self._m_sign,
                     self._m_view, self._m_help):
            menu.setFont(menu_font)

        toolbar_font = QFont("Microsoft YaHei UI")
        toolbar_font.setPointSizeF(8.5)
        toolbar_font.setWeight(QFont.Weight.Medium)
        toolbar_font.setHintingPreference(
            QFont.HintingPreference.PreferVerticalHinting)
        toolbar_font.setStyleStrategy(
            QFont.StyleStrategy.PreferAntialias |
            QFont.StyleStrategy.NoSubpixelAntialias)
        toolbar_font.setKerning(True)
        self.tb1.setFont(toolbar_font)
        self.tb2.setFont(toolbar_font)

    def _save_toolbar_order(self):
        order = {}
        for name, tb in (("file", self.tb1), ("edit", self.tb2)):
            keys = [a.property("do_key") for a in tb.actions()
                    if not a.isSeparator() and a.property("do_key")]
            order[name] = keys
        self.settings.setValue("toolbar_order", json.dumps(order))
        self.settings.sync()

    def _toolbar_order_changed(self):
        """保存拖动顺序，并在布局稳定后刷新按钮与溢出入口。"""
        self._save_toolbar_order()
        self.tb1._install_button_filters()
        self.tb2._install_button_filters()
        self.tb1.updateGeometry()
        self.tb2.updateGeometry()
        QTimer.singleShot(0, self._schedule_more_tools_visibility)

    def _build_menus(self):
        self._m_file = self.menuBar().addMenu(i18n.tr("menu_file"))
        self._m_file.addAction(self.act["open"])
        self._m_file.addAction(self.act["save"])
        self._m_file.addAction(self.act["save_as"])
        self._m_file.addAction(self.act["print"])
        self._m_file.addSeparator()
        self._m_file.addAction(self.act["close"])
        self._m_file.addSeparator()
        self._m_file.addAction(self.act["exit"] if "exit" in self.act else self._mk_exit())

        self._m_edit = self.menuBar().addMenu(i18n.tr("menu_edit"))
        for key, _l, _vm, _i in MODE_DEFS:
            self._m_edit.addAction(self.mode_actions[key])
        self._m_edit.addSeparator()
        self._m_edit.addAction(self.act["copy_all"])
        self._m_edit.addSeparator()
        self._m_edit.addAction(self.act["image"])
        self._m_edit.addAction(self.act["edit_color"])
        self._m_edit.addAction(self.act["delete_page"])

        self._m_tools = self.menuBar().addMenu(i18n.tr("menu_tools"))
        self._m_tools.addAction(self.act["merge"])
        self._m_tools.addAction(self.act["split_every"])
        self._m_tools.addAction(self.act["split_ranges"])
        self._m_tools.addAction(self.act["extract"])
        self._m_tools.addAction(self.act["watermark"])

        self._m_sign = self.menuBar().addMenu(i18n.tr("menu_sign"))
        self._m_sign.addAction(self.act["sign"])
        self._m_sign.addAction(self.act["sign_lib"])

        self._m_view = self.menuBar().addMenu(i18n.tr("menu_view"))
        self._m_theme = self._m_view.addMenu(i18n.tr("menu_theme"))
        self._m_theme.addAction(self.act["theme_light"])
        self._m_theme.addAction(self.act["theme_dark"])
        self._m_theme.addAction(self.act["theme_system"])

        # 语言子菜单
        self._m_lang = self._m_view.addMenu(i18n.tr("menu_lang"))
        self._lang_group = QActionGroup(self)
        self._lang_group.setExclusive(True)
        self._lang_zh_act = QAction(i18n.tr("lang_zh"), self, checkable=True)
        self._lang_en_act = QAction(i18n.tr("lang_en"), self, checkable=True)
        self._lang_group.addAction(self._lang_zh_act)
        self._lang_group.addAction(self._lang_en_act)
        self._lang_zh_act.triggered.connect(lambda: self.set_language("zh"))
        self._lang_en_act.triggered.connect(lambda: self.set_language("en"))
        self._m_lang.addAction(self._lang_zh_act)
        self._m_lang.addAction(self._lang_en_act)

        self._m_view.addSeparator()
        self._m_view.addAction(self.act["sidebar"])
        self._m_view.addAction(self.act["fullscreen"])

        self._m_help = self.menuBar().addMenu(i18n.tr("menu_help"))
        self._m_help.addAction(self.act["about"])

        self._lang_zh_act.setChecked(i18n.get_lang() == "zh")
        self._lang_en_act.setChecked(i18n.get_lang() == "en")

    def set_language(self, lang):
        i18n.set_lang(lang)
        self.settings.setValue("language", lang)
        self._apply_language()

    def _apply_language(self):
        for key, act in self.act.items():
            act.setText(i18n.tr(key, act.text()))
        for key, act in self.mode_actions.items():
            act.setText(i18n.tr(key))
            act.setToolTip(i18n.tr(key))
        self._m_file.setTitle(i18n.tr("menu_file"))
        self._m_edit.setTitle(i18n.tr("menu_edit"))
        self._m_tools.setTitle(i18n.tr("menu_tools"))
        self._m_sign.setTitle(i18n.tr("menu_sign"))
        self._m_view.setTitle(i18n.tr("menu_view"))
        self._m_theme.setTitle(i18n.tr("menu_theme"))
        self._m_lang.setTitle(i18n.tr("menu_lang"))
        self._m_help.setTitle(i18n.tr("menu_help"))
        self._lang_zh_act.setText(i18n.tr("lang_zh"))
        self._lang_en_act.setText(i18n.tr("lang_en"))
        self._lang_zh_act.setChecked(i18n.get_lang() == "zh")
        self._lang_en_act.setChecked(i18n.get_lang() == "en")
        if hasattr(self, "search_edit"):
            self.search_edit.setPlaceholderText(i18n.tr("search_placeholder"))

    def _mk_exit(self):
        self.act["exit"] = QAction(i18n.tr("exit"), self,
                                   shortcut=QKeySequence.StandardKey.Quit,
                                   triggered=self.close)
        return self.act["exit"]

    def _build_statusbar(self):
        self.page_label = QLabel("")
        self.page_label.setObjectName("pageStatus")
        self.zoom_label = QLabel("")
        self.zoom_label.setObjectName("zoomStatus")
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().addWidget(self.page_label)
        # 搜索框 + 上一条/下一条导航按钮
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(i18n.tr("search_placeholder"))
        self.search_edit.setFixedWidth(190)
        self.search_edit.setClearButtonEnabled(True)
        self.search_action = self.search_edit.addAction(
            icons.get("search", self._icon_color),
            QLineEdit.ActionPosition.LeadingPosition)
        self.search_edit.returnPressed.connect(self._do_search)

        self.btn_search = QToolButton()
        self.btn_search.setObjectName("btn_search")
        self.btn_search.setText(i18n.tr("search"))
        self.btn_search.setToolTip(i18n.tr("search"))
        self.btn_search.clicked.connect(self._do_search)

        self.btn_search_prev = QToolButton()
        self.btn_search_prev.setObjectName("btn_search_prev")
        self.btn_search_prev.setText("▲")
        self.btn_search_prev.setFixedSize(31, 28)
        self.btn_search_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_search_prev.setToolTip(i18n.tr("search_prev"))
        self.btn_search_prev.clicked.connect(self._search_prev)
        self.btn_search_next = QToolButton()
        self.btn_search_next.setObjectName("btn_search_next")
        self.btn_search_next.setText("▼")
        self.btn_search_next.setFixedSize(31, 28)
        self.btn_search_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_search_next.setToolTip(i18n.tr("search_next"))
        self.btn_search_next.clicked.connect(self._search_next)

        self.statusBar().addPermanentWidget(self.search_edit)
        self.statusBar().addPermanentWidget(self.btn_search)
        self.statusBar().addPermanentWidget(self.btn_search_prev)
        self.statusBar().addPermanentWidget(self.btn_search_next)
        self.statusBar().addPermanentWidget(self.zoom_label)

    # ================= 主题 =================
    def set_theme(self, mode):
        self.theme_mode = mode
        self.settings.setValue("theme", mode)
        self._apply_theme(refresh_native_frame=True)

    def _apply_theme(self, refresh_native_frame=False):
        # Windows 10 在窗口已显示时不会可靠地重绘原生标题栏，即使相关
        # API 返回成功。切换主题时短暂隐藏窗口，应用完主题后原样恢复，
        # 可触发系统重新绘制标题栏，同时保留尺寸与最大化/全屏状态。
        restore_window = (refresh_native_frame and sys.platform == "win32"
                          and self.isVisible())
        window_state = self.windowState() if restore_window else None
        was_active = self.isActiveWindow() if restore_window else False
        if restore_window:
            self.hide()

        dark = theme.is_dark(self.theme_mode)
        app = QApplication.instance()
        style_hints = app.styleHints()
        # 同时更新 Qt 的原生颜色方案。仅修改样式表无法约束 Windows
        # 标题栏，Qt 可能在稍后的系统事件中把它恢复成系统主题。
        if self.theme_mode == "system":
            style_hints.unsetColorScheme()
        elif dark:
            style_hints.setColorScheme(Qt.ColorScheme.Dark)
        else:
            style_hints.setColorScheme(Qt.ColorScheme.Light)
        app.setStyleSheet(theme.qss_for(self.theme_mode))
        self._icon_color = icons.icon_color_for_dark(dark)
        for act, ikey in self._icon_key_of.items():
            act.setIcon(icons.get(ikey, self._icon_color))
        if getattr(self, "search_action", None) is not None:
            self.search_action.setIcon(icons.get("search", self._icon_color))
        self.act["theme_light"].setChecked(self.theme_mode == "light")
        self.act["theme_dark"].setChecked(self.theme_mode == "dark")
        self.act["theme_system"].setChecked(self.theme_mode == "system")
        self._apply_titlebar_dark()
        # Windows 在切换样式表后会异步重建非客户区，分阶段同步可避免
        # 标题栏偶尔仍停留在上一个主题。
        QTimer.singleShot(0, self._apply_titlebar_dark)
        QTimer.singleShot(120, self._apply_titlebar_dark)
        QTimer.singleShot(360, self._apply_titlebar_dark)
        QTimer.singleShot(900, self._apply_titlebar_dark)

        if restore_window:
            self.show()
            self.setWindowState(window_state)
            if was_active:
                self.raise_()
                self.activateWindow()
            self._apply_titlebar_dark()

    def _apply_titlebar_dark(self, window=None):
        if sys.platform != "win32":
            return
        dark = theme.is_dark(self.theme_mode)
        try:
            hwnd = int((window or self).winId())
            dwmapi = ctypes.windll.dwmapi
            value = ctypes.c_int(1 if dark else 0)

            # DWMWA_USE_IMMERSIVE_DARK_MODE 在不同 Windows 版本中的编号不同。
            # DwmSetWindowAttribute 失败时只返回 HRESULT，不会抛出异常。
            for attr in (20, 19):
                try:
                    result = dwmapi.DwmSetWindowAttribute(
                        ctypes.c_void_p(hwnd), attr,
                        ctypes.byref(value), ctypes.sizeof(value))
                    if result == 0:
                        break
                except Exception:
                    continue

            # Windows 10 1903–22H2 在系统本身使用浅色主题时，部分机器即使
            # 上面的 DWM 调用返回成功也不会重绘标题栏；补充其兼容接口。
            class WindowCompositionAttributeData(ctypes.Structure):
                _fields_ = [
                    ("attribute", ctypes.c_int),
                    ("data", ctypes.c_void_p),
                    ("size", ctypes.c_size_t),
                ]

            composition = WindowCompositionAttributeData(
                26, ctypes.cast(ctypes.byref(value), ctypes.c_void_p),
                ctypes.sizeof(value))
            try:
                ctypes.windll.user32.SetWindowCompositionAttribute(
                    ctypes.c_void_p(hwnd), ctypes.byref(composition))
            except Exception:
                pass

            # Windows 11 可分别设置标题栏、标题文字和边框颜色；旧版本会
            # 安全地忽略这些属性，并继续使用上面的深浅模式提示。
            def colorref(red, green, blue):
                return red | (green << 8) | (blue << 16)

            palette = (
                ((30, 34, 42), (235, 239, 247), (56, 63, 75))
                if dark else
                ((247, 247, 249), (38, 38, 41), (213, 213, 218))
            )
            for attr, rgb in zip((35, 36, 34), palette):
                color = ctypes.c_uint(colorref(*rgb))
                try:
                    dwmapi.DwmSetWindowAttribute(
                        ctypes.c_void_p(hwnd), attr,
                        ctypes.byref(color), ctypes.sizeof(color))
                except Exception:
                    pass

            # 要求 Windows 立即重新计算并绘制非客户区（标题栏和边框）。
            flags = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020
            ctypes.windll.user32.SetWindowPos(
                ctypes.c_void_p(hwnd), None, 0, 0, 0, 0, flags)
            try:
                dwmapi.DwmFlush()
            except Exception:
                pass
        except Exception:
            pass

    def showEvent(self, e):
        super().showEvent(e)
        self._apply_titlebar_dark()
        QTimer.singleShot(80, self._apply_titlebar_dark)
        QTimer.singleShot(260, self._apply_titlebar_dark)
        QTimer.singleShot(0, self._schedule_more_tools_visibility)
        QTimer.singleShot(120, self._schedule_more_tools_visibility)
        QTimer.singleShot(0, self._position_toolbar_seam_cover)
        QTimer.singleShot(120, self._position_toolbar_seam_cover)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._schedule_more_tools_visibility()
        QTimer.singleShot(0, self._position_toolbar_seam_cover)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.Type.ThemeChange,
                        QEvent.Type.PaletteChange,
                        QEvent.Type.WindowStateChange):
            QTimer.singleShot(0, self._apply_titlebar_dark)
            QTimer.singleShot(180, self._apply_titlebar_dark)

    def _on_system_theme_changed(self, scheme):
        if self.theme_mode == "system":
            self._apply_theme(refresh_native_frame=True)
        else:
            # 即使用户选择了固定主题，系统/Qt 的晚到事件也不能覆盖标题栏。
            QTimer.singleShot(0, self._apply_titlebar_dark)
            QTimer.singleShot(240, self._apply_titlebar_dark)

    # ================= 打开 =================
    def open_pdf(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "打开文档", "",
            "文档 (*.pdf *.docx *.doc);;PDF 文件 (*.pdf);;Word 文件 (*.docx *.doc)")
        for path in paths:
            self.open_file(path)

    def open_file(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext in (".docx", ".doc"):
            self.statusBar().showMessage("正在转换 Word 文档…", 0)
            worker = WordConvertWorker(path, self)
            worker.converted.connect(self._on_word_converted)
            worker.failed.connect(self._on_word_failed)
            self._word_workers.append(worker)
            worker.finished.connect(lambda: self._cleanup_worker(worker))
            worker.start()
            return
        self._load_doc(path)

    def _cleanup_worker(self, worker):
        if worker in self._word_workers:
            self._word_workers.remove(worker)

    def _on_word_converted(self, pdf_path):
        self.statusBar().showMessage("转换完成", 2000)
        self._load_doc(pdf_path)

    def _on_word_failed(self, msg):
        self.statusBar().showMessage("", 0)
        QMessageBox.warning(
            self, "提示",
            f"无法转换 Word 文档（需要本机安装 Microsoft Word）：\n{msg}")

    def _load_doc(self, path):
        view = self.current_view()
        if view is not None and view.doc is None and self.tabs.count() == 1:
            view.load(path)
        else:
            view = self._new_tab()
            view.load(path)

    def _jump_to_page(self):
        try:
            n = int(self.page_edit.text())
            self.current_view().show_page(n - 1)
        except (ValueError, AttributeError):
            pass

    def _focus_search(self):
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _do_search(self):
        view = self.current_view()
        text = self.search_edit.text().strip()
        if view._search_results and text == getattr(view, "_search_text", None):
            view.search_next()   # 连续回车 = 下一条
        else:
            view.search(text)

    def _search_prev(self):
        view = self.current_view()
        if view:
            view.search_prev()

    def _search_next(self):
        view = self.current_view()
        if view:
            view.search_next()

    def _pick_color(self):
        view = self.current_view()
        if view:
            view.pick_edit_color()

    def _toggle_sidebar(self):
        view = self.current_view()
        if view:
            view.toggle_sidebar()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self._set_chrome_visible(True)
        else:
            view = self.current_view()
            self._fs_sidebar = view.side_tabs.isVisible() if view else False
            self.showFullScreen()
            self._set_chrome_visible(False)

    def _set_chrome_visible(self, visible):
        self.menuBar().setVisible(visible)
        for tb in self.findChildren(QToolBar):
            tb.setVisible(visible)
        if hasattr(self, "toolbar_seam_cover"):
            self.toolbar_seam_cover.setVisible(visible)
        self.statusBar().setVisible(visible)
        view = self.current_view()
        if view:
            view.side_tabs.setVisible(
                visible and getattr(self, "_fs_sidebar", False))

    # ================= 合并 / 拆分 =================
    def add_watermark(self):
        view = self._view_doc()
        if not view:
            return
        from document_view import AddWatermarkDialog
        dlg = AddWatermarkDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        text, fontsize, color, opacity, rotate, tiled = dlg.result()
        if not text:
            QMessageBox.information(self, "提示", "水印文字不能为空")
            return
        backend.add_watermark(view.doc, text, fontsize=fontsize, color=color,
                              opacity=opacity, rotate=rotate, tiled=tiled)
        view.modified = True
        view._refresh()
        self.statusBar().showMessage("已添加水印", 3000)

    def merge_pdfs(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择要合并的 PDF", "",
                                                "PDF 文件 (*.pdf)")
        if not paths:
            return
        out, _ = QFileDialog.getSaveFileName(self, "保存合并结果", "合并.pdf",
                                             "PDF 文件 (*.pdf)")
        if not out:
            return
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
        ok, res = backend.merge_pdfs(paths, out)
        if ok:
            QMessageBox.information(self, "完成", f"已合并 {len(paths)} 个文件：\n{res}")
        else:
            QMessageBox.critical(self, "错误", f"合并失败：{res}")

    def _view_doc(self):
        view = self.current_view()
        if view is None or view.doc is None:
            QMessageBox.information(self, "提示", "请先打开一个 PDF 文件")
            return None
        return view

    def split_every_n(self):
        view = self._view_doc()
        if not view:
            return
        n, ok = QInputDialog.getInt(self, "每 N 页拆分", "每几页拆为一份：", 1, 1, 9999)
        if not ok:
            return
        out_dir = QFileDialog.getExistingDirectory(self, "选择输出文件夹", "")
        if not out_dir:
            return
        ok, res = backend.split_every_n(view.doc, n, out_dir, self._base_name(view))
        self._split_result(ok, res)

    def split_by_ranges(self):
        view = self._view_doc()
        if not view:
            return
        text, ok = QInputDialog.getText(self, "按页码范围拆分",
                                        "输入页码范围（1-based，含端点），如：1-3,4-6,7-10")
        if not ok or not text.strip():
            return
        ranges = self._parse_ranges(text)
        if not ranges:
            QMessageBox.warning(self, "提示", "页码格式不正确，示例：1-3,4-6")
            return
        out_dir = QFileDialog.getExistingDirectory(self, "选择输出文件夹", "")
        if not out_dir:
            return
        ok, res = backend.split_by_ranges(view.doc, ranges, out_dir,
                                          self._base_name(view))
        self._split_result(ok, res)

    def extract_pages(self):
        view = self._view_doc()
        if not view:
            return
        text, ok = QInputDialog.getText(self, "提取指定页",
                                        "输入要提取的页码（1-based），如：1,3,5")
        if not ok or not text.strip():
            return
        pages = self._parse_pages(text)
        if not pages:
            QMessageBox.warning(self, "提示", "页码格式不正确，示例：1,3,5")
            return
        out, _ = QFileDialog.getSaveFileName(self, "保存提取结果", "提取页.pdf",
                                             "PDF 文件 (*.pdf)")
        if not out:
            return
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
        ok, res = backend.extract_pages(view.doc, pages, out)
        if ok:
            QMessageBox.information(self, "完成", f"已提取 {len(pages)} 页：\n{res}")
        else:
            QMessageBox.critical(self, "错误", f"提取失败：{res}")

    @staticmethod
    def _base_name(view):
        if view.file_path:
            return os.path.splitext(os.path.basename(view.file_path))[0] or "文档"
        return "文档"

    @staticmethod
    def _parse_ranges(text):
        ranges = []
        for part in text.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                try:
                    s, e = part.split("-")
                    ranges.append((int(s), int(e)))
                except ValueError:
                    return []
            else:
                try:
                    n = int(part)
                    ranges.append((n, n))
                except ValueError:
                    return []
        return ranges

    @staticmethod
    def _parse_pages(text):
        pages = []
        for part in text.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                pages.append(int(part) - 1)
            except ValueError:
                return []
        return pages

    def _split_result(self, ok, res):
        if ok:
            QMessageBox.information(self, "完成", f"已生成 {len(res)} 个文件。")
        else:
            QMessageBox.critical(self, "错误", f"拆分失败：{res}")

    # ================= 关于 =================
    def about(self):
        AboutDialog(self).exec()

    def _exec_themed_dialog(self, dialog):
        """显示对话框，并在 Windows 创建标题栏后同步当前主题。"""
        dialog.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        dialog.show()
        self._apply_titlebar_dark(dialog)
        QTimer.singleShot(0, lambda: self._apply_titlebar_dark(dialog))
        QTimer.singleShot(100, lambda: self._apply_titlebar_dark(dialog))
        QTimer.singleShot(300, lambda: self._apply_titlebar_dark(dialog))
        return dialog.exec()

    def closeEvent(self, e):
        for i in range(self.tabs.count()):
            view = self.tabs.widget(i)
            if view and view.modified:
                r = self._ask_save(
                    i18n.tr("unsaved_changes_file").format(f=view.file_path or "未命名"))
                if r == "save":
                    view.save()
                elif r == "cancel":
                    e.ignore()
                    return
        backend.cleanup_word()
        e.accept()

    def _ask_save(self, text):
        """弹出保存确认框，按钮文字随界面语言切换。返回 'save'/'discard'/'cancel'。"""
        box = QMessageBox(self)
        box.setWindowTitle(i18n.tr("hint"))
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(text)
        save_btn = box.addButton(i18n.tr("save"), QMessageBox.ButtonRole.AcceptRole)
        discard_btn = box.addButton(i18n.tr("discard"), QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton(i18n.tr("cancel"), QMessageBox.ButtonRole.RejectRole)
        self._exec_themed_dialog(box)
        clicked = box.clickedButton()
        if clicked == save_btn:
            return "save"
        if clicked == discard_btn:
            return "discard"
        return "cancel"
