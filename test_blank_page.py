"""侧边栏右键"插入/添加空白页"功能回归测试。"""
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
from PySide6.QtWidgets import QApplication

from document_view import DocumentView
import i18n as i18n_mod


def _drain_thumbnails(view, max_rounds=40):
    """缩略图分批异步渲染（QTimer），泵事件循环直到补齐。"""
    app = QApplication.instance()
    for _ in range(max_rounds):
        app.processEvents()
        if view.thumb_list.count() >= len(view.doc):
            break


class BlankPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        fd, self.path = tempfile.mkstemp(prefix="do-editor-blank-",
                                         suffix=".pdf")
        os.close(fd)
        doc = pymupdf.open()
        p0 = doc.new_page(width=400, height=500)
        p0.insert_text((40, 60), "page one")
        p1 = doc.new_page(width=300, height=200)
        p1.insert_text((40, 60), "page two")
        doc.save(self.path)
        doc.close()

    def tearDown(self):
        try:
            os.remove(self.path)
        except OSError:
            pass

    def _new_view(self):
        view = DocumentView()
        self.assertTrue(view.load(self.path))
        return view

    def test_insert_blank_page_after_selected(self):
        """右键"插入空白页"：新页插到选中页之后，尺寸与参考页一致。"""
        view = self._new_view()
        self.assertEqual(len(view.doc), 2)
        new_pno = view.insert_blank_page(0)
        self.assertEqual(new_pno, 1)
        self.assertEqual(len(view.doc), 3)
        # 新页尺寸 = 参考页（第 0 页）尺寸
        self.assertAlmostEqual(view.doc[1].rect.width, 400, delta=0.5)
        self.assertAlmostEqual(view.doc[1].rect.height, 500, delta=0.5)
        # 新页是空白页（无文本）
        self.assertEqual(view.doc[1].get_text().strip(), "")
        # 原第 1 页顺移到第 2 页
        self.assertIn("page two", view.doc[2].get_text())
        # 侧边栏缩略图同步重建为 3 页（分批异步，泵事件循环）
        _drain_thumbnails(view)
        self.assertEqual(view.thumb_list.count(), 3)
        self.assertTrue(view.modified)
        view.close()

    def test_add_blank_page_at_end(self):
        """空白处右键"添加空白页"：插到文档末尾，尺寸同最后一页。"""
        view = self._new_view()
        view._on_add_blank_page_empty()
        self.assertEqual(len(view.doc), 3)
        self.assertAlmostEqual(view.doc[2].rect.width, 300, delta=0.5)
        self.assertAlmostEqual(view.doc[2].rect.height, 200, delta=0.5)
        self.assertEqual(view.doc[2].get_text().strip(), "")
        _drain_thumbnails(view)
        self.assertEqual(view.thumb_list.count(), 3)
        view.close()

    def test_blank_page_survives_save_reload(self):
        """插入空白页后保存重开，页数与内容保持。"""
        view = self._new_view()
        view.insert_blank_page(0)
        fd, out_path = tempfile.mkstemp(prefix="do-editor-blank-save-",
                                        suffix=".pdf")
        os.close(fd)
        try:
            view.doc.save(out_path)
            view.doc.close()
            reopened = pymupdf.open(out_path)
            self.assertEqual(len(reopened), 3)
            self.assertIn("page one", reopened[0].get_text())
            self.assertEqual(reopened[1].get_text().strip(), "")
            self.assertIn("page two", reopened[2].get_text())
            reopened.close()
        finally:
            os.remove(out_path)
        view.close()

    def test_i18n_entries_exist(self):
        for key in ("insert_blank_page", "add_blank_page",
                    "insert_blank_done"):
            zh, en = i18n_mod._STRINGS[key]
            self.assertTrue(zh and en)
            self.assertTrue(i18n_mod.tr(key))


if __name__ == "__main__":
    unittest.main()
