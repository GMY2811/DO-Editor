"""DO编辑器 主窗口：多标签页 + 工具栏 + 主题。"""
import os
import sys
import json
import ctypes
import pymupdf
from PySide6.QtCore import (Qt, QSize, QSettings, QEvent, Signal, QTimer,
                            QThread, QPointF, QUrl, QRect, QPropertyAnimation,
                            QEasingCurve)
from PySide6.QtGui import (QAction, QKeySequence, QActionGroup, QGuiApplication,
                           QColor, QFont, QIcon, QShortcut, QPainter, QPen,
                           QDesktopServices)
from PySide6.QtWidgets import (QMainWindow, QDialog, QTabWidget, QToolBar,
                               QLabel, QLineEdit, QFileDialog, QMessageBox,
                               QApplication, QToolButton, QInputDialog, QMenu,
                               QProxyStyle, QStyle, QWidget, QVBoxLayout,
                               QHBoxLayout, QPushButton, QFrame, QTabBar,
                               QProgressDialog, QCheckBox, QFormLayout,
                               QGroupBox, QStyleOptionToolButton)

import backend
import app_config as cfg
import theme
import icons
import i18n
from document_view import DocumentView, MODE_DEFS


class ToolbarProxyStyle(QProxyStyle):
    """统一工具栏边距，并隐藏原生溢出入口。"""

    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PixelMetric.PM_ToolBarExtensionExtent:
            return 0
        if metric in (QStyle.PixelMetric.PM_ToolBarItemMargin,
                      QStyle.PixelMetric.PM_ToolBarFrameWidth):
            return 0
        return super().pixelMetric(metric, option, widget)


class RoundedMenuArrowStyle(QProxyStyle):
    """使用圆头、圆角折线绘制二级菜单箭头。"""

    def drawPrimitive(self, element, option, painter, widget=None):
        if (element == QStyle.PrimitiveElement.PE_IndicatorArrowRight and
                isinstance(widget, QMenu)):
            app = QApplication.instance()
            dark = bool(app.property("do_dark_theme")) if app else False
            enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
            selected = bool(option.state & QStyle.StateFlag.State_Selected)
            if not enabled:
                color = QColor("#77777d" if dark else "#a4a7ad")
            elif selected:
                color = QColor("#ffffff")
            else:
                color = QColor("#d5d8de" if dark else "#626872")

            center = option.rect.center()
            half_h = min(4.0, max(3.2, option.rect.height() * 0.22))
            half_w = min(2.8, max(2.2, option.rect.width() * 0.18))
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(
                color, 1.65, Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawLine(
                QPointF(center.x() - half_w, center.y() - half_h),
                QPointF(center.x() + half_w, center.y()))
            painter.drawLine(
                QPointF(center.x() + half_w, center.y()),
                QPointF(center.x() - half_w, center.y() + half_h))
            painter.restore()
            return
        super().drawPrimitive(element, option, painter, widget)


class TabCloseButton(QToolButton):
    """固定逻辑坐标绘制的标签关闭按钮，不受 QIcon/DPI 缓存影响。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._close_color = QColor("#1769aa")

    def setCloseColor(self, color):
        self._close_color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        # 先让当前主题绘制透明/悬停/按下背景，再绘制固定尺寸叉线。
        self.style().drawComplexControl(
            QStyle.ComplexControl.CC_ToolButton, option, painter, self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(
            self._close_color, 1.25, Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        center = self.rect().center()
        # 保持点击区域易用，但叉线本体只占 6x6 逻辑像素；在 150%/200%
        # 缩放下也不会显得像工具栏图标一样大。
        half = 3.0
        painter.drawLine(
            QPointF(center.x() - half, center.y() - half),
            QPointF(center.x() + half, center.y() + half))
        painter.drawLine(
            QPointF(center.x() + half, center.y() - half),
            QPointF(center.x() - half, center.y() + half))


class SortableToolBar(QToolBar):
    """支持拖动按钮调整顺序的工具栏；按钮溢出时自动显示 >> 下拉框。"""

    orderChanged = Signal()
    BUTTON_SIZE = QSize(80, 62)
    # 收窄按钮以显示更多功能；图标与文字高度保持不变，较长的
    # “删除当前页”等五字名称仍能在 80px 宽度内完整显示。
    ICON_SIZE = QSize(32, 24)

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
        # 覆盖部分 Windows/Qt 样式强制绘制的工具栏边缘高光。
        dark = theme.is_dark(getattr(self.window(), "theme_mode", "system"))
        painter = QPainter(self)
        color = QColor("#232529" if dark else "#f0f2f5")
        painter.fillRect(0, 0, self.width(), 2, color)
        painter.fillRect(0, max(0, self.height() - 2), self.width(), 2, color)
        # 两个 QToolBar 并排时 Windows 样式会在交界处强制画出一条
        # 明暗边线。将各自交界边缘恢复为工具栏底色；子按钮随后绘制，
        # 因而悬停和选中背景仍可无缝延伸到边缘。
        if self.objectName() == "fileToolBar":
            painter.fillRect(max(0, self.width() - 2), 0, 2,
                             self.height(), color)
        elif self.objectName() == "editToolBar":
            painter.fillRect(0, 0, 2, self.height(), color)

    def _install_button_filters(self):
        for btn in self.findChildren(QToolButton):
            if btn.objectName() == "qt_toolbar_ext_button":
                btn.setFixedWidth(0)
                btn.hide()
                continue
            if btn.objectName() == "toolbar_more_btn":
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
            btn.setFixedSize(self.BUTTON_SIZE)
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
        localized_app_name = i18n.tr("app_name", cfg.APP_NAME)
        about_title = i18n.tr("about_title").format(app=localized_app_name)
        self.setWindowTitle(about_title)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.setFixedWidth(460)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        title_bar = DialogTitleBar(self)
        title_bar.setObjectName("aboutTitleBar")
        title_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        title_bar.setFixedHeight(46)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(14, 0, 8, 0)
        title_layout.setSpacing(9)

        icon_label = QLabel(title_bar)
        icon_label.setObjectName("aboutTitleIcon")
        icon_label.setFixedSize(26, 26)
        icon_label.setPixmap(self.windowIcon().pixmap(24, 24))
        icon_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        title_layout.addWidget(icon_label)

        title_label = QLabel(about_title, title_bar)
        title_label.setObjectName("aboutTitleText")
        title_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        title_layout.addWidget(title_label, 1)

        close_button = QToolButton(title_bar)
        close_button.setObjectName("aboutCloseButton")
        close_button.setText("×")
        close_button.setToolTip(i18n.tr("dialog_close"))
        close_button.setFixedSize(34, 32)
        close_button.clicked.connect(self.reject)
        title_layout.addWidget(close_button)
        self._apply_header_theme(
            title_bar, title_label, close_button,
            theme.is_dark(getattr(parent, "theme_mode", "system")))
        outer.addWidget(title_bar)

        body = QWidget(self)
        body.setObjectName("aboutBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(32, 26, 32, 22)
        body_layout.setSpacing(20)

        hero = QWidget(body)
        hero.setObjectName("aboutHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(0, 0, 0, 0)
        hero_layout.setSpacing(18)

        app_icon = QLabel(hero)
        app_icon.setObjectName("aboutAppIcon")
        app_icon.setFixedSize(68, 68)
        app_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        app_icon.setPixmap(self.windowIcon().pixmap(48, 48))
        hero_layout.addWidget(app_icon)

        identity = QVBoxLayout()
        identity.setContentsMargins(0, 3, 0, 3)
        identity.setSpacing(5)
        app_name = QLabel(localized_app_name, hero)
        app_name.setObjectName("aboutAppName")
        version = QLabel(
            i18n.tr("about_version").format(version=cfg.APP_VERSION), hero)
        version.setObjectName("aboutVersion")
        summary = QLabel(i18n.tr("about_summary"), hero)
        summary.setObjectName("aboutSummary")
        identity.addWidget(app_name)
        identity.addWidget(version)
        identity.addStretch(1)
        identity.addWidget(summary)
        hero_layout.addLayout(identity, 1)
        body_layout.addWidget(hero)

        divider = QFrame(body)
        divider.setObjectName("aboutDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        body_layout.addWidget(divider)

        details = QWidget(body)
        details.setObjectName("aboutDetails")
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(18, 14, 18, 14)
        details_layout.setSpacing(11)

        def add_detail(label_text, value_text, selectable=False):
            row = QWidget(details)
            row.setObjectName("aboutDetailRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(16)
            label = QLabel(label_text, row)
            label.setObjectName("aboutMetaLabel")
            label.setFixedWidth(72)
            value = QLabel(value_text, row)
            value.setObjectName("aboutMetaValue")
            if selectable:
                value.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse)
            row_layout.addWidget(label)
            row_layout.addWidget(value, 1)
            details_layout.addWidget(row)

        add_detail(i18n.tr("about_developer"), cfg.DEVELOPER)
        add_detail(i18n.tr("about_email"), cfg.DEVELOPER_EMAIL, selectable=True)
        add_detail(i18n.tr("about_framework"), "PySide6 · PyMuPDF")
        body_layout.addWidget(details)

        footer = QHBoxLayout()
        footer.setSpacing(12)
        copyright_label = QLabel(cfg.COPYRIGHT, body)
        copyright_label.setObjectName("aboutCopyright")
        footer.addWidget(copyright_label)
        footer.addStretch(1)

        ok_button = QPushButton(i18n.tr("confirm"), body)
        ok_button.setObjectName("primaryButton")
        ok_button.setDefault(True)
        ok_button.setFixedSize(92, 34)
        ok_button.clicked.connect(self.accept)
        reward_button = QPushButton(i18n.tr("reward_title"), body)
        reward_button.setObjectName("rewardButton")
        reward_button.setFixedSize(112, 34)
        reward_button.clicked.connect(self._show_reward)
        footer.addWidget(reward_button)
        footer.addWidget(ok_button)
        body_layout.addLayout(footer)
        outer.addWidget(body)

    def _show_reward(self):
        from reward_dialog import RewardDialog
        d = RewardDialog(self)
        d.exec()

    @staticmethod
    def _apply_header_theme(title_bar, title_label, close_button, dark):
        """显式同步“关于”标题栏，避免继承到切换前的全局样式。"""
        title_bar.setProperty("do_theme_dark", dark)
        if dark:
            title_bar.setStyleSheet(
                "QWidget#aboutTitleBar { background: #242426; border: none; "
                "border-bottom: 1px solid #3a3a3c; }"
                "QLabel#aboutTitleText { color: #f5f5f7; font-size: 11pt; "
                "font-weight: 600; }"
                "QToolButton#aboutCloseButton { background: transparent; "
                "border: none; color: #d1d1d6; font-family: 'Segoe UI'; "
                "font-size: 20px; padding: 0; }"
                "QToolButton#aboutCloseButton:hover { background: #e5484d; "
                "color: #ffffff; }")
        else:
            title_bar.setStyleSheet(
                "QWidget#aboutTitleBar { background: #f7f7f9; border: none; "
                "border-bottom: 1px solid #d9dde3; }"
                "QLabel#aboutTitleText { color: #1d1d1f; font-size: 11pt; "
                "font-weight: 600; }"
                "QToolButton#aboutCloseButton { background: transparent; "
                "border: none; color: #3a3a3c; font-family: 'Segoe UI'; "
                "font-size: 20px; padding: 0; }"
                "QToolButton#aboutCloseButton:hover { background: #e5484d; "
                "color: #ffffff; }")
        title_label.ensurePolished()
        close_button.ensurePolished()
        title_bar.update()


class PdfSecurityDialog(QDialog):
    """设置 AES-256 密码与 PDF 使用权限。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置 PDF 密码")
        self.setModal(True)
        self.setMinimumWidth(470)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(16)

        intro = QLabel(
            "使用 AES-256 加密。打开密码用于查看文档；所有者密码用于管理权限。",
            self)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        self.user_password = QLineEdit(self)
        self.user_password.setPlaceholderText("可留空：无需密码即可打开")
        self.user_confirm = QLineEdit(self)
        self.owner_password = QLineEdit(self)
        self.owner_password.setPlaceholderText("必填，用于修改或移除保护")
        self.owner_confirm = QLineEdit(self)
        for edit in (self.user_password, self.user_confirm,
                     self.owner_password, self.owner_confirm):
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.setMaxLength(40)
        form.addRow("打开密码：", self.user_password)
        form.addRow("确认打开密码：", self.user_confirm)
        form.addRow("所有者密码：", self.owner_password)
        form.addRow("确认所有者密码：", self.owner_confirm)
        layout.addLayout(form)

        self.show_passwords = QCheckBox("显示密码", self)
        self.show_passwords.toggled.connect(self._toggle_passwords)
        layout.addWidget(self.show_passwords)

        permissions = QGroupBox("允许的操作", self)
        permission_layout = QVBoxLayout(permissions)
        self.allow_print = QCheckBox("打印", permissions)
        self.allow_copy = QCheckBox("复制文字和图片", permissions)
        self.allow_modify = QCheckBox("编辑文档与页面", permissions)
        self.allow_annotate = QCheckBox("添加批注和签名", permissions)
        for checkbox in (self.allow_print, self.allow_copy,
                         self.allow_modify, self.allow_annotate):
            checkbox.setChecked(True)
            permission_layout.addWidget(checkbox)
        layout.addWidget(permissions)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消", self)
        confirm = QPushButton("应用", self)
        confirm.setObjectName("primaryButton")
        confirm.setDefault(True)
        cancel.clicked.connect(self.reject)
        confirm.clicked.connect(self._validate_and_accept)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)

    def _toggle_passwords(self, shown):
        mode = (QLineEdit.EchoMode.Normal if shown else
                QLineEdit.EchoMode.Password)
        for edit in (self.user_password, self.user_confirm,
                     self.owner_password, self.owner_confirm):
            edit.setEchoMode(mode)

    def _validate_and_accept(self):
        user_pw = self.user_password.text()
        owner_pw = self.owner_password.text()
        if user_pw != self.user_confirm.text():
            QMessageBox.warning(self, "密码不一致", "两次输入的打开密码不一致。")
            self.user_confirm.setFocus()
            return
        if not owner_pw:
            QMessageBox.warning(self, "缺少密码", "必须设置所有者密码。")
            self.owner_password.setFocus()
            return
        if owner_pw != self.owner_confirm.text():
            QMessageBox.warning(self, "密码不一致", "两次输入的所有者密码不一致。")
            self.owner_confirm.setFocus()
            return
        if user_pw and user_pw == owner_pw:
            QMessageBox.warning(
                self, "密码重复", "打开密码和所有者密码应设置为不同内容。")
            self.owner_password.setFocus()
            return
        self.accept()

    def values(self):
        permissions = backend.pdf_permissions(
            self.allow_print.isChecked(), self.allow_copy.isChecked(),
            self.allow_modify.isChecked(), self.allow_annotate.isChecked())
        return self.user_password.text(), self.owner_password.text(), permissions


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


class OcrWorker(QThread):
    """在独立 PDF 快照上运行 OCR，避免阻塞或跨线程访问界面文档。"""

    progress = Signal(int, int)
    completed = Signal(object)
    failed = Signal(str)
    canceled = Signal()

    def __init__(self, pdf_bytes, pages, parent=None):
        super().__init__(parent)
        self.pdf_bytes = pdf_bytes
        self.pages = list(pages)

    def run(self):
        doc = None
        try:
            import pymupdf
            doc = pymupdf.open(stream=self.pdf_bytes, filetype="pdf")
            engine = backend.create_ocr_engine()
            results = []
            total = len(self.pages)
            for index, pno in enumerate(self.pages, 1):
                if self.isInterruptionRequested():
                    self.canceled.emit()
                    return
                lines = backend.recognize_page_ocr(engine, doc, pno)
                results.append({"page": pno, "lines": lines})
                self.progress.emit(index, total)
            if self.isInterruptionRequested():
                self.canceled.emit()
            else:
                self.completed.emit(results)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            if doc is not None:
                doc.close()


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
        self.sidebar_default_visible = self.settings.value(
            "sidebar_default_visible", True, type=bool)
        i18n.set_lang(self.settings.value("language", "zh"))
        self.setWindowTitle(i18n.tr("app_name", cfg.APP_NAME))
        self._icon_color = icons.icon_color_for_dark(theme.is_dark(self.theme_mode))
        self._word_workers = []
        self._ocr_worker = None
        self._ocr_progress = None
        self._ocr_target_view = None
        self._menu_arrow_style = RoundedMenuArrowStyle()
        # 监听整个应用内新出现的弹窗，统一同步 Windows 标题栏主题。
        QApplication.instance().installEventFilter(self)

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
        # 禁用 Qt 自动关闭按钮，完全由应用管理。原生按钮会在标题更新时
        # 被 Windows 样式重建，并与自定义按钮叠加成左右两个小叉。
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

    def current_view(self):
        return self.tabs.currentWidget()

    def _fit_window_to_document(self, page_w, page_h):
        """打开文档后按页面方向调整主窗口宽高比：竖版文件窗口瘦高，
        横版文件窗口宽扁。保持窗口面积近似不变，且不超出屏幕可用区域，
        调整后窗口居中显示（后续用户可随意拖动，不再干预）。"""
        view = self.current_view()
        if view is None or page_w <= 0 or page_h <= 0:
            return
        # 全屏/最大化状态下不改变窗口形态，避免打断用户的展示场景。
        if self.isFullScreen() or self.isMaximized():
            return
        screen = QApplication.primaryScreen()
        screen_geo = screen.availableGeometry() if screen else None
        area = max(400000.0, float(self.width() * self.height()))
        # 页面宽高比限制在合理范围，避免窗口过于极端。
        aspect = max(0.55, min(1.9, page_w / page_h))
        w = int((area * aspect) ** 0.5)
        h = int((area / aspect) ** 0.5)
        if screen_geo is not None:
            sw = max(760, screen_geo.width() - 40)
            sh = max(560, screen_geo.height() - 40)
            if w > sw or h > sh:
                scale = min(sw / w, sh / h)
                w = int(w * scale)
                h = int(h * scale)
        w = max(760, w)
        h = max(560, h)
        # 同方向的文档（如竖版→竖版）不重新调整窗口与位置，保留用户
        # 已拖放的位置；仅当文档方向变化（竖版↔横版）时才调整窗口形态。
        orientation = "portrait" if aspect < 1.0 else "landscape"
        if orientation == getattr(self, "_last_doc_orientation", None):
            return
        self._last_doc_orientation = orientation
        # 程序主动调整窗口：抑制 resizeEvent 的宽度适配，布局稳定后
        # 统一执行整页适配，保证打开后页面完整显示。
        view._suppress_resize_fit = True
        # 已显示的窗口：用动画平滑过渡窗口形态（横↔竖），避免瞬间跳变。
        if screen_geo is not None:
            x = screen_geo.x() + (screen_geo.width() - w) // 2
            if aspect < 1.0:
                y = screen_geo.y() + int(screen_geo.height() * 0.08)
                y = min(y, screen_geo.y() + screen_geo.height() - h - 20)
            else:
                y = screen_geo.y() + (screen_geo.height() - h) // 2
            target = QRect(x, y, w, h)
        else:
            target = None

        if (self.isVisible() and target is not None
                and self.geometry() != target):
            if getattr(self, "_orientation_anim", None) is not None:
                self._orientation_anim.stop()
            self._orientation_anim = QPropertyAnimation(
                self, b"geometry", self)
            self._orientation_anim.setDuration(220)
            self._orientation_anim.setEasingCurve(
                QEasingCurve.Type.OutCubic)
            self._orientation_anim.setStartValue(self.geometry())
            self._orientation_anim.setEndValue(target)
            self._orientation_anim.finished.connect(
                lambda v=view: self._after_orientation_change(v))
            self._orientation_anim.start()
            return
        self.resize(w, h)
        if target is not None:
            self.move(x, y)
        QTimer.singleShot(60, lambda v=view: self._after_orientation_change(v))

    def _after_orientation_change(self, view):
        """窗口形态调整完成后：恢复适配、统一整页显示。"""
        view._suppress_resize_fit = False
        # 停掉本次调整触发的适宽定时器，避免其随后覆盖整页适配。
        view._window_fit_timer.stop()
        if view.doc is not None:
            view.fit_page()
        # 同步视口尺寸基准，防止下一次 resizeEvent 重复触发适配。
        view._last_viewport_w = view.scroll.viewport().width()
        view._last_viewport_h = view.scroll.viewport().height()

    def _new_tab(self):
        view = DocumentView()
        view.openRequested.connect(self.open_pdf)
        view.statusMessage.connect(self._on_status)
        view.titleChanged.connect(lambda t, v=view: self._update_tab_title(v, t))
        view.pageChanged.connect(self._on_page_changed)
        view.securityChanged.connect(
            lambda v=view: self._sync_security_actions(v)
            if v is self.current_view() else None)
        view.undoAvailableChanged.connect(
            lambda _available, v=view: self._sync_undo_action(v)
            if v is self.current_view() else None)
        view.ocrRequested.connect(
            lambda pno, v=view: self.ocr_page(v, pno))
        view.pageOrientationChanged.connect(
            lambda pw, ph, v=view: self._fit_window_to_document(pw, ph)
            if v is self.current_view() else None)
        idx = self.tabs.addTab(view, i18n.tr("untitled"))
        view.set_sidebar_visible(self.sidebar_default_visible)
        self._style_tab_close_button(idx)
        # Qt 在加入第一个自定义标签按钮时可能重新继承系统字体。
        self._apply_ui_fonts()
        self.tabs.setCurrentIndex(idx)
        self._sync_mode_buttons(view)
        self._sync_security_actions(view)
        self._sync_undo_action(view)
        return view

    def _style_tab_close_button(self, index):
        """用主题一致的细线图标替换 Qt 默认标签关闭按钮。"""
        tab_bar = self.tabs.tabBar()
        left_pos = QTabBar.ButtonPosition.LeftSide
        right_pos = QTabBar.ButtonPosition.RightSide

        # 左侧永远不允许出现关闭按钮；清理旧版本留下的自定义按钮以及
        # Windows 样式可能生成的原生小叉。
        left_button = tab_bar.tabButton(index, left_pos)
        if left_button is not None:
            tab_bar.setTabButton(index, left_pos, None)
            left_button.deleteLater()

        existing = tab_bar.tabButton(index, right_pos)
        if isinstance(existing, TabCloseButton) and \
                existing.objectName() == "tabCloseButton":
            button = existing
        else:
            if existing is not None:
                tab_bar.setTabButton(index, right_pos, None)
                existing.deleteLater()
            view = self.tabs.widget(index)
            button = TabCloseButton(tab_bar)
            button.clicked.connect(
                lambda checked=False, v=view: self._close_tab_for_view(v))
            tab_bar.setTabButton(index, right_pos, button)
        button.setObjectName("tabCloseButton")
        # 自定义 QToolButton 上使用居中的矢量细线叉；既避开 Windows
        # 原生红色方形底板，也不会受字体字形和基线差异影响。
        dark = theme.is_dark(getattr(self, "theme_mode", "system"))
        close_color = "#72b4ff" if dark else "#1769aa"
        button.setText("")
        button.setIcon(QIcon())
        button.setCloseColor(close_color)
        button.setFixedSize(16, 16)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip("关闭标签页")

    def _close_tab_for_view(self, view):
        """关闭自定义标签按钮所属的页面，兼容标签拖动后的索引变化。"""
        index = self.tabs.indexOf(view)
        if index >= 0:
            self._close_tab(index)

    def _update_tab_title(self, view, title):
        idx = self.tabs.indexOf(view)
        if idx >= 0:
            self.tabs.setTabText(idx, title)
            # Windows 样式在标签文字由“未命名”变为文件名时，可能重新
            # 创建一个原生小型关闭按钮，而且重建可能发生在缩略图与页面
            # 布局完成之后。覆盖多个布局阶段重装自定义按钮，不能再依赖
            # 用户切换主题来触发恢复。
            self._schedule_tab_close_restyle(view)
            if view is self.current_view():
                self.setWindowTitle(
                    f"{i18n.tr('app_name', cfg.APP_NAME)} — {title}")

    def _schedule_tab_close_restyle(self, view):
        self._restyle_tab_close_for_view(view)
        for delay in (0, 40, 120, 280, 600):
            QTimer.singleShot(
                delay, lambda v=view: self._restyle_tab_close_for_view(v))

    def _restyle_tab_close_for_view(self, view):
        # 标签可能在延迟重绘计时器触发前已被关闭并销毁。
        try:
            idx = self.tabs.indexOf(view)
        except RuntimeError:
            return
        if idx >= 0:
            self._style_tab_close_button(idx)

    def _on_tab_changed(self, idx):
        view = self.tabs.widget(idx)
        if view:
            self._sync_mode_buttons(view)
            self._sync_security_actions(view)
            self._sync_undo_action(view)
            self._schedule_tab_close_restyle(view)
            if view.file_path:
                self.setWindowTitle(
                    f"{i18n.tr('app_name', cfg.APP_NAME)} — "
                    f"{os.path.basename(view.file_path)}")
            else:
                self.setWindowTitle(i18n.tr("app_name", cfg.APP_NAME))
        else:
            self._sync_security_actions(None)
            self._sync_undo_action(None)

    def _sync_mode_buttons(self, view):
        for k, act in self.mode_actions.items():
            act.setChecked(k == view.current_mode)

    def _sync_undo_action(self, view):
        if "undo" in self.act:
            self.act["undo"].setEnabled(bool(
                view and view.doc is not None and view.can_undo()))

    def _perform_undo(self):
        """文本输入控件优先撤销输入，其余情况撤销当前 PDF 编辑。"""
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit):
            focus.undo()
            return
        view = self.current_view()
        if view:
            view.undo()

    def _sync_security_actions(self, view):
        """根据 PDF 权限同步菜单、工具栏和快捷入口。"""
        has_doc = bool(view and view.doc is not None)

        def allowed(permission):
            return has_doc and view.permission_allowed(permission)

        can_print = allowed(pymupdf.PDF_PERM_PRINT)
        can_copy = allowed(pymupdf.PDF_PERM_COPY)
        can_modify = allowed(pymupdf.PDF_PERM_MODIFY)
        can_annotate = allowed(pymupdf.PDF_PERM_ANNOTATE)
        can_assemble = allowed(pymupdf.PDF_PERM_ASSEMBLE)

        self.act["print"].setEnabled(can_print)
        self.act["copy_all"].setEnabled(can_copy)
        for key in ("image", "watermark", "delete_page"):
            self.act[key].setEnabled(can_modify)
        for key in ("sign", "sign_lib", "annotation"):
            self.act[key].setEnabled(can_annotate)
        self.act["edit_color"].setEnabled(can_modify or can_annotate)
        for key in ("split_every", "split_ranges", "extract"):
            self.act[key].setEnabled(can_assemble)
        for key in ("ocr_current", "ocr_all", "ocr_toolbar"):
            self.act[key].setEnabled(can_modify and can_copy)
        for key in ("security_set", "security_remove", "security_status"):
            self.act[key].setEnabled(has_doc)
        # 无文档时这几个动作也跟随整体灰度：保存、适合宽度、侧边栏、幻灯片。
        for key in ("save", "fit_width", "sidebar", "slideshow"):
            self.act[key].setEnabled(has_doc)

        mode_permissions = {
            "text_select": can_copy,
            "replace_text": can_modify,
            "text": can_modify,
            "highlight": can_annotate,
            "underline": can_annotate,
            "strikeout": can_annotate,
            "rect": can_annotate,
            "line": can_annotate,
            "ink": can_annotate,
        }
        self.mode_actions["view"].setEnabled(has_doc)
        for key, enabled in mode_permissions.items():
            self.mode_actions[key].setEnabled(enabled)
        if has_doc and view.current_mode in mode_permissions and \
                not mode_permissions[view.current_mode]:
            view.set_mode("view")
            self._sync_mode_buttons(view)

        if has_doc and view._source_encrypted:
            if view._auth_level & 4:
                self.statusBar().showMessage(
                    "已用所有者密码打开：拥有完整管理权限", 5000)
            else:
                blocked = []
                for label, enabled in (("打印", can_print), ("复制", can_copy),
                                       ("编辑", can_modify),
                                       ("批注", can_annotate)):
                    if not enabled:
                        blocked.append(label)
                if blocked:
                    self.statusBar().showMessage(
                        "受保护 PDF：已禁止" + "、".join(blocked), 5000)

    def _on_status(self, msg, timeout):
        self.statusBar().showMessage(msg, timeout)

    def _on_page_changed(self, pno, total):
        if total > 0:
            self.page_label.setText(
                i18n.tr("page_status").format(p=pno + 1, t=total))
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
            self._update_tab_title(view, i18n.tr("untitled"))
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

        mk("undo", None, "撤销", shortcut=QKeySequence.StandardKey.Undo,
           triggered=self._perform_undo)
        a["undo"].setEnabled(False)

        mk("zoom_in", "zoom_in", "放大", shortcut=QKeySequence.StandardKey.ZoomIn,
           triggered=lambda: self.current_view().zoom_in())
        mk("zoom_out", "zoom_out", "缩小", shortcut=QKeySequence.StandardKey.ZoomOut,
           triggered=lambda: self.current_view().zoom_out())
        mk("fit_width", "fit_width", "适合宽度",
           triggered=lambda: self.current_view().fit_width())
        mk("sidebar", "sidebar", "侧边栏", triggered=self._toggle_sidebar)
        mk("sidebar_default", None, "启动时显示侧边栏", checkable=True,
           toggled=self._set_sidebar_default)
        a["sidebar_default"].setChecked(self.sidebar_default_visible)

        mk("delete_page", "trash", "删除当前页",
           triggered=lambda: self.current_view().delete_current_page())
        mk("merge", "merge", "合并 PDF", triggered=self.merge_pdfs)
        mk("split_every", "split", "每 N 页拆分", triggered=self.split_every_n)
        mk("split_ranges", None, "按页码范围拆分", triggered=self.split_by_ranges)
        mk("extract", None, "提取指定页", triggered=self.extract_pages)
        mk("watermark", "watermark", "添加水印", triggered=self.add_watermark)
        mk("ocr_current", "ocr", "识别当前页面",
           triggered=self.ocr_current_page)
        mk("ocr_all", "ocr_all", "识别全部页面",
           triggered=self.ocr_all_pages)
        mk("ocr_toolbar", "ocr", "OCR识别",
           triggered=self.ocr_current_page)
        mk("security_set", None, "设置密码", triggered=self.set_pdf_security)
        mk("security_remove", None, "删除密码", triggered=self.remove_pdf_security)
        mk("security_status", None, "查看加密状态",
           triggered=self.show_pdf_security_status)
        mk("copy_all", None, "复制本页全部文字",
           triggered=lambda: self.current_view().copy_page_text())
        mk("image", "image", "插入图片",
           triggered=lambda: self.current_view().start_image())
        mk("annotation", "annotation", "批注",
           triggered=lambda: self.current_view().start_note())
        mk("edit_color", "color", "编辑颜色", triggered=self._pick_color)
        mk("sign", "sign", "签名设计",
           triggered=lambda: self.current_view().start_sign())
        mk("sign_lib", "library", "签名库",
           triggered=lambda: self.current_view().open_sign_lib())
        mk("fullscreen", None, "全屏", triggered=self.toggle_fullscreen)
        mk("slideshow", "slideshow", "幻灯片", shortcut="F5",
           triggered=lambda: self.current_view().start_slideshow())
        mk("about", None, "关于", triggered=self.about)
        mk("star_us", None, "给个 Star", triggered=self._open_repo_url)
        mk("feedback", None, "反馈建议", triggered=self._open_feedback_url)
        mk("check_update", None, "检查更新", triggered=self._check_update_now)
        mk("reward", None, "支持作者", triggered=self._show_reward_from_menu)

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
        if self.isFullScreen():
            self.toggle_fullscreen()
            return
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
        default_file = ["save", "fit_width", "sidebar", "slideshow"]
        mode_keys = [k for k, _l, _vm, _i in MODE_DEFS[1:]]
        insert_at = mode_keys.index("replace_text") + 1
        default_edit = mode_keys[:insert_at] + ["sign", "sign_lib"] + \
            mode_keys[insert_at:]
        default_edit.insert(default_edit.index("text"), "watermark")
        default_edit += ["edit_color", "image", "annotation",
                         "ocr_toolbar", "delete_page"]
        saved_raw = self.settings.value("toolbar_order", None)
        saved = None
        if saved_raw:
            try:
                saved = json.loads(saved_raw)
            except Exception:
                saved = None

        # 分版本迁移旧布局；每项只执行一次，之后继续尊重用户拖动顺序。
        order_version = self.settings.value(
            "toolbar_order_version", 0, type=int)
        migrated = False
        if saved and order_version < 1:
            edit = list(saved.get("edit") or [])
            if "replace_text" in edit:
                for key in ("sign", "sign_lib"):
                    if key in edit:
                        edit.remove(key)
                at = edit.index("replace_text") + 1
                edit[at:at] = ["sign", "sign_lib"]
                saved["edit"] = edit
                migrated = True
        if saved and order_version < 2:
            file_items = list(saved.get("file") or [])
            edit = list(saved.get("edit") or [])
            for key in ("watermark", "ocr_toolbar"):
                if key in file_items:
                    file_items.remove(key)
                if key in edit:
                    edit.remove(key)
            if "text" in edit:
                edit.insert(edit.index("text"), "watermark")
            else:
                edit.append("watermark")
            if "image" in edit:
                edit.insert(edit.index("image") + 1, "ocr_toolbar")
            else:
                edit.append("ocr_toolbar")
            saved["file"] = file_items
            saved["edit"] = edit
            migrated = True
        if saved and order_version < 3:
            edit = list(saved.get("edit") or [])
            if "annotation" in edit:
                edit.remove("annotation")
            if "image" in edit:
                edit.insert(edit.index("image") + 1, "annotation")
            else:
                edit.append("annotation")
            saved["edit"] = edit
            migrated = True
        self.settings.setValue("toolbar_order_version", 3)
        if migrated:
            self.settings.setValue("toolbar_order", json.dumps(saved))

        # 第一行：文件/工具
        self.tb1 = SortableToolBar("文件", self)
        self.tb1.setObjectName("fileToolBar")
        self.tb1.setIconSize(SortableToolBar.ICON_SIZE)
        self.tb1.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.tb1.orderChanged.connect(self._toolbar_order_changed)
        self.addToolBar(self.tb1)
        file_order = list((saved.get("file") if saved else None) or default_file)
        # 水印已迁入编辑功能区；合并与按页拆分只保留在工具菜单。
        # 始终过滤旧布局，避免历史顺序把这些按钮重新带回文件功能区。
        file_toolbar_exclusions = {"watermark", "merge", "split_every"}
        file_order = [
            key for key in file_order if key not in file_toolbar_exclusions]
        file_order = list(dict.fromkeys(file_order))
        for key in default_file:  # 补齐默认顺序里新增的按钮
            if key not in file_order:
                file_order.append(key)
        for key in file_order:
            if key in self.act:
                self.tb1.addAction(self.act[key])

        # 第二行：编辑
        self.tb2 = SortableToolBar("编辑", self)
        self.tb2.setObjectName("editToolBar")
        self.tb2.setIconSize(SortableToolBar.ICON_SIZE)
        self.tb2.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.tb2.orderChanged.connect(self._toolbar_order_changed)
        self.addToolBar(self.tb2)
        edit_order = list((saved.get("edit") if saved else None) or default_edit)
        # 清理历史设置中可能保存的重复项；一个 QAction 在功能区只出现一次。
        edit_order = list(dict.fromkeys(edit_order))
        for key in default_edit:  # 补齐默认顺序里新增的按钮
            if key not in edit_order:
                if key == "watermark" and "text" in edit_order:
                    edit_order.insert(edit_order.index("text"), key)
                elif key == "ocr_toolbar" and "image" in edit_order:
                    edit_order.insert(edit_order.index("image") + 1, key)
                elif key == "annotation" and "image" in edit_order:
                    edit_order.insert(edit_order.index("image") + 1, key)
                elif key == "edit_color" and "image" in edit_order:
                    edit_order.insert(edit_order.index("image"), key)
                else:
                    edit_order.append(key)
        for key in edit_order:
            if key in self.mode_actions:
                self.tb2.addAction(self.mode_actions[key])
            elif key in self.act:
                self.tb2.addAction(self.act[key])

        # 两个工具栏及按钮均使用零横向间距，不再绘制交界补偿条。
        self.toolbar_seam_cover = QWidget(self)
        self.toolbar_seam_cover.setObjectName("toolbarSeamCover")
        self.toolbar_seam_cover.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.toolbar_seam_cover.setFixedWidth(0)
        self.toolbar_seam_cover.hide()

        # 独立溢出入口使用普通 QMenu，确保菜单背景与当前主题同步。
        self.more_tools_menu = QMenu(self)
        self.more_tools_menu.setObjectName("toolbarOverflowMenu")
        self.more_tools_menu.aboutToShow.connect(self._refresh_more_tools_menu)

        self.more_tools_btn = QToolButton(self.tb2)
        self.more_tools_btn.setObjectName("toolbar_more_btn")
        self.more_tools_btn.setText("")
        self.more_tools_btn.setIcon(
            icons.get("more_down", self._icon_color))
        self.more_tools_btn.setIconSize(QSize(20, 20))
        self.more_tools_btn.setToolTip("更多工具")
        self.more_tools_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_tools_btn.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_tools_btn.setMenu(self.more_tools_menu)
        self.more_tools_btn.setAutoRaise(True)
        self.more_tools_btn.setFixedSize(32, 30)
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
        self.toolbar_seam_cover.hide()
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
        toolbar_font.setPointSizeF(9.5)
        toolbar_font.setWeight(QFont.Weight.Medium)
        toolbar_font.setHintingPreference(
            QFont.HintingPreference.PreferVerticalHinting)
        toolbar_font.setStyleStrategy(
            QFont.StyleStrategy.PreferAntialias |
            QFont.StyleStrategy.NoSubpixelAntialias)
        toolbar_font.setKerning(True)
        self.tb1.setFont(toolbar_font)
        self.tb2.setFont(toolbar_font)

        # 标签文字独立缩小，避免“未命名/文件名”在紧凑标签栏里显得突兀。
        tab_font = QFont("Microsoft YaHei UI")
        tab_font.setPointSizeF(8.0)
        tab_font.setWeight(QFont.Weight.Normal)
        tab_font.setHintingPreference(
            QFont.HintingPreference.PreferVerticalHinting)
        tab_font.setStyleStrategy(
            QFont.StyleStrategy.PreferAntialias |
            QFont.StyleStrategy.NoSubpixelAntialias)
        self.tabs.tabBar().setFont(tab_font)

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
        self._m_edit.addAction(self.act["undo"])
        self._m_edit.addSeparator()
        for key, _l, _vm, _i in MODE_DEFS:
            self._m_edit.addAction(self.mode_actions[key])
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
        self._m_tools.addAction(self.act["annotation"])
        self._m_tools.addSeparator()
        self._m_signature_tools = self._m_tools.addMenu(i18n.tr("sign_title"))
        self._m_signature_tools.addAction(self.act["sign"])
        self._m_signature_tools.addAction(self.act["sign_lib"])
        self._m_tools.addSeparator()
        self._m_ocr = self._m_tools.addMenu(i18n.tr("menu_ocr"))
        self._m_ocr.addAction(self.act["ocr_current"])
        self._m_ocr.addAction(self.act["ocr_all"])

        self._m_sign = self.menuBar().addMenu(i18n.tr("menu_sign"))
        self._m_sign.addAction(self.act["security_set"])
        self._m_sign.addAction(self.act["security_remove"])
        self._m_sign.addSeparator()
        self._m_sign.addAction(self.act["security_status"])

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
        self._m_view.addAction(self.act["sidebar_default"])
        self._m_view.addAction(self.act["fullscreen"])
        self._m_view.addAction(self.act["slideshow"])

        self._m_help = self.menuBar().addMenu(i18n.tr("menu_help"))
        self._m_help.addAction(self.act["check_update"])
        self._m_help.addSeparator()
        self._m_help.addAction(self.act["star_us"])
        self._m_help.addAction(self.act["feedback"])
        self._m_help.addAction(self.act["reward"])
        self._m_help.addSeparator()
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
        self._m_signature_tools.setTitle(i18n.tr("sign_title"))
        self._m_ocr.setTitle(i18n.tr("menu_ocr"))
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
            self.btn_search.setText(i18n.tr("search"))
            self.btn_search.setToolTip(i18n.tr("search"))
            self.btn_search_prev.setToolTip(i18n.tr("search_prev"))
            self.btn_search_next.setToolTip(i18n.tr("search_next"))
        if hasattr(self, "more_tools_btn"):
            self.more_tools_btn.setToolTip(i18n.tr("more_tools"))
        for index in range(self.tabs.count()):
            view = self.tabs.widget(index)
            if isinstance(view, DocumentView):
                view.apply_language()
                if view.file_path is None:
                    self.tabs.setTabText(index, i18n.tr("untitled"))
        current = self.current_view()
        if current and current.doc is not None:
            self._on_page_changed(
                current.page_view.current_page(), len(current.doc))
        self._on_tab_changed(self.tabs.currentIndex())

    # ================= OCR =================
    def ocr_current_page(self):
        view = self.current_view()
        if not view or view.doc is None:
            QMessageBox.information(self, i18n.tr("hint"), "请先打开 PDF 文件。")
            return
        self.ocr_page(view, view.page_view.current_page())

    def ocr_page(self, view, pno):
        """识别指定文档视图的指定页面，供工具栏和右键菜单共用。"""
        if not view or view.doc is None:
            return
        if not (view.permission_allowed(pymupdf.PDF_PERM_MODIFY) and
                view.permission_allowed(pymupdf.PDF_PERM_COPY)):
            self.statusBar().showMessage("文档安全设置禁止 OCR 提取或写入文字", 4000)
            return
        pno = max(0, min(int(pno), len(view.doc) - 1))
        existing = backend.extract_text(view.doc, pno)
        if existing:
            answer = QMessageBox.question(
                self, "OCR 文字识别",
                f"第 {pno + 1} 页已经包含可搜索文字。继续识别可能产生重复文字层，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._start_ocr(view, [pno])

    def ocr_all_pages(self):
        view = self.current_view()
        if not view or view.doc is None:
            QMessageBox.information(self, i18n.tr("hint"), "请先打开 PDF 文件。")
            return
        if not (view.permission_allowed(pymupdf.PDF_PERM_MODIFY) and
                view.permission_allowed(pymupdf.PDF_PERM_COPY)):
            self.statusBar().showMessage("文档安全设置禁止 OCR 提取或写入文字", 4000)
            return
        # 全文识别默认跳过已有文字的页面，防止反复执行后叠加重复文字层。
        pages = [pno for pno in range(len(view.doc))
                 if not backend.extract_text(view.doc, pno)]
        skipped = len(view.doc) - len(pages)
        if not pages:
            QMessageBox.information(
                self, "OCR 文字识别", "所有页面都已经包含可搜索文字，无需重复识别。")
            return
        if skipped:
            self.statusBar().showMessage(
                f"已自动跳过 {skipped} 个包含文字的页面", 4000)
        self._start_ocr(view, pages)

    def _start_ocr(self, view, pages):
        if self._ocr_worker is not None and self._ocr_worker.isRunning():
            QMessageBox.information(self, i18n.tr("hint"), "OCR 正在运行，请稍候。")
            return
        try:
            snapshot = view.doc.tobytes(garbage=3, deflate=True)
        except Exception as e:
            QMessageBox.warning(self, "OCR 文字识别", f"无法准备文档：{e}")
            return

        self._ocr_target_view = view
        progress = QProgressDialog("正在准备离线识别…", "取消", 0, len(pages), self)
        progress.setWindowTitle("OCR 文字识别")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        self._ocr_progress = progress

        worker = OcrWorker(snapshot, pages, self)
        self._ocr_worker = worker
        progress.canceled.connect(worker.requestInterruption)
        worker.progress.connect(self._on_ocr_progress)
        worker.completed.connect(self._on_ocr_completed)
        worker.failed.connect(self._on_ocr_failed)
        worker.canceled.connect(self._on_ocr_canceled)
        worker.finished.connect(worker.deleteLater)
        worker.start()
        progress.show()

    def _on_ocr_progress(self, current, total):
        if self._ocr_progress is not None:
            self._ocr_progress.setLabelText(
                i18n.tr("ocr_progress").format(p=current, t=total))
            self._ocr_progress.setValue(current)

    def _finish_ocr_ui(self):
        if self._ocr_progress is not None:
            self._ocr_progress.close()
            self._ocr_progress.deleteLater()
        self._ocr_progress = None
        self._ocr_worker = None

    def _on_ocr_completed(self, results):
        view = self._ocr_target_view
        self._ocr_target_view = None
        self._finish_ocr_ui()
        if view is None or view.doc is None:
            return
        try:
            view.begin_undo_step(document_change=True)
            inserted = backend.add_ocr_text_layer(view.doc, results)
        except Exception as e:
            QMessageBox.warning(self, "OCR 文字识别", f"写入文字层失败：{e}")
            return
        text = "\n\n".join(
            "\n".join(line["text"] for line in item.get("lines", []))
            for item in results).strip()
        if not inserted or not text:
            QMessageBox.information(self, "OCR 文字识别", "未识别到清晰文字。")
            return
        QApplication.clipboard().setText(text)
        view.modified = True
        view._search_results = []
        view.page_view.clear_search_highlights()
        QMessageBox.information(
            self, "OCR 文字识别",
            f"识别完成：共写入 {inserted} 行可搜索文字。\n"
            "识别结果已复制到剪贴板；保存文档即可永久保留文字层。")
        self.statusBar().showMessage(
            f"OCR 完成，已写入 {inserted} 行并复制识别文字", 5000)

    def _on_ocr_failed(self, message):
        self._ocr_target_view = None
        self._finish_ocr_ui()
        QMessageBox.warning(self, "OCR 文字识别", f"识别失败：{message}")

    def _on_ocr_canceled(self):
        self._ocr_target_view = None
        self._finish_ocr_ui()
        self.statusBar().showMessage("OCR 已取消，文档未作修改", 3000)

    # ================= PDF 安全 =================
    def set_pdf_security(self):
        view = self._view_doc()
        if not view:
            return
        dialog = PdfSecurityDialog(self)
        if self._exec_themed_dialog(dialog) != QDialog.DialogCode.Accepted:
            return
        user_pw, owner_pw, permissions = dialog.values()
        view.set_pdf_encryption(user_pw, owner_pw, permissions)
        QMessageBox.information(
            self, "PDF 安全",
            "已设置 AES-256 加密。保存文档后密码与权限设置正式生效。\n\n"
            "请妥善保管所有者密码，遗失后无法由软件恢复。")
        self.statusBar().showMessage("已设置 PDF 加密，保存后生效", 5000)

    def remove_pdf_security(self):
        view = self._view_doc()
        if not view:
            return
        status = view.security_status()
        if status == "plain":
            QMessageBox.information(self, "PDF 安全", "当前文档没有密码保护。")
            return

        if view._source_encrypted and not (view._auth_level & 4):
            owner_pw, ok = QInputDialog.getText(
                self, "验证所有者密码",
                "移除 PDF 保护需要输入所有者密码：",
                QLineEdit.EchoMode.Password)
            if not ok:
                return
            auth_level = int(view.doc.authenticate(owner_pw))
            if not (auth_level & 4):
                QMessageBox.warning(self, "验证失败", "所有者密码不正确。")
                return
            view._auth_level = auth_level
            view._open_password = owner_pw

        answer = QMessageBox.question(
            self, "删除 PDF 密码",
            "确定在下次保存时移除打开密码和全部权限限制吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        view.remove_pdf_encryption()
        self.statusBar().showMessage("已设置移除 PDF 密码，保存后生效", 5000)

    def show_pdf_security_status(self):
        view = self._view_doc()
        if not view:
            return
        status = view.security_status()
        if status == "pending_encrypt":
            permissions = int(view._security_options.get("permissions", 0))
            headline = "已设置 AES-256 加密（保存后生效）"
        elif status == "pending_remove":
            QMessageBox.information(
                self, "PDF 安全状态", "已设置删除密码，保存文档后生效。")
            return
        elif status == "plain":
            QMessageBox.information(
                self, "PDF 安全状态", "当前文档未加密，没有使用权限限制。")
            return
        else:
            permissions = int(view.doc.permissions)
            headline = "当前文档已加密"

        def allowed(mask):
            return "允许" if permissions & mask else "禁止"

        details = (
            f"{headline}\n\n"
            f"打印：{allowed(pymupdf.PDF_PERM_PRINT)}\n"
            f"复制：{allowed(pymupdf.PDF_PERM_COPY)}\n"
            f"编辑：{allowed(pymupdf.PDF_PERM_MODIFY)}\n"
            f"批注：{allowed(pymupdf.PDF_PERM_ANNOTATE)}")
        QMessageBox.information(self, "PDF 安全状态", details)

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
        self.btn_search_prev.setIcon(
            icons.get("search_up", self._icon_color))
        self.btn_search_prev.setIconSize(QSize(18, 18))
        self.btn_search_prev.setFixedSize(32, 30)
        self.btn_search_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_search_prev.setToolTip(i18n.tr("search_prev"))
        self.btn_search_prev.clicked.connect(self._search_prev)
        self.btn_search_next = QToolButton()
        self.btn_search_next.setObjectName("btn_search_next")
        self.btn_search_next.setIcon(
            icons.get("search_down", self._icon_color))
        self.btn_search_next.setIconSize(QSize(18, 18))
        self.btn_search_next.setFixedSize(32, 30)
        self.btn_search_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_search_next.setToolTip(i18n.tr("search_next"))
        self.btn_search_next.clicked.connect(self._search_next)

        self.statusBar().addPermanentWidget(self.search_edit)
        self.statusBar().addPermanentWidget(self.btn_search)
        self.statusBar().addPermanentWidget(self.btn_search_prev)
        self.statusBar().addPermanentWidget(self.btn_search_next)
        self.search_nav_spacer = QWidget()
        self.search_nav_spacer.setObjectName("searchNavSpacer")
        self.search_nav_spacer.setFixedWidth(8)
        self.statusBar().addPermanentWidget(self.search_nav_spacer)
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
        app.setProperty("do_dark_theme", dark)
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
        # 应用级 QSS 会在部分 Windows/Qt 组合上把标签字体恢复为系统
        # 默认值；主题落地后再次锁定菜单、工具栏和紧凑标签字体。
        self._apply_ui_fonts()
        self._icon_color = icons.icon_color_for_dark(dark)
        for act, ikey in self._icon_key_of.items():
            act.setIcon(icons.get(ikey, self._icon_color))
        for index in range(self.tabs.count()):
            self._style_tab_close_button(index)
        if getattr(self, "search_action", None) is not None:
            self.search_action.setIcon(icons.get("search", self._icon_color))
        if getattr(self, "btn_search_prev", None) is not None:
            nav_color = "#7fc0ff" if dark else "#176fb6"
            self.btn_search_prev.setIcon(
                icons.get("search_up", nav_color))
            self.btn_search_next.setIcon(
                icons.get("search_down", nav_color))
        if getattr(self, "more_tools_btn", None) is not None:
            more_color = "#ff7048" if dark else "#d9502b"
            self.more_tools_btn.setIcon(
                icons.get("more_down", more_color))
        self.act["theme_light"].setChecked(self.theme_mode == "light")
        self.act["theme_dark"].setChecked(self.theme_mode == "dark")
        self.act["theme_system"].setChecked(self.theme_mode == "system")
        self._apply_titlebar_dark()
        for top_level in app.topLevelWidgets():
            if isinstance(top_level, QDialog):
                self._schedule_dialog_titlebar_sync(top_level)
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
                ((36, 36, 38), (245, 245, 247), (58, 58, 60))
                if dark else
                ((247, 247, 249), (29, 29, 31), (210, 210, 215))
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

    def _schedule_dialog_titlebar_sync(self, dialog):
        """在窗口句柄建立和 Windows 延迟重绘后持续同步弹窗标题栏。"""
        if not isinstance(dialog, QDialog):
            return
        dialog.setProperty("do_theme_managed", True)
        if dialog.windowIcon().isNull():
            dialog.setWindowIcon(self.windowIcon())
        if dialog.windowFlags() & Qt.WindowType.FramelessWindowHint:
            return
        self._apply_titlebar_dark(dialog)
        for delay in (0, 80, 220, 500):
            QTimer.singleShot(
                delay,
                lambda window=dialog: self._apply_titlebar_dark(window))

    def eventFilter(self, obj, event):
        """同步弹窗标题栏，并为所有菜单应用圆润的二级菜单箭头。"""
        if isinstance(obj, QMenu) and event.type() == QEvent.Type.Show:
            if not obj.property("do_rounded_menu_arrow"):
                obj.setStyle(self._menu_arrow_style)
                obj.setProperty("do_rounded_menu_arrow", True)
        if isinstance(obj, QDialog) and event.type() == QEvent.Type.Show:
            self._schedule_dialog_titlebar_sync(obj)
        return super().eventFilter(obj, event)

    def showEvent(self, e):
        super().showEvent(e)
        self._apply_titlebar_dark()
        QTimer.singleShot(80, self._apply_titlebar_dark)
        QTimer.singleShot(260, self._apply_titlebar_dark)
        QTimer.singleShot(0, self._schedule_more_tools_visibility)
        QTimer.singleShot(120, self._schedule_more_tools_visibility)
        QTimer.singleShot(0, self._position_toolbar_seam_cover)
        if not getattr(self, "_reward_posted", False):
            self._reward_posted = True
            QTimer.singleShot(1500, self._maybe_show_reward)
        # 启动后异步检查更新（不阻塞 UI）
        if not getattr(self, "_update_check_posted", False):
            self._update_check_posted = True
            QTimer.singleShot(2500, self._maybe_check_update)
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
        password = None
        wrong_password = False
        while True:
            try:
                probe = backend.open_pdf(path, password)
                probe.close()
                break
            except (backend.PdfPasswordRequired, backend.PdfPasswordInvalid):
                prompt = ("密码不正确，请重新输入：" if wrong_password else
                          "该 PDF 已加密，请输入打开密码：")
                password, ok = QInputDialog.getText(
                    self, "打开加密 PDF", prompt,
                    QLineEdit.EchoMode.Password)
                if not ok:
                    self.statusBar().showMessage("已取消打开加密 PDF", 3000)
                    return
                wrong_password = True
            except Exception as e:
                QMessageBox.critical(self, "错误", f"无法打开该文件：\n{e}")
                return

        view = self.current_view()
        if view is not None and view.doc is None and self.tabs.count() == 1:
            view.load(path, password)
        else:
            view = self._new_tab()
            view.load(path, password)

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

    def _set_sidebar_default(self, visible):
        """保存侧边栏默认状态，并立即同步所有已打开的标签页。"""
        self.sidebar_default_visible = bool(visible)
        self.settings.setValue(
            "sidebar_default_visible", self.sidebar_default_visible)
        self.settings.sync()
        for index in range(self.tabs.count()):
            view = self.tabs.widget(index)
            if isinstance(view, DocumentView):
                view.set_sidebar_visible(self.sidebar_default_visible)

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
            view.set_sidebar_visible(
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
        res = dlg.result()
        if res[0] == "image":
            _, img_path, scale, opacity, rotate, tiled = res
            if not img_path:
                QMessageBox.information(
                    self, i18n.tr("hint"),
                    i18n.tr("watermark_image_empty"))
                return
        else:
            _, text, fontsize, color, opacity, rotate, tiled = res
            if not text:
                QMessageBox.information(
                    self, i18n.tr("hint"), i18n.tr("watermark_empty"))
                return
        # 校验通过后再记录撤销状态，避免失败操作污染撤销历史。
        view.begin_undo_step(document_change=True)
        if res[0] == "image":
            if not backend.add_image_watermark(
                    view.doc, img_path, opacity=opacity,
                    rotate=rotate, tiled=tiled, scale=scale):
                QMessageBox.information(
                    self, i18n.tr("hint"),
                    i18n.tr("watermark_image_invalid"))
                return
        else:
            backend.add_watermark(view.doc, text, fontsize=fontsize,
                                  color=color, opacity=opacity,
                                  rotate=rotate, tiled=tiled)
        view.modified = True
        view._refresh()
        self.statusBar().showMessage(i18n.tr("watermark_added"), 3000)

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

    def _open_repo_url(self):
        QDesktopServices.openUrl(QUrl("https://github.com/GMY2811/DO-Editor"))

    def _open_feedback_url(self):
        QDesktopServices.openUrl(
            QUrl("https://github.com/GMY2811/DO-Editor/issues/new"))

    def _check_update_now(self):
        from update_checker import check_update_async
        check_update_async(self, manual=True)

    def _maybe_show_reward(self):
        from reward_dialog import (bump_launch_count, is_reward_dismissed,
                                   RewardDialog, SHOW_AT_LAUNCH)
        if is_reward_dismissed():
            return
        # 第 N 次启动（默认 3）时才弹出，避免新用户一打开就被打扰。
        if bump_launch_count() < SHOW_AT_LAUNCH:
            return
        d = RewardDialog(self)
        d.exec()

    def _show_reward_from_menu(self):
        from reward_dialog import RewardDialog
        RewardDialog(self).exec()

    def _maybe_check_update(self):
        """异步调用 update_checker，避免阻塞启动。"""
        from update_checker import check_update_async
        check_update_async(self)

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
        if self._ocr_worker is not None and self._ocr_worker.isRunning():
            self._ocr_worker.requestInterruption()
            if not self._ocr_worker.wait(5000):
                QMessageBox.information(
                    self, "OCR 文字识别", "正在结束当前识别任务，请稍后再退出。")
                e.ignore()
                return
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
