"""签名工具从文字修改模式切换与放置的回归测试。"""
import os
import math
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

from document_view import DocumentView


class SignatureModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        fd, self.path = tempfile.mkstemp(prefix="do-editor-sign-mode-",
                                         suffix=".pdf")
        os.close(fd)
        doc = pymupdf.open()
        doc.new_page(width=400, height=500)
        doc.save(self.path)
        doc.close()

    def tearDown(self):
        try:
            os.remove(self.path)
        except OSError:
            pass

    def _signature_image(self):
        image = QImage(120, 40, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        image.setPixelColor(20, 20, QColor("black"))
        return image

    def test_design_and_library_signatures_place_from_replace_text_mode(self):
        view = DocumentView()
        self.assertTrue(view.load(self.path))
        image = self._signature_image()

        # 签名设计路径。
        view.set_mode("replace_text")
        self.assertTrue(view.page_view._edit_overlay)
        view._prepare_sign(image, match_image_scale=False)
        self.assertEqual(view.current_mode, "sign")
        self.assertFalse(view.page_view._edit_overlay)
        view._on_point(0, QPointF(60, 80))
        self.assertEqual(view.objects[-1]["kind"], "signature")
        self.assertIsNone(view.pending_sign_qimg)
        self.assertEqual(view.current_mode, "replace_text")
        self.assertTrue(view.page_view._edit_overlay)

        # 签名库路径使用同一入口，但采用图片式等比初始尺寸。
        view.set_mode("replace_text")
        self.assertTrue(view.page_view._edit_overlay)
        view._prepare_sign(image, match_image_scale=True)
        self.assertFalse(view.page_view._edit_overlay)
        view._on_point(0, QPointF(80, 160))
        self.assertEqual(view.objects[-1]["kind"], "signature")
        self.assertIsNone(view.pending_sign_qimg)
        self.assertEqual(view.current_mode, "replace_text")

        view._bake_objects()
        self.assertEqual(len(view.doc[0].get_images(full=True)), 2)
        view.close_doc()

    def test_saved_signature_can_move_and_delete_only_in_edit_mode(self):
        view = DocumentView()
        self.assertTrue(view.load(self.path))
        view._add_object(self._signature_image(), "signature", 0,
                         QPointF(60, 80), 120.0)
        view._bake_objects()
        view.page_view.invalidate_text_cache(0)

        image_line = next(item for item in view.page_view._edit_line_hits(0)
                          if item.get("kind") == "image")
        original = image_line["rect"]
        view._on_text_line_clicked(0, image_line)
        self.assertIsNotNone(view._selected_pdf_content)
        moved = original.translated(15.0, 9.0)
        view._on_pdf_image_changed(0, moved, original)
        self.assertIsNotNone(view._selected_pdf_content)

        view.set_mode("view")
        self.assertIsNone(view.page_view.selected_id())
        self.assertIsNone(view._selected_pdf_content)
        self.assertFalse(view.page_view._edit_overlay)

        view.set_mode("replace_text")
        moved_line = next(item for item in view.page_view._edit_line_hits(0)
                          if item.get("kind") == "image")
        view._on_text_line_clicked(0, moved_line)
        view.delete_selected()
        # PDF 资源字典允许保留未使用的图片引用；以页面实际绘制记录判断。
        self.assertFalse(any(item[0] == "fill-image"
                             for item in view.doc[0].get_bboxlog()))
        view.close_doc()

    def test_read_mode_does_not_activate_signature_object(self):
        view = DocumentView()
        self.assertTrue(view.load(self.path))
        view._add_object(self._signature_image(), "signature", 0,
                         QPointF(60, 80), 120.0)
        signature = view.objects[-1]
        pv = view.page_view
        center = QPointF(signature["rect"].center().x() * pv._zoom,
                         pv._offsets[0] +
                         signature["rect"].center().y() * pv._zoom)

        view.set_mode("view")
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress, center,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        pv.mousePressEvent(press)
        self.assertIsNone(pv.selected_id())
        self.assertIsNone(pv._drag)

        view.set_mode("replace_text")
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress, center,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        pv.mousePressEvent(press)
        self.assertEqual(pv.selected_id(), signature["id"])
        self.assertIsNotNone(pv._drag)
        view.close_doc()

    def test_signature_arbitrary_rotation_is_undoable_and_saves(self):
        view = DocumentView()
        self.assertTrue(view.load(self.path))
        view._add_object(self._signature_image(), "signature", 0,
                         QPointF(80, 100), 120.0)
        signature = view.objects[-1]
        original = QRectF(signature["rect"])
        view._on_object_rotated(signature["id"], 32.0, 0.0)
        self.assertAlmostEqual(signature["rotation"], 32.0)
        self.assertTrue(view.undo())
        signature = view.objects[-1]
        self.assertAlmostEqual(float(signature.get("rotation", 0.0)), 0.0)

        view._on_object_rotated(signature["id"], 32.0, 0.0)
        view._bake_objects()
        bbox = pymupdf.Rect(view.doc[0].get_image_info(xrefs=True)[0]["bbox"])
        radians = math.radians(32.0)
        expected_w = abs(original.width() * math.cos(radians)) + \
            abs(original.height() * math.sin(radians))
        expected_h = abs(original.width() * math.sin(radians)) + \
            abs(original.height() * math.cos(radians))
        self.assertAlmostEqual(bbox.width, expected_w, delta=0.5)
        self.assertAlmostEqual(bbox.height, expected_h, delta=0.5)
        view.close_doc()

    def test_signature_rotation_handle_drag(self):
        view = DocumentView()
        self.assertTrue(view.load(self.path))
        view._add_object(self._signature_image(), "signature", 0,
                         QPointF(80, 100), 120.0)
        signature = view.objects[-1]
        pv = view.page_view
        rect = pv._widget_rect(0, signature["rect"])
        center = rect.center()
        handle = pv._rotation_handle_point(rect)
        target = pv._rotate_widget_point(handle, center, 45.0)
        pv.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, handle,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
        pv.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove, target,
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
        pv.mouseReleaseEvent(QMouseEvent(
            QEvent.Type.MouseButtonRelease, target,
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier))
        self.assertAlmostEqual(float(signature.get("rotation", 0.0)),
                               45.0, delta=0.5)
        view.close_doc()


if __name__ == "__main__":
    unittest.main()
