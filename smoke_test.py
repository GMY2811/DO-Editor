"""DO编辑器 冒烟测试：后端逻辑 + 连续滚动 + 多标签页 + 编辑。"""
import os
import sys
import tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pymupdf
import backend
import i18n
import app_config as cfg

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
    extract_test = os.path.join(
        tempfile.gettempdir(), f"do-editor-extract-{os.getpid()}.pdf")
    ok, _ = backend.extract_pages(d, [0, 2, 4], extract_test)
    assert ok
    extracted_doc = backend.open_pdf(extract_test)
    assert len(extracted_doc) == 3
    extracted_doc.close()
    os.remove(extract_test)
    print("[OK] merge / split / extract")

    # OCR：把一页文字渲染成纯图片 PDF，再识别并写回隐藏文字层。
    source = pymupdf.open()
    source_page = source.new_page(width=500, height=120)
    source_page.insert_text((35, 75), "DO EDITOR OCR TEST 123", fontsize=30)
    scan_png = source_page.get_pixmap(
        matrix=pymupdf.Matrix(2.5, 2.5), alpha=False).tobytes("png")
    source.close()
    scan = pymupdf.open()
    scan_page = scan.new_page(width=500, height=120)
    scan_page.insert_image(scan_page.rect, stream=scan_png)
    assert not scan_page.get_text().strip()
    ocr_lines = backend.recognize_page_ocr(
        backend.create_ocr_engine(), scan, 0)
    assert any("OCR" in line["text"] for line in ocr_lines)
    assert backend.add_ocr_text_layer(
        scan, [{"page": 0, "lines": ocr_lines}]) > 0
    assert scan[0].search_for("OCR")
    assert "OCR" in backend.extract_text(scan, 0)
    ocr_saved = os.path.join(tempfile.gettempdir(), "do-editor-ocr-searchable.pdf")
    if os.path.exists(ocr_saved):
        os.remove(ocr_saved)
    scan.save(ocr_saved, garbage=3, deflate=True)
    scan.close()
    reopened_scan = pymupdf.open(ocr_saved)
    assert reopened_scan[0].search_for("OCR")
    reopened_scan.close()
    os.remove(ocr_saved)
    print("[OK] 离线 OCR + 可搜索隐藏文字层")

    # AES-256 加密后必须验证密码，权限位应按设置写入。
    secure_path = os.path.join(tempfile.gettempdir(), "do-editor-secure.pdf")
    if os.path.exists(secure_path):
        os.remove(secure_path)
    secure_source = pymupdf.open()
    secure_source.new_page().insert_text((40, 60), "SECRET")
    secure_source.save(
        secure_path, encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw="reader", owner_pw="owner-secret",
        permissions=backend.pdf_permissions(True, False, False, True))
    secure_source.close()
    try:
        backend.open_pdf(secure_path)
        raise AssertionError("encrypted PDF opened without a password")
    except backend.PdfPasswordRequired:
        pass
    try:
        backend.open_pdf(secure_path, "wrong")
        raise AssertionError("encrypted PDF accepted a wrong password")
    except backend.PdfPasswordInvalid:
        pass
    secured = backend.open_pdf(secure_path, "reader")
    assert secured._do_auth_level & 2
    assert "SECRET" in secured[0].get_text()
    assert secured.permissions & pymupdf.PDF_PERM_PRINT
    assert not (secured.permissions & pymupdf.PDF_PERM_COPY)
    secured.close()
    os.remove(secure_path)
    print("[OK] AES-256 密码验证 + PDF 权限")

    page = d[0]
    backend.add_highlight(page, pymupdf.Rect(50, 50, 200, 80))
    backend.add_underline(page, pymupdf.Rect(50, 90, 200, 110), (0.0, 0.0, 1.0))
    backend.add_strikeout(page, pymupdf.Rect(50, 130, 200, 150))
    backend.add_rect(page, pymupdf.Rect(50, 170, 200, 210))
    backend.add_line(page, (50, 230), (200, 260), (1.0, 0.0, 0.0))
    note_annot = backend.add_note(page, (50, 300), "a note", (1.0, 0.6, 0.0))
    assert note_annot.info.get("content") == "a note"
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
    from PySide6.QtWidgets import (QApplication, QWidget, QLabel, QDialog,
                                   QAbstractItemView, QMenu)
    from PySide6.QtCore import (QPoint, QPointF, QRectF, QEvent, Qt, QSettings,
                                QTimer, QSize, QSizeF, QEventLoop)
    from PySide6.QtGui import QColor, QImage, QMouseEvent, QIcon
    import icons
    import theme
    from main_window import (MainWindow, AboutDialog, PdfSecurityDialog,
                             TabCloseButton, RoundedMenuArrowStyle)
    from document_view import DocumentView, ReplaceTextDialog, AddWatermarkDialog
    from sign_dialog import (save_signature, list_signatures, qimage_to_png_bytes,
                             DrawingCanvas, SignatureDialog,
                             SignatureFontComboBox,
                             text_to_signature_image)

    app = QApplication([])

    text_signature = text_to_signature_image("清晰签名", font_size=12)
    assert text_signature.devicePixelRatio() == 3.0
    assert text_signature.width() > text_signature.deviceIndependentSize().width()
    alpha = text_signature.convertToFormat(QImage.Format.Format_Alpha8)
    assert any(bytes(alpha.constBits())), "文字签名不应是全透明空图"
    signature_dialog = SignatureDialog()
    assert isinstance(signature_dialog._font_combo, SignatureFontComboBox)
    signature_dialog._text_edit.setText("格式签名")
    signature_dialog._bold_check.setChecked(True)
    signature_dialog._italic_check.setChecked(True)
    signature_dialog._make_text_signature()
    assert signature_dialog._image is not None
    assert signature_dialog._image.devicePixelRatio() == 3.0
    dialog_alpha = signature_dialog._image.convertToFormat(
        QImage.Format.Format_Alpha8)
    assert any(bytes(dialog_alpha.constBits()))
    replace_dialog = ReplaceTextDialog(old_text="文字")
    assert isinstance(replace_dialog._font_combo, SignatureFontComboBox)

    # GUI 测试使用独立的 INI 设置目录，不能改动用户真实的主题和工具栏顺序。
    settings_dir = tempfile.mkdtemp(prefix="do-editor-settings-")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,
                      QSettings.Scope.UserScope, settings_dir)

    for name in icons.ICONS:
        assert not icons.get(name).isNull(), name
    print("[OK] icons (%d 个)" % len(icons.ICONS))

    win = MainWindow()
    assert win.sidebar_default_visible is True
    assert win.act["sidebar_default"].isChecked()
    assert not win.current_view().side_tabs.isHidden()
    win.act["sidebar_default"].setChecked(False)
    assert win.sidebar_default_visible is False
    assert win.current_view().side_tabs.isHidden()
    sidebar_test_view = win._new_tab()
    assert sidebar_test_view.side_tabs.isHidden()
    win.act["sidebar_default"].setChecked(True)
    assert all(not win.tabs.widget(i).side_tabs.isHidden()
               for i in range(win.tabs.count()))
    win.tabs.removeTab(win.tabs.indexOf(sidebar_test_view))
    win.tabs.setCurrentIndex(0)
    test_submenu = QMenu(win)
    win.eventFilter(test_submenu, QEvent(QEvent.Type.Show))
    assert test_submenu.property("do_rounded_menu_arrow") is True
    win.set_language("en")
    assert win.windowTitle() == "DO Editor"
    assert win.tabs.tabText(0) == "Untitled"
    assert win.current_view().side_tabs.tabText(0) == "Pages"
    assert win.current_view().start_title.text() == "DO Editor"
    assert win.current_view().start_open_btn.text() == "Open Document"
    assert win.act["watermark"].text() == "Add Watermark"
    assert win.act["sign"].text() == "Signature Design"
    assert win.act["sidebar_default"].text() == "Show Sidebar by Default"
    watermark_dialog = AddWatermarkDialog(win)
    assert watermark_dialog.windowTitle() == "Add Watermark"
    assert watermark_dialog._tiled_check.text() == "Tiled"
    assert watermark_dialog._text_edit.text() == "CONFIDENTIAL"
    english_about = AboutDialog(win)
    assert english_about.windowTitle() == "About DO Editor"
    assert english_about.findChild(QLabel, "aboutTitleText").text() == \
        "About DO Editor"
    assert english_about.findChild(QLabel, "aboutAppName").text() == \
        "DO Editor"
    assert english_about.findChild(QLabel, "aboutVersion").text() == \
        f"Version {cfg.APP_VERSION}"
    assert english_about.findChild(QLabel, "aboutSummary").text() == \
        "A lightweight, focused PDF reader and editor"
    assert {label.text() for label in english_about.findChildren(
        QLabel, "aboutMetaLabel")} == {"Developer", "Email", "Framework"}
    assert english_about.findChild(QWidget, "primaryButton").text() == "OK"
    win.set_language("zh")
    assert win.act["sign"].text() == "签名设计"
    assert win.act["sidebar_default"].text() == "启动时显示侧边栏"
    assert win.act["copy_all"] not in win._m_edit.actions()
    assert win.mode_actions["text_select"].text() == "快捷复制"
    assert i18n.tr("select_text") == "快捷复制"
    win.open_file(sample)
    view = win.current_view()
    assert view.doc is not None
    assert view.page_view.page_count() == 5
    assert view.thumb_list.count() == 5
    first_thumb_icon = view.thumb_list.item(0).icon()
    normal_thumb = first_thumb_icon.pixmap(
        view.thumb_list.iconSize(), QIcon.Mode.Normal).toImage()
    selected_thumb = first_thumb_icon.pixmap(
        view.thumb_list.iconSize(), QIcon.Mode.Selected).toImage()
    assert normal_thumb == selected_thumb
    assert view._sidebar_default_width == 104
    assert view.thumb_list.objectName() == "thumbnailList"
    assert view.scroll.objectName() == "documentScroll"
    assert view._splitter.handleWidth() == 1
    assert view._sidebar_fit_timer.isSingleShot()
    assert view._sidebar_fit_timer.interval() == 32
    assert view.side_tabs.minimumWidth() == 88
    assert view.side_tabs.maximumWidth() == 180
    narrow_icon, narrow_grid = view._thumbnail_layout_for_width(90)
    wide_icon, wide_grid = view._thumbnail_layout_for_width(160)
    assert wide_icon.width() > narrow_icon.width()
    assert abs(wide_icon.height() / wide_icon.width() - 1.414) < 0.02
    assert narrow_grid.width() >= narrow_icon.width() + 8
    assert wide_grid.width() >= wide_icon.width() + 8
    assert narrow_grid.height() == narrow_icon.height() + 14
    assert wide_grid.height() == wide_icon.height() + 14
    assert view.thumb_list.itemDelegate().__class__.__name__ == "ThumbnailDelegate"
    assert view.thumb_list.itemDelegate().PAGE_BAND_COLOR == \
        QColor(248, 250, 252, 112)
    assert view.thumb_list.itemDelegate().PAGE_TEXT_COLOR == \
        QColor(156, 163, 175, 255)
    QApplication.clipboard().setText("直接粘贴测试")
    object_count = len(view.objects)
    view.paste_text(0, QPointF(24, 36))
    assert len(view.objects) == object_count + 1
    pasted = view.objects[-1]
    assert pasted["text"] == "直接粘贴测试"
    assert pasted["page"] == 0
    assert pasted["rect"].topLeft() == QPointF(24, 36)
    view.objects.pop()
    view._refresh_objects()
    placement_image = QImage(400, 200, QImage.Format.Format_ARGB32)
    image_page, image_point, image_width = view._default_image_placement(
        placement_image)
    image_page_rect = view.doc[image_page].rect
    assert image_width <= 160
    assert image_point.x() >= image_page_rect.x0
    assert image_point.y() >= image_page_rect.y0
    assert image_point.x() + image_width <= image_page_rect.x1
    assert image_point.y() + image_width * 0.5 <= image_page_rect.y1
    assert abs((image_point.x() + image_width / 2) -
               (image_page_rect.x0 + image_page_rect.x1) / 2) < 0.01
    assert image_point.y() < image_page_rect.y0 + image_page_rect.height * 0.2
    assert view.thumb_list.selectionMode() == \
        QAbstractItemView.SelectionMode.ExtendedSelection
    assert view.thumb_list.flow() == view.thumb_list.Flow.TopToBottom
    assert not view.thumb_list.isWrapping()
    assert view.thumb_list.dragDropMode() == \
        QAbstractItemView.DragDropMode.InternalMove
    assert view.thumb_list.defaultDropAction() == Qt.DropAction.MoveAction
    reorder_view = DocumentView()
    assert reorder_view.load(sample)
    reorder_view.objects.append({
        "id": 999, "page": 0, "rect": QRectF(10, 10, 40, 20),
        "text": "reorder", "color": QColor(0, 0, 0), "fontsize": 12,
        "fontfamily": "", "bold": False, "italic": False, "kind": "text",
    })
    assert reorder_view._reorder_pages([1, 0, 2, 3, 4])
    assert "page 2" in backend.extract_text(reorder_view.doc, 0)
    assert reorder_view.objects[0]["page"] == 1
    assert [reorder_view.thumb_list.item(i).text() for i in range(5)] == \
        ["1", "2", "3", "4", "5"]
    reorder_view.close_doc()
    annotation_view = DocumentView()
    assert annotation_view.load(sample)
    for mode, rect in (
            ("highlight", QRectF(70, 80, 150, 24)),
            ("underline", QRectF(70, 120, 150, 20)),
            ("strikeout", QRectF(70, 160, 150, 20)),
            ("rect", QRectF(70, 200, 150, 60))):
        annotation_view.set_mode(mode)
        annotation_view._on_rect(0, rect)
        assert annotation_view.objects[-1]["kind"] == mode
        assert annotation_view.page_view.selected_id() == \
            annotation_view.objects[-1]["id"]
    annotation_view.set_mode("line")
    annotation_view._on_line(0, QPointF(80, 300), QPointF(220, 340))
    assert annotation_view.objects[-1]["kind"] == "line"
    assert len(annotation_view.objects[-1]["points"]) == 2
    annotation_view.set_mode("ink")
    annotation_view._on_ink(
        0, [QPointF(80, 380), QPointF(120, 360), QPointF(190, 400)])
    assert annotation_view.objects[-1]["kind"] == "ink"
    assert len(annotation_view.objects) == 6
    rect_object = next(o for o in annotation_view.objects if o["kind"] == "rect")
    annotation_view.page_view.select(rect_object["id"])
    annotation_view.delete_selected()
    assert len(annotation_view.objects) == 5
    annotation_view._bake_objects()
    assert not annotation_view.objects
    annotation_types = []
    annotation_page = annotation_view.doc[0]
    annot = annotation_page.first_annot
    while annot is not None:
        annotation_types.append(annot.type[1])
        annot = annot.next
    assert {"Highlight", "Underline", "StrikeOut", "Line", "Ink"}.issubset(
        set(annotation_types))
    annotation_view.close_doc()
    note_view = DocumentView()
    assert note_view.load(sample)
    assert note_view._add_note_at("界面批注测试", 0, QPointF(80, 120))
    assert note_view.modified
    note_object = note_view.objects[-1]
    assert note_object["kind"] == "note"
    assert note_object["color"] == QColor("#ff9f0a")
    assert note_object["rect"].topLeft() == QPointF(80, 120)
    assert note_object["rect"].size() == QSizeF(16, 16)
    assert not note_object["img"].isNull()
    tooltip_html = note_view.page_view._note_tooltip_html("第一行\n<第二行>")
    assert "第一行<br>&lt;第二行&gt;" in tooltip_html
    assert "max-width: 360px" in tooltip_html
    assert note_view.page_view._note_preview.objectName() == "noteHoverPreview"
    assert note_view.page_view._note_preview.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    marker = note_object["img"]
    assert marker.devicePixelRatio() == 4.0
    assert marker.width() == 64 and marker.height() == 64
    opaque = [(x, y) for y in range(marker.height())
              for x in range(marker.width())
              if marker.pixelColor(x, y).alpha() > 0]
    assert min(x for x, _y in opaque) >= 2
    assert max(x for x, _y in opaque) <= 61
    assert min(y for _x, y in opaque) >= 2
    assert max(y for _x, y in opaque) <= 61
    assert note_view.page_view.selected_id() == note_object["id"]
    moved_note_rect = QRectF(140, 180, 16, 16)
    note_view._on_object_changed(note_object["id"], moved_note_rect)
    assert note_object["rect"] == moved_note_rect
    note_view._bake_objects()
    assert not note_view.objects
    note_contents = []
    note_page = note_view.doc[0]
    annot = note_page.first_annot
    while annot is not None:
        note_contents.append(annot.info.get("content", ""))
        annot = annot.next
    assert "界面批注测试" in note_contents
    note_view.close_doc()
    delete_view = DocumentView()
    assert delete_view.load(sample)
    delete_view.thumb_list.clearSelection()
    delete_view.thumb_list.item(1).setSelected(True)
    delete_view.thumb_list.item(3).setSelected(True)
    assert delete_view._thumb_delete_shortcut.context() == \
        Qt.ShortcutContext.WidgetWithChildrenShortcut
    assert delete_view._delete_selected_thumbnails(confirm=False)
    assert len(delete_view.doc) == 3
    assert delete_view.thumb_list.count() == 3
    assert delete_view.modified
    delete_view.close_doc()
    assert not hasattr(view, "bookmark_tree")   # 书签模块已移除
    assert win.act["edit_color"] in win.tb2.actions()
    assert win.act["ocr_current"] in win._m_ocr.actions()
    assert win.act["ocr_all"] in win._m_ocr.actions()
    assert win.act["ocr_current"].text() == "识别当前页面"
    assert win._icon_key_of[win.act["ocr_current"]] == "ocr"
    assert win._icon_key_of[win.act["ocr_all"]] == "ocr_all"
    assert win._m_signature_tools.menuAction() in win._m_tools.actions()
    assert win.act["sign"] in win._m_signature_tools.actions()
    assert win.act["sign_lib"] in win._m_signature_tools.actions()
    assert win.act["sign"] not in win._m_tools.actions()
    assert win.act["sign_lib"] not in win._m_tools.actions()
    assert win.act["annotation"] in win._m_tools.actions()
    assert not win.act["annotation"].icon().isNull()
    assert not win.act["ocr_current"].icon().isNull()
    assert not win.act["ocr_toolbar"].icon().isNull()
    print("[OK] OCR 工具菜单")
    assert win._m_sign.title() == "安全"
    assert win.act["sign"] not in win._m_sign.actions()
    assert win.act["sign_lib"] not in win._m_sign.actions()
    assert win.act["security_set"] in win._m_sign.actions()
    assert win.act["security_remove"] in win._m_sign.actions()
    security_dialog = PdfSecurityDialog(win)
    security_dialog.user_password.setText("reader")
    security_dialog.user_confirm.setText("reader")
    security_dialog.owner_password.setText("owner-secret")
    security_dialog.owner_confirm.setText("owner-secret")
    user_pw, owner_pw, permissions = security_dialog.values()
    assert user_pw == "reader" and owner_pw == "owner-secret"
    assert permissions & pymupdf.PDF_PERM_PRINT
    security_dialog.close()
    print("[OK] PDF 安全菜单 + 密码设置窗口")

    # DocumentView 保存链路：加密、保持原加密、删除密码均需可重开。
    security_view = DocumentView()
    assert security_view.load(sample)
    security_output = os.path.join(
        tempfile.gettempdir(), "do-editor-security-flow.pdf")
    if os.path.exists(security_output):
        os.remove(security_output)
    security_view.set_pdf_encryption(
        "reader", "owner-secret",
        backend.pdf_permissions(True, False, True, True))
    security_view._save_to(security_output)
    assert security_view.security_status() == "encrypted"
    assert security_view._auth_level & 2
    assert not (security_view._auth_level & 4)
    win._sync_security_actions(security_view)
    assert win.act["print"].isEnabled()
    assert not win.act["copy_all"].isEnabled()
    assert not win.mode_actions["text_select"].isEnabled()
    assert not win.act["ocr_toolbar"].isEnabled()
    assert win.mode_actions["replace_text"].isEnabled()
    security_view.set_mode("text_select")
    assert security_view.current_mode == "view"
    security_view._save_to(security_output)  # 普通保存继续保持加密
    encrypted_check = backend.open_pdf(security_output, "reader")
    assert any(page.get_text().strip() for page in encrypted_check)
    encrypted_check.close()
    # 所有者认证后可管理全部权限，并允许移除保护。
    security_view._auth_level = int(
        security_view.doc.authenticate("owner-secret"))
    assert security_view._auth_level & 4
    win._sync_security_actions(security_view)
    assert win.act["copy_all"].isEnabled()
    security_view.remove_pdf_encryption()
    assert security_view.security_status() == "pending_remove"
    security_view._save_to(security_output)
    plain_check = backend.open_pdf(security_output)
    assert not plain_check._do_was_encrypted
    assert any(page.get_text().strip() for page in plain_check)
    plain_check.close()
    security_view.close_doc()
    os.remove(security_output)
    win._sync_security_actions(view)
    print("[OK] 设置/保持/删除 PDF 密码保存链路")
    assert not win.act["edit_color"].icon().isNull()
    start_icon = win.findChild(QLabel, "startAppIcon")
    assert start_icon is not None
    assert start_icon.pixmap() is not None
    assert not start_icon.pixmap().isNull()
    print("[OK] 欢迎页应用图标")
    assert win.btn_search_prev.size() == win.btn_search_next.size()
    assert win.btn_search_prev.iconSize() == win.btn_search_next.iconSize()
    assert win.btn_search_prev.contentsRect().size() == \
        win.btn_search_next.contentsRect().size()
    assert not win.btn_search_prev.icon().isNull()
    assert not win.btn_search_next.icon().isNull()
    print("[OK] 搜索上下导航按钮尺寸一致")
    tab_close = win.tabs.tabBar().tabButton(
        0, win.tabs.tabBar().ButtonPosition.RightSide)
    if tab_close is None:
        tab_close = win.tabs.tabBar().tabButton(
            0, win.tabs.tabBar().ButtonPosition.LeftSide)
    assert tab_close is not None
    assert isinstance(tab_close, TabCloseButton)
    assert tab_close.objectName() == "tabCloseButton"
    assert tab_close.icon().isNull()
    assert tab_close.text() == ""
    assert tab_close.size() == QSize(16, 16)
    assert win.tabs.tabBar().tabButton(
        0, win.tabs.tabBar().ButtonPosition.LeftSide) is None
    # 标签由“未命名”变为文件名时，Qt/Windows 不能偷偷换回原生小叉。
    win._update_tab_title(view, "打开后的文件名.pdf")
    # 等待超过最后一次常见的 Qt 延迟布局阶段，模拟真实打开文件过程。
    close_wait = QEventLoop()
    QTimer.singleShot(700, close_wait.quit)
    close_wait.exec()
    tab_close_after_open = win.tabs.tabBar().tabButton(
        0, win.tabs.tabBar().ButtonPosition.RightSide)
    if tab_close_after_open is None:
        tab_close_after_open = win.tabs.tabBar().tabButton(
            0, win.tabs.tabBar().ButtonPosition.LeftSide)
    assert isinstance(tab_close_after_open, TabCloseButton)
    assert tab_close_after_open.objectName() == "tabCloseButton"
    assert tab_close_after_open.size() == QSize(16, 16)
    assert tab_close_after_open.icon().isNull()
    assert win.tabs.tabBar().tabRect(0).height() <= 20
    assert win.tabs.tabBar().tabButton(
        0, win.tabs.tabBar().ButtonPosition.LeftSide) is None
    print("[OK] 标签关闭按钮主题样式")

    # 所有新建弹窗都应被全局主题监听接管，不能再遗漏签名、调色盘或提示框。
    managed_dialog = QDialog(win)
    managed_dialog.setWindowTitle("主题同步测试")
    managed_dialog.show()
    app.processEvents()
    assert managed_dialog.property("do_theme_managed") is True
    assert not managed_dialog.windowIcon().isNull()
    managed_dialog.close()
    print("[OK] 全局弹窗标题栏主题同步")

    # 拖动排序后按钮不能残留按下态，也不能丢失图标+文字样式。
    win.show()
    app.processEvents()
    toolbar_buttons = [
        toolbar.widgetForAction(action)
        for toolbar in (win.tb1, win.tb2)
        for action in toolbar.actions()
        if action.property("do_key")
    ]
    assert toolbar_buttons
    assert all(button.size() == win.tb1.BUTTON_SIZE
               for button in toolbar_buttons)
    assert win.tb1.BUTTON_SIZE == QSize(80, 62)
    assert len({(button.width(), button.height())
                for button in toolbar_buttons}) == 1
    assert win.tb1.iconSize() == win.tb1.ICON_SIZE
    assert win.tb2.iconSize() == win.tb2.ICON_SIZE
    assert all(button.iconSize() == win.tb1.ICON_SIZE
               for button in toolbar_buttons)
    edit_keys = [action.property("do_key") for action in win.tb2.actions()
                 if action.property("do_key")]
    replace_index = edit_keys.index("replace_text")
    assert edit_keys[replace_index + 1:replace_index + 3] == \
        ["sign", "sign_lib"]
    assert win.act["watermark"] not in win.tb1.actions()
    assert win.act["merge"] not in win.tb1.actions()
    assert win.act["split_every"] not in win.tb1.actions()
    assert win.act["merge"] in win._m_tools.actions()
    assert win.act["split_every"] in win._m_tools.actions()
    assert sum(action is win.act["watermark"]
               for toolbar in (win.tb1, win.tb2)
               for action in toolbar.actions()) == 1
    assert edit_keys.index("watermark") + 1 == edit_keys.index("text")
    assert edit_keys.index("image") + 1 == edit_keys.index("annotation")
    assert edit_keys.index("annotation") + 1 == edit_keys.index("ocr_toolbar")
    print("[OK] 水印、批注与 OCR 功能区按钮位置")
    print("[OK] 签名按钮位于修改文字之后")
    print("[OK] 功能区按钮尺寸统一")
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
    about_title_bar = about_dialog.findChild(QWidget, "aboutTitleBar")
    assert about_title_bar is not None
    assert about_title_bar.property("do_theme_dark") is theme.is_dark(
        win.theme_mode)
    assert about_dialog.findChild(QWidget, "aboutHero") is not None
    assert about_dialog.findChild(QWidget, "aboutDetails") is not None
    print("[OK] 关于窗口标题栏同步")

    view.set_mode("highlight")
    view.set_mode("text_select")
    view.set_mode("replace_text")
    view.set_mode("view")
    print("[OK] 主窗口 + 连续滚动 + 模式")

    # ESC 在全屏状态下应优先退出全屏，并恢复全部界面栏。
    win.toggle_fullscreen()
    app.processEvents()
    assert win.isFullScreen()
    win._escape_to_select()
    app.processEvents()
    assert not win.isFullScreen()
    assert win.menuBar().isVisible()
    assert win.statusBar().isVisible()
    print("[OK] ESC 退出全屏")

    img = QImage(40, 20, QImage.Format.Format_ARGB32)
    img.fill(QColor(200, 0, 0))
    view._add_object(img, "signature", 0, QPointF(50, 50), 180.0)
    assert len(view.objects) == 1
    assert view._content_delete_shortcut.context() == \
        Qt.ShortcutContext.WidgetShortcut
    view.page_view.select(view.objects[0]["id"])
    view._content_delete_shortcut.activated.emit()
    assert len(view.objects) == 0
    view._add_object(img, "signature", 0, QPointF(50, 50), 180.0)
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
    assert view._inline_box.width() == 620
    assert view._inline_box.styleSheet() == ""
    assert view._inline_box.layout().count() == 2
    for object_name in ("inlineTextInput", "inlineTextFont",
                        "inlineTextSize", "inlineTextColor",
                        "inlineTextOk", "inlineTextCancel"):
        assert view._inline_box.findChild(QWidget, object_name) is not None
    assert view._inline_box.findChild(
        SignatureFontComboBox, "inlineTextFont") is not None
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
    dark_about = AboutDialog(win)
    assert dark_about.findChild(QWidget, "aboutTitleBar").property(
        "do_theme_dark") is True
    dark_about.close()
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
