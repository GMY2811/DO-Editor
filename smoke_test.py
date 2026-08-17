"""DO编辑器 冒烟测试：后端逻辑 + 连续滚动 + 多标签页 + 编辑。"""
import os
import sys
import tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pymupdf
import backend

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sample = "sample.pdf"


def tiny_png():
    td = pymupdf.open()
    tp = td.new_page(width=40, height=20)
    tp.insert_text((2, 12), "x", fontsize=10)
    pix = tp.get_pixmap(matrix=pymupdf.Matrix(1, 1))
    td.close()
    return pix.tobytes("png")


def main():
    # 1. 生成样本（含书签）
    doc = pymupdf.open()
    for i in range(5):
        p = doc.new_page(width=595, height=842)
        p.insert_text((72, 100), f"Hello DO editor, page {i+1}", fontsize=24)
    doc.set_toc([[1, "章节一", 1], [2, "小节 1.1", 1], [1, "章节二", 3]])
    doc.save(sample)
    doc.close()

    d = backend.open_pdf(sample)
    assert backend.page_count(d) == 5

    ok, _ = backend.merge_pdfs([sample, sample], "merged.pdf")
    assert ok and len(backend.open_pdf("merged.pdf")) == 10
    ok, files = backend.split_every_n(d, 2, ".", "split")
    assert ok and len(files) == 3
    ok, files = backend.split_by_ranges(d, [(1, 2), (3, 5)], ".", "range")
    assert ok and len(files) == 2
    ok, _ = backend.extract_pages(d, [0, 2, 4], "extract.pdf")
    assert ok and len(backend.open_pdf("extract.pdf")) == 3
    print("[OK] merge / split / extract")

    page = d[0]
    backend.add_highlight(page, pymupdf.Rect(50, 50, 200, 80))
    backend.add_underline(page, pymupdf.Rect(50, 90, 200, 110), (0.0, 0.0, 1.0))
    backend.add_strikeout(page, pymupdf.Rect(50, 130, 200, 150))
    backend.add_rect(page, pymupdf.Rect(50, 170, 200, 210))
    backend.add_line(page, (50, 230), (200, 260), (1.0, 0.0, 0.0))
    backend.add_note(page, (50, 300), "a note")
    backend.add_ink(page, [(50, 400), (80, 430)], (0.0, 1.0, 0.0))
    backend.add_image(page, pymupdf.Rect(300, 50, 340, 70), tiny_png())
    assert "Hello DO editor" in backend.extract_text(d, 0)
    backend.replace_text(page, pymupdf.Rect(60, 80, 400, 120), "替换文字")
    print("[OK] annotations + extract_text + replace_text")

    tmp = sample + ".tmp"
    d.save(tmp, garbage=3, deflate=True)
    d.close()
    os.replace(tmp, sample)
    d2 = backend.open_pdf(sample)
    d2.delete_page(0)
    assert len(d2) == 4
    d2.close()
    print("[OK] save-over + delete_page")

    # ================= GUI =================
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtCore import QPoint, QPointF, QEvent, Qt, QSettings, QTimer
    from PySide6.QtGui import QColor, QImage, QMouseEvent
    import icons
    from main_window import MainWindow, AboutDialog
    from sign_dialog import save_signature, list_signatures, qimage_to_png_bytes, DrawingCanvas

    app = QApplication([])

    # GUI 测试使用独立的 INI 设置目录，不能改动用户真实的主题和工具栏顺序。
    settings_dir = tempfile.mkdtemp(prefix="do-editor-settings-")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,
                      QSettings.Scope.UserScope, settings_dir)

    for name in icons.ICONS:
        assert not icons.get(name).isNull(), name
    print("[OK] icons (%d 个)" % len(icons.ICONS))

    win = MainWindow()
    win.open_file(sample)
    view = win.current_view()
    assert view.doc is not None
    assert view.page_view.page_count() == 5
    assert view.thumb_list.count() == 5
    assert not hasattr(view, "bookmark_tree")   # 书签模块已移除
    assert win.act["edit_color"] in win.tb2.actions()
    assert not win.act["edit_color"].icon().isNull()

    # 拖动排序后按钮不能残留按下态，也不能丢失图标+文字样式。
    win.show()
    app.processEvents()
    toolbar_actions = [a for a in win.tb1.actions() if a.property("do_key")]
    drag_action = toolbar_actions[-1]
    target_action = toolbar_actions[0]
    drag_button = win.tb1.widgetForAction(drag_action)
    target_button = win.tb1.widgetForAction(target_action)
    drag_global = drag_button.mapToGlobal(drag_button.rect().center())
    target_global = target_button.mapToGlobal(target_button.rect().center())
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(drag_button.rect().center()),
        QPointF(drag_global), Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    move = QMouseEvent(
        QEvent.Type.MouseMove, QPointF(drag_button.rect().center()),
        QPointF(target_global), Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(drag_button.rect().center()),
        QPointF(target_global), Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    win.tb1.eventFilter(drag_button, press)
    drag_button.setDown(True)
    win.tb1.eventFilter(drag_button, move)
    win.tb1.eventFilter(drag_button, release)
    app.processEvents()
    moved_button = win.tb1.widgetForAction(drag_action)
    assert win.tb1.actions().index(drag_action) < win.tb1.actions().index(target_action)
    assert not moved_button.isDown()
    assert moved_button.toolButtonStyle() == win.tb1.toolButtonStyle()
    assert moved_button.iconSize() == win.tb1.iconSize()
    assert moved_button.font() == win.tb1.font()
    assert moved_button.style().metaObject().className() == \
        app.style().metaObject().className()
    print("[OK] 工具栏拖动排序外观")

    # 菜单使用稳定的直角系统弹窗；多级菜单应正常显示并继承同一主题。
    win._m_view.popup(QPoint(40, 40))
    app.processEvents()
    theme_rect = win._m_view.actionGeometry(win._m_theme.menuAction())
    win._m_theme.popup(win._m_view.mapToGlobal(theme_rect.topRight()))
    app.processEvents()
    assert win._m_view.isVisible()
    assert win._m_theme.isVisible()
    assert len(win._m_theme.actions()) == 3
    assert not win._m_view.testAttribute(
        Qt.WidgetAttribute.WA_TranslucentBackground)
    assert not win._m_theme.testAttribute(
        Qt.WidgetAttribute.WA_TranslucentBackground)
    win._m_theme.hide()
    win._m_view.hide()
    print("[OK] 直角下拉菜单 + 多级菜单")

    # “关于”窗口使用应用自绘标题栏，不依赖不同步的 Windows 原生标题栏。
    closed_about = []
    QTimer.singleShot(30, lambda: [
        (closed_about.append(widget), widget.accept())
        for widget in app.topLevelWidgets()
        if isinstance(widget, AboutDialog)])
    win.about()
    assert closed_about
    about_dialog = closed_about[0]
    assert about_dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert about_dialog.findChild(QWidget, "aboutTitleBar") is not None
    print("[OK] 关于窗口标题栏同步")

    view.set_mode("highlight")
    view.set_mode("text_select")
    view.set_mode("replace_text")
    view.set_mode("view")
    print("[OK] 主窗口 + 连续滚动 + 模式")

    img = QImage(40, 20, QImage.Format.Format_ARGB32)
    img.fill(QColor(200, 0, 0))
    view._add_object(img, "signature", 0, QPointF(50, 50), 180.0)
    assert len(view.objects) == 1
    view._add_text_object("测试文本", 0, QPointF(60, 60))
    assert view.objects[1]["kind"] == "text"
    view._bake_objects()
    assert len(view.objects) == 0
    view.edit_color = QColor(0, 0, 255)
    assert view._edit_rgb() == (0.0, 0.0, 1.0)
    print("[OK] 浮动对象 + 文本定位框 + 颜色")

    # 12. 文本选择（直接滑动选文字）+ 字体烘焙
    view.show_page(0)
    from PySide6.QtCore import QPointF as _QPF
    pv = view.page_view
    pv._sel_start = _QPF(10, 10)
    pv._sel_cur = _QPF(400, 200)
    pv._compute_selection()
    assert pv.has_selection()
    assert pv.selected_text().strip()  # 文字可能已被 replace_text 替换，仅要求非空
    pv.clear_selection()
    assert not pv.has_selection()
    view._add_text_object("字体测试", 0, _QPF(60, 60), "Microsoft YaHei", 18)
    assert view.objects[0]["fontfamily"] == "Microsoft YaHei"
    assert view.objects[0]["fontsize"] == 18
    view._bake_objects()  # 含中文 + 字体烘焙不崩溃
    assert len(view.objects) == 0
    # inline 文本编辑器
    view.set_mode("text")
    view._start_inline_text(0, _QPF(80, 80))
    assert view._inline_box is not None
    view._close_inline_editor()
    assert view._inline_box is None
    # 文本工具保持激活时，双击刚确认的文本仍应重新进入编辑。
    view._add_text_object("双击修改", 0, _QPF(100, 100), keep_mode=True)
    text_obj = view.objects[-1]
    view.set_mode("text")
    text_pos = _QPF(
        (text_obj["rect"].center().x()) * pv._zoom,
        pv._offsets[0] + text_obj["rect"].center().y() * pv._zoom)
    double_click = QMouseEvent(
        QEvent.Type.MouseButtonDblClick, text_pos,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier)
    pv.mouseDoubleClickEvent(double_click)
    assert view._inline_oid == text_obj["id"]
    assert view._inline_edit.text() == "双击修改"
    view._close_inline_editor()
    print("[OK] 文本选择 + 字体 + inline 编辑器")

    win.set_theme("dark")
    assert win.theme_mode == "dark"
    if app.platformName() == "windows":
        assert app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    win.set_theme("light")
    if app.platformName() == "windows":
        assert app.styleHints().colorScheme() == Qt.ColorScheme.Light
    win.set_theme("system")
    canvas = DrawingCanvas()
    canvas.set_pen_width(8)
    canvas.set_pen_color(QColor(255, 0, 0))
    canvas.render_image()
    print("[OK] 主题 + 签名颜色")

    # 多标签页
    win._new_tab()
    assert win.tabs.count() == 2
    print("[OK] 多标签页")

    # 签名库
    tmp_dir = tempfile.mkdtemp()
    os.environ["APPDATA"] = tmp_dir
    save_signature(qimage_to_png_bytes(img), "测试签名")
    assert len(list_signatures()) == 1
    print("[OK] 签名库")

    view.modified = False
    win.close()
    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    main()
