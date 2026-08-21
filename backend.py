"""PDF 核心逻辑（纯 PyMuPDF，无界面依赖，便于独立测试）。"""
import hashlib
import os
import queue
import tempfile
import threading
import pymupdf


class PdfPasswordRequired(Exception):
    """PDF 已加密且需要打开密码。"""


class PdfPasswordInvalid(Exception):
    """提供的 PDF 密码不正确。"""


def _has_encrypt_dictionary(doc):
    try:
        return doc.xref_get_key(-1, "Encrypt")[0] != "null"
    except Exception:
        return bool(doc.needs_pass)


def open_pdf(path, password=None):
    """打开 PDF；加密文件会验证密码并记录认证级别。"""
    doc = pymupdf.open(path)
    # 需要密码时不能在 authenticate() 之前读取 Encrypt 字典；MuPDF
    # 会因此提前解析加密对象，随后重写文档可能产生损坏的 AES 数据流。
    requires_password = bool(doc.needs_pass)
    encrypted = True if requires_password else _has_encrypt_dictionary(doc)
    auth_level = 0
    if requires_password and password is None:
        doc.close()
        raise PdfPasswordRequired(path)
    if encrypted and password is not None:
        auth_level = int(doc.authenticate(password))
        # PyMuPDF 1.28 在 authenticate() 成功后再次读取 needs_pass 会
        # 破坏后续 AES 流解码，因此只使用认证前缓存的布尔值。
        if requires_password and not auth_level:
            doc.close()
            raise PdfPasswordInvalid(path)
    doc._do_was_encrypted = encrypted
    doc._do_auth_level = auth_level
    doc._do_open_password = password
    return doc


def pdf_permissions(allow_print=True, allow_copy=True, allow_modify=True,
                    allow_annotate=True):
    """生成 PyMuPDF 权限位；始终保留辅助功能读取权限。"""
    value = pymupdf.PDF_PERM_ACCESSIBILITY
    if allow_print:
        value |= pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_PRINT_HQ
    if allow_copy:
        value |= pymupdf.PDF_PERM_COPY
    if allow_modify:
        value |= (pymupdf.PDF_PERM_MODIFY | pymupdf.PDF_PERM_ASSEMBLE |
                  pymupdf.PDF_PERM_FORM)
    if allow_annotate:
        value |= pymupdf.PDF_PERM_ANNOTATE
    return value


_word_thread = None
_word_queue = None
_word_thread_lock = threading.Lock()


def _word_cache_path(src_path):
    """按路径、大小和修改时间生成转换缓存；源文件变化后自动失效。"""
    absolute = os.path.abspath(src_path)
    stat = os.stat(absolute)
    fingerprint = f"{os.path.normcase(absolute)}\0{stat.st_size}\0{stat.st_mtime_ns}"
    key = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    cache_dir = os.path.join(tempfile.gettempdir(), "do_editor_word_cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"{key}.pdf")


def _word_conversion_loop(requests):
    """在固定 COM 线程中转换 Word；每次转换结束后立即退出 Word。"""
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        while True:
            request = requests.get()
            if request is None:
                break
            src_path, out_path, done, result = request
            doc = None
            word = None
            try:
                # 仅在用户实际打开 Word 文档时创建独立的隐藏实例，避免
                # 软件空闲时长期驻留 WINWORD.EXE 后台进程。
                word = win32com.client.DispatchEx("Word.Application")
                word.Visible = False
                word.DisplayAlerts = 0
                try:
                    word.ScreenUpdating = False
                    word.AutomationSecurity = 3  # 禁用文档宏
                except Exception:
                    pass
                doc = word.Documents.Open(
                    os.path.abspath(src_path), ConfirmConversions=False,
                    ReadOnly=True, AddToRecentFiles=False, Visible=False,
                    OpenAndRepair=False, NoEncodingDialog=True)
                # ExportAsFixedFormat 比 SaveAs 更直接，不触发格式转换提示。
                doc.ExportAsFixedFormat(
                    OutputFileName=out_path, ExportFormat=17,
                    OpenAfterExport=False, OptimizeFor=0)
                result["path"] = out_path
            except Exception as exc:
                result["error"] = exc
            finally:
                if doc is not None:
                    try:
                        doc.Close(False)
                    except Exception:
                        pass
                if word is not None:
                    try:
                        word.Quit()
                    except Exception:
                        pass
                if done is not None:
                    done.set()
    finally:
        pythoncom.CoUninitialize()


def _ensure_word_thread():
    global _word_thread, _word_queue
    with _word_thread_lock:
        if _word_thread is None or not _word_thread.is_alive():
            _word_queue = queue.Queue()
            _word_thread = threading.Thread(
                target=_word_conversion_loop, args=(_word_queue,),
                name="DOEditorWordConverter", daemon=True)
            _word_thread.start()
        return _word_queue


def word_to_pdf(src_path):
    """用本机 Microsoft Word 把 .docx/.doc 转为 PDF，返回临时 PDF 路径。

    仅在转换期间启动隐藏 Word 实例，完成后立即退出；需要本机安装
    Word；失败抛异常。
    """
    out_path = _word_cache_path(src_path)
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        return out_path

    done = threading.Event()
    result = {}
    _ensure_word_thread().put((src_path, out_path, done, result))
    done.wait()
    if "error" in result:
        # 不保留 Word 可能写到一半的无效缓存。
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except OSError:
            pass
        raise result["error"]
    return result["path"]


def cleanup_word():
    """程序退出时释放复用的 Word 实例。"""
    global _word_thread, _word_queue
    with _word_thread_lock:
        thread = _word_thread
        requests = _word_queue
        _word_thread = None
        _word_queue = None
    if thread is not None and thread.is_alive():
        requests.put(None)
        thread.join(timeout=5)


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


def get_outline(doc):
    """返回 PDF 自带大纲/书签：`[level, title, page, ...]` 的列表。
    无大纲或解析失败时返回空列表。"""
    try:
        toc = doc.get_toc(simple=False)
    except Exception:
        return []
    out = []
    for entry in toc:
        if not entry:
            continue
        level = int(entry[0]) if len(entry) > 0 else 1
        title = entry[1] if len(entry) > 1 else ""
        page = int(entry[2]) - 1 if len(entry) > 2 else 0   # PyMuPDF 页码 1-based → 0-based
        if page < 0:
            page = 0
        out.append([level, str(title), page])
    return out


def extract_text(doc, pno, rect=None):
    """提取第 pno 页文字；rect 为 fitz.Rect 时仅提取该区域。"""
    page = doc[pno]
    if rect is not None:
        return page.get_text("text", clip=rect).strip()
    return page.get_text("text").strip()


# ---------------- OCR ----------------

def create_ocr_engine():
    """创建离线 RapidOCR 引擎；延迟导入以免拖慢普通启动。"""
    from rapidocr import RapidOCR
    return RapidOCR()


def recognize_page_ocr(engine, doc, pno, dpi=220, min_score=0.45):
    """识别一页并返回 PDF 坐标系中的文字行。

    返回值中的每一项为 ``text / score / rect``。OCR 在较高分辨率的
    RGB 图像上运行，随后把检测框精确缩放回 72 dpi 的 PDF 页面坐标。
    """
    import numpy as np

    page = doc[pno]
    scale = max(1.0, float(dpi) / 72.0)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n)
    if pix.n > 3:
        image = image[:, :, :3]
    result = engine(image)
    boxes = getattr(result, "boxes", None)
    texts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if boxes is None or texts is None:
        return []

    sx = page.rect.width / max(1, pix.width)
    sy = page.rect.height / max(1, pix.height)
    lines = []
    for box, text, score in zip(boxes, texts, scores or (1.0,) * len(texts)):
        text = str(text).strip()
        score = float(score)
        if not text or score < min_score:
            continue
        xs = [float(point[0]) * sx for point in box]
        ys = [float(point[1]) * sy for point in box]
        rect = pymupdf.Rect(min(xs), min(ys), max(xs), max(ys))
        if rect.width < 1 or rect.height < 1:
            continue
        lines.append({
            "text": text,
            "score": score,
            "rect": (rect.x0, rect.y0, rect.x1, rect.y1),
        })
    return lines


def add_ocr_text_layer(doc, page_results):
    """把 OCR 结果作为不可见文字层写入 PDF，返回写入的文字行数。"""
    inserted = 0
    for item in page_results:
        pno = int(item["page"])
        if pno < 0 or pno >= len(doc):
            continue
        page = doc[pno]
        for line in item.get("lines", []):
            text = str(line.get("text", "")).strip()
            if not text:
                continue
            rect = pymupdf.Rect(line["rect"])
            # 略微放宽检测框，避免倾斜或紧边界导致 insert_textbox 拒绝写入。
            rect = pymupdf.Rect(rect.x0, rect.y0,
                                min(page.rect.x1, rect.x1 + 2),
                                min(page.rect.y1, rect.y1 + 2))
            fontsize = max(4.0, min(48.0, rect.height * 0.78))
            fontname = "china-s" if _has_cjk(text) else "helv"
            remaining = page.insert_textbox(
                rect, text, fontname=fontname, fontsize=fontsize,
                render_mode=3, overlay=True, lineheight=1.0)
            # 长行偶尔比检测框略宽，逐级缩小直至成功。
            while remaining < 0 and fontsize > 4.0:
                fontsize *= 0.86
                remaining = page.insert_textbox(
                    rect, text, fontname=fontname, fontsize=fontsize,
                    render_mode=3, overlay=True, lineheight=1.0)
            if remaining >= 0:
                inserted += 1
    return inserted


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


def add_image_watermark(doc, image_path, opacity=0.3, rotate=0, tiled=True,
                        scale=0.5):
    """给所有页面添加图片水印。

    image_path: 图片文件路径；opacity: 0-1 透明度；rotate: 旋转角度；
    tiled: True 平铺 / False 居中单张；scale: 水印图相对页面宽度的比例(0.05-1)。
    """
    from io import BytesIO
    from PIL import Image as PILImage
    try:
        img = PILImage.open(image_path).convert("RGBA")
    except Exception:
        return False
    # 应用透明度（直接把 alpha 通道按 opacity 压缩）。
    r, g, b, a = img.split()
    a = a.point(lambda v: int(v * opacity))
    img = PILImage.merge("RGBA", (r, g, b, a))
    if rotate:
        # 真正旋转图片内容（expand 保留完整画幅，避免内容被裁切）。
        img = img.rotate(rotate, expand=True, resample=PILImage.BICUBIC)
    buf = BytesIO()
    img.save(buf, format="PNG")
    pix = pymupdf.Pixmap(buf.getvalue())
    iw, ih = pix.width, pix.height
    if iw <= 0 or ih <= 0:
        return False
    for page in doc:
        pr = page.rect
        target_w = max(20.0, pr.width * max(0.05, min(1.0, scale)))
        target_h = target_w * ih / iw
        if tiled:
            step_x = max(target_w * 2.0, target_w + 40)
            step_y = max(target_h * 2.0, target_h + 40)
            y = pr.y0 + step_y / 2
            while y < pr.y1 - 10:
                x = pr.x0 + step_x / 2
                while x < pr.x1 - 10:
                    page.insert_image(
                        pymupdf.Rect(x, y, x + target_w, y + target_h),
                        pixmap=pix, overlay=True)
                    x += step_x
                y += step_y
        else:
            cx, cy = pr.width / 2, pr.height / 2
            page.insert_image(
                pymupdf.Rect(cx - target_w / 2, cy - target_h / 2,
                             cx + target_w / 2, cy + target_h / 2),
                pixmap=pix, overlay=True)
    return True


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
        # PyMuPDF 的文本标记颜色属于 stroke；fill 会被 PDF 引擎忽略。
        _color(a, stroke=color)
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


def add_note(page, point, text, color=None):
    annot = page.add_text_annot(point, text)
    if color is not None:
        _color(annot, stroke=color)
    return annot


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
