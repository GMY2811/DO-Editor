"""PDF 核心逻辑（纯 PyMuPDF，无界面依赖，便于独立测试）。"""
import hashlib
import json
import os
import queue
import re
import tempfile
import threading
import uuid
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
    elif encrypted and not requires_password:
        # 只设了所有者密码、打开密码为空的文件：任何人不输密码即可
        # 打开。主动以空密码认证，让 _auth_level 记录真实的 user 级
        # 权限（authenticate 返回 2 = user / 4 = owner），避免上层把
        # 这种文档误判为"未认证(0)"而绕过所有者保护。
        try:
            auth_level = int(doc.authenticate(""))
        except Exception:
            auth_level = 0
    doc._do_was_encrypted = encrypted
    doc._do_auth_level = auth_level
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

_ocr_engine = None
_ocr_engine_lock = threading.Lock()

def create_ocr_engine():
    """取得进程级复用的离线 RapidOCR 引擎。

    三个 ONNX session 的初始化约需 0.8 秒。旧实现每次点击 OCR 都重新
    创建；现在只创建一次，后续页面和任务直接复用。
    """
    global _ocr_engine
    if _ocr_engine is not None:
        return _ocr_engine
    with _ocr_engine_lock:
        if _ocr_engine is not None:
            return _ocr_engine
        _ocr_engine = _create_ocr_engine_uncached()
        return _ocr_engine


def _create_ocr_engine_uncached():
    """实际创建 RapidOCR 引擎；由 create_ocr_engine 串行调用。"""
    from pathlib import Path
    import rapidocr
    from rapidocr import RapidOCR
    # 修复：rapidocr 内部在 Windows 下会将 pathlib.WindowsPath 直接赋给
    # OmegaConf 字段 Global.model_root_dir，导致 "WindowsPath is not a supported
    # primitive type"。这里提前以 str 路径注入 params，让其保持非 None，
    # 库内 main.py:60 的 is None 分支不会触发，绕开该 OmegaConf 限制。
    models_dir = Path(rapidocr.__file__).resolve().parent / "models"
    return RapidOCR(params={"Global.model_root_dir": str(models_dir)})


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
    # 保留完整方向分类和 220 DPI 输入：小字号、低质量扫描和倒置文本
    # 都以识别率优先，不用质量换速度。
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

_WATERMARK_OCG_PREFIX = "DOEditor.Watermark."
_WATERMARK_STREAM_MARKER = b"% DOEDITOR_WATERMARK "


def _new_pdf_stream(doc, data, object_type="DOEditorWatermarkData"):
    """创建由 PDF 引用关系持有的私有数据流。"""
    xref = doc.get_new_xref()
    doc.update_object(xref, f"<< /Type /{object_type} >>")
    doc.update_stream(xref, data)
    return xref


def _xref_from_key(doc, xref, key):
    try:
        kind, value = doc.xref_get_key(xref, key)
    except Exception:
        return 0
    if kind != "xref":
        return 0
    match = re.match(r"\s*(\d+)\s+\d+\s+R", value or "")
    return int(match.group(1)) if match else 0


def _read_watermark_meta(doc, ocg_xref):
    meta_xref = _xref_from_key(doc, ocg_xref, "DOEditorMeta")
    if not meta_xref:
        return None
    try:
        value = json.loads(doc.xref_stream(meta_xref).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(value, dict) or value.get("schema") != 1:
        return None
    value["ocg_xref"] = int(ocg_xref)
    value["meta_xref"] = meta_xref
    value["source_xref"] = _xref_from_key(doc, ocg_xref, "DOEditorSource")
    value["origin"] = "do-editor"
    return value


def _write_watermark_meta(doc, ocg_xref, meta, source_bytes=None):
    """把设置写入 OCG 引用的私有流；引用在 xref 重排后仍然有效。"""
    stored = dict(meta)
    stored["schema"] = 1
    stored.pop("ocg_xref", None)
    stored.pop("meta_xref", None)
    stored.pop("source_xref", None)
    stored.pop("origin", None)
    data = json.dumps(stored, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    meta_xref = _xref_from_key(doc, ocg_xref, "DOEditorMeta")
    if not meta_xref:
        meta_xref = _new_pdf_stream(doc, data)
        doc.xref_set_key(ocg_xref, "DOEditorMeta", f"{meta_xref} 0 R")
    else:
        doc.update_stream(meta_xref, data)
    if source_bytes is not None:
        source_xref = _xref_from_key(doc, ocg_xref, "DOEditorSource")
        if not source_xref:
            source_xref = _new_pdf_stream(
                doc, source_bytes, "DOEditorWatermarkSource")
            doc.xref_set_key(ocg_xref, "DOEditorSource", f"{source_xref} 0 R")
        else:
            doc.update_stream(source_xref, source_bytes)


def _watermark_context(doc, kind, settings, watermark_id=None, ocg_xref=0,
                       source_bytes=None):
    watermark_id = watermark_id or uuid.uuid4().hex
    if not ocg_xref:
        ocg_xref = doc.add_ocg(_WATERMARK_OCG_PREFIX + watermark_id)
    meta = dict(settings)
    meta.update({"id": watermark_id, "kind": kind, "schema": 1})
    _write_watermark_meta(doc, ocg_xref, meta, source_bytes)
    return watermark_id, ocg_xref


def _mark_new_watermark_streams(doc, page, previous, watermark_id):
    marker = _WATERMARK_STREAM_MARKER + watermark_id.encode("ascii") + b"\n"
    for xref in page.get_contents():
        if xref in previous:
            continue
        try:
            stream = doc.xref_stream(xref)
            if marker not in stream:
                doc.update_stream(xref, marker + stream)
        except Exception:
            continue


def _blank_watermark_streams(doc, watermark_id):
    """只清空带本水印 UUID 的独立内容流，绝不重写正文内容流。"""
    marker = _WATERMARK_STREAM_MARKER + watermark_id.encode("ascii")
    count = 0
    for page in doc:
        for xref in page.get_contents():
            try:
                stream = doc.xref_stream(xref)
            except Exception:
                continue
            if marker in stream:
                doc.update_stream(xref, b"")
                count += 1
    return count


def _set_ocg_hidden(doc, ocg_xref):
    """关闭外部 OCG；失败时不改变文档。"""
    try:
        state = doc.get_layer(-1) or {}
        on = [x for x in state.get("on", []) if x != ocg_xref]
        off = list(dict.fromkeys(list(state.get("off", [])) + [ocg_xref]))
        doc.set_layer(-1, basestate=state.get("basestate"), on=on, off=off,
                      rbgroups=state.get("rbgroups"), locked=state.get("locked"))
        return True
    except Exception:
        try:
            doc.set_layer(-1, off=[ocg_xref])
            return True
        except Exception:
            return False


def _page_resource_xref(doc, page):
    """查找页面或父 Pages 节点继承的 Resources 字典。"""
    xref = page.xref
    visited = set()
    while xref and xref not in visited:
        visited.add(xref)
        kind, value = doc.xref_get_key(xref, "Resources")
        if kind == "xref":
            return int(value.split()[0])
        parent = _xref_from_key(doc, xref, "Parent")
        xref = parent
    return 0


def _page_ocg_property_names(doc, page, ocg_xref):
    resources = _page_resource_xref(doc, page)
    if not resources:
        return set()
    kind, value = doc.xref_get_key(resources, "Properties")
    if kind == "xref":
        value = doc.xref_object(int(value.split()[0]), compressed=True)
    if kind not in ("dict", "xref"):
        return set()
    pattern = re.compile(r"/([^\s/<>{}\[\]()]+)\s+" +
                         str(int(ocg_xref)) + r"\s+\d+\s+R\b")
    return {match.group(1) for match in pattern.finditer(value)}


def _remove_marked_content(stream, property_names, ocg_xref):
    """从内容流中移除目标 OCG 的 BDC/EMC 区段，保留其余操作符。"""
    starts = []
    for name in property_names:
        starts.extend(re.finditer(
            rb"/OC\s+/" + re.escape(name.encode("latin1")) + rb"\s+BDC\b",
            stream))
    starts.extend(re.finditer(
        rb"/OC\s+" + str(int(ocg_xref)).encode("ascii") +
        rb"\s+\d+\s+R\s+BDC\b", stream))
    spans = []
    token_re = re.compile(rb"\b(BDC|BMC|EMC)\b")
    for start in starts:
        depth = 1
        end = None
        for token in token_re.finditer(stream, start.end()):
            if token.group(1) in (b"BDC", b"BMC"):
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    end = token.end()
                    break
        if end is not None:
            spans.append((start.start(), end))
    if not spans:
        return stream, False
    out = bytearray(stream)
    for start, end in sorted(spans, reverse=True):
        out[start:end] = b"\n% removed watermark\n"
    return bytes(out), True


def _remove_ocg_page_content(doc, ocg_xref):
    """精确移除 OCG 标记内容及直接挂载该 OCG 的 XObject 调用。"""
    changed = 0
    for page in doc:
        property_names = _page_ocg_property_names(doc, page, ocg_xref)
        xobject_names = set()
        try:
            for item in page.get_xobjects():
                xref, name = int(item[0]), str(item[1])
                try:
                    if doc.get_oc(xref) == ocg_xref:
                        xobject_names.add(name)
                except Exception:
                    pass
        except Exception:
            pass
        for stream_xref in page.get_contents():
            try:
                original = doc.xref_stream(stream_xref)
            except Exception:
                continue
            updated, touched = _remove_marked_content(
                original, property_names, ocg_xref)
            for name in xobject_names:
                updated, n = re.subn(
                    rb"/" + re.escape(name.encode("latin1")) + rb"\s+Do\b",
                    # 不能写入无换行的 % 注释：某些生成器把整页操作符
                    # 压在一行，注释会吞掉水印之后的全部页面内容。
                    lambda match: b" " * (match.end() - match.start()),
                    updated)
                touched = touched or bool(n)
            if touched and updated != original:
                doc.update_stream(stream_xref, updated)
                changed += 1
    return changed


def _ocg_text_preview(page, layer_name):
    for span in page.get_texttrace():
        if span.get("layer") != layer_name:
            continue
        chars = []
        for char in span.get("chars", []):
            try:
                codepoint = int(char[0])
                if codepoint > 0:
                    chars.append(chr(codepoint))
            except Exception:
                pass
        text = "".join(chars).strip()
        if text:
            return text, float(span.get("size", 50)), float(span.get("opacity", 1))
    return "", 50.0, 1.0


def list_watermarks(doc, include_candidates=False):
    """枚举可安全管理的水印，并可选执行保守的普通对象候选检测。"""
    result = []
    ocgs = doc.get_ocgs() or {}
    for xref, info in ocgs.items():
        meta = _read_watermark_meta(doc, xref)
        if meta:
            meta["label"] = (meta.get("text") or meta.get("image_name") or
                             ("文字水印" if meta.get("kind") == "text" else "图片水印"))
            result.append(meta)
            continue
        name = str(info.get("name", ""))
        # 已删除的 DO 水印仍可能留下一个空 OCG 外壳；它既没有内容也没有
        # 元数据，不能再作为 Acrobat 外部水印重新列出。
        if name.startswith(_WATERMARK_OCG_PREFIX):
            continue
        if doc.xref_get_key(xref, "DOEditorRemoved")[1] == "true":
            continue
        raw = doc.xref_object(xref, compressed=False)
        # Acrobat 普通水印使用 OCG。名称或 Usage/PageElement 中含 Watermark
        # 才认为可安全隐藏，避免把普通 CAD / 多语言图层误判成水印。
        if not (re.search(r"water\s*mark|水印", name, re.I) or
                re.search(r"/Subtype\s*/Watermark\b", raw, re.I)):
            continue
        kind = "unknown"
        preview = ""
        pages = []
        for pno, page in enumerate(doc):
            entries = [x for x in page.get_bboxlog(layers=True)
                       if len(x) > 2 and x[2] == name]
            if not entries:
                continue
            pages.append(pno)
            types = {x[0] for x in entries}
            if any("image" in x for x in types):
                kind = "image"
            elif any("text" in x for x in types):
                kind = "text"
                if not preview:
                    preview = _ocg_text_preview(page, name)[0]
        result.append({
            "id": f"ocg:{xref}", "kind": kind, "origin": "acrobat-ocg",
            "ocg_xref": int(xref), "name": name, "text": preview,
            "pages": pages, "label": preview or name or "Acrobat Watermark",
        })

    # FixedPrint 使用标准 /Subtype /Watermark 注释，不走普通页面 OCG。
    for pno, page in enumerate(doc):
        annot = page.first_annot
        while annot:
            if annot.type[0] == pymupdf.PDF_ANNOT_WATERMARK:
                try:
                    text = annot.get_text().strip()
                except Exception:
                    text = ""
                result.append({
                    "id": f"fixed:{pno}:{annot.xref}",
                    "kind": "text" if text else "image",
                    "origin": "acrobat-fixed", "page": pno,
                    "annot_xref": annot.xref, "pages": [pno],
                    "text": text, "image_name": "FixedPrint Watermark.png",
                    "label": text or f"FixedPrint Watermark (p. {pno + 1})",
                })
            annot = annot.next
    if include_candidates:
        result.extend(detect_watermark_candidates(doc))
    return result


def watermark_source_bytes(doc, record):
    xref = int(record.get("source_xref") or 0)
    if xref:
        try:
            return doc.xref_stream(xref)
        except Exception:
            pass
    # Acrobat 图片水印有时把 OCG 直接挂在 Image XObject 上。
    ocg = int(record.get("ocg_xref") or 0)
    if ocg:
        for page in doc:
            for image in page.get_images(full=True):
                image_xref = int(image[0])
                try:
                    if doc.get_oc(image_xref) == ocg:
                        return doc.extract_image(image_xref).get("image")
                except Exception:
                    continue
    if record.get("origin") == "acrobat-fixed":
        try:
            page = doc[int(record["page"])]
            annot = page.load_annot(int(record["annot_xref"]))
            if annot is not None:
                return annot.get_pixmap(alpha=True).tobytes("png")
        except Exception:
            pass
    if record.get("origin") == "candidate" and record.get("image_xref"):
        try:
            return doc.extract_image(int(record["image_xref"])).get("image")
        except Exception:
            pass
    return None


def _candidate_text(page):
    traces = page.get_texttrace()
    if not traces:
        return None
    texts = []
    opacity = 1.0
    size = 0.0
    rotated = False
    for span in traces:
        chars = []
        for char in span.get("chars", []):
            try:
                if int(char[0]) > 0:
                    chars.append(chr(int(char[0])))
            except Exception:
                pass
        if chars:
            texts.append("".join(chars))
        opacity = min(opacity, float(span.get("opacity", 1)))
        size = max(size, float(span.get("size", 0)))
        direction = span.get("dir", (1, 0))
        rotated = rotated or abs(float(direction[1])) > 0.08
    text = " ".join(x.strip() for x in texts if x.strip()).strip()
    if not text or len(text) > 300:
        return None
    if opacity >= 0.9 and not rotated and size < 24:
        return None
    return {"kind": "text", "text": text, "opacity": opacity,
            "fontsize": size, "rotated": rotated}


def detect_watermark_candidates(doc):
    """检测位于独立页面内容流中的疑似水印。

    每个候选的删除单位都是完整独立流，所以不会擦除其下方正文。只把淡色、
    旋转或大字号文字，以及独立图片流列为候选；最终仍须用户确认。
    """
    try:
        probe = pymupdf.open(stream=doc.tobytes(garbage=0), filetype="pdf")
    except Exception:
        return []
    found = []
    try:
        for pno in range(len(probe)):
            source_page = doc[pno]
            probe_page = probe[pno]
            for stream_xref in source_page.get_contents():
                try:
                    stream = doc.xref_stream(stream_xref)
                except Exception:
                    continue
                if not stream.strip() or _WATERMARK_STREAM_MARKER in stream:
                    continue
                probe.xref_set_key(probe_page.xref, "Contents",
                                   f"{stream_xref} 0 R")
                probe_page = probe.reload_page(probe_page)
                # 标准 OCG 会走上面的确定性识别，不重复列为候选。
                boxes = probe_page.get_bboxlog(layers=True)
                if boxes and any(len(x) > 2 and x[2] for x in boxes):
                    continue
                info = _candidate_text(probe_page)
                if info:
                    signature = "text:" + re.sub(r"\s+", " ", info["text"]).casefold()
                else:
                    painted = [x for x in boxes if x[0] == "fill-image"]
                    non_image = [x for x in boxes if x[0] != "fill-image"]
                    if not painted or non_image:
                        continue
                    signature = "image:" + hashlib.sha256(stream).hexdigest()
                    info = {"kind": "image", "text": ""}
                info.update({"page": pno, "stream_xref": stream_xref,
                             "signature": signature})
                found.append(info)
    finally:
        probe.close()

    groups = {}
    for item in found:
        groups.setdefault(item["signature"], []).append(item)
    result = []
    for signature, items in groups.items():
        first = items[0]
        repeated = len({x["page"] for x in items}) >= 2
        # 许多 Office / 打印驱动生成的水印并不用透明度，而是用浅灰填充色。
        # Acrobat 的“编辑 PDF”仍会把这种大号旋转文字识别为独立对象。
        # 旧条件强制 opacity < .65，因而漏掉用户样本中 90pt、旋转 20°、
        # 灰色但 opacity=1 的 UPDATED 水印。
        strong_single = (first["kind"] == "text" and (
            (first.get("rotated") and first.get("fontsize", 0) >= 24) or
            (first.get("opacity", 1) < 0.65 and
             first.get("fontsize", 0) >= 24)))
        if not repeated and not strong_single:
            continue
        ident = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:20]
        label = first.get("text") or "疑似图片水印"
        result.append({
            "id": f"candidate:{ident}", "kind": first["kind"],
            "origin": "candidate", "label": label,
            "text": first.get("text", ""),
            "pages": sorted({x["page"] for x in items}),
            "locations": [{"page": x["page"], "stream_xref": x["stream_xref"]}
                          for x in items],
        })
    return result


def _isolated_stream_page(doc, pno, stream_xref):
    """返回仅显示指定页面内容流的临时文档和页面。

    xref 在 ``doc.tobytes(garbage=0)`` 中保持不变。调用方必须关闭返回的
    document。该探针只用于判断对象边界，不会修改用户文档。
    """
    probe = pymupdf.open(stream=doc.tobytes(garbage=0), filetype="pdf")
    page = probe[pno]
    probe.xref_set_key(page.xref, "Contents", f"{int(stream_xref)} 0 R")
    page = probe.reload_page(page)
    return probe, page


def _font_unicode_map(doc, font_xref):
    """读取字体 ToUnicode CMap，返回 Unicode 单字符到原字形代码的映射。"""
    try:
        kind, value = doc.xref_get_key(int(font_xref), "ToUnicode")
        match = re.search(r"(\d+)\s+0\s+R", value or "") if kind == "xref" else None
        if not match:
            return {}
        raw = doc.xref_stream(int(match.group(1)))
    except Exception:
        return {}
    result = {}

    def add_pair(source_hex, target_hex):
        try:
            source = bytes.fromhex(source_hex.decode("ascii"))
            text = bytes.fromhex(target_hex.decode("ascii")).decode("utf-16-be")
            if len(text) == 1:
                result.setdefault(text, source)
        except Exception:
            pass

    for block in re.finditer(rb"beginbfchar(.*?)endbfchar", raw, re.S | re.I):
        for source, target in re.findall(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block.group(1)):
            add_pair(source, target)
    for block in re.finditer(rb"beginbfrange(.*?)endbfrange", raw, re.S | re.I):
        body = block.group(1)
        for start, end, target in re.findall(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*"
                rb"<([0-9A-Fa-f]+)>", body):
            try:
                src0, src1 = int(start, 16), int(end, 16)
                dst0, width = int(target, 16), len(start) // 2
                for offset, code in enumerate(range(src0, src1 + 1)):
                    result.setdefault(chr(dst0 + offset), code.to_bytes(width, "big"))
            except Exception:
                pass
        for start, end, targets in re.findall(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]",
                body, re.S):
            try:
                src0, src1 = int(start, 16), int(end, 16)
                width = len(start) // 2
                values = re.findall(rb"<([0-9A-Fa-f]+)>", targets)
                for code, target in zip(range(src0, src1 + 1), values):
                    source = code.to_bytes(width, "big").hex().encode("ascii")
                    add_pair(source, target)
            except Exception:
                pass
    return result


def _font_encoding_map(doc, font_row):
    """返回可用于原内容流改写的 Unicode -> 字节映射。

    嵌入字体优先使用 ToUnicode；PDF 内置字体通常没有 ToUnicode，需按
    字体资源声明的编码生成映射。这样 Helvetica 等标准字体也无需经过
    redact + insert_text（该路径会重新选字体并改变视觉格式）。
    """
    cmap = _font_unicode_map(doc, int(font_row[0]))
    if cmap:
        return cmap
    encoding = str(font_row[5] or "")
    codec = {
        "WinAnsiEncoding": "cp1252",
        "MacRomanEncoding": "mac_roman",
    }.get(encoding)
    if codec:
        result = {}
        for value in range(256):
            try:
                char = bytes([value]).decode(codec)
            except UnicodeDecodeError:
                continue
            if len(char) == 1:
                result.setdefault(char, bytes([value]))
        return result
    # PyMuPDF 的 CJK 内置字体使用这些 Unicode CMap，内容字符串本身就是
    # UTF-16BE 编码；直接替换编码值即可保留原 Tf / Tm / 颜色等操作符。
    if encoding in {
            "UniGB-UTF16-H", "UniCNS-UTF16-H",
            "UniJIS-UTF16-H", "UniKS-UTF16-H"}:
        return {chr(value): chr(value).encode("utf-16-be")
                for value in range(0x10000)
                if not 0xD800 <= value <= 0xDFFF}
    return {}


def _normalized_font_name(name):
    name = re.sub(r"^[A-Za-z]{6}\+", "", str(name or ""))
    normalized = re.sub(r"[\s,_-]+", "", name).lower()
    # 提取层常报告 Arial-BoldMT，而 BaseFont 为 Arial Bold；MT 只是
    # PostScript 命名后缀，不代表不同字体。
    if normalized.endswith("mt"):
        normalized = normalized[:-2]
    return normalized


_HEX_TJ_RE = re.compile(rb"<([0-9A-Fa-f\s]*)>\s*Tj\b", re.I)
_HEX_TJ_ARRAY_RE = re.compile(rb"\[(.*?)\]\s*TJ\b", re.S)
_FONT_SELECT_RE = re.compile(
    rb"/([^\s/<>{}\[\]()]+)\s+[-+]?(?:\d+(?:\.\d*)?|\.\d+)\s+Tf\b")


def _hex_text_tokens(stream):
    """枚举简单十六进制 Tj/TJ，返回 (start, end, encoded_bytes)。"""
    tokens, array_ranges = [], []
    for match in _HEX_TJ_ARRAY_RE.finditer(stream):
        chunks = re.findall(rb"<([0-9A-Fa-f\s]*)>", match.group(1))
        try:
            encoded = b"".join(bytes.fromhex(
                re.sub(rb"\s+", b"", chunk).decode("ascii")) for chunk in chunks)
        except Exception:
            continue
        if chunks:
            tokens.append((match.start(), match.end(), encoded))
            array_ranges.append((match.start(), match.end()))
    for match in _HEX_TJ_RE.finditer(stream):
        if any(start <= match.start() < end for start, end in array_ranges):
            continue
        try:
            encoded = bytes.fromhex(
                re.sub(rb"\s+", b"", match.group(1)).decode("ascii"))
        except Exception:
            continue
        tokens.append((match.start(), match.end(), encoded))
    return sorted(tokens)


def find_direct_text_object(doc, pno, text, rect, span_font):
    """定位可在原内容流中直接改字形代码的单样式文字。"""
    if pno < 0 or pno >= len(doc) or not text or not span_font:
        return None
    page = doc[pno]
    wanted_font = _normalized_font_name(span_font)
    font_row = next((item for item in page.get_fonts(full=True)
                     if _normalized_font_name(item[3]) == wanted_font), None)
    if font_row is None:
        return None
    cmap = _font_encoding_map(doc, font_row)
    try:
        encoded_old = b"".join(cmap[ch] for ch in str(text))
    except KeyError:
        return None
    resource = str(font_row[4] or "").encode("latin-1")
    candidates = []
    for stream_xref in page.get_contents():
        try:
            raw = doc.xref_stream(int(stream_xref))
        except Exception:
            continue
        fonts = list(_FONT_SELECT_RE.finditer(raw))
        for start, end, encoded in _hex_text_tokens(raw):
            if encoded != encoded_old:
                continue
            prior = [match for match in fonts if match.start() < start]
            if prior and prior[-1].group(1) == resource:
                candidates.append((int(stream_xref), raw, start, end))
    if not candidates:
        return None

    occurrence, seen, found = 0, 0, None
    target = pymupdf.Rect(rect)
    try:
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if (str(span.get("text", "")) == str(text) and
                            _normalized_font_name(span.get("font")) == wanted_font):
                        box = pymupdf.Rect(span.get("bbox"))
                        if box.intersects(target):
                            found = seen
                            break
                        seen += 1
                if found is not None:
                    break
            if found is not None:
                break
        occurrence = int(found or 0)
    except Exception:
        pass
    if occurrence >= len(candidates):
        return None
    stream_xref, source, start, end = candidates[occurrence]
    return {
        "kind": "text", "origin": "direct-text", "page": int(pno),
        "stream_xref": stream_xref, "source_stream": source,
        "token_start": int(start), "token_end": int(end),
        "source_token": source[start:end],
        "unicode_map": cmap, "font": str(span_font), "text": str(text),
    }


def replace_direct_text_object(doc, record, new_text):
    """按原字体 CMap 重写目标 Tj/TJ，完整保留其余格式操作符。"""
    if record.get("origin") != "direct-text":
        return False
    try:
        cmap = record.get("unicode_map") or {}
        encoded = b"".join(cmap[ch] for ch in str(new_text))
        source = bytes(record["source_stream"])
        start, end = int(record["token_start"]), int(record["token_end"])
        source_token = bytes(record.get("source_token") or source[start:end])
        old_chunks = list(re.finditer(rb"<([0-9A-Fa-f\s]*)>", source_token))
        old_size = sum(len(re.sub(rb"\s+", b"", match.group(1))) // 2
                       for match in old_chunks)
        if old_chunks and old_size == len(encoded):
            # 等长替换时保留原 Tj/TJ 结构以及 TJ 数组中的字距调整值；这对
            # 字体、字距、位置的视觉一致性比把数组统一改写成 Tj 更可靠。
            offset = 0

            def replace_chunk(match):
                nonlocal offset
                size = len(re.sub(rb"\s+", b"", match.group(1))) // 2
                chunk = encoded[offset:offset + size]
                offset += size
                return b"<" + chunk.hex().upper().encode("ascii") + b">"

            replacement = re.sub(rb"<([0-9A-Fa-f\s]*)>",
                                 replace_chunk, source_token)
        else:
            replacement = b"<" + encoded.hex().upper().encode("ascii") + b">Tj"
        doc.update_stream(int(record["stream_xref"]),
                          source[:start] + replacement + source[end:])
        return True
    except Exception:
        return False


def find_isolated_text_object(doc, pno, text, bbox=None):
    """查找只承载所点文字的独立内容流。

    这正是 Acrobat“编辑 PDF”使用的安全对象边界之一。返回值可直接交给
    :func:`remove_watermark`；找不到明确的独立流时返回 ``None``，让调用方
    继续使用普通正文编辑路径。
    """
    if not text or pno < 0 or pno >= len(doc):
        return None
    wanted = re.sub(r"\s+", " ", str(text)).strip()
    target = pymupdf.Rect(bbox) if bbox is not None else None
    for stream_xref in reversed(list(doc[pno].get_contents())):
        try:
            raw = doc.xref_stream(stream_xref)
            if not raw.strip():
                continue
            probe, page = _isolated_stream_page(doc, pno, stream_xref)
        except Exception:
            continue
        try:
            got = re.sub(r"\s+", " ", page.get_text("text")).strip()
            if got != wanted:
                continue
            candidate = _candidate_text(page)
            # 独立内容流并不等于水印：不少生成器会给每一行正文单独建流。
            # 只有大号旋转或大号半透明文字才启用“整对象全选”路径；普通
            # 独立正文继续使用原来的按字符点击编辑，避免误替换整行。
            if not candidate or not (
                    (candidate.get("rotated") and
                     candidate.get("fontsize", 0) >= 24) or
                    (candidate.get("opacity", 1) < 0.65 and
                     candidate.get("fontsize", 0) >= 24)):
                continue
            painted = page.get_bboxlog()
            # 流中除目标文字外还有图像/矢量绘制时，不把它当作可独立删除
            # 的文字对象，避免误删组合图形。
            if any(kind not in ("fill-text", "stroke-text", "ignore-text")
                   for kind, _rect, *rest in painted):
                continue
            rects = [pymupdf.Rect(item[1]) for item in painted
                     if item[0] in ("fill-text", "stroke-text")]
            if not rects:
                continue
            obj_rect = rects[0]
            for rect in rects[1:]:
                obj_rect |= rect
            if target is not None and not obj_rect.intersects(target):
                continue
            traces = page.get_texttrace()
            main_trace = max(traces, key=lambda item: float(item.get("size", 0)))
            chars = main_trace.get("chars") or []
            origin = list(chars[0][2]) if chars and len(chars[0]) > 2 else None
            return {
                "id": f"content:{pno}:{int(stream_xref)}",
                "kind": "text", "origin": "candidate",
                "label": wanted, "text": str(text), "page": int(pno),
                "pages": [int(pno)], "rect": list(obj_rect),
                "locations": [{"page": int(pno),
                               "stream_xref": int(stream_xref)}],
                # live 编辑从原始模板反复生成，删空后继续输入也能恢复。
                "source_stream": raw,
                "style": {
                    "font": str(main_trace.get("font") or "Helvetica"),
                    "fontsize": float(main_trace.get("size") or 12.0),
                    "color": tuple(main_trace.get("color") or (0.0, 0.0, 0.0)),
                    "opacity": float(main_trace.get("opacity", 1.0)),
                    "dir": tuple(main_trace.get("dir") or (1.0, 0.0)),
                    "origin": origin,
                },
            }
        finally:
            probe.close()
    return None


def isolated_image_objects(doc, pno):
    """列出页面中可精确定位的直接 Image XObject 绘制。

    旧实现只返回“整个内容流仅含一张图片”的对象。实际 Office、扫描和
    排版软件常把文字与多张图片写在同一内容流；现在记录具体 ``/Name
    Do`` 的序号，后续删除、移动、替换只改这一条绘制指令。
    """
    if pno < 0 or pno >= len(doc):
        return []
    page = doc[pno]
    try:
        infos = list(page.get_image_info(xrefs=True) or [])
        resources = {}
        for item in page.get_images(full=True):
            if len(item) > 7:
                resources[str(item[7])] = int(item[0])
    except Exception:
        return []
    by_xref = {}
    for info in infos:
        xref = int(info.get("xref") or 0)
        if xref:
            by_xref.setdefault(xref, []).append(info)
    used = {xref: 0 for xref in by_xref}
    result = []
    pattern = re.compile(rb"/([^\s/<>{}\[\]()]+)\s+Do\b")
    for stream_xref in list(page.get_contents()):
        try:
            raw = doc.xref_stream(stream_xref)
            if not raw.strip():
                continue
        except Exception:
            continue
        matches = list(pattern.finditer(raw))
        for invoke_index, match in enumerate(matches):
            try:
                resource_name = match.group(1).decode("latin-1")
            except Exception:
                continue
            image_xref = int(resources.get(resource_name) or 0)
            candidates = by_xref.get(image_xref) or []
            position = used.get(image_xref, 0)
            if not image_xref or position >= len(candidates):
                # Form XObject、inline image 等不能在页面流中安全定位，
                # 宁可不提供编辑，也绝不误改组合图形。
                continue
            info = candidates[position]
            used[image_xref] = position + 1
            rect = pymupdf.Rect(info.get("bbox"))
            result.append({
                "id": (f"image:{pno}:{int(stream_xref)}:"
                       f"{int(invoke_index)}"),
                "kind": "image", "origin": "page-image",
                "label": "图片", "page": int(pno), "pages": [int(pno)],
                "rect": list(rect),
                "resource_name": resource_name,
                "image_xref": image_xref,
                "invoke_index": int(invoke_index),
                "transform": [float(v) for v in info.get("transform", ())],
                "locations": [{"page": int(pno),
                               "stream_xref": int(stream_xref),
                               "invoke_index": int(invoke_index)}],
            })
    return result


_IMAGE_DO_PATTERN = re.compile(rb"/([^\s/<>{}\[\]()]+)\s+Do\b")


def _image_invocation(stream, record):
    """返回记录所指向的单次 image Do 匹配；位置不一致时安全失败。"""
    locations = record.get("locations") or []
    if len(locations) != 1:
        return None
    index = int(locations[0].get(
        "invoke_index", record.get("invoke_index", 0)))
    matches = list(_IMAGE_DO_PATTERN.finditer(stream))
    if index < 0 or index >= len(matches):
        return None
    match = matches[index]
    expected = str(record.get("resource_name") or "").encode("latin-1")
    if expected and match.group(1) != expected:
        return None
    return match


def remove_pdf_image_object(doc, record):
    """只删除目标图片的一次绘制，不影响同流文字或其他图片。"""
    locations = record.get("locations") or []
    if len(locations) != 1:
        return False
    try:
        xref = int(locations[0]["stream_xref"])
        original = doc.xref_stream(xref)
        match = _image_invocation(original, record)
        if match is None:
            return False
        # 用等长空白精确抹掉一次 /Image Do 调用。旧实现写入没有结尾
        # 换行的 ``% DOEditor removed image``；若 PDF 把整页内容压在同
        # 一行，% 会把此后的文字、矢量和图片全部注释掉，表现为整页被
        # 删除。空白既不改变相邻 token 边界，也不会影响其余操作符。
        blank = b" " * (match.end() - match.start())
        updated = original[:match.start()] + blank + original[match.end():]
        doc.update_stream(xref, updated)
        return True
    except Exception:
        return False


def pdf_image_rotation_preview(doc, record, zoom=1.0, dpr=1.0):
    """返回旋转拖动所需的无目标页面位图和目标图片 PNG。

    只在一次同步渲染期间临时把目标 ``Do`` 替换为空白，并在 ``finally``
    中恢复原始内容流。这样拖动预览既不会留下原图残影，也不会把每个
    mouse-move 写入 PDF 或撤销栈。
    """
    locations = record.get("locations") or []
    image_xref = int(record.get("image_xref") or 0)
    if len(locations) != 1 or not image_xref:
        return None
    stream_xref = int(locations[0].get("stream_xref") or 0)
    pno = int(locations[0].get("page", record.get("page", 0)))
    if not stream_xref or pno < 0 or pno >= len(doc):
        return None

    try:
        source = pymupdf.Pixmap(doc, image_xref)
        smask_xref = 0
        for info in doc[pno].get_images(full=True):
            if int(info[0]) == image_xref:
                smask_xref = int(info[1] or 0)
                break
        if smask_xref:
            try:
                source = pymupdf.Pixmap(source, pymupdf.Pixmap(doc, smask_xref))
            except Exception:
                pass
        source_png = source.tobytes("png")
    except Exception:
        try:
            source_png = doc.extract_image(image_xref).get("image")
        except Exception:
            source_png = None
    if not source_png:
        return None

    original = None
    try:
        original = doc.xref_stream(stream_xref)
        match = _image_invocation(original, record)
        if match is None:
            return None
        blank = b" " * (match.end() - match.start())
        doc.update_stream(
            stream_xref,
            original[:match.start()] + blank + original[match.end():])
        background = page_pixmap(doc, pno, float(zoom), float(dpr))
        # Pixmap 的 samples 在下一次页面更新后不能再假定有效，调用者需复制。
        background_png = background.tobytes("png")
        return background_png, source_png
    except Exception:
        return None
    finally:
        if original is not None:
            try:
                doc.update_stream(stream_xref, original)
            except Exception:
                pass


def move_pdf_image_object(doc, record, dx, dy):
    """移动目标图片绘制，dx/dy 使用 PyMuPDF 的页面坐标（右/下为正）。"""
    locations = record.get("locations") or []
    transform = list(record.get("transform") or [])
    if len(locations) != 1 or len(transform) != 6:
        return False
    a, b, c, d, _e, _f = (float(v) for v in transform)
    determinant = a * d - b * c
    if abs(determinant) < 1e-9:
        return False
    # Do 执行点的坐标系已受图片 cm 影响。PyMuPDF 返回的图片 transform
    # 已包含 PDF(y 向上) → 页面(y 向下)的翻转，因此局部平移到页面位移
    # 的线性部分是 [[a,-c],[b,-d]]，这里求其逆矩阵。该写法同时覆盖
    # 0/90/180/270 度以及任意仿射旋转图片。
    dx, dy = float(dx), float(dy)
    tx = (d * dx - c * dy) / determinant
    ty = (b * dx - a * dy) / determinant
    try:
        xref = int(locations[0]["stream_xref"])
        original = doc.xref_stream(xref)
        match = _image_invocation(original, record)
        if match is None:
            return False
        matrix = ("q 1 0 0 1 %.10g %.10g cm " % (tx, ty)).encode("ascii")
        replacement = matrix + match.group(0) + b" Q"
        updated = original[:match.start()] + replacement + original[match.end():]
        doc.update_stream(xref, updated)
        record["rect"] = [float(v) + (float(dx) if i % 2 == 0 else float(dy))
                          for i, v in enumerate(record.get("rect") or [])]
        record["transform"] = [a, b, c, d,
                               float(transform[4]) + float(dx),
                               float(transform[5]) + float(dy)]
        return True
    except Exception:
        return False


def _apply_pdf_image_page_transform(doc, record, page_change):
    """将页面坐标仿射矩阵只应用于目标图片的一次 Do 调用。"""
    locations = record.get("locations") or []
    transform = list(record.get("transform") or [])
    if len(locations) != 1 or len(transform) != 6:
        return False
    a, b, c, d, e, f = (float(v) for v in transform)
    determinant = a * d - b * c
    if abs(determinant) < 1e-12:
        return False

    def mul(left, right):
        return [[sum(left[row][k] * right[k][col] for k in range(3))
                 for col in range(3)] for row in range(3)]

    # 先在 PyMuPDF 页面坐标（y 向下）中得到目标图片变换 A*T。
    current_page = [[a, c, e], [b, d, f], [0.0, 0.0, 1.0]]
    target_page = mul(page_change, current_page)

    # PDF Image XObject 绘制还隐含一次图像纵轴翻转。将 PyMuPDF 返回的
    # 页面矩阵精确还原成 PDF y-up 的 cm 矩阵，再求 M^-1*M'，可避免
    # 旋转图片缩放时出现与宽度相关的横向漂移。
    page_height = float(doc[int(locations[0].get(
        "page", record.get("page", 0)))].rect.height)

    def to_pdf_matrix(value):
        pa, pc, pe = value[0]
        pb, pd, pf = value[1]
        return [[pa, -pc, pe + pc],
                [-pb, pd, page_height - pd - pf],
                [0.0, 0.0, 1.0]]

    current_pdf = to_pdf_matrix(current_page)
    target_pdf = to_pdf_matrix(target_page)
    ma, mc, me = current_pdf[0]
    mb, md, mf = current_pdf[1]
    pdf_det = ma * md - mb * mc
    if abs(pdf_det) < 1e-12:
        return False
    inverse_pdf = [[md / pdf_det, -mc / pdf_det,
                    (mc * mf - md * me) / pdf_det],
                   [-mb / pdf_det, ma / pdf_det,
                    (mb * me - ma * mf) / pdf_det],
                   [0.0, 0.0, 1.0]]
    local = mul(inverse_pdf, target_pdf)
    pdf_values = (local[0][0], local[1][0], local[0][1],
                  local[1][1], local[0][2], local[1][2])
    try:
        xref = int(locations[0]["stream_xref"])
        original = doc.xref_stream(xref)
        match = _image_invocation(original, record)
        if match is None:
            return False
        prefix = ("q %.12g %.12g %.12g %.12g %.12g %.12g cm " %
                  pdf_values).encode("ascii")
        replacement = prefix + match.group(0) + b" Q"
        updated = original[:match.start()] + replacement + original[match.end():]
        doc.update_stream(xref, updated)
        ta, tc, te = target_page[0]
        tb, td, tf = target_page[1]
        record["transform"] = [ta, tb, tc, td, te, tf]
        corners = [(te, tf), (ta + te, tb + tf),
                   (tc + te, td + tf),
                   (ta + tc + te, tb + td + tf)]
        xs = [point[0] for point in corners]
        ys = [point[1] for point in corners]
        record["rect"] = [min(xs), min(ys), max(xs), max(ys)]
        return True
    except Exception:
        return False


def resize_pdf_image_object(doc, record, new_rect):
    """把目标图片的一次绘制自由缩放/移动到 ``new_rect``。"""
    old_values = list(record.get("rect") or [])
    if len(old_values) != 4:
        return False
    old = pymupdf.Rect(old_values)
    new = pymupdf.Rect(new_rect)
    if (old.width <= 1e-7 or old.height <= 1e-7 or
            new.width <= 1e-7 or new.height <= 1e-7):
        return False
    sx = float(new.width / old.width)
    sy = float(new.height / old.height)
    ax = float(new.x0 - sx * old.x0)
    ay = float(new.y0 - sy * old.y0)
    return _apply_pdf_image_page_transform(
        doc, record,
        [[sx, 0.0, ax], [0.0, sy, ay], [0.0, 0.0, 1.0]])


def rotate_pdf_image_object(doc, record, degrees):
    """绕当前可见边界中心自由旋转目标图片的一次绘制。"""
    import math
    values = list(record.get("rect") or [])
    if len(values) != 4:
        return False
    rect = pymupdf.Rect(values)
    if rect.width <= 1e-7 or rect.height <= 1e-7:
        return False
    angle = math.radians(float(degrees))
    cosine, sine = math.cos(angle), math.sin(angle)
    cx, cy = (rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0
    # 页面坐标 y 向下，正角度为视觉顺时针。
    tx = cx - cosine * cx + sine * cy
    ty = cy - sine * cx - cosine * cy
    return _apply_pdf_image_page_transform(
        doc, record,
        [[cosine, -sine, tx], [sine, cosine, ty], [0.0, 0.0, 1.0]])


def replace_isolated_image_object(doc, record, image_bytes):
    """替换独立图片流引用的 Image XObject，同时保留原 cm/gs 变换。

    新图片先通过 PyMuPDF 注册为一个新资源，再只改目标内容流中的 ``Do``
    名称；原来的缩放、旋转、剪裁与透明度操作符完全不动，因此不会影响
    正文或共享的旧图片资源。
    """
    locations = record.get("locations") or []
    old_name = str(record.get("resource_name") or "")
    if len(locations) != 1 or not old_name or not image_bytes:
        return False
    pno = int(locations[0].get("page", record.get("page", -1)))
    xref = int(locations[0].get("stream_xref", 0))
    if pno < 0 or pno >= len(doc) or not xref:
        return False
    page = doc[pno]
    original_stream = doc.xref_stream(xref)
    target = _image_invocation(original_stream, record)
    if target is None:
        return False
    previous_contents = set(page.get_contents())
    try:
        # 1×1 临时绘制仅用于让 PyMuPDF 正确创建图片对象和资源字典。
        new_image_xref = int(page.insert_image(
            pymupdf.Rect(0, 0, 1, 1), stream=bytes(image_bytes), overlay=True))
        added_streams = [item for item in page.get_contents()
                         if item not in previous_contents]
        if not added_streams:
            raise RuntimeError("image resource stream was not created")
        new_name = None
        for added_xref in added_streams:
            added_raw = doc.xref_stream(added_xref)
            match = re.search(rb"/([^\s/<>{}\[\]()]+)\s+Do\b", added_raw)
            if match:
                new_name = match.group(1).decode("latin-1")
            # 临时 1×1 绘制不能留在页面上。
            doc.update_stream(int(added_xref), b"")
        if not new_name:
            raise RuntimeError("new image resource name was not found")
        updated = (original_stream[:target.start(1)] +
                   new_name.encode("latin-1") +
                   original_stream[target.end(1):])
        doc.update_stream(xref, updated)
        record["resource_name"] = new_name
        record["image_xref"] = new_image_xref
        return True
    except Exception:
        doc.update_stream(xref, original_stream)
        for added_xref in set(page.get_contents()) - previous_contents:
            try:
                doc.update_stream(int(added_xref), b"")
            except Exception:
                pass
        return False


def _decode_pdf_literal(data):
    """解码 PDF literal string 的常用转义（用于精确 Tj 替换）。"""
    out = bytearray()
    i = 0
    escapes = {ord("n"): 10, ord("r"): 13, ord("t"): 9,
               ord("b"): 8, ord("f"): 12}
    while i < len(data):
        c = data[i]
        if c != 92:
            out.append(c); i += 1; continue
        i += 1
        if i >= len(data):
            break
        c = data[i]
        if c in escapes:
            out.append(escapes[c]); i += 1
        elif 48 <= c <= 55:
            j = i
            while j < min(i + 3, len(data)) and 48 <= data[j] <= 55:
                j += 1
            out.append(int(data[i:j], 8)); i = j
        elif c in (10, 13):
            if c == 13 and i + 1 < len(data) and data[i + 1] == 10:
                i += 1
            i += 1
        else:
            out.append(c); i += 1
    return bytes(out)


def _replace_simple_tj(stream, old_text, new_text):
    """替换简单 Tj/TJ 字符串，保留原字体、矩阵、颜色与透明度。"""
    try:
        encoded_new = new_text.encode("latin-1")
    except UnicodeEncodeError:
        return None
    # PyMuPDF insert_text 常生成 ``[<HEX>]TJ``，Office 也常见此形式。
    for pattern, wrapped in (
            (rb"\[\s*<([0-9A-Fa-f\s]+)>\s*\]\s*TJ\b", True),
            (rb"<([0-9A-Fa-f\s]+)>\s*Tj\b", False)):
        for match in re.finditer(pattern, stream):
            try:
                old_bytes = bytes.fromhex(re.sub(rb"\s+", b"", match.group(1)).decode())
            except Exception:
                continue
            if old_bytes.decode("latin-1", errors="replace") != old_text:
                continue
            token = encoded_new.hex().upper().encode("ascii")
            replacement = (b"[<" + token + b">]TJ" if wrapped
                           else b"<" + token + b"> Tj")
            return stream[:match.start()] + replacement + stream[match.end():]
    i = 0
    while i < len(stream):
        if stream[i] != 40:  # (
            i += 1
            continue
        start = i
        i += 1
        depth = 1
        body_start = i
        while i < len(stream) and depth:
            if stream[i] == 92:
                i += 2
                continue
            if stream[i] == 40:
                depth += 1
            elif stream[i] == 41:
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth:
            return None
        end = i + 1
        tail = stream[end:]
        match = re.match(rb"\s*Tj\b", tail)
        if (match and _decode_pdf_literal(stream[body_start:i]).decode(
                "latin-1", errors="replace") == old_text):
            encoded = encoded_new
            encoded = (encoded.replace(b"\\", b"\\\\")
                       .replace(b"(", b"\\(").replace(b")", b"\\)"))
            return stream[:start] + b"(" + encoded + b")" + stream[end:]
        i = end
    return None


def replace_isolated_text_object(doc, record, new_text):
    """在独立文字流内原位替换文字；不做 redaction，不触碰下层正文。"""
    locations = record.get("locations") or []
    if len(locations) != 1:
        return False
    xref = int(locations[0]["stream_xref"])
    template = record.get("source_stream")
    if template is None:
        template = doc.xref_stream(xref)
    # Unicode 重建可能产生新的独立内容流；下一次键入前先清掉上一版。
    for replacement_xref in record.get("replacement_xrefs", []):
        try:
            doc.update_stream(int(replacement_xref), b"")
        except Exception:
            pass
    record["replacement_xrefs"] = []
    if new_text == "":
        doc.update_stream(xref, b"")
        return True
    updated = _replace_simple_tj(
        bytes(template), str(record.get("text") or ""), str(new_text))
    if updated is not None:
        doc.update_stream(xref, updated)
        return True

    # 原字体编码无法表达中文/特殊符号时，不退回会擦伤下层正文的
    # redaction。只清空目标流，再创建一个新的独立文字流；旋转矩阵、
    # 基线、字号、颜色和透明度均来自目标对象自身。
    style = record.get("style") or {}
    origin = style.get("origin")
    if not origin or len(origin) != 2:
        return False
    pno = int(locations[0].get("page", record.get("page", -1)))
    if pno < 0 or pno >= len(doc):
        return False
    page = doc[pno]
    previous = set(page.get_contents())
    old_target = doc.xref_stream(xref)
    try:
        doc.update_stream(xref, b"")
        point = pymupdf.Point(float(origin[0]), float(origin[1]))
        direction = style.get("dir") or (1.0, 0.0)
        a = float(direction[0])
        b = -float(direction[1])
        matrix = pymupdf.Matrix(a, b, -b, a, 0, 0)
        raw_color = style.get("color") or (0.0, 0.0, 0.0)
        if isinstance(raw_color, (int, float)):
            color = (float(raw_color),)
        else:
            color = tuple(float(x) for x in raw_color)
        fontname = ("china-s" if any(ord(ch) > 255 for ch in new_text)
                    else "helv")
        kwargs = {
            "fontname": fontname,
            "fontsize": max(1.0, float(style.get("fontsize") or 12.0)),
            "color": color,
            "fill_opacity": max(0.0, min(1.0, float(
                style.get("opacity", 1.0)))),
        }
        if abs(b) > 1e-5 or abs(a - 1.0) > 1e-5:
            kwargs["morph"] = (point, matrix)
        page.insert_text(point, str(new_text), **kwargs)
        added = [item for item in page.get_contents() if item not in previous]
        if not added:
            raise RuntimeError("no replacement content stream was created")
        record["replacement_xrefs"] = added
        return True
    except Exception:
        doc.update_stream(xref, old_target)
        for item in set(page.get_contents()) - previous:
            try:
                doc.update_stream(int(item), b"")
            except Exception:
                pass
        record["replacement_xrefs"] = []
        return False


def remove_watermark(doc, record):
    """删除/隐藏一个已枚举水印，返回实际处理的对象数量。"""
    origin = record.get("origin")
    # 兼容旧调用入口；普通 PDF 图片仍按单次 Do 指令精确删除。
    if origin == "page-image" and record.get("kind") == "image":
        return int(remove_pdf_image_object(doc, record))
    if origin == "do-editor":
        count = _blank_watermark_streams(doc, record["id"])
        ocg = int(record.get("ocg_xref") or 0)
        if ocg:
            doc.xref_set_key(ocg, "DOEditorMeta", "null")
            doc.xref_set_key(ocg, "DOEditorSource", "null")
            _set_ocg_hidden(doc, ocg)
        return count
    if origin == "acrobat-ocg":
        ocg = int(record["ocg_xref"])
        changed = _remove_ocg_page_content(doc, ocg)
        if not _set_ocg_hidden(doc, ocg):
            return changed
        doc.xref_set_key(ocg, "DOEditorRemoved", "true")
        return max(1, changed)
    if origin == "acrobat-fixed":
        page = doc[int(record["page"])]
        annot = page.load_annot(int(record["annot_xref"]))
        if annot is None:
            return 0
        page.delete_annot(annot)
        return 1
    if origin == "candidate":
        count = 0
        for loc in record.get("locations", []):
            try:
                xref = int(loc["stream_xref"])
                doc.update_stream(xref, b"")
                count += 1
            except Exception:
                pass
        return count
    return 0

def add_watermark(doc, text, fontsize=50, color=(0.5, 0.5, 0.5), opacity=0.3,
                  rotate=45, tiled=True, watermark_id=None, ocg_xref=0,
                  pages=None):
    """给所有页面添加文字水印。color 为 (r,g,b) 0-1，opacity 为 0-1。"""
    import math
    fontname = "china-s" if _has_cjk(text) else "helv"
    target_pages = (list(range(len(doc))) if pages is None else
                    sorted({int(p) for p in pages if 0 <= int(p) < len(doc)}))
    settings = {"text": text, "fontsize": float(fontsize),
                "color": list(color), "opacity": float(opacity),
                "rotate": float(rotate), "tiled": bool(tiled),
                "pages": target_pages}
    watermark_id, ocg_xref = _watermark_context(
        doc, "text", settings, watermark_id, ocg_xref)
    rad = math.radians(rotate)
    a, b = math.cos(rad), math.sin(rad)
    mat = pymupdf.Matrix(a, b, -b, a, 0, 0)
    for pno in target_pages:
        page = doc[pno]
        previous = set(page.get_contents())
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
                                     fill_opacity=opacity, morph=(fp, mat),
                                     oc=ocg_xref)
                    x += step_x
                y += step_y
        else:
            fp = pymupdf.Point(pr.width / 2, pr.height / 2)
            page.insert_text(fp, text, fontname=fontname, fontsize=fontsize,
                             color=color, fill_opacity=opacity, morph=(fp, mat),
                             oc=ocg_xref)
        _mark_new_watermark_streams(doc, page, previous, watermark_id)
    return watermark_id


def add_image_watermark(doc, image_path, opacity=0.3, rotate=0, tiled=True,
                        scale=0.5, watermark_id=None, ocg_xref=0,
                        image_bytes=None, image_name=None, pages=None):
    """给所有页面添加图片水印。

    image_path: 图片文件路径；opacity: 0-1 透明度；rotate: 旋转角度；
    tiled: True 平铺 / False 居中单张；scale: 水印图相对页面宽度的比例(0.05-1)。
    """
    from io import BytesIO
    from PIL import Image as PILImage
    try:
        if image_bytes is None:
            with open(image_path, "rb") as source:
                image_bytes = source.read()
        img = PILImage.open(BytesIO(image_bytes)).convert("RGBA")
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
    image_name = image_name or os.path.basename(image_path or "watermark.png")
    target_pages = (list(range(len(doc))) if pages is None else
                    sorted({int(p) for p in pages if 0 <= int(p) < len(doc)}))
    settings = {"image_name": image_name, "scale": float(scale),
                "opacity": float(opacity), "rotate": float(rotate),
                "tiled": bool(tiled), "pages": target_pages}
    watermark_id, ocg_xref = _watermark_context(
        doc, "image", settings, watermark_id, ocg_xref, image_bytes)
    for pno in target_pages:
        page = doc[pno]
        previous = set(page.get_contents())
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
                        pixmap=pix, overlay=True, oc=ocg_xref)
                    x += step_x
                y += step_y
        else:
            cx, cy = pr.width / 2, pr.height / 2
            page.insert_image(
                pymupdf.Rect(cx - target_w / 2, cy - target_h / 2,
                             cx + target_w / 2, cy + target_h / 2),
                pixmap=pix, overlay=True, oc=ocg_xref)
        _mark_new_watermark_streams(doc, page, previous, watermark_id)
    return watermark_id


def update_watermark(doc, record, **changes):
    """修改 DO 水印；清空旧专用流并使用同一 UUID/OCG 重建。"""
    if record.get("origin") != "do-editor":
        return False
    watermark_id = record["id"]
    ocg_xref = int(record["ocg_xref"])
    _blank_watermark_streams(doc, watermark_id)
    kind = changes.get("kind", record.get("kind"))
    if kind == "text":
        return add_watermark(
            doc, changes.get("text", record.get("text", "")),
            fontsize=changes.get("fontsize", record.get("fontsize", 50)),
            color=changes.get("color", record.get("color", (0.5, 0.5, 0.5))),
            opacity=changes.get("opacity", record.get("opacity", 0.3)),
            rotate=changes.get("rotate", record.get("rotate", 45)),
            tiled=changes.get("tiled", record.get("tiled", True)),
            pages=changes.get("pages", record.get("pages")),
            watermark_id=watermark_id, ocg_xref=ocg_xref)
    source = changes.get("image_bytes")
    image_path = changes.get("image_path")
    if source is None and not image_path:
        source = watermark_source_bytes(doc, record)
    if not source and not image_path:
        return False
    return add_image_watermark(
        doc, image_path,
        opacity=changes.get("opacity", record.get("opacity", 0.3)),
        rotate=changes.get("rotate", record.get("rotate", 0)),
        tiled=changes.get("tiled", record.get("tiled", True)),
        scale=changes.get("scale", record.get("scale", 0.5)),
        pages=changes.get("pages", record.get("pages")),
        watermark_id=watermark_id, ocg_xref=ocg_xref,
        image_bytes=source,
        image_name=changes.get("image_name", record.get("image_name")))


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
                              x_start=None, y_baseline=None):
    """CJK + italic 合成斜体直接绘制(支持从任意 x 起点并返回占用宽度)。

    segments: [(seg_text, is_cjk), ...] — 由 _partition_italic 生成。
    单一基线单行(无 wrap): text 过长超出 rect 时仍按左对齐绘制, 右侧
    可能溢出, 与原始 htmlbox 行为一致(短文本场景)。
    y_baseline: 可选外部传入的共享基线 y(多 run 混排时用), 缺省按 rect 算。
    """
    import pymupdf as _pym
    tan_a = 0.2493    # tan(14°), 合成右倾 italic(主流 PDF 阅读器方向; PyMuPDF
                 # 自家 get_pixmap 渲染下方向会反转, 故此处不用负号)
    skew_matrix = _pym.Matrix(1, 0, tan_a, 1, 0, 0)
    if y_baseline is None:
        y_baseline = rect.y0 + fontsize * 0.8
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
    # 多 run 走直接绘制还需共享基线: htmlbox 路径会把行框外的大字号 run
    # 折到下一行(用户反馈"同行文字拆分成两行"——根因)。只要 run 字号不一
    # 致, 统一改走直接绘制, 共享基线按最大字号算出, 视觉底部对齐。
    # 其它情形(同字号多 run / 单一 run)仍走 htmlbox, 渲染与旧版一致。
    any_cjk_italic = any(
        r.get("italic") and any(_is_cjk_char(c) for c in (r.get("text") or ""))
        for r in runs or [])
    size_vary = len({float(r.get("size") or 12.0) for r in runs or []}) > 1
    if any_cjk_italic or size_vary:
        # 共用基线 = 行底 + max_size * 0.8 (PyMuPDF insert_text 接受 y=基线)
        sizes = [max(1.0, float(r.get("size") or 12.0)) for r in runs or []]
        y_shared = rect.y0 + (max(sizes) if sizes else 12.0) * 0.8
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
            if italic and has_cjk:
                w = _draw_italic_cjk_segments(
                    page, rect, _partition_italic(text), size, color,
                    bold=bold, x_start=x_cursor,
                    y_baseline=y_shared)
                x_cursor += w
            elif has_cjk:
                page.insert_text((x_cursor, y_shared), text,
                                 fontname="china-s", fontsize=size,
                                 color=color_f)
                x_cursor += _pym.Font("china-s").text_length(text, size)
            else:
                fontname = (
                    "hebi" if (italic and bold) else
                    "heit" if italic else
                    "hebo" if bold else "helv")
                page.insert_text((x_cursor, y_shared), text,
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


def _erase_text_in(page, rect):
    """移除矩形内文字内容，但保留图片/矢量背景（透出页面底色）。

    MuPDF Page.apply_redactions 默认 images=PDF_REDACT_IMAGE_PIXELS——
    会把与擦除矩形相交的图片按矩形挖洞并填白，因此非纯白背景的 PDF
    （底色矩形、扫描图、水印图等）在修改/删除文字后，改动区域会出现
    一块白底，破坏原背景。显式指定 images=NONE、graphics=NONE 后只删
    除文本层：图片、矢量底色、表格线等一律保留，底色自然透出；纯白
    文档视觉与原先完全一致。
    """
    import pymupdf as _pym
    page.add_redact_annot(rect)
    page.apply_redactions(
        images=_pym.PDF_REDACT_IMAGE_NONE,
        graphics=_pym.PDF_REDACT_LINE_ART_NONE,
        text=_pym.PDF_REDACT_TEXT_REMOVE)


def redact_rect(page, rect):
    """删除指定矩形区域内的原有内容（用于修改文字前清除原文）。"""
    _erase_text_in(page, rect)


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
    page.apply_redactions(
        images=_pym.PDF_REDACT_IMAGE_NONE,
        graphics=_pym.PDF_REDACT_LINE_ART_NONE,
        text=_pym.PDF_REDACT_TEXT_REMOVE)


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
