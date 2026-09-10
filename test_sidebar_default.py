# -*- coding: utf-8 -*-
"""回归：首启欢迎页复用空标签打开文档时，侧边栏应按默认值显示。

复现路径：MainWindow 启动（含欢迎页空标签）→ _load_doc 打开 PDF。
修复前：复用分支不调用 set_sidebar_visible，侧边栏保持初始隐藏。
"""
import os
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

import app_config as cfg
from main_window import MainWindow


def _reset_sidebar_setting():
    """清掉本机残留的侧边栏默认值，模拟真实首启。"""
    s = QSettings(cfg.ORG_NAME, getattr(cfg, "SETTINGS_APP_NAME", cfg.APP_NAME))
    s.remove("sidebar_default_visible")
    s.sync()


def _close_window(w):
    """关闭窗口内全部文档视图（释放 PDF 文件句柄），再关窗口。"""
    for i in range(w.tabs.count()):
        view = w.tabs.widget(i)
        if view is not None:
            try:
                view.close()
            except Exception:
                pass
    w.close()
    w.deleteLater()


def _remove(path):
    for _ in range(5):
        try:
            os.remove(path)
            return
        except PermissionError:
            time.sleep(0.2)
    # 最终仍被占用也不让测试失败（Windows 文件锁延迟释放）
    try:
        os.remove(path)
    except OSError:
        pass


class TestSidebarDefault(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _make_pdf(self, name):
        path = os.path.join(tempfile.gettempdir(), name)
        doc = pymupdf.open()
        doc.new_page(width=400, height=300)
        doc.save(path)
        doc.close()
        self.addCleanup(_remove, path)
        return path

    def test_welcome_tab_reuse_shows_sidebar(self):
        _reset_sidebar_setting()
        w = MainWindow()
        try:
            self.assertTrue(w.sidebar_default_visible)
            self.assertEqual(w.tabs.count(), 1)
            view = w.current_view()
            self.assertIsNone(view.doc)
            # 走 _load_doc：命中"复用欢迎页空标签"分支
            w._load_doc(self._make_pdf("_sidebar_reuse.pdf"))
            self.assertIsNotNone(view.doc)
            self.assertEqual(w.tabs.count(), 1, "应复用原标签而非新建")
            self.assertFalse(
                view.side_tabs.isHidden(),
                "复用标签打开文档后侧边栏应按默认值显示")
        finally:
            _close_window(w)

    def test_second_tab_also_shows_sidebar(self):
        _reset_sidebar_setting()
        w = MainWindow()
        try:
            w._load_doc(self._make_pdf("_sidebar_a.pdf"))
            w._load_doc(self._make_pdf("_sidebar_b.pdf"))
            self.assertEqual(w.tabs.count(), 2)
            view = w.current_view()
            self.assertFalse(
                view.side_tabs.isHidden(),
                "新建标签打开文档后侧边栏应显示")
        finally:
            _close_window(w)


if __name__ == "__main__":
    unittest.main(verbosity=2)
