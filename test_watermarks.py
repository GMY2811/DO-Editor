"""水印管理回归测试：持久识别、修改、删除和外部候选隔离。"""
import os
import tempfile
import unittest

import pymupdf

import backend


class WatermarkTests(unittest.TestCase):
    def make_doc(self, pages=2):
        doc = pymupdf.open()
        for index in range(pages):
            page = doc.new_page(width=400, height=500)
            page.insert_text((40, 80), f"BODY PAGE {index + 1}", fontsize=12)
        return doc

    def reopen(self, doc):
        path = os.path.join(tempfile.gettempdir(),
                            f"do-editor-watermark-{os.getpid()}.pdf")
        if os.path.exists(path):
            os.remove(path)
        doc.save(path, garbage=3, deflate=True)
        doc.close()
        reopened = pymupdf.open(path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return reopened

    def test_owned_text_watermark_survives_reopen_update_and_delete(self):
        doc = self.make_doc()
        watermark_id = backend.add_watermark(
            doc, "CONFIDENTIAL", fontsize=36, opacity=0.3,
            rotate=45, tiled=False)
        self.assertTrue(watermark_id)
        doc = self.reopen(doc)
        records = backend.list_watermarks(doc)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["id"], watermark_id)
        self.assertEqual(record["text"], "CONFIDENTIAL")
        self.assertEqual(record["pages"], [0, 1])
        self.assertIn("BODY PAGE 1", doc[0].get_text())

        self.assertTrue(backend.update_watermark(
            doc, record, kind="text", text="REVIEWED", fontsize=30,
            color=(1, 0, 0), opacity=0.4, rotate=30, tiled=False))
        self.assertNotIn("CONFIDENTIAL", doc[0].get_text())
        self.assertIn("REVIEWED", doc[0].get_text())
        updated = backend.list_watermarks(doc)[0]
        self.assertEqual(updated["text"], "REVIEWED")

        self.assertGreater(backend.remove_watermark(doc, updated), 0)
        self.assertEqual(backend.list_watermarks(doc), [])
        self.assertNotIn("REVIEWED", doc[0].get_text())
        self.assertIn("BODY PAGE 1", doc[0].get_text())
        doc.close()

    def test_owned_image_watermark_keeps_original_source(self):
        source = pymupdf.open()
        page = source.new_page(width=80, height=40)
        page.insert_text((5, 25), "LOGO", fontsize=16)
        png = page.get_pixmap(alpha=True).tobytes("png")
        source.close()

        doc = self.make_doc()
        watermark_id = backend.add_image_watermark(
            doc, None, image_bytes=png, image_name="logo.png",
            opacity=0.25, rotate=20, tiled=False, scale=0.3)
        self.assertTrue(watermark_id)
        doc = self.reopen(doc)
        record = backend.list_watermarks(doc)[0]
        self.assertEqual(record["kind"], "image")
        self.assertEqual(record["image_name"], "logo.png")
        self.assertEqual(backend.watermark_source_bytes(doc, record), png)
        self.assertGreater(backend.remove_watermark(doc, record), 0)
        self.assertIn("BODY PAGE 1", doc[0].get_text())
        doc.close()

    def test_acrobat_style_ocg_is_detected_and_hidden(self):
        doc = self.make_doc(1)
        ocg = doc.add_ocg("Watermark")
        page = doc[0]
        page.insert_text((80, 250), "ADOBE WATERMARK", fontsize=32,
                         fill_opacity=0.3, oc=ocg)
        records = backend.list_watermarks(doc)
        external = [x for x in records if x["origin"] == "acrobat-ocg"]
        self.assertEqual(len(external), 1)
        self.assertTrue(backend.remove_watermark(doc, external[0]))
        self.assertIn(ocg, doc.get_layer(-1).get("off", []))
        self.assertFalse(any(x["origin"] == "acrobat-ocg"
                             for x in backend.list_watermarks(doc)))
        self.assertIn("BODY PAGE 1", doc[0].get_text())
        self.assertNotIn("ADOBE WATERMARK", doc[0].get_text())
        doc.close()

    def test_fixedprint_watermark_annotation_is_deleted_only(self):
        doc = self.make_doc(1)
        page = doc[0]
        annot_xref = doc.get_new_xref()
        doc.update_object(annot_xref,
                          f"<< /Type /Annot /Subtype /Watermark "
                          f"/Rect [50 50 200 100] /P {page.xref} 0 R >>")
        doc.xref_set_key(page.xref, "Annots", f"[{annot_xref} 0 R]")
        page = doc.reload_page(page)
        fixed = [x for x in backend.list_watermarks(doc)
                 if x["origin"] == "acrobat-fixed"]
        self.assertEqual(len(fixed), 1)
        self.assertEqual(fixed[0]["annot_xref"], annot_xref)
        self.assertEqual(backend.remove_watermark(doc, fixed[0]), 1)
        self.assertEqual(list(doc[0].annots() or []), [])
        self.assertIn("BODY PAGE 1", doc[0].get_text())
        doc.close()

    def test_isolated_candidate_deletion_preserves_body_stream(self):
        doc = self.make_doc()
        for page in doc:
            point = pymupdf.Point(80, 260)
            matrix = pymupdf.Matrix(0.8, 0.6, -0.6, 0.8, 0, 0)
            page.insert_text(point, "SUSPECT", fontsize=38,
                             fill_opacity=0.3, morph=(point, matrix))
        candidates = backend.detect_watermark_candidates(doc)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["text"], "SUSPECT")
        self.assertEqual(len(candidates[0]["pages"]), 2)
        self.assertEqual(backend.remove_watermark(doc, candidates[0]), 2)
        for index, page in enumerate(doc):
            self.assertIn(f"BODY PAGE {index + 1}", page.get_text())
            self.assertNotIn("SUSPECT", page.get_text())
        doc.close()

    def test_opaque_large_rotated_watermark_is_detected_and_directly_edited(self):
        """回归用户样本：灰色 opacity=1、90pt、旋转文字也属于水印。"""
        doc = pymupdf.open()
        page = doc.new_page(width=600, height=500)
        page.insert_text((40, 80), "BODY PAGE 1", fontsize=12)
        point = pymupdf.Point(100, 300)
        matrix = pymupdf.Matrix(0.9396926, 0.34202015,
                                -0.34202015, 0.9396926, 0, 0)
        page.insert_text(point, "UPDATED", fontname="helv", fontsize=90,
                         color=(0.9, 0.9, 0.9), morph=(point, matrix))

        candidates = backend.detect_watermark_candidates(doc)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["text"], "UPDATED")

        hit = page.search_for("UPDATED")[0]
        record = backend.find_isolated_text_object(
            doc, 0, "UPDATED", list(hit))
        self.assertIsNotNone(record)
        body_xref = page.get_contents()[0]
        body_before = doc.xref_stream(body_xref)
        self.assertTrue(backend.replace_isolated_text_object(
            doc, record, "APPROVED"))
        self.assertIn("APPROVED", page.get_text())
        self.assertNotIn("UPDATED", page.get_text())
        self.assertEqual(doc.xref_stream(body_xref), body_before)
        self.assertTrue(backend.replace_isolated_text_object(
            doc, record, "审核→"))
        self.assertIn("审核→", page.get_text())
        self.assertEqual(doc.xref_stream(body_xref), body_before)
        self.assertTrue(backend.replace_isolated_text_object(doc, record, ""))
        self.assertNotIn("审核→", page.get_text())
        self.assertIn("BODY PAGE 1", page.get_text())
        self.assertEqual(doc.xref_stream(body_xref), body_before)
        doc.close()

    def test_isolated_image_is_a_safe_direct_delete_object(self):
        src = pymupdf.open()
        sp = src.new_page(width=20, height=20)
        sp.draw_rect((1, 1, 19, 19), color=(1, 0, 0), fill=(1, 0, 0))
        png = sp.get_pixmap().tobytes("png")
        src.close()
        doc = self.make_doc(1)
        page = doc[0]
        body_xref = page.get_contents()[0]
        body_before = doc.xref_stream(body_xref)
        page.insert_image((100, 150, 260, 310), stream=png, overlay=True)
        records = backend.isolated_image_objects(doc, 0)
        self.assertEqual(len(records), 1)
        original_rect = records[0]["rect"]
        replacement_doc = pymupdf.open()
        replacement_page = replacement_doc.new_page(width=30, height=10)
        replacement_page.draw_rect(
            (1, 1, 29, 9), color=(0, 0, 1), fill=(0, 0, 1))
        replacement_png = replacement_page.get_pixmap().tobytes("png")
        replacement_doc.close()
        self.assertTrue(backend.replace_isolated_image_object(
            doc, records[0], replacement_png))
        after = backend.isolated_image_objects(doc, 0)
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]["rect"], original_rect)
        self.assertEqual(doc.xref_stream(body_xref), body_before)
        self.assertEqual(backend.remove_watermark(doc, after[0]), 1)
        self.assertIn("BODY PAGE 1", page.get_text())
        self.assertEqual(doc.xref_stream(body_xref), body_before)
        doc.close()

    def test_ordinary_isolated_text_is_not_promoted_to_watermark_object(self):
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=500)
        page.insert_text((40, 80), "Ordinary body line", fontsize=12)
        hit = page.search_for("Ordinary body line")[0]
        self.assertIsNone(backend.find_isolated_text_object(
            doc, 0, "Ordinary body line", list(hit)))
        doc.close()


if __name__ == "__main__":
    unittest.main()
