"""保存、无控制台启动和连续行编辑的回归测试（离屏、临时样本）。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import pathlib
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pymupdf
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QTextCursor, QCloseEvent, QMouseEvent
from PySide6.QtCore import QEvent, Qt, QPointF, QRectF
from PySide6.QtTest import QTest
from document_view import DocumentView
from main_window import MainWindow


class RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='do-regression-')
        self.addCleanup(self.temp.cleanup)
        self.path = str(pathlib.Path(self.temp.name) / 'sample.pdf')
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((72, 100), 'ABCDE', fontsize=12)
            page.insert_text((72, 150), 'Neighbor', fontsize=12)
            doc.save(self.path)
        self.view = DocumentView()
        self.assertTrue(self.view.load(self.path))
        self.addCleanup(self.view.close_doc)

    def start_edit(self):
        self.view.set_mode('replace_text')
        self.view._begin_row_edit(0, self.view.page_view._edit_line_hits(0)[0])
        return self.view._row_edit

    def replace(self, edit, start, end, text):
        cursor = edit.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        edit.setTextCursor(cursor)
        edit.insertPlainText(text)

    def text(self):
        return self.view.doc[0].get_text(sort=True).replace('\n', '')

    def test_repeated_changes_and_saved_contents(self):
        edit = self.start_edit()
        for start, end, value, expected in [
            (0, 1, 'X', 'XBCDE'), (0, 1, 'A', 'ABCDE'),
            (5, 5, 'Z', 'ABCDEZ'), (5, 6, '', 'ABCDE'),
            (2, 3, 'Y', 'ABYDE'), (2, 3, 'C', 'ABCDE'),
        ]:
            self.replace(edit, start, end, value)
            self.assertEqual(edit.toPlainText(), expected)
            self.assertEqual(self.text(), 'Neighbor' + expected if self.text().startswith('Neighbor') else expected + 'Neighbor')
        self.assertTrue(self.view.save())
        with pymupdf.open(self.path) as saved:
            self.assertIn('ABCDE', saved[0].get_text())
            self.assertNotIn('XBCDE', saved[0].get_text())

    def test_format_only_then_restore_and_cancel(self):
        edit = self.start_edit()
        edit.selectAll()
        edit._apply_char(size_pt=24, color=QColor('red'))
        spans = [s for b in self.view.doc[0].get_text('dict')['blocks']
                 for line in b.get('lines', []) for s in line['spans']]
        changed = next(s for s in spans if s['text'] == 'ABCDE')
        self.assertAlmostEqual(changed['size'], 24)
        self.assertEqual(changed['color'], 0xFF0000)
        edit._apply_char(size_pt=12, color=QColor('black'))
        self.assertEqual(self.text().count('ABCDE'), 1)
        self.view._commit_row_edit(commit=False)
        self.assertEqual(self.text(), 'ABCDENeighbor')
        self.assertFalse(self.view.modified)

    def test_append_and_partial_format_preserve_prefix(self):
        edit = self.start_edit()
        self.replace(edit, 5, 5, 'Z')
        self.assertIn('ABCDEZ', self.text())
        cursor = edit.textCursor()
        cursor.setPosition(2)
        cursor.setPosition(4, QTextCursor.MoveMode.KeepAnchor)
        edit.setTextCursor(cursor)
        edit._apply_char(color=QColor('red'))
        self.assertIn('ABCDEZ', self.text())
        spans = [s for b in self.view.doc[0].get_text('dict')['blocks']
                 for line in b.get('lines', []) for s in line['spans']]
        self.assertTrue(any(s['text'] == 'CD' and s['color'] == 0xFF0000
                            for s in spans))

    def test_font_only_change_is_written_to_pdf(self):
        edit = self.start_edit()
        edit.selectAll()
        edit._apply_char(family='Cambria')
        spans = [s for b in self.view.doc[0].get_text('dict')['blocks']
                 for line in b.get('lines', []) for s in line['spans']]
        changed = next(s for s in spans if s['text'] == 'ABCDE')
        self.assertIn('Cambria', changed['font'])

    def test_font_combo_family_outside_static_map_is_written(self):
        font_path = self.view._system_font_file('Candara')
        if not font_path:
            self.skipTest('Candara is not installed')
        edit = self.start_edit()
        edit.selectAll()
        edit._apply_char(family='Candara')
        spans = [s for b in self.view.doc[0].get_text('dict')['blocks']
                 for line in b.get('lines', []) for s in line['spans']]
        changed = next(s for s in spans if s['text'] == 'ABCDE')
        self.assertIn('Candara', changed['font'])

    def test_add_text_selected_font_survives_bake(self):
        if not self.view._system_font_file('Candara'):
            self.skipTest('Candara is not installed')
        self.view.set_mode('text')
        self.view._begin_inplace_text(0, QPointF(72, 220))
        edit = self.view._inplace_edit
        edit.insertPlainText('NEWFONT')
        edit.selectAll()
        edit._apply_char(family='Candara')
        self.view._commit_inplace_text(commit=True)
        obj = self.view.objects[-1]
        self.assertEqual(obj['fontfamily'], 'Candara')
        self.assertTrue(obj.get('embed', {}).get('file', '').lower().endswith(
            'candara.ttf'))
        self.view._bake_objects()
        span = next(s for b in self.view.doc[0].get_text('dict')['blocks']
                    for line in b.get('lines', []) for s in line['spans']
                    if s['text'] == 'NEWFONT')
        self.assertIn('Candara', span['font'])

    def test_added_text_enters_edit_mode_and_can_be_dragged(self):
        self.view.set_mode('text')
        self.view._begin_inplace_text(0, QPointF(72, 220))
        self.view._inplace_edit.insertPlainText('MOVE ME')
        self.view._commit_inplace_text(commit=True)

        obj = self.view.objects[-1]
        pv = self.view.page_view
        self.assertEqual(self.view.current_mode, 'replace_text')
        self.assertTrue(pv._edit_overlay)
        self.assertEqual(pv.selected_id(), obj['id'])

        old_rect = QRectF(obj['rect'])
        center = QPointF(old_rect.center().x() * pv._zoom,
                         pv._offsets[0] + old_rect.center().y() * pv._zoom)
        moved = center + QPointF(24, 16)
        pv.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, center,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
        pv.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove, moved,
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
        pv.mouseReleaseEvent(QMouseEvent(
            QEvent.Type.MouseButtonRelease, moved,
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier))

        self.assertAlmostEqual(obj['rect'].x(),
                               old_rect.x() + 24 / pv._zoom, delta=0.2)
        self.assertAlmostEqual(obj['rect'].y(),
                               old_rect.y() + 16 / pv._zoom, delta=0.2)

    def test_pasted_text_stays_movable_until_save(self):
        QApplication.clipboard().setText('PASTED MOVE')
        self.view.set_mode('view')
        self.view.paste_text(0, QPointF(90, 230))

        obj = self.view.objects[-1]
        pv = self.view.page_view
        self.assertEqual(obj['kind'], 'text')
        self.assertEqual(obj['text'], 'PASTED MOVE')
        self.assertEqual(self.view.current_mode, 'replace_text')
        self.assertTrue(pv._edit_overlay)
        self.assertEqual(pv.selected_id(), obj['id'])

        old_rect = QRectF(obj['rect'])
        center = QPointF(old_rect.center().x() * pv._zoom,
                         pv._offsets[0] + old_rect.center().y() * pv._zoom)
        moved = center + QPointF(18, 12)
        pv.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, center,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
        pv.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove, moved,
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
        pv.mouseReleaseEvent(QMouseEvent(
            QEvent.Type.MouseButtonRelease, moved,
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier))
        self.assertGreater(obj['rect'].x(), old_rect.x())
        self.assertGreater(obj['rect'].y(), old_rect.y())

        self.assertTrue(self.view.save())
        self.assertFalse(self.view.objects)
        self.assertIn('PASTED MOVE', self.view.doc[0].get_text())

    def test_add_text_format_priority_front_previous_next(self):
        calibri = r'C:\Windows\Fonts\calibri.ttf'
        cambria = r'C:\Windows\Fonts\cambria.ttc'
        if not pathlib.Path(calibri).exists() or not pathlib.Path(cambria).exists():
            self.skipTest('Calibri/Cambria are not installed')
        self.view.close_doc()
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_font(fontname='frontcalibri', fontfile=calibri)
            page.insert_font(fontname='frontcambria', fontfile=cambria)
            page.insert_text((72, 100), 'LEFT', fontname='frontcalibri',
                             fontsize=11, color=(1, 0, 0))
            page.insert_text((110, 100), 'RIGHT', fontname='frontcambria',
                             fontsize=17, color=(0, 0, 1))
            page.insert_text((72, 150), 'NEXT', fontname='frontcalibri',
                             fontsize=13, color=(0, 0.5, 0))
            doc.save(self.path)
        self.assertTrue(self.view.load(self.path))

        # 同行前方：取最靠近点击点的 RIGHT/Cambria。
        same = self.view._detect_format_at(0, QPointF(180, 95))
        self.assertEqual(same['family'], 'Cambria')
        self.assertAlmostEqual(same['size'], 17, delta=0.1)
        self.assertEqual(same['color'].blue(), 255)

        # 新行左侧没有前方文字：先继承上一行最后一段 Cambria。
        previous = self.view._detect_format_at(0, QPointF(40, 145))
        self.assertEqual(previous['family'], 'Cambria')
        self.assertAlmostEqual(previous['size'], 17, delta=0.1)

        # 页面顶部无前方/上一行：最后才使用下一行首段 Calibri。
        following = self.view._detect_format_at(0, QPointF(40, 35))
        self.assertEqual(following['family'], 'Calibri')
        self.assertAlmostEqual(following['size'], 11, delta=0.1)

        self.view.set_mode('text')
        self.view._begin_inplace_text(0, QPointF(180, 95))
        self.assertEqual(self.view._inplace_meta['family'], 'Cambria')
        self.assertAlmostEqual(self.view._inplace_meta['size'], 17, delta=0.1)
        self.view._commit_inplace_text(commit=False)

    def test_mixed_text_replacement_inherits_preceding_format(self):
        from rich_text import RichEditBox, single_run
        edit = RichEditBox()
        edit.set_runs(
            single_run('AA', 'Calibri', 10, QColor('red')) +
            single_run('BB', 'Cambria', 18, QColor('blue')))

        # 混排边界插入：位置 2 的前方是 Calibri。
        cur = edit.textCursor()
        cur.setPosition(2)
        edit.setTextCursor(cur)
        edit.sync_typing_format_from_cursor()
        edit.insertPlainText('X')
        inserted = next(r for r in edit.to_runs() if 'X' in r['text'])
        self.assertEqual(inserted['family'], 'Calibri')
        self.assertAlmostEqual(inserted['size'], 10, delta=0.01)
        self.assertEqual(inserted['color'].name(), QColor('red').name())

        # 从首位替换选区：没有前方字符，继承原首字符而非默认字体。
        edit.set_runs(
            single_run('AA', 'Calibri', 10, QColor('red')) +
            single_run('BB', 'Cambria', 18, QColor('blue')))
        cur = edit.textCursor()
        cur.setPosition(0)
        cur.setPosition(2, QTextCursor.MoveMode.KeepAnchor)
        edit.setTextCursor(cur)
        edit.insertPlainText('中')
        first = edit.to_runs()[0]
        self.assertEqual(first['family'], 'Calibri')
        self.assertAlmostEqual(first['size'], 10, delta=0.01)
        edit.deleteLater()

    def test_add_text_keeps_vertical_position_after_bake(self):
        """新增文字保存后，其 PDF 行顶应仍位于用户点击的 y 坐标。"""
        family = 'Candara'
        if not self.view._system_font_file(family):
            family = 'Microsoft YaHei'
        if not self.view._system_font_file(family):
            self.skipTest('No embeddable test font is installed')
        top = 220.0
        self.view._add_text_object(
            'POSITION', 0, QPointF(72, top), family, 18,
            QColor('black'), keep_mode=True)
        obj = self.view.objects[-1]
        self.assertAlmostEqual(obj['rect'].top(), top, places=3)
        self.view._bake_objects()
        span = next(s for b in self.view.doc[0].get_text('dict')['blocks']
                    for line in b.get('lines', []) for s in line['spans']
                    if s['text'] == 'POSITION')
        self.assertAlmostEqual(float(span['bbox'][1]), top, delta=0.35)

    def test_save_result_and_cancel(self):
        self.view.modified = True
        with patch('document_view.QMessageBox.critical'):
            self.assertFalse(self.view._save_to(str(pathlib.Path(self.temp.name) / 'missing' / 'out.pdf')))
        self.assertTrue(self.view.modified)
        self.assertFalse(self.view.doc.is_closed)
        with patch('document_view.QFileDialog.getSaveFileName', return_value=('', '')):
            self.assertFalse(self.view.save_as())
        self.assertTrue(self.view.save())
        self.assertFalse(self.view.modified)

    def test_pdf_click_drag_and_insert_at_multiple_zooms(self):
        # PDF 水平拉伸字距，确保系统字体的 Qt 排版不能代替真实字符坐标。
        page = self.view.doc[0]
        page.insert_text((72, 240), 'WiMi123', fontname='tiro', fontsize=18,
                         morph=(pymupdf.Point(72, 240), pymupdf.Matrix(1.7, 1)))
        for zoom in (0.75, 1.25, 2.0):
            self.view.page_view.invalidate_text_cache()
            self.view._set_zoom(zoom)
            self.view.set_mode('replace_text')
            line = next(ln for ln in self.view.page_view._edit_line_hits(0)
                        if ln['text'] == 'WiMi123')
            line = dict(line, cx=line['char_x'][2][0] + 0.1)
            self.view._begin_row_edit(0, line)
            edit = self.view._row_edit
            self.assertEqual(edit.textCursor().position(), 2)
            self.assertAlmostEqual(edit.cursorRect().left() + edit.x(),
                                   line['char_x'][2][0] * zoom, delta=1.1)
            def pos(index):
                return QPointF(edit._pdf_ranges[index][0] + 0.1,
                               (edit._pdf_top + edit._pdf_bottom) / 2).toPoint()
            QTest.mouseClick(edit.viewport(), Qt.MouseButton.LeftButton, pos=pos(3))
            self.assertEqual(edit.textCursor().position(), 3)
            edit.insertPlainText('X')
            self.assertEqual(edit.toPlainText(), 'WiMXi123')
            # 输入后继续按新坐标拖选，再替换所选的字符。
            QTest.mousePress(edit.viewport(), Qt.MouseButton.LeftButton, pos=pos(3))
            QTest.mouseMove(edit.viewport(), pos(5))
            QTest.mouseRelease(edit.viewport(), Qt.MouseButton.LeftButton, pos=pos(5))
            self.assertEqual(edit.textCursor().selectedText(), 'Xi')
            edit.insertPlainText('Z')
            self.assertEqual(edit.toPlainText(), 'WiMZ123')
            self.assertIn('WiMZ123', self.text())
            self.view._commit_row_edit(commit=False)

    def test_pdf_cursor_utf16_positions(self):
        from rich_text import PdfRowEditBox, single_run
        edit = PdfRowEditBox()
        edit.set_runs(single_run('A😀中B'))
        edit.set_pdf_layout('A😀中B', [(0, 10), (10, 30), (30, 45), (45, 55)], 0, 20)
        self.assertEqual(edit.cursorForPosition(QPointF(30, 10)).position(), 3)
        edit.setTextCursor(edit.cursorForPosition(QPointF(45, 10)))
        self.assertEqual(edit.textCursor().position(), 4)
        self.assertEqual(edit.cursorRect().left(), 45)
        edit.deleteLater()

    def test_chinese_mixed_line_click_after_insertion(self):
        self.view.doc[0].insert_text((72, 240), '中文测试ABC', fontname='china-s', fontsize=16)
        self.view.page_view.invalidate_text_cache()
        self.view.set_mode('replace_text')
        line = next(ln for ln in self.view.page_view._edit_line_hits(0)
                    if ln['text'] == '中文测试ABC')
        self.view._begin_row_edit(0, dict(line, cx=line['char_x'][2][0]))
        edit = self.view._row_edit
        self.assertEqual(edit.textCursor().position(), 2)
        edit.insertPlainText('插入')
        self.assertIn('中文插入测试ABC', self.text())
        local = QPointF(edit._pdf_ranges[4][0] + 0.1,
                        (edit._pdf_top + edit._pdf_bottom) / 2).toPoint()
        QTest.mouseClick(edit.viewport(), Qt.MouseButton.LeftButton, pos=local)
        self.assertEqual(edit.textCursor().position(), 4)
        edit.insertPlainText('新')
        self.assertIn('中文插入新测试ABC', self.text())
        actual = [c for b in self.view.doc[0].get_text('rawdict')['blocks']
                  for ln in b.get('lines', []) for span in ln['spans']
                  for c in span['chars'] if abs(c['origin'][1] - 240) < 0.1]
        self.assertEqual(len(actual), len(edit._pdf_ranges))
        zoom = self.view.page_view._zoom
        for char, (left, right) in zip(actual, edit._pdf_ranges):
            self.assertAlmostEqual(left + edit.x(), char['bbox'][0] * zoom, delta=0.2)
            self.assertAlmostEqual(right + edit.x(), char['bbox'][2] * zoom, delta=0.2)

    def test_save_failure_prevents_close_and_exit(self):
        calls = []
        view = SimpleNamespace(modified=True, file_path='sample.pdf',
                               save=lambda: False, close_doc=lambda: calls.append('closed'))
        tabs = SimpleNamespace(widget=lambda _: view, count=lambda: 1)
        win = SimpleNamespace(tabs=tabs, _ocr_worker=None,
                              _ask_save=lambda _: 'save',
                              _update_tab_title=lambda *a: None,
                              _on_page_changed=lambda *a: None)
        MainWindow._close_tab(win, 0)
        self.assertEqual(calls, [])
        event = QCloseEvent()
        with patch('backend.cleanup_word') as cleanup:
            MainWindow.closeEvent(win, event)
            cleanup.assert_not_called()
        self.assertFalse(event.isAccepted())
        view.save = lambda: True
        MainWindow._close_tab(win, 0)
        self.assertEqual(calls, ['closed'])

    def test_font_and_glyph_size_preserved_during_insertion(self):
        cases = [('Calibri', r'C:\Windows\Fonts\calibri.ttf', 'AAAA', 9.94),
                 ('SimSun', r'C:\Windows\Fonts\simsun.ttc', '中中中中', 10.5)]
        def ink_height(page, rect):
            pix = page.get_pixmap(matrix=pymupdf.Matrix(8, 8), clip=rect, alpha=False)
            data = pix.samples
            rows = [y for y in range(pix.height)
                    if min(data[y * pix.stride:(y + 1) * pix.stride], default=255) < 120]
            return rows[-1] - rows[0] + 1 if rows else 0
        for index, (family, fontfile, text, size) in enumerate(cases):
            if not pathlib.Path(fontfile).exists():
                continue
            base = 260 + 90 * index
            page = self.view.doc[0]
            page.insert_font(fontname='test' + family, fontfile=fontfile)
            page.insert_text((72, base), text, fontname='test' + family, fontsize=size)
            self.view._undo_pdf_cache = None
            self.view.page_view.invalidate_text_cache()
            line = next(ln for ln in self.view.page_view._edit_line_hits(0) if ln['text'] == text)
            first = pymupdf.Rect(line['char_x'][0][0], base - size * 2,
                                  line['char_x'][0][1], base + size)
            original = page.get_pixmap(matrix=pymupdf.Matrix(8, 8), clip=first).samples
            original_height = ink_height(page, first)
            for zoom in (.75, 1.33, 2.0):
                self.view._set_zoom(zoom)
                self.view._begin_row_edit(0, dict(line, cx=line['char_x'][-1][1]))
                edit = self.view._row_edit
                edit.insertPlainText(text[0])
                self.assertEqual(edit.to_runs()[0]['size'], size)
                page = self.view.doc[0]
                self.assertEqual(page.get_pixmap(matrix=pymupdf.Matrix(8, 8), clip=first).samples,
                                 original, f'{family} zoom={zoom} keep={self.view._row_edit_meta.get("preserved_prefix")} runs={edit.to_runs()}')
                spans = [s for b in page.get_text('rawdict')['blocks']
                         for ln in b.get('lines', []) for s in ln['spans']
                         if abs(s['origin'][1] - base) < .1]
                inserted = spans[-1]
                self.assertIn(family.lower(), inserted['font'].lower())
                self.assertAlmostEqual(inserted['size'], size, delta=.01)
                char = inserted['chars'][-1]
                crop = pymupdf.Rect(char['bbox'][0], base - size * 2,
                                     char['bbox'][2], base + size)
                self.assertAlmostEqual(ink_height(page, crop), original_height, delta=2)
                if zoom == 2.0:
                    with pymupdf.open(stream=self.view.doc.tobytes(), filetype='pdf') as saved:
                        saved.subset_fonts()
                        with pymupdf.open(stream=saved.tobytes(garbage=3, deflate=True),
                                          filetype='pdf') as reopened:
                            self.assertAlmostEqual(ink_height(reopened[0], crop), original_height, delta=2)
                            self.assertIn(text + text[0], reopened[0].get_text(sort=True))
                self.view._commit_row_edit(commit=False)

    def test_font_resources_survive_multiple_row_undo_snapshots(self):
        fontfile = pathlib.Path(r'C:\Windows\Fonts\calibri.ttf')
        if not fontfile.exists():
            self.skipTest('Calibri is not installed')
        self.view.close_doc()
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_font(fontname='original', fontfile=str(fontfile))
            for index, text in enumerate(('AlphaRow', 'BravoRow', 'DeltaRow')):
                page.insert_text((72, 100 + 40 * index), text,
                                 fontname='original', fontsize=10)
            doc.subset_fonts()
            doc.save(self.path, garbage=3)
        self.view.load(self.path)
        expected_lines = []
        for original in ('AlphaRow', 'BravoRow', 'DeltaRow'):
            self.assertIn(original, [ln['text'] for ln in self.view.page_view._edit_line_hits(0)])
            line = next(ln for ln in self.view.page_view._edit_line_hits(0)
                        if ln['text'] == original)
            self.view._begin_row_edit(0, dict(line, cx=line['char_x'][3][0]))
            edit = self.view._row_edit
            for char in 'WEREWRE123':
                edit.insertPlainText(char)
                self.assertIn(edit.toPlainText(), self.text())
                for previous in expected_lines:
                    self.assertIn(previous, self.text())
                for font in self.view.doc[0].get_fonts():
                    self.assertIn(font[2], ('Type0', 'TrueType', 'Type1'))
            expected_lines.append(edit.toPlainText())
            self.view._commit_row_edit()
        self.assertTrue(self.view.save())
        for expected in expected_lines:
            self.assertIn(expected, self.text())
        line = next(ln for ln in self.view.page_view._edit_line_hits(0)
                    if ln['text'].startswith('Alp'))
        self.view._begin_row_edit(0, dict(line, cx=line['char_x'][-1][1]))
        self.view._row_edit.insertPlainText('XYZ')
        self.assertIn(self.view._row_edit.toPlainText(), self.text())

    def test_pdf_format_round_trip_does_not_change_size_or_family(self):
        from rich_text import RichEditBox, single_run
        for zoom in (.25, .75, 1.33, 2.0):
            edit = RichEditBox()
            edit.set_scale(zoom)
            edit.set_runs(single_run('AB', 'Calibri', 9.94))
            edit.insertPlainText('C')
            self.assertEqual(edit.to_runs()[0]['size'], 9.94)
            self.assertEqual(edit.to_runs()[0]['family'], 'Calibri')
            edit.selectAll()
            edit._apply_char(size_pt=10.75, family='Cambria')
            self.assertEqual(edit.to_runs()[0]['size'], 10.75)
            self.assertEqual(edit.to_runs()[0]['family'], 'Cambria')
            edit.deleteLater()

    def test_unicode_symbols_in_standard_pdf_fonts_survive_save(self):
        for fontname in ('helv', 'tiro', 'cour'):
            page = self.view.doc[0]
            page.insert_text((72, 260), 'Symbols:', fontname=fontname, fontsize=12)
            self.view._undo_pdf_cache = None
            self.view.page_view.invalidate_text_cache()
            line = next(ln for ln in self.view.page_view._edit_line_hits(0)
                        if ln['text'] == 'Symbols:')
            self.view._begin_row_edit(0, dict(line, cx=line['char_x'][-1][1]))
            edit = self.view._row_edit
            for ch in '→Ω≥é中文①':
                edit.insertPlainText(ch)
                self.assertIn(edit.toPlainText(), self.text())
            expected = edit.toPlainText()
            with pymupdf.open(stream=self.view.doc.tobytes(), filetype='pdf') as saved:
                saved.subset_fonts()
                with pymupdf.open(stream=saved.tobytes(garbage=3), filetype='pdf') as reopened:
                    self.assertIn(expected, reopened[0].get_text(sort=True))
            self.view._commit_row_edit(commit=False)
            # 下一轮使用不同标准字体，在一份全新的测试文档上运行。
            self.view.close_doc()
            self.view.load(self.path)

    def test_windowed_entry_without_standard_streams(self):
        code = '''
import sys
import main
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
class Window:
    def show(self):
        QTimer.singleShot(0, QApplication.instance().quit)
main.MainWindow = Window
main.remove_default_signatures = lambda: None
sys.stdout = sys.stderr = None
main.main()
'''
        result = subprocess.run([sys.executable, '-c', code],
                                cwd=str(pathlib.Path(__file__).parent),
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
