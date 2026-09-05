"""打印分辨率、物理尺寸和分块输出回归测试，不向实体打印机发送任务。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import pymupdf
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QRectF, QMarginsF
from PySide6.QtGui import QImage, QPainter, QColor, QPageSize, QPageLayout
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtTest import QTest
from document_view import DocumentView
from print_dialog import PrintDialog, PAPERS, print_target_size, SCALE_ACTUAL, SCALE_CUSTOM, SCALE_FIT


class PrintQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_a4_render_retains_300dpi_and_rotation(self):
        with pymupdf.open() as doc:
            page = doc.new_page(width=595, height=842)
            page.insert_text((72, 100), 'Fine print 0123456789', fontsize=8)
            view = DocumentView()
            try:
                image = view._render_print_page(0, 300 / 72, doc=doc)
                self.assertEqual((image.width(), image.height()), (2480, 3509))
                rotated = view._render_print_page(0, 300 / 72, 90, True, doc)
                self.assertEqual((rotated.width(), rotated.height()), (3509, 2480))
            finally:
                view.close()

    def test_physical_size_and_nup_fit(self):
        rect = pymupdf.Rect(0, 0, 72, 144)
        cell = QRectF(0, 0, 600, 600)
        size = DocumentView._print_target_size
        self.assertEqual(size(rect, cell, 600, SCALE_ACTUAL), (600, 1200))
        self.assertEqual(size(rect, cell, 600, SCALE_CUSTOM, .5), (300, 600))
        self.assertEqual(size(rect, cell, 600, SCALE_ACTUAL, 1, 90), (1200, 600))
        self.assertEqual(size(rect, cell, 600, SCALE_FIT), (300, 600))

    def test_setting_changes_coalesce_and_reuse_preview(self):
        with pymupdf.open() as doc:
            doc.new_page().insert_text((72, 100), 'Preview cache')
            dlg = PrintDialog(doc)
            try:
                with patch.object(dlg, '_configured_printer',
                                  wraps=dlg._configured_printer) as driver, \
                     patch.object(pymupdf.Page, 'get_pixmap', autospec=True,
                                  side_effect=pymupdf.Page.get_pixmap) as render:
                    dlg._refresh_preview()
                    self.assertEqual(driver.call_count, 1)
                    self.assertEqual(render.call_count, 1)
                    with patch.object(dlg, '_preview_image', wraps=dlg._preview_image) as image:
                        dlg._rb_custom.setChecked(True)
                        for value in range(50, 151):
                            dlg._scale_spin.setValue(value)
                        dlg._rb_pos_top.setChecked(True)
                        self.assertEqual(image.call_count, 0)
                        QTest.qWait(180)
                        self.assertEqual(image.call_count, 1)
                        self.assertEqual(driver.call_count, 1)
                        self.assertEqual(render.call_count, 1)
                        self.assertIn('150%', dlg._scale_badge.text())
                    dlg._rb_gray.setChecked(True)
                    QTest.qWait(180)
                    self.assertEqual(render.call_count, 2)
                    self.assertEqual(driver.call_count, 1)
            finally:
                dlg.close()
                dlg.deleteLater()

    def test_tiles_preserve_pixels_across_boundaries(self):
        source = QImage(2107, 2031, QImage.Format.Format_RGB32)
        source.fill(QColor('white'))
        painter = QPainter(source)
        painter.fillRect(1998, 0, 5, 2031, QColor('black'))
        painter.fillRect(0, 1998, 2107, 5, QColor('red'))
        painter.end()
        output = QImage(source.size(), source.format())
        output.fill(QColor('blue'))
        painter = QPainter(output)
        DocumentView._draw_print_image(painter, QRectF(0, 0, 2107, 2031), source)
        painter.end()
        self.assertEqual(bytes(source.constBits()), bytes(output.constBits()))

    def test_preview_and_pdf_print_use_same_scale(self):
        with tempfile.TemporaryDirectory() as folder:
            source = str(Path(folder) / 'source.pdf')
            with pymupdf.open() as doc:
                page = doc.new_page(width=595, height=842)
                page.draw_rect(pymupdf.Rect(240, 400, 312, 410),
                               color=None, fill=(0, 0, 0))
                doc.save(source)
            view = DocumentView()
            view.load(source)
            widths = []
            try:
                cases = [(SCALE_FIT, 100), (SCALE_ACTUAL, 100)] + [
                    (SCALE_CUSTOM, percent) for percent in (29, 50, 100, 125, 200)]
                for mode, percent in cases:
                    output = str(Path(folder) / f'{mode}-{percent}.pdf')
                    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
                    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
                    printer.setOutputFileName(output)
                    printer.setResolution(144)
                    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
                    printer.setPageMargins(QMarginsF(10, 10, 10, 10),
                                           QPageLayout.Unit.Millimeter)
                    dlg = PrintDialog(view.doc, view)
                    buttons = {SCALE_FIT: dlg._rb_fit, SCALE_ACTUAL: dlg._rb_actual,
                               SCALE_CUSTOM: dlg._rb_custom}
                    buttons[mode].setChecked(True)
                    dlg._scale_spin.setValue(percent)
                    self.assertEqual(dlg.scale_mode(), mode)
                    self.assertEqual(dlg.scale_percent(), percent / 100)
                    with patch.object(dlg, '_configured_printer', return_value=printer):
                        dlg._refresh_preview()
                    self.assertFalse(dlg._preview_label.pixmap().isNull())
                    if mode == SCALE_CUSTOM:
                        self.assertIn(f'{percent}%', dlg._scale_badge.text())
                    with patch('print_dialog.PrintDialog', return_value=dlg) as factory, \
                         patch.object(dlg, 'exec', return_value=PrintDialog.DialogCode.Accepted), \
                         patch.object(dlg, 'result_printer', return_value=printer):
                        factory.DialogCode = PrintDialog.DialogCode
                        view.print_pdf()
                    with pymupdf.open(output) as printed:
                        pix = printed[0].get_pixmap(matrix=pymupdf.Matrix(2, 2),
                                                   colorspace=pymupdf.csGRAY)
                        dark = [i % pix.width for i, value in enumerate(pix.samples)
                                if value < 80]
                        width = max(dark) - min(dark) + 1
                        widths.append(width)
                    points = printer.pageLayout().paintRect(QPageLayout.Unit.Point)
                    preview_w, _ = print_target_size(view.doc[0].rect, points, 72, mode,
                                                     percent / 100)
                    self.assertAlmostEqual(width, 144 * preview_w / 595, delta=2)
                    dlg.deleteLater()
                self.assertGreater(widths[1], widths[0] + 10)
            finally:
                view.close_doc()
                view.close()

    def test_paper_sizes_ranges_and_multiple_copies(self):
        with tempfile.TemporaryDirectory() as folder:
            source = str(Path(folder) / 'source.pdf')
            with pymupdf.open() as doc:
                for index in range(5):
                    doc.new_page().insert_text((72, 100), f'Page {index + 1}')
                doc.save(source)
            view = DocumentView()
            view.load(source)
            try:
                with patch('print_dialog.QPrinterInfo.availablePrinters', return_value=[]):
                    dlg = PrintDialog(view.doc, view)
                dlg._rb_pages.setChecked(True)
                dlg._from_spin.setValue(2)
                dlg._to_spin.setValue(4)
                dlg._rb_pps2.setChecked(True)
                dlg._copy_spin.setValue(2)
                self.assertEqual(dlg.selected_pages(), [1, 2, 3])
                self.assertEqual(dlg._total_sheets(), 2)
                self.assertEqual(PAPERS['B5'].size(QPageSize.Unit.Millimeter).toTuple(),
                                 (182.0, 257.0))
                for paper in ('A4', 'A5', 'B5', 'B5 (ISO)', 'Letter', 'Legal', 'A3'):
                    for landscape in (False, True):
                        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
                        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
                        printer.setResolution(72)
                        output = str(Path(folder) / f'{paper}-{landscape}.pdf')
                        printer.setOutputFileName(output)
                        dlg._configured_printers[dlg._printer_combo.currentData()] = printer
                        dlg._paper_combo.setCurrentIndex(dlg._paper_combo.findData(paper))
                        (dlg._rb_landscape if landscape else dlg._rb_portrait).setChecked(True)
                        dlg._result_code = PrintDialog.DialogCode.Accepted
                        with patch('print_dialog.PrintDialog', return_value=dlg) as factory, \
                             patch.object(dlg, 'exec', return_value=PrintDialog.DialogCode.Accepted):
                            factory.DialogCode = PrintDialog.DialogCode
                            view.print_pdf()
                        with pymupdf.open(output) as printed:
                            self.assertEqual(len(printed), 4, 'Each copy must start a new sheet')
                            expected = PAPERS[paper].size(QPageSize.Unit.Point)
                            width, height = expected.toTuple()
                            if landscape:
                                width, height = height, width
                            self.assertAlmostEqual(printed[0].rect.width, width, delta=1)
                            self.assertAlmostEqual(printed[0].rect.height, height, delta=1)
                            self.assertEqual([len(p.get_image_info()) for p in printed], [2, 1, 2, 1])
                # 驱动未支持 ISO B5 时禁止静默回退到 A4。
                dlg._supported_papers[None] = [PAPERS['A4'], PAPERS['B5']]
                dlg._paper_combo.setCurrentIndex(dlg._paper_combo.findData('B5 (ISO)'))
                with self.assertRaises(ValueError):
                    dlg._configured_printer()
                dlg._current_page = 3
                dlg._rb_current.setChecked(True)
                self.assertEqual(dlg.selected_pages(), [3])
                self.assertEqual(dlg._total_sheets(), 1)
                dlg._rb_auto.setChecked(True)
                dlg._rot_btns[90].setChecked(True)
                self.assertTrue(dlg.paper_landscape())
                dlg._rb_pages.setChecked(True)
                dlg._from_spin.setValue(4)
                dlg._to_spin.setValue(2)
                self.assertEqual(dlg.selected_pages(), [])
                dlg.close()
                dlg.deleteLater()
            finally:
                view.close_doc()
                view.close()


if __name__ == '__main__':
    unittest.main()
