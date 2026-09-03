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


def _is_cjk_char(ch):
    """判定字符属于 CJK 书写系统(汉字/假名/谚文/CJK 符号/全角)。

    PyMuPDF Story 引擎对 CJK 字符统一落到 Droid Sans Fallback Regular,
    不区分斜体字面(真实斜体面不存在)且不做合成斜体, 因此含 CJK 的斜体
    需走 transform: skewX(-14deg) 合成斜体; 否则 CSS font-style:italic
    对汉字无声地退化为正体(导致保存斜体失效, 见 _verify_cjk_italic.py)。
    """
    if not ch:
        return False
    c = ord(ch)
    return (0x4E00 <= c <= 0x9FFF      # CJK Unified Ideographs
            or 0x3400 <= c <= 0x4DBF   # CJK Ext A
            or 0x3040 <= c <= 0x30FF   # Hiragana / Katakana
            or 0xAC00 <= c <= 0xD7AF   # Hangul Syllables
            or 0x3000 <= c <= 0x303F   # CJK Symbols & Punctuation
            or 0xFF00 <= c <= 0xFFEF)  # Halfwidth / Fullwidth Forms


def _partition_italic(text):
    """按 CJK / 非 CJK 把文本切成段, 用于对含汉字的斜体做分段样式处理。

    返回 [(seg_text, is_cjk_segment), ...]; 连续同类字符合并为一段。
    """
    if not text:
        return []
    out = []
    cur_is_cjk = _is_cjk_char(text[0])
    start = 0
    for i in range(1, len(text)):
        if _is_cjk_char(text[i]) != cur_is_cjk:
            out.append((text[start:i], cur_is_cjk))
            start = i
            cur_is_cjk = not cur_is_cjk
    out.append((text[start:], cur_is_cjk))
    return out


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


def font_style_flags(fontname, flags=0):
    """综合 PDF 字体名与 span flags 推断粗体/斜体。

    部分 PDF 生产工具不写 bold/italic flags，而是把样式拼进字体名
    （例如 Arial-BoldMT / SimSun,Italic），只查 flags 会漏判。
    返回 (bold, italic)。
    """
    low = (fontname or "").lower()
    bold = bool(flags & 16) or any(
        k in low for k in ("bold", "black", "heavy", "demi", "semibold",
                           "extrabold", "ultrabold"))
    italic = bool(flags & 2) or any(
        k in low for k in ("italic", "oblique", "kursiv"))
    return bold, italic



def insert_text_auto(page, rect, text, fontsize=12, color=(0, 0, 0), fontfamily="",
                     bold=False, italic=False):
    """插入文字，自动处理中英文字体。fontfamily 为系统字体名，映射为衬线/无衬线/等宽。

    含 CJK 字符且 italic=True 时, 把文本按 CJK / 非 CJK 分段, 绕开
    insert_htmlbox(实测: CSS `font-style:italic` 对内置 CJK 字面无声;
    CSS `transform:skewX` 在 insert_htmlbox 也不生效) 直接用
    `page.insert_text` 绘制: CJK 段走内置 `china-s` 字体 + morph 错切
    矩阵合成斜体; 非 CJK 段走内置 `hebo`(Helvetica Oblique, 加粗时
    `hebi`) 真斜体字面; 两类在同一基线上累加 `text_length` 推进光标。
    其余分支维持原有 htmlbox 单行 + CSS 路径不变。
    """
    import pymupdf as _pym

    if italic and any(_is_cjk_char(c) for c in text):
        r255 = _rgb255(color)
        _draw_italic_cjk_segments(
            page, rect, _partition_italic(text), fontsize, r255, bold=bold)
        return

    import html as _html
    r, g, b = [int(round(c * 255)) for c in color]
    fam = _css_font_family(fontfamily)
    weight = "bold" if bold else "normal"
    style = "italic" if italic else "normal"
    css = (f"* {{ font-family: {fam}; font-size: {fontsize}px; "
           f"color: rgb({r},{g},{b}); font-weight: {weight}; font-style: {style}; }}")
    page.insert_htmlbox(rect, _html.escape(text).replace("\n", "<br>"), css=css)


def _draw_italic_cjk_segments(page, rect, segments, fontsize, color_255, bold=False,
                              x_start=None):
    """CJK + italic 合成斜体直接绘制(支持从任意 x 起点并返回占用宽度)。

    segments: [(seg_text, is_cjk), ...] — 由 _partition_italic 生成。
    单一基线单行(无 wrap): text 过长超出 rect 时仍按左对齐绘制, 右侧
    可能溢出, 与原始 htmlbox 行为一致(短文本场景)。
    """
    import pymupdf as _pym
    tan_a = 0.2493    # tan(14°), 合成右倾 italic(主流 PDF 阅读器方向; PyMuPDF
                 # 自家 get_pixmap 渲染下方向会反转, 故此处不用负号)
    skew_matrix = _pym.Matrix(1, 0, tan_a, 1, 0, 0)
    ascender = fontsize * 0.8
    y_baseline = rect.y0 + ascender
    if x_start is None:
        x_start = rect.x0
    f_cjk = _pym.Font("china-s")
    f_lat = _pym.Font("hebi" if bold else "heit")
    color_f = tuple(c / 255.0 for c in color_255)
    x_cursor = x_start
    for seg, is_cjk in segments:
        if not seg:
            continue
        if is_cjk:
            pivot = _pym.Point(x_cursor, y_baseline)
            page.insert_text(
                (x_cursor, y_baseline), seg,
                fontname="china-s", fontsize=fontsize,
                color=color_f, morph=(pivot, skew_matrix))
        else:
            page.insert_text(
                (x_cursor, y_baseline), seg,
                fontname=f_lat.name, fontsize=fontsize,
                color=color_f)
        x_cursor += f_cjk.text_length(seg, fontsize) if is_cjk \
                    else f_lat.text_length(seg, fontsize)
    return x_cursor - x_start


def _rgb255(color):
    """颜色值(QColor 或 (r,g,b) 0..1 或 (r,g,b) 0..255)→ (r,g,b) 0..255。"""
    if hasattr(color, "redF"):          # QColor / QColor-like
        return (int(round(color.redF() * 255)),
                int(round(color.greenF() * 255)),
                int(round(color.blueF() * 255)))
    try:
        r, g, b = (float(c) for c in color[:3])
    except Exception:
        return 0, 0, 0
    if max(r, g, b) <= 1.0001:
        return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))
    return int(round(r)), int(round(g)), int(round(b))


def insert_rich_text_auto(page, rect, runs):
    """插入富文本（字符级混排）。runs 为样式段列表，每段含
    text / family(系统字体名) / size(pt) / color / bold / italic。

    逐段生成内联 span 后由 insert_htmlbox 排版；字号以 pt 语义
    与 insert_text_auto 保持一致。

    若任一 run 含 CJK 且 italic=True, htmlbox 无法合成 CJK 斜体, 改走
    直接 `page.insert_text` 路径: CJK 段内置 china-s + morph 错切合成
    斜体; 非 CJK 段内置 hebo/hebi 真斜体; 各 run 按自己的 size/color/
    bold 在同一基线上串联(以 rect.x0 起步, x 累加 text_length)。
    其余分支维持原有 htmlbox 路径不变。
    """
    import pymupdf as _pym

    # 若任何 run 含 CJK 且 italic=True, htmlbox 路径无法合成 CJK 斜体
    # (CSS transform 在 insert_htmlbox 不生效, font-style:italic 对汉字无声);
    # 改走直接 page.insert_text 路径: CJK 段内置 china-s + morph 错切,
    # 非 CJK 段内置 hebo/hebi 真斜体, 各 run 按尺寸/颜色在同一基线串联。
    if any(r.get("italic") and any(_is_cjk_char(c) for c in (r.get("text") or ""))
           for r in runs or []):
        x_cursor = rect.x0
        for run in runs or []:
            text = (run.get("text") or "")
            if not text:
                continue
            size = max(1.0, float(run.get("size") or 12.0))
            color = _rgb255(run.get("color") or (0, 0, 0))
            color_f = tuple(c / 255.0 for c in color)
            italic = bool(run.get("italic"))
            bold = bool(run.get("bold"))
            has_cjk = any(_is_cjk_char(c) for c in text)
            y_run = rect.y0 + size * 0.8
            if italic and has_cjk:
                w = _draw_italic_cjk_segments(
                    page, rect, _partition_italic(text), size, color,
                    bold=bold, x_start=x_cursor)
                x_cursor += w
            elif has_cjk:
                # 非斜体 CJK 段: 内置 china-s 覆盖汉字, 同步推进 x_cursor
                page.insert_text((x_cursor, y_run), text,
                                 fontname="china-s", fontsize=size,
                                 color=color_f)
                x_cursor += _pym.Font("china-s").text_length(text, size)
            else:
                fontname = (
                    "hebi" if (italic and bold) else
                    "heit" if italic else
                    "hebo" if bold else "helv")
                page.insert_text((x_cursor, y_run), text,
                                 fontname=fontname, fontsize=size,
                                 color=color_f)
                x_cursor += _pym.Font(fontname).text_length(text, size)
        return

    import html as _html
    parts = []
    for run in runs or []:
        text = (run.get("text") or "")
        if not text:
            continue
        fam = _css_font_family(run.get("family") or "")
        weight = "bold" if run.get("bold") else "normal"
        run_italic = bool(run.get("italic"))
        size = max(1.0, float(run.get("size") or 12.0))
        r, g, b = _rgb255(run.get("color") or (0, 0, 0))
        style = "italic" if run_italic else "normal"
        esc = _html.escape(text).replace("\n", "<br>")
        parts.append(
            f'<span style="font-family:{fam};font-size:{size}px;'
            f'font-weight:{weight};font-style:{style};'
            f'color:rgb({r},{g},{b});">{esc}</span>')
    if not parts:
        return
    page.insert_htmlbox(rect, "".join(parts),
                        css="*{margin:0;padding:0;}")


def redact_rect(page, rect):
    """删除指定矩形区域内的原有内容（用于修改文字前清除原文）。"""
    page.add_redact_annot(rect)
    page.apply_redactions()


def _safe_y_range(page, line_rect, self_cy=None):
    """把行 bbox 的 y 范围钳制到不与任何其它文字行 bbox 相交。

    PyMuPDF 行 bbox 含字体 ascend/descend，行距紧凑的文档（正文/表格）
    相邻行 bbox 互相交叠；红act 会删除与矩形相交的整段文本，直接按
    整行 bbox 擦除会把相邻整行文字一并吞掉。这里把 y 上/下界收缩到
    最近邻行的内侧边缘（留 0.1pt 安全缝），红act 矩形即与其它行零
    相交。返回 (y0, y1)；收缩过狠（不足半行高）时仍返回原范围由
    调用方决定。
    """
    import pymupdf as _pym
    y0, y1 = float(line_rect.y0), float(line_rect.y1)
    h = y1 - y0
    cy = float(self_cy) if self_cy is not None else (y0 + y1) / 2.0
    eps = 0.1
    above_bottom = None      # 上方最近的其它行底
    below_top = None         # 下方最近的其它行顶
    try:
        data = page.get_text("dict")
    except Exception:
        data = {}
    for b in data.get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []) or []:
            bb = ln.get("bbox")
            if not bb or len(bb) != 4:
                continue
            oy0, oy1 = float(bb[1]), float(bb[3])
            ocy = (oy0 + oy1) / 2.0
            if abs(ocy - cy) < h * 0.6:
                continue                 # 同一行（含上下交叠的同带兄弟行），跳过
            if oy1 <= cy:
                if above_bottom is None or oy1 > above_bottom:
                    above_bottom = oy1
            elif oy0 >= cy:
                if below_top is None or oy0 < below_top:
                    below_top = oy0
    if above_bottom is not None:
        y0 = max(y0, above_bottom + eps)
    if below_top is not None:
        y1 = min(y1, below_top - eps)
    return y0, y1


def redact_line_safe(page, line_rect, erase_rect=None):
    """按行删除文字，但不误伤相邻行。

    line_rect 为命中行 bbox（决定删除哪一行），erase_rect 为字符级
    实际区域（决定 x 范围，默认取 line_rect）；y 方向按邻行边界钳制，
    保证红act 矩形不与其它行相交，杜绝整行误删。
    """
    import pymupdf as _pym
    er = erase_rect or line_rect
    y0, y1 = _safe_y_range(page, line_rect)
    if y1 - y0 < 0.2:
        # 整行被上下行夹死（理论极罕见）：退回整行红act，宁残留不扩散
        redact_rect(page, er)
        return
    page.add_redact_annot(
        _pym.Rect(er.x0, y0, er.x1, y1))
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
