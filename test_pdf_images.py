"""PDF 内嵌图片精确选择、挪动与删除回归测试。"""
import os
import math
import tempfile
import unittest
from io import BytesIO

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
from PIL import Image
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

import backend
from document_view import DocumentView


def _png(color, size=(24, 16)):
    stream = BytesIO()
    Image.new("RGB", size, color).save(stream, "PNG")
    return stream.getvalue()


class PdfImageObjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _mixed_page(self):
        doc = pymupdf.open()
        page = doc.new_page(width=420, height=520)
        page.insert_text((35, 45), "BODY MUST SURVIVE", fontsize=12)
        page.insert_image((50, 80, 150, 140), stream=_png("red"))
        page.insert_image((210, 180, 330, 250), stream=_png("blue"))
        streams = list(page.get_contents())
        # 模拟 Word / 排版软件常见的文字与多图共用内容流。
        combined = b"\n".join(doc.xref_stream(xref) for xref in streams)
        doc.update_stream(streams[0], combined)
        for xref in streams[1:]:
            doc.update_stream(xref, b"")
        return doc, page, streams[0]

    def test_delete_one_image_from_mixed_stream_preserves_body_and_other_image(self):
        doc, page, mixed_xref = self._mixed_page()
        body_before = page.get_text()
        records = backend.isolated_image_objects(doc, 0)
        self.assertEqual(len(records), 2)
        self.assertTrue(backend.remove_pdf_image_object(doc, records[1]))
        self.assertEqual(page.get_text(), body_before)
        self.assertIn(b"TJ", doc.xref_stream(mixed_xref))
        remaining = backend.isolated_image_objects(doc, 0)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["image_xref"], records[0]["image_xref"])
        doc.close()

    def test_delete_image_from_single_line_stream_preserves_following_page(self):
        doc = pymupdf.open()
        page = doc.new_page(width=420, height=520)
        page.insert_text((35, 45), "BEFORE IMAGE", fontsize=12)
        page.insert_image((50, 80, 150, 140), stream=_png("red"))
        page.insert_text((35, 190), "AFTER IMAGE MUST SURVIVE", fontsize=12)
        page.insert_image((210, 220, 330, 290), stream=_png("blue"))
        streams = list(page.get_contents())
        # 模拟把整页所有操作符压缩到同一行的 PDF 生成器。此场景会把
        # 无换行的 % 删除标记扩散成“注释掉后续整页”。
        combined = b" ".join(
            doc.xref_stream(xref).replace(b"\r", b" ").replace(b"\n", b" ")
            for xref in streams)
        doc.update_stream(streams[0], combined)
        for xref in streams[1:]:
            doc.update_stream(xref, b"")

        records = backend.isolated_image_objects(doc, 0)
        self.assertEqual(len(records), 2)
        self.assertTrue(backend.remove_pdf_image_object(doc, records[0]))
        text = page.get_text()
        self.assertIn("BEFORE IMAGE", text)
        self.assertIn("AFTER IMAGE MUST SURVIVE", text)
        self.assertEqual(len(backend.isolated_image_objects(doc, 0)), 1)
        self.assertEqual(backend.isolated_image_objects(doc, 0)[0]["image_xref"],
                         records[1]["image_xref"])
        self.assertNotIn(b"% DOEditor removed image",
                         doc.xref_stream(streams[0]))
        doc.close()

    def test_move_image_preserves_size_rotation_and_other_content(self):
        doc = pymupdf.open()
        page = doc.new_page(width=420, height=520)
        page.insert_text((35, 45), "BODY MUST SURVIVE", fontsize=12)
        page.insert_image((80, 100, 200, 180), stream=_png("green"), rotate=90)
        record = backend.isolated_image_objects(doc, 0)[0]
        before = pymupdf.Rect(record["rect"])
        self.assertTrue(backend.move_pdf_image_object(doc, record, 45, 30))
        after = pymupdf.Rect(backend.isolated_image_objects(doc, 0)[0]["rect"])
        self.assertAlmostEqual(after.x0 - before.x0, 45, delta=0.1)
        self.assertAlmostEqual(after.y0 - before.y0, 30, delta=0.1)
        self.assertAlmostEqual(after.width, before.width, delta=0.1)
        self.assertAlmostEqual(after.height, before.height, delta=0.1)
        self.assertIn("BODY MUST SURVIVE", page.get_text())
        reopened = pymupdf.open(stream=doc.tobytes(), filetype="pdf")
        persisted = pymupdf.Rect(
            backend.isolated_image_objects(reopened, 0)[0]["rect"])
        self.assertAlmostEqual(persisted.x0, after.x0, delta=0.1)
        self.assertAlmostEqual(persisted.y0, after.y0, delta=0.1)
        reopened.close()
        doc.close()

    def test_free_resize_rotated_image_preserves_other_content(self):
        doc = pymupdf.open()
        page = doc.new_page(width=420, height=520)
        page.insert_text((35, 45), "BODY MUST SURVIVE", fontsize=12)
        page.insert_image((80, 100, 200, 180), stream=_png("green"), rotate=90)
        record = backend.isolated_image_objects(doc, 0)[0]
        before = pymupdf.Rect(record["rect"])
        target = pymupdf.Rect(before.x0 + 18, before.y0 + 12,
                              before.x0 + before.width * 1.6,
                              before.y0 + before.height * 0.65)
        self.assertTrue(backend.resize_pdf_image_object(doc, record, target))
        after = pymupdf.Rect(backend.isolated_image_objects(doc, 0)[0]["rect"])
        for actual, expected in zip(after, target):
            self.assertAlmostEqual(actual, expected, delta=0.15)
        self.assertIn("BODY MUST SURVIVE", page.get_text())
        doc.close()

    def test_arbitrary_rotation_preserves_center_resource_and_body(self):
        doc = pymupdf.open()
        page = doc.new_page(width=420, height=520)
        page.insert_text((35, 45), "BODY MUST SURVIVE", fontsize=12)
        page.insert_image((80, 100, 200, 180), stream=_png("green"))
        record = backend.isolated_image_objects(doc, 0)[0]
        before = pymupdf.Rect(record["rect"])
        self.assertTrue(backend.rotate_pdf_image_object(doc, record, 37.0))
        after_record = backend.isolated_image_objects(doc, 0)[0]
        after = pymupdf.Rect(after_record["rect"])
        radians = math.radians(37.0)
        expected_w = abs(before.width * math.cos(radians)) + \
            abs(before.height * math.sin(radians))
        expected_h = abs(before.width * math.sin(radians)) + \
            abs(before.height * math.cos(radians))
        self.assertAlmostEqual(after.width, expected_w, delta=0.15)
        self.assertAlmostEqual(after.height, expected_h, delta=0.15)
        self.assertAlmostEqual(after.x0 + after.x1,
                               before.x0 + before.x1, delta=0.15)
        self.assertAlmostEqual(after.y0 + after.y1,
                               before.y0 + before.y1, delta=0.15)
        self.assertEqual(after_record["image_xref"], record["image_xref"])
        self.assertIn("BODY MUST SURVIVE", page.get_text())
        doc.close()

    def test_saved_image_rotation_has_live_preview_and_custom_cursor(self):
        doc = pymupdf.open()
        page = doc.new_page(width=420, height=520)
        page.insert_text((35, 45), "BODY MUST SURVIVE", fontsize=12)
        page.insert_image((80, 100, 200, 180), stream=_png("green"))
        record = backend.isolated_image_objects(doc, 0)[0]
        stream_xref = int(record["locations"][0]["stream_xref"])
        stream_before = doc.xref_stream(stream_xref)
        preview = backend.pdf_image_rotation_preview(doc, record, 1.0, 1.0)
        self.assertIsNotNone(preview)
        self.assertFalse(QImage.fromData(preview[0]).isNull())
        self.assertFalse(QImage.fromData(preview[1]).isNull())
        # 预览渲染结束后，真实 PDF 内容流必须原样恢复。
        self.assertEqual(doc.xref_stream(stream_xref), stream_before)

        view = DocumentView()
        view.doc = doc
        view.page_view.set_document(doc, 1.0, 1.0)
        view.page_view.set_edit_overlay(True)
        view.page_view.set_mode("point")
        rect = QRectF(*record["rect"][:2],
                      record["rect"][2] - record["rect"][0],
                      record["rect"][3] - record["rect"][1])
        view.page_view.set_edit_selection(0, rect, record)
        pv = view.page_view
        wr = pv._widget_rect(0, rect)
        handle = pv._rotation_handle_point(wr)
        target = pv._rotate_widget_point(handle, wr.center(), 35.0)
        pv._update_cursor(handle)
        self.assertEqual(pv.cursor().shape(), Qt.CursorShape.BitmapCursor)
        pv.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, handle,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
        pv.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove, target,
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
        self.assertIsNotNone(pv._edit_rotation_background)
        self.assertIsNotNone(pv._edit_rotation_source)
        self.assertAlmostEqual(pv._edit_rotation_preview, 35.0, delta=0.5)
        # 不触发 release，避免本单元测试提交文档变换；清理所有权。
        view.doc = None
        pv.set_document(None, 1.0, 1.0)
        doc.close()

    def test_document_view_move_is_undoable(self):
        fd, path = tempfile.mkstemp(prefix="do-editor-image-move-",
                                    suffix=".pdf")
        os.close(fd)
        try:
            doc = pymupdf.open()
            page = doc.new_page(width=400, height=500)
            page.insert_text((30, 40), "BODY")
            page.insert_image((70, 90, 170, 150), stream=_png("purple"))
            doc.save(path)
            doc.close()

            view = DocumentView()
            self.assertTrue(view.load(path))
            view.set_mode("replace_text")
            record = backend.isolated_image_objects(view.doc, 0)[0]
            before = QRectF(record["rect"][0], record["rect"][1],
                            record["rect"][2] - record["rect"][0],
                            record["rect"][3] - record["rect"][1])
            view._selected_pdf_content = record
            view.page_view.set_edit_selection(0, before)
            moved = QRectF(before).translated(35, 20)
            view._on_pdf_image_changed(0, moved, before)
            actual = pymupdf.Rect(
                backend.isolated_image_objects(view.doc, 0)[0]["rect"])
            self.assertAlmostEqual(actual.x0 - before.x(), 35, delta=0.1)
            self.assertAlmostEqual(actual.y0 - before.y(), 20, delta=0.1)
            self.assertTrue(view.modified)
            self.assertTrue(view.undo())
            restored = pymupdf.Rect(
                backend.isolated_image_objects(view.doc, 0)[0]["rect"])
            self.assertAlmostEqual(restored.x0, before.x(), delta=0.1)
            self.assertAlmostEqual(restored.y0, before.y(), delta=0.1)

            # DocumentView 的同一信号也负责自由宽高缩放，并可一步撤销。
            view.set_mode("replace_text")
            record = backend.isolated_image_objects(view.doc, 0)[0]
            original = pymupdf.Rect(record["rect"])
            old_qrect = QRectF(original.x0, original.y0,
                               original.width, original.height)
            resized = QRectF(original.x0 + 8, original.y0 + 6,
                             original.width * 1.45, original.height * 0.7)
            view._selected_pdf_content = record
            view.page_view.set_edit_selection(0, old_qrect)
            view._on_pdf_image_changed(0, resized, old_qrect)
            actual = pymupdf.Rect(
                backend.isolated_image_objects(view.doc, 0)[0]["rect"])
            self.assertAlmostEqual(actual.width, resized.width(), delta=0.15)
            self.assertAlmostEqual(actual.height, resized.height(), delta=0.15)
            self.assertTrue(view.undo())
            restored = pymupdf.Rect(
                backend.isolated_image_objects(view.doc, 0)[0]["rect"])
            self.assertAlmostEqual(restored.width, original.width, delta=0.15)
            self.assertAlmostEqual(restored.height, original.height, delta=0.15)
            view.close_doc()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
