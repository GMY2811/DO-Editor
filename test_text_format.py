"""修改文字时保留原 PDF 字体与格式的回归测试。"""
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
from PySide6.QtWidgets import QApplication

import backend
from document_view import DocumentView


class TextFormatPreservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _make_embedded_font_doc():
        font_path = r"C:\Windows\Fonts\arialbd.ttf"
        if not os.path.exists(font_path):
            return None
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=300)
        page.insert_font(fontname="OriginalEmbedded", fontfile=font_path)
        page.insert_text((55, 90), "FORMAT123", fontname="OriginalEmbedded",
                         fontsize=13, color=(0.2, 0.4, 0.7))
        return doc

    def test_direct_edit_keeps_font_size_color_and_origin(self):
        doc = self._make_embedded_font_doc()
        if doc is None:
            self.skipTest("Windows Arial Bold is unavailable")
        # 经过序列化后再测，覆盖真实 PDF 的嵌入字体/ToUnicode 结构。
        doc = pymupdf.open(stream=doc.tobytes(), filetype="pdf")
        page = doc[0]
        before = next(s for b in page.get_text("dict")["blocks"]
                      if b.get("type") == 0
                      for line in b.get("lines", [])
                      for s in line.get("spans", [])
                      if s.get("text") == "FORMAT123")
        record = backend.find_direct_text_object(
            doc, 0, before["text"], before["bbox"], before["font"])
        self.assertIsNotNone(record)
        # 只使用原字体已嵌入的字符，重排内容但不触发字体替换。
        self.assertTrue(backend.replace_direct_text_object(
            doc, record, "FORMAT321"))
        page = doc.reload_page(page)
        after = next(s for b in page.get_text("dict")["blocks"]
                     if b.get("type") == 0
                     for line in b.get("lines", [])
                     for s in line.get("spans", [])
                     if s.get("text") == "FORMAT321")
        for key in ("font", "size", "color", "flags", "origin"):
            self.assertEqual(after[key], before[key], key)
        doc.close()

    def test_standard_helvetica_edit_keeps_format_and_tj_structure(self):
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=300)
        page.insert_text((43, 77), "PLAIN123", fontname="helv",
                         fontsize=11.5, color=(0.7, 0.1, 0.3))
        doc = pymupdf.open(stream=doc.tobytes(), filetype="pdf")
        page = doc[0]
        before = next(s for b in page.get_text("dict")["blocks"]
                      if b.get("type") == 0
                      for line in b.get("lines", [])
                      for s in line.get("spans", []))
        record = backend.find_direct_text_object(
            doc, 0, before["text"], before["bbox"], before["font"])
        self.assertIsNotNone(record)
        old_token = record["source_token"]
        self.assertTrue(backend.replace_direct_text_object(
            doc, record, "PLAIN321"))
        new_stream = doc.xref_stream(record["stream_xref"])
        new_token = new_stream[record["token_start"]:
                               record["token_start"] + len(old_token)]
        self.assertEqual(new_token.rstrip().endswith(b"TJ"),
                         old_token.rstrip().endswith(b"TJ"))
        page = doc.reload_page(page)
        after = next(s for b in page.get_text("dict")["blocks"]
                     if b.get("type") == 0
                     for line in b.get("lines", [])
                     for s in line.get("spans", []))
        self.assertEqual(after["text"], "PLAIN321")
        for key in ("font", "size", "color", "flags", "origin"):
            self.assertEqual(after[key], before[key], key)
        doc.close()

    def test_document_view_edit_uses_direct_format_preserving_path(self):
        doc = self._make_embedded_font_doc()
        if doc is None:
            self.skipTest("Windows Arial Bold is unavailable")
        fd, path = tempfile.mkstemp(prefix="do-editor-text-format-",
                                    suffix=".pdf")
        os.close(fd)
        try:
            doc.save(path)
            doc.close()
            view = DocumentView()
            self.assertTrue(view.load(path))
            before = next(s for b in view.doc[0].get_text("dict")["blocks"]
                          if b.get("type") == 0
                          for line in b.get("lines", [])
                          for s in line.get("spans", []))
            line = next(item for item in view.page_view._edit_line_hits(0)
                        if item.get("text") == "FORMAT123")
            view.set_mode("replace_text")
            view._begin_row_edit(0, line)
            self.assertIsNotNone(view._row_edit_meta.get("direct_record"))
            view._row_edit.selectAll()
            view._row_edit.insertPlainText("FORMAT321")
            self.app.processEvents()
            view._commit_row_edit(commit=True)
            after = next(s for b in view.doc[0].get_text("dict")["blocks"]
                         if b.get("type") == 0
                         for row in b.get("lines", [])
                         for s in row.get("spans", [])
                         if s.get("text") == "FORMAT321")
            for key in ("font", "size", "color", "flags", "origin"):
                self.assertEqual(after[key], before[key], key)
            view.close_doc()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def test_missing_cjk_glyph_falls_back_and_next_input_still_works(self):
        doc = self._make_embedded_font_doc()
        if doc is None:
            self.skipTest("Windows Arial Bold is unavailable")
        fd, path = tempfile.mkstemp(prefix="do-editor-cjk-fallback-",
                                    suffix=".pdf")
        os.close(fd)
        try:
            doc.save(path)
            doc.close()
            view = DocumentView()
            self.assertTrue(view.load(path))
            line = next(item for item in view.page_view._edit_line_hits(0)
                        if item.get("text") == "FORMAT123")
            view.set_mode("replace_text")
            view._begin_row_edit(0, line)
            self.assertIsNotNone(view._row_edit_meta.get("direct_record"))

            view._row_edit.selectAll()
            view._row_edit.insertPlainText("汉字")
            self.app.processEvents()
            self.assertIn("汉字", view.doc[0].get_text("text"))
            self.assertIsNone(view._row_edit_meta.get("direct_record"))

            # 曾经输入过缺失字形后，再改回英文也必须继续实时写入。
            view._row_edit.selectAll()
            view._row_edit.insertPlainText("RECOVER321")
            self.app.processEvents()
            self.assertIn("RECOVER321", view.doc[0].get_text("text"))
            view._commit_row_edit(commit=True)
            view.close_doc()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
