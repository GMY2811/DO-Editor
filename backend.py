"""PDF 核心逻辑（纯 PyMuPDF，无界面依赖，便于独立测试）。"""
import os
import threading
import pymupdf


def open_pdf(path):
    return pymupdf.open(path)


_word_app = None
_word_lock = threading.Lock()


def word_to_pdf(src_path):
    """用本机 Microsoft Word 把 .docx/.doc 转为 PDF，返回临时 PDF 路径。

    复用 Word 实例以加快连续转换；需要本机安装 Word；失败抛异常。
    """
    import tempfile
    import win32com.client
    global _word_app
    with _word_lock:
        if _word_app is None:
            _word_app = win32com.client.Dispatch("Word.Application")
            try:
                _word_app.Visible = False
            except Exception:
                pass
        out_dir = tempfile.mkdtemp(prefix="do_word_")
        out_path = os.path.join(out_dir, "converted.pdf")
        doc = _word_app.Documents.Open(src_path, ReadOnly=True)
        try:
            doc.SaveAs(out_path, FileFormat=17)  # 17 = wdFormatPDF
        finally:
            doc.Close(False)
        return out_path


def cleanup_word():
    """程序退出时释放复用的 Word 实例。"""
    global _word_app
    if _word_app is not None:
        try:
            _word_app.Quit()
        except Exception:
            pass
        _word_app = None


def page_count(doc):
    return len(doc)


def page_pixmap(doc, pno, zoom, dpr=1.0):
    """渲染第 pno 页为 pixmap，zoom 为缩放倍数（1.0 = 72dpi），dpr 为设备像素比。"""
    page = doc[pno]
    mat = pymupdf.Matrix(zoom * dpr, zoom * dpr)
    return page.get_pixmap(matrix=mat, alpha=False)


def page_size(doc, pno):
    r = doc[pno].rect
    return r.width, r.height


def extract_text(doc, pno, rect=None):
    """提取第 pno 页文字；rect 为 fitz.Rect 时仅提取该区域。"""
    page = doc[pno]
    if rect is not None:
        return page.get_text("text", clip=rect).strip()
    return page.get_text("text").strip()


# ---------------- 水印 ----------------

def add_watermark(doc, text, fontsize=50, color=(0.5, 0.5, 0.5), opacity=0.3,
                  rotate=45, tiled=True):
    """给所有页面添加文字水印。color 为 (r,g,b) 0-1，opacity 为 0-1。"""
    import math
    fontname = "china-s" if _has_cjk(text) else "helv"
    rad = math.radians(rotate)
    a, b = math.cos(rad), math.sin(rad)
    mat = pymupdf.Matrix(a, b, -b, a, 0, 0)
    for page in doc:
        pr = page.rect
        if tiled:
            step_y = max(120.0, fontsize * 2.6)
            text_w = sum(fontsize if '\u4e00' <= c <= '\u9fff' else fontsize * 0.55
                         for c in text)
            step_x = max(240.0, text_w + 80)
            y = pr.y0 + step_y / 2
            while y < pr.y1 - 20:
                x = pr.x0 + step_x / 2
                while x < pr.x1 - 20:
                    fp = pymupdf.Point(x, y)
                    page.insert_text(fp, text, fontname=fontname,
                                     fontsize=fontsize, color=color,
                                     fill_opacity=opacity, morph=(fp, mat))
                    x += step_x
                y += step_y
        else:
            fp = pymupdf.Point(pr.width / 2, pr.height / 2)
            page.insert_text(fp, text, fontname=fontname, fontsize=fontsize,
                             color=color, fill_opacity=opacity, morph=(fp, mat))


# ---------------- 合并 / 拆分 ----------------

def merge_pdfs(paths, out_path):
    """合并多个 PDF 文件，返回 (ok, 结果)。"""
    out = pymupdf.open()
    try:
        for p in paths:
            with pymupdf.open(p) as src:
                out.insert_pdf(src)
        out.save(out_path, garbage=3, deflate=True)
        return True, out_path
    except Exception as e:
        return False, str(e)
    finally:
        out.close()


def split_by_ranges(doc, ranges, out_dir, base):
    """按页码范围拆分。ranges: [(start, end)]，1-based 含端点。返回 (ok, 文件列表)。"""
    results = []
    try:
        for i, (s, e) in enumerate(ranges, 1):
            s = max(1, int(s))
            e = min(len(doc), int(e))
            if s > e:
                continue
            out = pymupdf.open()
            out.insert_pdf(doc, from_page=s - 1, to_page=e - 1)
            fp = os.path.join(out_dir, f"{base}_{i}.pdf")
            out.save(fp, garbage=3, deflate=True)
            out.close()
            results.append(fp)
        return True, results
    except Exception as e:
        return False, str(e)


def split_every_n(doc, n, out_dir, base):
    """每 n 页拆一份。返回 (ok, 文件列表)。"""
    results = []
    try:
        total = len(doc)
        i = 1
        start = 0
        while start < total:
            end = min(start + n, total)
            out = pymupdf.open()
            out.insert_pdf(doc, from_page=start, to_page=end - 1)
            fp = os.path.join(out_dir, f"{base}_{i}.pdf")
            out.save(fp, garbage=3, deflate=True)
            out.close()
            results.append(fp)
            start = end
            i += 1
        return True, results
    except Exception as e:
        return False, str(e)


def extract_pages(doc, pages, out_path):
    """提取指定页（0-based 页码列表）为新文件。返回 (ok, 结果)。"""
    out = pymupdf.open()
    try:
        for p in pages:
            if 0 <= p < len(doc):
                out.insert_pdf(doc, from_page=p, to_page=p)
        out.save(out_path, garbage=3, deflate=True)
        return True, out_path
    except Exception as e:
        return False, str(e)
    finally:
        out.close()


# ---------------- 标注 ----------------

def add_highlight(page, rect, color=None):
    a = page.add_highlight_annot(rect)
    if color is not None:
        _color(a, fill=color)
    return a


def add_underline(page, rect, color=None):
    a = page.add_underline_annot(rect)
    _color(a, stroke=color or (0.85, 0.1, 0.1))
    return a


def add_strikeout(page, rect, color=None):
    a = page.add_strikeout_annot(rect)
    _color(a, stroke=color or (0.85, 0.1, 0.1))
    return a


def add_squiggly(page, rect, color=None):
    a = page.add_squiggly_annot(rect)
    _color(a, stroke=color or (0.85, 0.1, 0.1))
    return a


def add_rect(page, rect, color=None):
    a = page.add_rect_annot(rect)
    _color(a, stroke=color or (0.85, 0.1, 0.1))
    return a


def add_line(page, p1, p2, color=None):
    a = page.add_line_annot(p1, p2)
    _color(a, stroke=color or (0.85, 0.1, 0.1))
    return a


def add_note(page, point, text):
    return page.add_text_annot(point, text)


def add_text_box(page, rect, text, color=None):
    a = page.add_freetext_annot(rect, text, fontsize=11, fill_color=(1, 1, 1))
    if color is not None:
        try:
            a.update(fontcolor=color)
        except Exception:
            pass
    return a


def add_ink(page, points, color=None):
    a = page.add_ink_annot([points])
    _color(a, stroke=color or (0.1, 0.25, 0.9))
    return a


def add_image(page, rect, png_bytes):
    page.insert_image(rect, stream=png_bytes)
    return rect


def _has_cjk(text):
    return any('\u4e00' <= c <= '\u9fff' for c in text)


def _css_font_family(family):
    """系统字体名 → CSS font-family 类别（serif/sans-serif/monospace）。

    PyMuPDF 的 Story 引擎只内置了衬线/无衬线/等宽三类字体（中文字形统一用
    内置 CJK 字体），因此把系统字体归并到这三类即可得到可见的字体差异。
    """
    low = (family or "").lower()
    if any(k in low for k in ("mono", "courier", "consolas", "console", "等宽")):
        return "monospace"
    if any(k in low for k in ("times", "roman", "serif", "宋体", "simsun",
                              "楷", "仿宋", "fangsong", "kaiti", "song",
                              "songti", "georgia", "garamond")):
        return "serif"
    return "sans-serif"


def insert_text_auto(page, rect, text, fontsize=12, color=(0, 0, 0), fontfamily="",
                     bold=False, italic=False):
    """插入文字，自动处理中英文字体。fontfamily 为系统字体名，映射为衬线/无衬线/等宽。"""
    import html as _html
    safe = _html.escape(text).replace("\n", "<br>")
    r, g, b = [int(round(c * 255)) for c in color]
    fam = _css_font_family(fontfamily)
    weight = "bold" if bold else "normal"
    style = "italic" if italic else "normal"
    css = (f"* {{ font-family: {fam}; font-size: {fontsize}px; "
           f"color: rgb({r},{g},{b}); font-weight: {weight}; font-style: {style}; }}")
    page.insert_htmlbox(rect, safe, css=css)


def redact_rect(page, rect):
    """删除指定矩形区域内的原有内容（用于修改文字前清除原文）。"""
    page.add_redact_annot(rect)
    page.apply_redactions()


def replace_text(page, rect, new_text, fontsize=12, color=(0, 0, 0), fontfamily="",
                 bold=False, italic=False):
    """覆盖式修改文字：删除原区域内容后写入新文字。返回新文本。"""
    redact_rect(page, rect)
    insert_text_auto(page, rect, new_text, fontsize=fontsize, color=color,
                     fontfamily=fontfamily, bold=bold, italic=italic)
    return new_text


def _color(annot, stroke=None, fill=None):
    """设置标注颜色（失败静默，使用默认色）。"""
    try:
        d = {}
        if stroke is not None:
            d["stroke"] = stroke
        if fill is not None:
            d["fill"] = fill
        if d:
            annot.set_colors(d)
            annot.update()
    except Exception:
        pass
