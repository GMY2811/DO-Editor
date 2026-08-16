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
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QImage
    import icons
    from main_window import MainWindow
    from sign_dialog import save_signature, list_signatures, qimage_to_png_bytes, DrawingCanvas

    app = QApplication([])

    for name in icons.ICONS:
        assert not icons.get(name).isNull(), name
    print("[OK] icons (%d 个)" % len(icons.ICONS))

    win = MainWindow()
    win.open_file(sample)
    view = win.current_view()
    assert view.doc is not None
    assert view.page_view.page_count() == 5
    assert view.thumb_list.count() == 5
    assert view.bookmark_tree.topLevelItemCount() == 2   # 两个一级书签
    view.set_mode("highlight")
    view.set_mode("text_select")
    view.set_mode("replace_text")
    view.set_mode("view")
    print("[OK] 主窗口 + 连续滚动 + 书签 + 模式")

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
    print("[OK] 文本选择 + 字体 + inline 编辑器")

    win.set_theme("dark")
    assert win.theme_mode == "dark"
    win.set_theme("light")
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
