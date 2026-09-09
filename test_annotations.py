"""PDF 原生批注保存、重载、再次编辑回归测试。"""
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import QApplication

from document_view import DocumentView


class AnnotationPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        fd, self.path = tempfile.mkstemp(prefix="do-editor-annotations-",
                                         suffix=".pdf")
        os.close(fd)
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=500)
        page.insert_text((40, 60), "annotation persistence")
        doc.save(self.path)
        doc.close()

    def tearDown(self):
        try:
            os.remove(self.path)
        except OSError:
            pass

    @staticmethod
    def _native_annots(view):
        return list(view.doc[0].annots() or [])

    def test_save_reload_edit_delete_without_duplicates(self):
        view = DocumentView()
        self.assertTrue(view.load(self.path))
        self.assertTrue(view._add_note_at(
            "保存后仍可编辑", 0, QPointF(50, 80)))
        view._add_annotation_object(
            "highlight", 0, QRectF(40, 120, 150, 22), QColor("#ffd400"))
        view._add_annotation_object(
            "underline", 0, QRectF(40, 155, 150, 20), QColor("#d02020"))
        view._add_annotation_object(
            "strikeout", 0, QRectF(40, 190, 150, 20), QColor("#d02020"))
        view._add_annotation_object(
            "rect", 0, QRectF(35, 225, 170, 45), QColor("#d02020"))
        view._add_annotation_object(
            "line", 0, QRectF(40, 290, 150, 25), QColor("#d02020"),
            [QPointF(40, 290), QPointF(190, 315)])
        view._add_annotation_object(
            "ink", 0, QRectF(40, 340, 150, 30), QColor("#2050d0"),
            [QPointF(40, 355), QPointF(90, 340), QPointF(190, 370)])

        self.assertTrue(view._save_to(self.path))
        self.assertEqual(len(self._native_annots(view)), 7)
        self.assertEqual(len(view.objects), 7)
        self.assertTrue(all(o.get("native_proxy") for o in view.objects))
        self.assertEqual({o["kind"] for o in view.objects}, {
            "note", "highlight", "underline", "strikeout", "rect", "line", "ink"})
        note = next(o for o in view.objects if o["kind"] == "note")
        self.assertEqual(note["text"], "保存后仍可编辑")

        # 未修改直接再次保存，原生批注数量不能翻倍。
        self.assertTrue(view._save_to(self.path))
        self.assertEqual(len(self._native_annots(view)), 7)

        # 模拟 PageView 拖动：共享对象已先变成新矩形，再发送旧矩形。
        note = next(o for o in view.objects if o["kind"] == "note")
        old_rect = QRectF(note["rect"])
        new_rect = QRectF(180, 210, old_rect.width(), old_rect.height())
        note["rect"] = QRectF(new_rect)
        view._on_object_changed(note["id"], new_rect, old_rect)
        self.assertFalse(note.get("native_proxy", False))
        self.assertTrue(view._save_to(self.path))
        self.assertEqual(len(self._native_annots(view)), 7)
        reloaded_note = next(o for o in view.objects if o["kind"] == "note")
        self.assertAlmostEqual(reloaded_note["rect"].x(), 180, delta=0.1)
        self.assertAlmostEqual(reloaded_note["rect"].y(), 210, delta=0.1)

        highlight = next(o for o in view.objects if o["kind"] == "highlight")
        view.delete_object(highlight["id"])
        self.assertTrue(view._save_to(self.path))
        self.assertEqual(len(self._native_annots(view)), 6)
        self.assertNotIn("highlight", [o["kind"] for o in view.objects])
        view.close_doc()

    def test_saved_annotation_is_active_in_read_mode(self):
        view = DocumentView()
        self.assertTrue(view.load(self.path))
        view._add_annotation_object(
            "highlight", 0, QRectF(40, 120, 150, 22), QColor("#ffd400"))
        self.assertTrue(view._save_to(self.path))
        annotation = next(o for o in view.objects if o["kind"] == "highlight")
        self.assertTrue(annotation.get("native_proxy"))

        view.set_mode("view")
        pv = view.page_view
        pv.select(None)
        center = QPointF(annotation["rect"].center().x() * pv._zoom,
                         pv._offsets[0] +
                         annotation["rect"].center().y() * pv._zoom)
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress, center,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        pv.mousePressEvent(press)
        self.assertEqual(pv.selected_id(), annotation["id"])
        self.assertIsNotNone(pv._drag)

        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease, center,
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier)
        pv.mouseReleaseEvent(release)
        view.delete_selected()
        self.assertNotIn(annotation["id"], [o["id"] for o in view.objects])
        self.assertEqual(len(self._native_annots(view)), 0)
        view.close_doc()

    def test_note_content_appears_on_hover_without_click(self):
        view = DocumentView()
        self.assertTrue(view.load(self.path))
        self.assertTrue(view._add_note_at(
            "无需点击即可查看", 0, QPointF(80, 110)))
        note = next(o for o in view.objects if o["kind"] == "note")

        view.set_mode("view")
        pv = view.page_view
        pv.select(None)
        center = QPointF(note["rect"].center().x() * pv._zoom,
                         pv._offsets[0] +
                         note["rect"].center().y() * pv._zoom)
        pv._update_cursor(center)

        self.assertIsNone(pv.selected_id())
        self.assertEqual(pv._hover_note_id, note["id"])
        self.assertIn("无需点击即可查看", pv._note_preview.text())

        pv._update_cursor(QPointF(350, 450))
        self.assertIsNone(pv._hover_note_id)
        view.close_doc()


if __name__ == "__main__":
    unittest.main()
