"""回归：保存失败后 doc 不得停留在 closed 状态（防 document closed 崩溃）。

覆盖场景：
1. 保存（os.replace 抛 WinError 5）→ _save_to 抛 RuntimeError，
   但 self.doc 已从 .recover.pdf 恢复为 open（is_closed=False）、
   page_count > 0、内容含新写入文字 —— 视图重绘不再崩溃；
2. .recover.pdf 存在且内容 = 最新修改（数据未丢）；
3. 失败恢复后二次保存（目标可写）成功 → 目标文件含最新文字、
   .tmp 与 .recover.pdf 均被清理（无残留垃圾）；
4. page_view._doc_open() 对 closed 文档返回 False（防御层生效）。
"""

import os
import sys
import shutil
import tempfile
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(__file__))

import pymupdf
from PySide6.QtWidgets import QApplication

import backend
import document_view as dv
from document_view import DocumentView

app = QApplication.instance() or QApplication([])

# _save_to 失败会弹 QMessageBox.critical 模态框（阻塞非交互测试），
# 这里整体替换为 no-op，让异常沿 except 链直接抛出供测试断言。
_critical_box = dv.QMessageBox.critical
dv.QMessageBox.critical = staticmethod(lambda *a, **k: None)


def _make_pdf(path, text="你好世界"):
    d = pymupdf.open()
    pg = d.new_page(width=595, height=842)
    pg.insert_text((72, 100), text, fontsize=24)
    d.save(path)
    d.close()


def _open_view(path):
    v = DocumentView()
    assert v.load(path), "load 应成功"
    return v


def _append_text(v, text, y=200):
    """绕过对象系统，直接在 doc 首页插入新文字并标记修改。"""
    page = v.doc[0]
    backend.insert_text_auto(
        page, pymupdf.Rect(72, y, 500, y + 40), text, fontsize=20)
    v.modified = True


def _winerr5():
    err = OSError(13, "Permission denied")
    err.winerror = 5
    return err


def _fail_replace_to(target_path):
    """构造 os.replace mock：替换到 target_path 时报 WinError 5，
    其他目标（如 .recover.pdf 恢复路径）放行真实 os.replace。"""
    real_replace = os.replace

    def wrapper(src, dst, *a, **k):
        if os.path.normcase(dst) == os.path.normcase(target_path):
            raise _winerr5()
        return real_replace(src, dst, *a, **k)

    return wrapper


def test_save_failure_recovers_doc():
    td = tempfile.mkdtemp(prefix="do_rec_")
    v = None
    try:
        path = os.path.join(td, "a.pdf")
        _make_pdf(path)
        v = _open_view(path)
        _append_text(v, "保存失败测试", 200)

        # 让替换到目标 pdf 时抛 WinError 5（_save_to 会吞异常弹框，
        # 框已被替换为 no-op，这里验证失败后的恢复状态）
        with mock.patch("os.replace", side_effect=_fail_replace_to(path)):
            v._save_to(path)

        # 核心断言：doc 不得 closed！
        assert v.doc is not None
        assert not v.doc.is_closed, \
            "保存失败后 doc 必须恢复为 open，否则重绘会 document closed 崩溃"
        assert v.doc.page_count > 0
        text = "".join(p.get_text() for p in v.doc)
        assert "保存失败测试" in text, "recover 文档应含用户最新修改"

        # .recover.pdf 存在且含最新内容
        recover = path + ".recover.pdf"
        assert os.path.exists(recover), ".recover.pdf 应被创建"
        rdoc = pymupdf.open(recover)
        rtext = "".join(p.get_text() for p in rdoc)
        assert "保存失败测试" in rtext
        rdoc.close()

        # 无 .tmp 残留
        assert not os.path.exists(path + ".tmp"), ".tmp 不应残留"
    finally:
        if v is not None:
            try:
                v.doc.close()
            except Exception:
                pass
            try:
                v.close_doc()
            except Exception:
                pass
        shutil.rmtree(td, ignore_errors=True)
    print("CASE_OK save-failure-recovers-doc")


def test_second_save_succeeds_and_cleans():
    td = tempfile.mkdtemp(prefix="do_rec_")
    v = None
    try:
        path = os.path.join(td, "b.pdf")
        _make_pdf(path)
        v = _open_view(path)
        _append_text(v, "二次保存成功", 260)

        # 第一次：失败（占用）——_save_to 吞异常弹框（框已被 no-op）
        with mock.patch("os.replace", side_effect=_fail_replace_to(path)):
            v._save_to(path)
        assert not v.doc.is_closed, "失败后 doc 应仍 open"
        recover = path + ".recover.pdf"
        assert os.path.exists(recover)

        # 第二次：目标不再被占用 → 应成功
        v._save_to(path)
        assert os.path.exists(path)
        d = pymupdf.open(path)
        text = "".join(p.get_text() for p in d)
        assert "二次保存成功" in text, f"最终文件应含最新修改: {text!r}"
        d.close()
        # 残留清理
        assert not os.path.exists(path + ".tmp"), ".tmp 应清理"
        assert not os.path.exists(path + ".recover.pdf"), ".recover.pdf 应清理"
    finally:
        if v is not None:
            try:
                v.doc.close()
            except Exception:
                pass
            try:
                v.close_doc()
            except Exception:
                pass
        shutil.rmtree(td, ignore_errors=True)
    print("CASE_OK second-save-succeeds-and-cleans")


def test_paint_guard_doc_open():
    td = tempfile.mkdtemp(prefix="do_rec_")
    v = None
    try:
        path = os.path.join(td, "c.pdf")
        _make_pdf(path)
        v = _open_view(path)
        from page_view import PageView
        pv = PageView()
        pv.set_document(v.doc, 1.0)
        assert pv._doc_open(), "open 文档 _doc_open 应为 True"
        assert pv.page_count() == 1

        v.doc.close()          # 模拟外部把 doc 关了
        assert pv._doc_open() is False, "closed 文档 _doc_open 应为 False"
        assert pv.page_count() == 0, "closed 文档 page_count 应为 0"

        # 触发真实重绘，覆盖 paintEvent 中 len(self._doc) 访问不抛异常
        pv.resize(600, 800)
        pv.repaint()
        app.processEvents()
    finally:
        if v is not None:
            try:
                v.close_doc()
            except Exception:
                pass
        shutil.rmtree(td, ignore_errors=True)
    print("CASE_OK paint-guard-doc-open")


if __name__ == "__main__":
    test_save_failure_recovers_doc()
    test_second_save_succeeds_and_cleans()
    test_paint_guard_doc_open()
    print("ALL RECOVER TESTS PASSED")
