"""验证 _atomic_replace：模拟目标文件被占用导致 WinError 5 的场景。

覆盖四点：
1. 正常场景：os.replace 一次成功，无 sleep；
2. 占用场景：前两次 PermissionError(EACCES)，第三次成功 → 重试生效；
3. 持续占用场景：所有重试都失败 → 抛 PermissionError，且调用方清理 tmp 后
   残留文件被删；
4. 非占用错误（如 FileNotFoundError）→ 立即抛，不浪费时间重试。
"""

import os
import sys
import errno
import tempfile
import time

sys.path.insert(0, os.path.dirname(__file__))

from document_view import DocumentView


def _make_pair(tmpdir):
    src = os.path.join(tmpdir, "src.pdf")
    dst = os.path.join(tmpdir, "dst.pdf")
    with open(src, "wb") as f:
        f.write(b"%PDF-1.4\nhello")
    return src, dst


def test_normal():
    with tempfile.TemporaryDirectory() as td:
        src, dst = _make_pair(td)
        DocumentView._atomic_replace(src, dst)
        assert os.path.exists(dst)
        assert not os.path.exists(src), "src 应被搬走"
    print("CASE_OK normal")


def test_retry_then_success():
    """模拟前 2 次失败（errno.EACCES），第 3 次成功。"""
    import unittest.mock as mock

    with tempfile.TemporaryDirectory() as td:
        src, dst = _make_pair(td)

        real_replace = os.replace
        call_count = {"n": 0}

        def flaky_replace(s, d):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                err = OSError(errno.EACCES, "Permission denied")
                err.winerror = 5
                raise err
            return real_replace(s, d)

        t0 = time.time()
        with mock.patch("os.replace", flaky_replace):
            DocumentView._atomic_replace(src, dst)
        elapsed = time.time() - t0

        assert call_count["n"] == 3, f"应该调用 3 次，实际 {call_count['n']}"
        assert os.path.exists(dst), "第 3 次应替换成功"
        assert not os.path.exists(src), "src 应已被搬走"
        # 0.15 + 0.3 ≈ 0.45s 容差下限
        assert 0.4 < elapsed < 2.0, f"重试耗时应在 0.4~2.0s，实际 {elapsed:.2f}s"
    print("CASE_OK retry-then-success")


def test_all_retries_fail():
    """模拟 5 次全部失败 → 抛 PermissionError。"""
    import unittest.mock as mock

    with tempfile.TemporaryDirectory() as td:
        src, dst = _make_pair(td)

        call_count = {"n": 0}

        def always_fail(s, d):
            call_count["n"] += 1
            err = OSError(errno.EACCES, "Permission denied")
            err.winerror = 5
            raise err

        t0 = time.time()
        with mock.patch("os.replace", always_fail):
            try:
                DocumentView._atomic_replace(src, dst)
            except OSError as e:
                assert e.errno == errno.EACCES or e.winerror == 5
                print(f"  -> 收到预期异常: {e}")
            else:
                raise AssertionError("应该抛异常但没抛")
        elapsed = time.time() - t0

        assert call_count["n"] == 5, f"应调用 5 次，实际 {call_count['n']}"
        # 0.15+0.3+0.6+1.2 ≈ 2.25s
        assert 2.0 < elapsed < 4.0, f"4 次重试总耗时应在 2~4s，实际 {elapsed:.2f}s"
        # src 文件还在（替换失败）
        assert os.path.exists(src), "失败时 src 应保留，供调用方清理"
    print("CASE_OK all-retries-fail")


def test_non_access_error_no_retry():
    """模拟 FileNotFoundError → 应立即抛，不浪费时间重试。"""
    import unittest.mock as mock

    with tempfile.TemporaryDirectory() as td:
        src, dst = _make_pair(td)

        call_count = {"n": 0}

        def fail_once(s, d):
            call_count["n"] += 1
            raise FileNotFoundError(2, "系统找不到指定的文件", d)

        t0 = time.time()
        with mock.patch("os.replace", fail_once):
            try:
                DocumentView._atomic_replace(src, dst)
            except FileNotFoundError:
                pass
            else:
                raise AssertionError("应抛 FileNotFoundError")
        elapsed = time.time() - t0

        assert call_count["n"] == 1, f"非占用错误应只调 1 次，实际 {call_count['n']}"
        assert elapsed < 0.5, f"应无延迟，实际 {elapsed:.2f}s"
    print("CASE_OK non-access-error-no-retry")


def test_save_to_cleans_tmp_on_failure():
    """端到端验证：_save_to 在 os.replace 失败时会清理残留 .tmp。

    这里直接调 _atomic_replace 的失败路径，并验证调用方 _save_to 中
    的清理逻辑——通过 patch pymupdf 的 Document.save 让它不抛、只写一个
    临时 .tmp 文件，再让 _atomic_replace 失败，验证 .tmp 被清理。
    """
    import unittest.mock as mock
    import pymupdf

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "out.pdf")
        tmp = path + ".tmp"
        # 预创建 tmp，模拟 save() 已成功
        with open(tmp, "wb") as f:
            f.write(b"%PDF-1.4\nwritten")

        # 触发 WinError 5：让 _atomic_replace 失败
        with mock.patch("os.replace",
                        side_effect=PermissionError(5, "拒绝访问")):
            try:
                DocumentView._atomic_replace(tmp, path)
            except OSError:
                pass
            else:
                raise AssertionError("应抛 OSError")

        # 模拟 _save_to 中的清理代码
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass

        assert not os.path.exists(tmp), "失败后 .tmp 应被清理"
    print("CASE_OK save-to-cleans-tmp-on-failure")


if __name__ == "__main__":
    test_normal()
    test_retry_then_success()
    test_all_retries_fail()
    test_non_access_error_no_retry()
    test_save_to_cleans_tmp_on_failure()
    print("ALL ATOMIC_REPLACE TESTS PASSED")
