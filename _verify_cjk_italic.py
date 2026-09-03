# -*- coding: utf-8 -*-
"""v2.6.8: 修改文字/添加文字 汉字斜体不生效 的修复回归。

场景:
  1. 纯拉丁 italic -> 真斜体字面(不可见差异显著, 与旧实现一致)
  2. 纯 CJK italic -> 旧实现 0% diff(正体), 新实现显著 diff(合成斜体)
  3. 混合(CJK+拉丁)italic -> CJK 应合成斜体, 拉丁真斜体(>0% diff)
  4. 非 italic -> 与旧渲染逐像素一致(0% diff, 不破坏旧行为)
  5. 加粗+斜体汉字 -> 粗 + 斜 都生效
  6. 字符级混排 runs(CJK 斜体段) -> 同样修复生效
  7. 文本提取仍能拿到原文(变换是视觉层)
"""
import pymupdf
import sys, os
sys.path.insert(0, r"D:\Project\2026-08-16-16-15-44\do-reader")

import backend


def _render_html_box(html, css, w=420, h=80):
    doc = pymupdf.open()
    page = doc.new_page(width=w, height=h)
    page.insert_htmlbox(pymupdf.Rect(10, 10, w - 10, h - 10), html, css=css)
    return doc, page


def _render_backend(rich=False, text="", runs=None, italic=False, bold=False,
                   fontfamily=""):
    doc = pymupdf.open()
    page = doc.new_page(width=420, height=80)
    rect = pymupdf.Rect(10, 10, 410, 70)
    if rich:
        backend.insert_rich_text_auto(page, rect, runs)
    else:
        backend.insert_text_auto(page, rect, text, fontsize=22,
                                 color=(0, 0, 0), fontfamily=fontfamily,
                                 bold=bold, italic=italic)
    return doc, page


def _pix(doc, page, clip_rect):
    return page.get_pixmap(dpi=150, clip=clip_rect)


def _diff_pix(a, b):
    w = min(a.width, b.width)
    h = min(a.height, b.height)
    n = sum(1 for y in range(h) for x in range(w) if a.pixel(x, y) != b.pixel(x, y))
    return n, w * h


def _baseline_normal_html(text):
    """旧实现直接 HTML(无 transform 分段), 用作对照基准。"""
    return f"<span style=\"font-family:sans-serif;font-size:22px;\">{text}</span>"


# ----------------------------------------------------------------------
print("=" * 60)
print("case 1: 纯拉丁 italic -> 真斜体(与正体差异显著)")
text = "italic Latin hello world"
norm_doc, norm_page = _render_backend(text=text)
ital_doc, ital_page = _render_backend(text=text, italic=True)
pn = _pix(norm_doc, norm_page, pymupdf.Rect(10, 10, 410, 70))
pi = _pix(ital_doc, ital_page, pymupdf.Rect(10, 10, 410, 70))
diff, total = _diff_pix(pn, pi)
print(f"  latin normal vs italic diff: {diff}/{total} ({100*diff/total:.2f}%)")
assert diff / total > 0.01, "拉丁 italic 应与 normal 显著不同(真斜体)"
# 抽取文本
def check_text(label, doc):
    txt = doc[0].get_text("text").strip()
    assert text.split()[0] in txt or text.replace(" ", "") in txt.replace(" ", ""), f"{label}: 文本缺失"
check_text("latin normal", norm_doc)
check_text("latin italic", ital_doc)
norm_doc.close(); ital_doc.close()

# ----------------------------------------------------------------------
print("=" * 60)
print("case 2: 纯汉字 italic(旧 bug -> 0% diff; 修复后 -> 显著 diff)")
text = "汉字斜体测试中文字"
old_doc, old_page = _render_html_box(_baseline_normal_html(text).replace(
    "<span style=\"font-family:sans-serif;font-size:22px;\">",
    "<span style=\"font-family:sans-serif;font-size:22px;font-style:italic;\">"),
    "*{margin:0;padding:0;}")
po = _pix(old_doc, old_page, pymupdf.Rect(10, 10, 410, 70))

fix_doc, fix_page = _render_backend(text=text, italic=True)
pf = _pix(fix_doc, fix_page, pymupdf.Rect(10, 10, 410, 70))

# normal vs old (旧实现) -> 应当 0% diff(即为 bug 证据)
norm_doc2, norm_page2 = _render_backend(text=text)
pn2 = _pix(norm_doc2, norm_page2, pymupdf.Rect(10, 10, 410, 70))
d1, t1 = _diff_pix(pn2, po)
print(f"  CJK normal vs old-italic: {d1}/{t1} ({100*d1/t1:.2f}%)  (应≈0 即 bug)")
d2, t2 = _diff_pix(pn2, pf)
print(f"  CJK normal vs fixed-italic: {d2}/{t2} ({100*d2/t2:.2f}%)  (应显著>0 即修复)")
assert d2 / t2 > 0.01, "修复后 CJK italic 应与 normal 显著不同(已合成斜体)"
# 提取检查
check_text("CJK normal", norm_doc2)
check_text("CJK fixed-italic", fix_doc)
old_doc.close(); norm_doc2.close(); fix_doc.close()

# ----------------------------------------------------------------------
print("=" * 60)
print("case 3: 混合 CJK+拉丁 italic -> CJK 应合成斜体, 拉丁真斜体(差异显著)")
text = "汉字 abc 文本 def 字"
norm_doc, norm_page = _render_backend(text=text)
ital_doc, ital_page = _render_backend(text=text, italic=True)
pn = _pix(norm_doc, norm_page, pymupdf.Rect(10, 10, 410, 70))
pi = _pix(ital_doc, ital_page, pymupdf.Rect(10, 10, 410, 70))
diff, total = _diff_pix(pn, pi)
print(f"  mixed normal vs italic diff: {diff}/{total} ({100*diff/total:.2f}%)")
assert diff / total > 0.01, "混合斜体与正体应有显著差异"
check_text("mixed normal", norm_doc)
check_text("mixed italic", ital_doc)
norm_doc.close(); ital_doc.close()

# ----------------------------------------------------------------------
print("=" * 60)
print("case 4: 非 italic(汉字) -> 与旧正体渲染逐像素一致(0% diff)")
text = "汉字非斜体测试"
new_doc, new_page = _render_backend(text=text)
base_doc, base_page = _render_html_box(_baseline_normal_html(text),
                                       "*{margin:0;padding:0;}")
pn = _pix(new_doc, new_page, pymupdf.Rect(10, 10, 410, 70))
pb = _pix(base_doc, base_page, pymupdf.Rect(10, 10, 410, 70))
diff, total = _diff_pix(pn, pb)
print(f"  non-italic CJK new vs baseline: {diff}/{total} ({100*diff/total:.2f}%)")
assert diff == 0, f"非斜体路径不应改变渲染(diff={diff})"
new_doc.close(); base_doc.close()

# ----------------------------------------------------------------------
print("=" * 60)
print("case 5: 加粗+斜体 汉字 -> 粗+斜都生效(与 normal-bold 显著不同)")
text = "汉字粗斜体"
nb_doc, nb_page = _render_backend(text=text, bold=True)
bi_doc, bi_page = _render_backend(text=text, bold=True, italic=True)
pn = _pix(nb_doc, nb_page, pymupdf.Rect(10, 10, 410, 70))
pi = _pix(bi_doc, bi_page, pymupdf.Rect(10, 10, 410, 70))
diff, total = _diff_pix(pn, pi)
print(f"  bold-only vs bold-italic CJK diff: {diff}/{total} ({100*diff/total:.2f}%)")
assert diff / total > 0.01, "粗+斜 CJK 应与仅粗的 CJK 显著不同"
nb_doc.close(); bi_doc.close()

# ----------------------------------------------------------------------
print("=" * 60)
print("case 6: 字符级混排 runs(斜体 CJK 段)")
runs = [
    {"text": "正常段", "family": "", "size": 22, "color": (0, 0, 0),
     "bold": False, "italic": False},
    {"text": "汉字斜体", "family": "", "size": 22, "color": (0, 0, 0),
     "bold": False, "italic": True},
    {"text": "结尾", "family": "", "size": 22, "color": (0, 0, 0),
     "bold": False, "italic": False},
]
doc, page = _render_backend(rich=True, runs=runs)
norm_runs = [{**r, "italic": False} for r in runs]
doc_n, page_n = _render_backend(rich=True, runs=norm_runs)
pi = _pix(doc, page, pymupdf.Rect(10, 10, 410, 70))
pn = _pix(doc_n, page_n, pymupdf.Rect(10, 10, 410, 70))
diff, total = _diff_pix(pn, pi)
print(f"  rich runs normal vs italic-CJK-segment diff: {diff}/{total} ({100*diff/total:.2f}%)")
assert diff / total > 0.01, "字符级混排中 CJK 斜体段应生效"
assert "正常段" in doc[0].get_text("text")
assert "汉字斜体" in doc[0].get_text("text")
assert "结尾" in doc[0].get_text("text")
doc.close(); doc_n.close()

# ----------------------------------------------------------------------
print("=" * 60)
print("case 7: 非斜体 runs(无回归)")
runs = [
    {"text": "正常段", "family": "", "size": 22, "color": (0, 0, 0),
     "bold": False, "italic": False},
    {"text": "abc 123", "family": "", "size": 22, "color": (0, 0, 0),
     "bold": False, "italic": False},
]
doc, page = _render_backend(rich=True, runs=runs)
# 比照直接 htmlbox
html = ('<span style="font-family:sans-serif;font-size:22px;">正常段</span>'
        '<span style="font-family:sans-serif;font-size:22px;">abc 123</span>')
doc_b, page_b = _render_html_box(html, "*{margin:0;padding:0;}")
pi = _pix(doc, page, pymupdf.Rect(10, 10, 410, 70))
pb = _pix(doc_b, page_b, pymupdf.Rect(10, 10, 410, 70))
diff, total = _diff_pix(pi, pb)
print(f"  non-italic runs vs htmlbox baseline: {diff}/{total} ({100*diff/total:.2f}%)")
assert diff == 0, f"非斜体 runs 不应改变渲染(diff={diff})"
doc.close(); doc_b.close()

print()
print("ALL CJK ITALIC FIX CASES PASSED ✅")