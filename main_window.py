"""DO编辑器 主窗口：多标签页 + 工具栏 + 主题。"""
import os
import sys
import json
import ctypes
from PySide6.QtCore import Qt, QSettings, QEvent, Signal, QTimer, QThread
from PySide6.QtGui import (QAction, QKeySequence, QActionGroup, QGuiApplication,
                           QColor, QIcon, QShortcut)
from PySide6.QtWidgets import (QMainWindow, QDialog, QTabWidget, QToolBar,
                               QLabel, QLineEdit, QFileDialog, QMessageBox,
                               QApplication, QToolButton, QInputDialog)

import backend
import app_config as cfg
import theme
import icons
import i18n
from document_view import DocumentView, MODE_DEFS


class SortableToolBar(QToolBar):
    """支持拖动按钮调整顺序的工具栏；按钮溢出时自动显示 >> 下拉框。"""

    orderChanged = Signal()

    def __init__(self, title, parent=None):
        super().__init__(title, parent)
        self.setMovable(True)
        self._drag_action = None
        self._drag_start = None
        self._dragging = False

    def showEvent(self, event):
        super().showEvent(event)
        self._install_button_filters()

    def actionEvent(self, event):
        super().actionEvent(event)
        QTimer.singleShot(0, self._install_button_filters)

    def _install_button_filters(self):
        for btn in self.findChildren(QToolButton):
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
            elif t == QEvent.Type.MouseButtonRelease:
                was_drag = self._dragging
                if was_drag and self._drag_action is not None:
                    pos = self.mapFromGlobal(event.globalPosition().toPoint())
                    target = self.actionAt(pos)
                    if target is not None and target is not self._drag_action \
                            and not target.isSeparator():
                        self.removeAction(self._drag_action)
                        self.insertAction(target, self._drag_action)
                        self.orderChanged.emit()
                self._drag_action = None
                self._drag_start = None
                self._dragging = False
                if was_drag:
                    return True
        return super().eventFilter(obj, event)


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

        self.settings = QSettings(cfg.ORG_NAME, cfg.APP_NAME)
        self.theme_mode = self.settings.value("theme", "system")
        i18n.set_lang(self.settings.value("language", "zh"))
        self._icon_color = icons.icon_color_for_dark(theme.is_dark(self.theme_mode))
        self._word_workers = []

        self._build_tabs()
        self._build_actions()
        self._build_toolbars()
        self._build_menus()
        self._build_statusbar()
        self._apply_theme()

        self._new_tab()

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self._escape_to_select)
        QShortcut(QKeySequence(Qt.Key.Key_F11), self, self.toggle_fullscreen)
        QShortcut(QKeySequence.StandardKey.Copy, self, self._copy_shortcut)
        QShortcut(QKeySequence.StandardKey.Paste, self, self._paste_shortcut)

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
        self._update_color_btn(view)

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
            r = QMessageBox.question(
                self, "提示", "文档有未保存的修改，是否保存？",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Save:
                view.save()
            elif r == QMessageBox.StandardButton.Cancel:
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
        mk("sidebar", None, "侧边栏", triggered=self._toggle_sidebar)

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
                       ["image", "sign", "sign_lib", "delete_page"]
        saved_raw = self.settings.value("toolbar_order", None)
        saved = None
        if saved_raw:
            try:
                saved = json.loads(saved_raw)
            except Exception:
                saved = None

        # 第一行：文件/工具
        self.tb1 = SortableToolBar("文件", self)
        self.tb1.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.tb1.orderChanged.connect(self._save_toolbar_order)
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
        self.tb2.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.tb2.orderChanged.connect(self._save_toolbar_order)
        self.addToolBar(self.tb2)
        edit_order = list((saved.get("edit") if saved else None) or default_edit)
        for key in default_edit:  # 补齐默认顺序里新增的按钮
            if key not in edit_order:
                edit_order.append(key)
        for key in edit_order:
            if key in self.mode_actions:
                self.tb2.addAction(self.mode_actions[key])
            elif key in self.act:
                self.tb2.addAction(self.act[key])
        self.tb2.addSeparator()
        self.color_btn = QToolButton(self)
        self.color_btn.setToolTip("编辑颜色")
        self.color_btn.setFixedSize(26, 26)
        self.color_btn.clicked.connect(self._pick_color)
        self.tb2.addWidget(self.color_btn)

    def _save_toolbar_order(self):
        order = {}
        for name, tb in (("file", self.tb1), ("edit", self.tb2)):
            keys = [a.property("do_key") for a in tb.actions()
                    if not a.isSeparator() and a.property("do_key")]
            order[name] = keys
        self.settings.setValue("toolbar_order", json.dumps(order))

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
        self.zoom_label = QLabel("")
        self.statusBar().addWidget(self.page_label)
        # 搜索框放到状态栏，避免被工具栏挤压
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(i18n.tr("search_placeholder"))
        self.search_edit.setFixedWidth(200)
        self.search_action = self.search_edit.addAction(
            icons.get("search", self._icon_color),
            QLineEdit.ActionPosition.LeadingPosition)
        self.search_edit.returnPressed.connect(self._do_search)
        self.statusBar().addPermanentWidget(self.search_edit)
        self.statusBar().addPermanentWidget(self.zoom_label)

    # ================= 主题 =================
    def set_theme(self, mode):
        self.theme_mode = mode
        self.settings.setValue("theme", mode)
        self._apply_theme()

    def _apply_theme(self):
        dark = theme.is_dark(self.theme_mode)
        QApplication.instance().setStyleSheet(theme.qss_for(self.theme_mode))
        self._icon_color = icons.icon_color_for_dark(dark)
        for act, ikey in self._icon_key_of.items():
            act.setIcon(icons.get(ikey, self._icon_color))
        if getattr(self, "search_action", None) is not None:
            self.search_action.setIcon(icons.get("search", self._icon_color))
        self.act["theme_light"].setChecked(self.theme_mode == "light")
        self.act["theme_dark"].setChecked(self.theme_mode == "dark")
        self.act["theme_system"].setChecked(self.theme_mode == "system")
        self._apply_titlebar_dark()

    def _apply_titlebar_dark(self):
        if sys.platform != "win32":
            return
        dark = theme.is_dark(self.theme_mode)
        try:
            hwnd = int(self.winId())
            value = ctypes.c_int(1 if dark else 0)
            dwmapi = ctypes.windll.dwmapi
            for attr in (20, 19):
                try:
                    dwmapi.DwmSetWindowAttribute(
                        ctypes.c_void_p(hwnd), attr,
                        ctypes.byref(value), ctypes.sizeof(value))
                    break
                except Exception:
                    continue
        except Exception:
            pass

    def showEvent(self, e):
        super().showEvent(e)
        self._apply_titlebar_dark()

    def _on_system_theme_changed(self, scheme):
        if self.theme_mode == "system":
            self._apply_theme()

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

    def _do_search(self):
        self.current_view().search(self.search_edit.text().strip())

    def _pick_color(self):
        view = self.current_view()
        if view:
            view.pick_edit_color()
            self._update_color_btn(view)

    def _update_color_btn(self, view):
        self.color_btn.setStyleSheet(
            f"background:{view.edit_color.name()};"
            f"border:1px solid #888;border-radius:5px;")

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
        QMessageBox.about(
            self, f"关于 {cfg.APP_NAME}",
            f"<h3>{cfg.APP_NAME}</h3>"
            f"<p>版本 {cfg.APP_VERSION}</p>"
            f"<p>开发者：{cfg.DEVELOPER}<br>邮箱：{cfg.DEVELOPER_EMAIL}</p>"
            f"<p>基于 PySide6 + PyMuPDF 构建</p>"
            f"<p>{cfg.COPYRIGHT}</p>")

    def closeEvent(self, e):
        for i in range(self.tabs.count()):
            view = self.tabs.widget(i)
            if view and view.modified:
                r = QMessageBox.question(
                    self, "提示", f"「{view.file_path or '未命名'}」有未保存的修改，是否保存？",
                    QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                    | QMessageBox.StandardButton.Cancel)
                if r == QMessageBox.StandardButton.Save:
                    view.save()
                elif r == QMessageBox.StandardButton.Cancel:
                    e.ignore()
                    return
        backend.cleanup_word()
        e.accept()
