# -*- coding: utf-8 -*-
"""就地富文本编辑控件与文字段(runs)工具。

文字段(runs)模型：一段文字的内容由若干连续样式段组成
    {"text": str, "family": str, "size": float(pt), "color": QColor,
     "bold": bool, "italic": bool}
同一段内样式一致；相邻同格式段在落库前合并，保证 runs 最少化。

RichEditBox：仿 QLineEdit 的单行就地编辑控件，内容却是富文本：
- 可以用鼠标拖动选中部分字符（局部高亮）；
- 右键菜单保持干净（系统标准项 + 顶部一个「格式编辑…」入口），点入口
  才弹出独立的格式编辑模块（字体/粗细/斜体/字号/颜色 五项），结果只
  作用于右键时选中的字符（无选中则作用于光标处的后续输入），实现字符级混排；
- 回车 = 提交（submitRequested）、Esc = 取消（cancelRequested）；
- 粘贴自动过滤换行，控件始终保持单行。
"""

import os

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QTimer
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QPalette,
                           QTextBlockFormat, QTextCharFormat, QTextCursor,
                           QTextFormat, QPainter, QPen, QPolygonF)
from PySide6.QtWidgets import (QColorDialog, QDialog, QDoubleSpinBox,
                               QFontComboBox, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QTextEdit, QVBoxLayout)

# Qt 中 1pt 按逻辑 DPI(96) 渲染为 4/3 逻辑像素。编辑器以「pt*scale
# 逻辑像素」精确显示（与页面位图文字等大），故写入字符格式的点阵值 =
# 目标像素 / (96/72)；读回时再乘回。scale 由 set_scale 传入（=页面 zoom
# 或带 1.08 输入放大系数）。
_PX_PER_PT = 96.0 / 72.0

# 字体族名的自定义属性键：写 _char_format 时随字符格式一并保存；读回时
# 只做 QVariant 属性读取，绝不触发 Qt 的 QFont 字族解析——Qt 在部分字符
# 格式（空字族、文档默认格式等）上 fontFamily()/fontFamilies() 会触发
# 不可被 try/except 捕获的原生访问违例（access violation）。
_FAM_PROP = int(QTextFormat.Property.UserProperty) + 101
_SIZE_PROP = int(QTextFormat.Property.UserProperty) + 102


# PDF 子集字体里看到的家族名（如 "Arial Regular"/"Calibri Regular"/
# "Nimbus Sans Regular"/"Droid Sans Fallback" 等）只是排版惯例字符串，
# Windows 真实安装的字体族名往往不同。直接拿这些字符串交给 QFont/QPainter
# 在 Widget 上画，会得到「空字族 → 全方块」豆腐视图。这里把常见字符串
# 规范成系统已装族名（且已知含全量 CJK），最后再用 QFontDatabase 校验一次。
_WIN_FAMILY_REMAP = {
    "arial regular": "Arial",
    "arial bold": "Arial",
    "arial italic": "Arial",
    "arial bolditalic": "Arial",
    "calibri regular": "Calibri",
    "calibri bold": "Calibri",
    "calibri italic": "Calibri",
    "calibri bolditalic": "Calibri",
    "times new roman regular": "Times New Roman",
    "times new roman bold": "Times New Roman",
    "times": "Times New Roman",
    "times-regular": "Times New Roman",
    "times bold": "Times New Roman",
    "nimbus sans regular": "Arial",
    "nimbus sans italic": "Arial",
    "nimbus sans bold": "Arial",
    "nimbus mono": "Courier New",
    "droid sans fallback regular": "Microsoft YaHei",
    "droid sans fallback bold": "Microsoft YaHei",
    "noto sans regular": "Microsoft YaHei",
    "noto sans cjk": "Microsoft YaHei",
    "noto sans cjk sc regular": "Microsoft YaHei",
    "fangsong": "FangSong",
    "kaiti": "KaiTi",
    "simsun": "SimSun",
    "simhei": "SimHei",
    "dengxian": "DengXian",
    "dengxian light": "DengXian",
    "microsoft yahei": "Microsoft YaHei",
    "microsoft yahei ui": "Microsoft YaHei",
    "microsoft yahei bold": "Microsoft YaHei",
    "microsoft yahui": "Microsoft YaHei",
    "msyh": "Microsoft YaHei",
    "pingfangsc": "Microsoft YaHei",
    "苹方": "Microsoft YaHei",
    "微软雅黑": "Microsoft YaHei",
    "等线": "DengXian",
    "黑体": "SimHei",
    "宋体": "SimSun",
    "楷体": "KaiTi",
    "仿宋": "FangSong",
}

_CJK_FONT_FALLBACK = "Microsoft YaHei UI"  # Qt 在 Windows 上 DirectWrite 真实可解析的族名


def _qt_safe_family(family):
    """把任意 PDF 字体族名规范为当前系统已装的 QFont 字体族名。

    不可用时按 `黑体/宋体/楷体/仿宋 → CJK → 西文` 优先级回退，
    始终返回一个能让 QTextEdit/QPainter 画出来且覆盖中日韩文+常用符号的族。
    """
    raw = (family or "").strip()
    if not raw:
        return _CJK_FONT_FALLBACK
    key = raw.lower()
    remap = _WIN_FAMILY_REMAP.get(key)
    if remap:
        raw = remap
    try:
        installed = set(QFontDatabase.families())
    except Exception:
        installed = set()
    if raw in installed:
        return raw
    if remap and remap in installed:
        return remap
    strip = raw.rstrip()
    for suffix in (" Regular", " Reg", " Bold", " Italic", " BoldItalic",
                   " Black", " Medium", " Light", " Thin"):
        if strip.endswith(suffix):
            stripped = strip[: -len(suffix)].rstrip()
            if stripped in installed:
                return stripped
    # Windows DirectWrite 真实可用的优先级：UI 版本在 DirectWrite 下最稳定
    for cand in ("Microsoft YaHei UI", "Microsoft YaHei",
                 "SimHei", "SimSun", "DengXian",
                 "Arial", "Segoe UI", "Calibri"):
        if cand in installed:
            return cand
    return _CJK_FONT_FALLBACK


# ---------------------------------------------------------------------------
# 启动期"真实试字体"：把 Windows 上的字体文件显式注入 DirectWrite，确保
# PyInstaller / 容器化环境下的 QFontDatabase 能拿到字形。
# ---------------------------------------------------------------------------
_FONTS_INJECTED = False


def _inject_windows_fonts_once():
    """在 PyInstaller / 容器环境启动后，把 Windows 字体文件显式注入 Qt，
    让 QFontDatabase 在 DirectWrite 下能拿到完整字形数据。
    只执行一次。"""
    global _FONTS_INJECTED
    if _FONTS_INJECTED:
        return
    _FONTS_INJECTED = True
    win_fonts = os.environ.get("WINDIR", r"C:\Windows") + r"\Fonts"
    candidates = [
        ("msyh.ttc", "Microsoft YaHei"),
        ("msyh.ttc", "Microsoft YaHei UI"),
        ("simhei.ttf", "SimHei"),
        ("simsun.ttc", "SimSun"),
        ("arial.ttf", "Arial"),
        ("seguiemj.ttf", "Segoe UI Emoji"),
    ]
    installed = set(QFontDatabase.families())
    loaded_files = set()
    for fname, fam in candidates:
        # 已安装的系统字体由 DirectWrite 原生解析，避免重复注册 TTC
        # 覆盖系统字族、改变界面小字号的栅格化结果。
        if fam in installed or fname in loaded_files:
            continue
        fpath = os.path.join(win_fonts, fname)
        if os.path.exists(fpath):
            try:
                QFontDatabase.addApplicationFont(fpath)
                loaded_files.add(fname)
                installed.update(QFontDatabase.families())
            except Exception:
                pass




# --------------------------------------------------------------------------
# runs 工具
# --------------------------------------------------------------------------

def _style_key(run):
    """一段的样式指纹（不含文本），用于判断相邻段是否同格式。"""
    c = run.get("color")
    if isinstance(c, QColor):
        cr, cg, cb = c.red(), c.green(), c.blue()
    else:
        try:
            cr, cg, cb = int(c.redF() * 255), int(c.greenF() * 255), int(c.blueF() * 255)
        except Exception:
            cr, cg, cb = 0, 0, 0
    return ((run.get("family") or "").lower(),
            round(float(run.get("size") or 12.0), 2),
            cr, cg, cb,
            bool(run.get("bold")), bool(run.get("italic")))


def merge_runs(runs):
    """合并相邻同格式段，丢弃空文本段；返回新列表（不修改入参）。"""
    out = []
    for r in runs or []:
        text = (r.get("text") or "")
        if not text:
            continue
        if out and _style_key(out[-1]) == _style_key(r):
            out[-1]["text"] += text
            continue
        color = r.get("color")
        if not isinstance(color, QColor):
            color = QColor(0, 0, 0)
        out.append({
            "text": text,
            "family": (r.get("family") or ""),
            "size": round(float(r.get("size") or 12.0), 2),
            "color": QColor(color),
            "bold": bool(r.get("bold")),
            "italic": bool(r.get("italic")),
        })
    return out


def runs_text(runs):
    return "".join((r.get("text") or "") for r in (runs or []))


def single_run(text, family="", size=12.0, color=None, bold=False, italic=False):
    """普通文本 → 单段 runs。"""
    if color is None or not isinstance(color, QColor):
        color = QColor(0, 0, 0)
    return [{"text": text, "family": family or "", "size": float(size),
             "color": QColor(color), "bold": bool(bold), "italic": bool(italic)}]


def runs_all_same_style(runs):
    """runs 是否只有一种样式（含空/单段），供上层决定能否走单样式写回。"""
    runs = merge_runs(runs)
    if len(runs) <= 1:
        return True
    k = _style_key(runs[0])
    return all(_style_key(r) == k for r in runs[1:])


# --------------------------------------------------------------------------
# 富文本就地编辑控件
# --------------------------------------------------------------------------

class RichEditBox(QTextEdit):
    """单行富文本就地编辑框，支持局部字符格式与右键格式设置。"""

    submitRequested = Signal()
    cancelRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scale = 1.0              # 屏幕像素 = pt * scale
        self._suppress_focusout = 0
        self._text_visible = True      # set_text_visible 状态，paintEvent 用
        # 仅记录用户通过格式工具发起的变更。QTextDocument 的
        # contentsChanged 无法区分“改文字”和“只改格式”，文档层需要这个
        # 标记决定是否还能走只替换 Tj/TJ 字形编码的原格式保真路径。
        self._format_revision = 0
        # 基准格式：setText/程序化整文替换时沿用（空文档光标 charFormat
        # 读取在某些平台/空文档上会触发原生崩溃，故自行记录）
        self._base_fmt = {
            "family": "", "size": 12.0,
            "color": QColor(0, 0, 0), "bold": False, "italic": False,
        }
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAcceptRichText(False)   # 粘贴一律转纯文本
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.setTabChangesFocus(True)
        self.document().setDocumentMargin(1)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

    # -- 公共 API ----------------------------------------------------------

    def set_scale(self, scale):
        """像素字号换算系数（通常为页面缩放 zoom）。"""
        self._scale = max(0.05, float(scale))

    def set_runs(self, runs):
        """载入多段富文本（保留各段样式）。"""
        runs = merge_runs(runs)
        if runs:
            r0 = runs[0]
            self._base_fmt = {
                "family": r0.get("family") or self._base_fmt["family"],
                "size": float(r0.get("size") or self._base_fmt["size"]),
                "color": r0.get("color")
                if isinstance(r0.get("color"), QColor)
                else self._base_fmt["color"],
                "bold": bool(r0.get("bold")),
                "italic": bool(r0.get("italic")),
            }
        cur = self.textCursor()
        cur.select(QTextCursor.SelectionType.Document)
        cur.removeSelectedText()
        if runs:
            cur.movePosition(QTextCursor.MoveOperation.Start)
            for r in runs:
                cur.insertText(r["text"], self._char_format(r))
        self.setTextCursor(cur)
        # 锁死行高：贴齐字形本体像素 + 2，避免 Qt 默认用 widget 字体的
        # lineSpacing（约 1.35×）撑高行框，让就地编辑框看起来比页面同
        # 行字"放大"了。
        base_px = max(1.0, float(self._base_fmt["size"]) * self._scale)
        line_px = max(1, int(round(base_px)) + 2)
        doc = self.document()
        bc = QTextCursor(doc)
        bc.select(QTextCursor.SelectionType.Document)
        bfmt = bc.blockFormat()
        bfmt.setLineHeight(line_px,
                           QTextBlockFormat.LineHeightTypes.FixedHeight.value)
        bc.setBlockFormat(bfmt)
        self.document().clearUndoRedoStacks()

    def text(self):
        """与 QLineEdit 语义兼容：返回纯文本。"""
        return self.toPlainText()


    def selectedText(self):
        """与 QLineEdit 语义兼容：返回选中文字。"""
        return self.textCursor().selectedText()


    def setText(self, text):
        """与 QLineEdit 语义兼容：整文替换。

        等价于「全选后输入」——新文本继承当前基准字符格式（set_runs /
        set_default_format 记录的首段样式），不会因程序化 setText 丢掉
        原有样式（就地编辑链依赖该行为）。
        """
        text = text or ""
        base = dict(self._base_fmt)
        if not (text or ""):
            self.set_runs([])
            return
        self.set_runs([{
            "text": text,
            "family": base["family"],
            "size": base["size"],
            "color": base["color"],
            "bold": base["bold"],
            "italic": base["italic"],
        }])

    def set_text_visible(self, visible):
        """按需显示/隐藏框内全部文字（只切 alpha，保留各 run 原 RGB 色）。

        Acrobat「点击不动原字」的实现关键：进入编辑瞬间框内文字透明
        隐藏（页面画布仍显示 PDF 位图原字形，视觉零变化、只有光标），
        用户真正输入/删除的那一刹那才调 visible=True 把 Qt 文字显出来
        （同时画布填纸色盖掉原字形）。隐藏/恢复都只改 foreground 的
        alpha（255/0），RGB 通道原样不动，故恢复无需记忆原色。
        """
        alpha = 255 if visible else 0
        self._text_visible = bool(visible)
        doc = self.document()
        # 第一遍：只读收集每段 range 及其 charFormat（改副本 alpha），
        # 绝不在遍历 fragment 时写文档（会合并/拆分 fragment 使迭代器失效）。
        items = []
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid():
                    cf = frag.charFormat()
                    col = cf.foreground().color()
                    col.setAlpha(alpha)
                    cf.setForeground(QBrush(col))
                    items.append((frag.position(), frag.length(), cf))
                it += 1
            block = block.next()
        # 第二遍：逐 range 用独立 QTextCursor 应用新格式（只改格式不改文本，
        # 字符位置全程稳定）。
        for pos, length, cf in items:
            if length <= 0:
                continue
            c = QTextCursor(doc)
            c.setPosition(pos)
            c.setPosition(pos + length, QTextCursor.MoveMode.KeepAnchor)
            c.setCharFormat(cf)

    def paintEvent(self, event):
        """字形层硬保障：文字被隐藏（_text_visible=False，Acrobat 就地
        编辑）时，Qt 画选区/光标只准画高亮底、绝不画字形——否则会与下方
        MuPDF 单引擎字形叠成"变大/变形/方块"。绘制前把会重画选中字形的
        palette 角色压成透明（HighlightedText/Text）；选区底由样式表负责。
        """
        if not self._text_visible:
            pal = self.palette()
            z = QColor(0, 0, 0, 0)
            if (pal.highlightedText().color() != z
                    or pal.text().color() != z):
                pal.setColor(QPalette.ColorRole.HighlightedText, z)
                pal.setColor(QPalette.ColorRole.Text, z)
                self.setPalette(pal)
        super().paintEvent(event)

    def sync_typing_format_from_cursor(self):
        """把光标处字符格式同步为后续输入格式。

        继承顺序固定为光标/选区前一字符；前方无字符时取当前位置（通常
        是首字符）。这避免混排 span 边界和整段替换时 Qt 自行取到右侧
        或控件默认字体。空文档沿用 set_default_format 的基准格式。
        """
        if not self.toPlainText():
            self.set_default_format(self._base_fmt)
            return
        cur = self.textCursor()
        pos = cur.selectionStart() if cur.hasSelection() else cur.position()
        char_pos = pos - 1 if pos > 0 else 0
        cf = self._char_format_at(char_pos)
        if not self._fmt_family(cf):
            cf = self._char_format(self._base_fmt)
        self.setCurrentCharFormat(cf)

    def insertPlainText(self, text):
        """替换选区时显式继承选区前方（首位则首字符）的原格式。"""
        if self.textCursor().hasSelection():
            self.sync_typing_format_from_cursor()
        super().insertPlainText(text)

    def set_default_format(self, fmt):
        """设置空文档/后续输入的默认字符格式（不改变已有内容）。

        fmt 形如 {family, size, color, bold, italic}。用户随即输入的字符
        将以该样式呈现；若框内已选中文本则不覆盖选区。
        """
        fmt = fmt or {}
        color = fmt.get("color")
        if not isinstance(color, QColor):
            color = QColor(0, 0, 0)
        self._base_fmt = {
            "family": fmt.get("family") or self._base_fmt["family"],
            "size": float(fmt.get("size") or self._base_fmt["size"]),
            "color": QColor(color),
            "bold": bool(fmt.get("bold", self._base_fmt["bold"])),
            "italic": bool(fmt.get("italic", self._base_fmt["italic"])),
        }
        cf = self._char_format({
            "text": "",
            "family": self._base_fmt["family"],
            "size": self._base_fmt["size"],
            "color": self._base_fmt["color"],
            "bold": self._base_fmt["bold"],
            "italic": self._base_fmt["italic"],
        })
        self.setCurrentCharFormat(cf)

    def to_runs(self):
        """把当前文档序列化为合并后的 runs（pt 字号，屏幕坐标换算回 PDF pt）。"""
        runs = []
        doc = self.document()
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid() and frag.text():
                    cf = frag.charFormat()
                    runs.append({
                        "text": frag.text(),
                        "family": self._fmt_family(cf),
                        "size": self._fmt_size_pt(cf),
                        "color": QColor(cf.foreground().color()),
                        "bold": self._fmt_bold(cf),
                        "italic": cf.fontItalic(),
                    })
                it += 1
            block = block.next()
        return merge_runs(runs)

    # -- 格式工具 ----------------------------------------------------------

    def _fmt_family(self, cf):
        """安全读取字符格式的字体族。

        族名在 _char_format 写入时随字符格式保存为自定义属性 _FAM_PROP，
        这里只做纯 QVariant 属性读取——绝不调用 fontFamily()/fontFamilies()。
        Qt 对「空字族 / 文档默认格式」等字符格式执行字族解析会触发不可被
        try/except 捕获的原生访问违例（实测 access violation），属性读取
        与之完全隔离。属性缺失（非本控件创建的格式）返回空串，由调用方
        兜底为基准字族。
        """
        try:
            v = cf.property(_FAM_PROP)
            if isinstance(v, str) and v:
                return v
        except Exception:
            pass
        return ""

    def _fmt_size_pt(self, cf):
        """字符格式中存储的点数 → PDF pt（去除 scale 与 Qt 96dpi 换算）。"""
        size = cf.property(_SIZE_PROP)
        if isinstance(size, (int, float)) and size > 0:
            return float(size)
        ps = cf.fontPointSize()
        if ps > 0 and self._scale > 0:
            return round(ps * _PX_PER_PT / self._scale, 2)
        return float(self._base_fmt.get("size") or 12.0)

    def _fmt_bold(self, cf):
        return cf.fontWeight() >= QFont.Weight.Bold

    def _char_format(self, run):
        cf = QTextCharFormat()
        # 空字族会生成「无字体」fragment，后续 fontFamily()/fontFamilies()
        # 读取在本机 PySide/Qt 上触发原生访问违例（不可被 try 捕获），
        # 故一律兜底为非空字族。同时把 PDF 子集里来的家族名（"Nimbus Sans
        # Regular"/"Calibri Regular"/"Droid Sans Fallback" 等）规范成
        # 本机 QFontDatabase 里真实存在的族名，否则 QTextEdit 渲染出全豆腐。
        family = _qt_safe_family(run.get("family")
                                 or self._base_fmt.get("family"))
        cf.setFontFamilies([family])
        # 同时存为自定义属性：读回族名走 _fmt_family 属性读取，
        # 避免 Qt 字族解析在特定字符格式上的原生访问违例。
        cf.setProperty(_FAM_PROP, run.get("family")
                       or self._base_fmt.get("family") or family)
        # 存点阵值 = 目标像素 / (96/72)，使 Qt 渲染像素 ≈ pt*scale
        size = float(run.get("size") or 12.0)
        cf.setProperty(_SIZE_PROP, size)
        pt = max(1.0, size * self._scale / _PX_PER_PT)
        cf.setFontPointSize(round(pt, 2))
        cf.setFontWeight(QFont.Weight.Bold
                         if run.get("bold") else QFont.Weight.Normal)
        cf.setFontItalic(bool(run.get("italic")))
        color = run.get("color")
        if not isinstance(color, QColor):
            color = QColor(0, 0, 0)
        cf.setForeground(QBrush(QColor(color)))
        return cf


    def _apply_char(self, bold=None, italic=None, family=None, size_pt=None,
                    color=None):
        """把指定样式并入当前选区（无选区则并入光标处后续输入格式）。"""
        cf = QTextCharFormat()
        if bold is not None:
            cf.setFontWeight(QFont.Weight.Bold
                             if bold else QFont.Weight.Normal)
        if italic is not None:
            cf.setFontItalic(italic)
        if family:
            cf.setFontFamilies([family])
            cf.setProperty(_FAM_PROP, family)
        if size_pt is not None:
            cf.setProperty(_SIZE_PROP, float(size_pt))
            cf.setFontPointSize(max(
                1.0, float(size_pt) * self._scale / _PX_PER_PT))
        if color is not None:
            cf.setForeground(QBrush(QColor(color)))
        # 必须在 merge 之前递增：Qt 会在 mergeCurrentCharFormat 内同步发出
        # contentsChanged，文档层的槽函数需在那一刻就知道这是格式修改。
        self._format_revision += 1
        # mergeCurrentCharFormat：有选区时并入选中字符，
        # 无选区时并入当前字符格式——均同步为后续输入样式，不会整体替换
        self.mergeCurrentCharFormat(cf)

    # -- 右键「格式编辑…」独立模块 --------------------------------------

    def _char_format_at(self, pos):
        """按 QTextFragment 定位 pos 处**字符**的格式。

        QTextCursor.setPosition(pos).charFormat() 在 pos 恰为 fragment
        边界（选区起点=新样式片段第一个字符）时会退化返回上一段样式，
        导致选中加粗/斜体/彩色字符时对话框状态读不到真实样式。
        这里遍历所在 block 的 fragment，取「包含 pos 的片段」——
        fragment.position() <= pos < position()+len 保证 pos 落在该片段
        的字符上，边界处取右侧片段，符合「读取该处字符样式」语义。
        """
        doc = self.document()
        pos = int(pos)
        if pos < 0:
            return QTextCharFormat()
        block = doc.findBlock(min(pos, max(0, doc.characterCount() - 1)))
        it = block.begin()
        while not it.atEnd():
            f = it.fragment()
            if (f.isValid() and f.text()
                    and f.position() <= pos < f.position() + len(f.text())):
                return f.charFormat()
            it += 1
        return QTextCharFormat()

    def _snapshot_from_cf(self, cf):
        return {
            "family": self._fmt_family(cf),
            "size": self._fmt_size_pt(cf),
            "color": QColor(cf.foreground().color()),
            "bold": self._fmt_bold(cf),
            "italic": bool(cf.fontItalic()),
        }

    def _format_selection_snapshot(self, anchor, end, had_selection):
        """打开对话框前的样式快照。

        有选区 → 读「选区首字符」所在片段的样式（fragment 定位，避免
        起点恰在新样式片段边界时读成上一段）；无选区 → 读光标处字符
        样式（=后续输入将采用的格式）。
        """
        if had_selection and end > anchor:
            cf = self._char_format_at(anchor)
            return self._snapshot_from_cf(cf)
        return self._format_at_position(anchor)

    def _format_at_position(self, pos):
        """取文档 pos 处字符格式为 {family,size,color,bold,italic}。"""
        doc = self.document()
        last = max(0, doc.characterCount() - 1)
        tc = QTextCursor(doc)
        tc.setPosition(min(max(0, int(pos)), last))
        cf = tc.charFormat()
        return self._snapshot_from_cf(cf)

    def _open_format_editor(self, anchor, end, had_selection):
        """弹出独立「格式编辑」模块；确认后应用到右键时的选区/光标。

        anchor/end/had_selection 在弹出右键菜单时捕获。菜单与对话框
        exec 期间编辑框会失焦，调用方须保证 _suppress_focusout 生效，
        避免上层把编辑提交关掉导致改动无处可落。
        """
        snap = self._format_selection_snapshot(anchor, end, had_selection)
        dlg = FormatDialog(snap, self.window())
        self._suppress_focusout += 1
        try:
            ok = dlg.exec() == QDialog.DialogCode.Accepted
        finally:
            self._suppress_focusout -= 1
        if not ok:
            return
        fmt = dlg.result_format()
        # 对话框可能改变了光标/选区，重新按右键时的范围恢复，确保只
        # 作用在那段字符上（字符级混排的关键）。
        doc = self.document()
        last = max(0, doc.characterCount() - 1)
        a = min(max(0, int(anchor)), last)
        b = min(max(0, int(end)), last)
        tc = QTextCursor(doc)
        if had_selection and b > a:
            tc.setPosition(a)
            tc.setPosition(b, QTextCursor.MoveMode.KeepAnchor)
        else:
            tc.setPosition(a)
        self.setTextCursor(tc)
        self._apply_char(bold=fmt["bold"], italic=fmt["italic"],
                         family=fmt["family"] or None,
                         size_pt=fmt["size"], color=fmt["color"])
        self.setFocus()

    def contextMenuEvent(self, event):
        # 记录右键时选区，供「格式编辑…」确认后精确恢复。
        cur = self.textCursor()
        had_sel = bool(cur.hasSelection() and cur.selectedText())
        anchor = cur.selectionStart() if had_sel else cur.position()
        end = cur.selectionEnd() if had_sel else cur.position()

        menu = self.createStandardContextMenu()
        act_edit = menu.addAction("格式编辑…")
        act_edit.setToolTip("打开独立的格式编辑模块（字体/粗细/斜体/字号/颜色）")
        first = menu.actions()
        if first and first[0] is not act_edit:
            menu.insertAction(first[0], act_edit)
            menu.insertSeparator(first[0])
        act_edit.triggered.connect(
            lambda _c=False: self._on_format_edit_action(menu, anchor,
                                                         end, had_sel))
        # 关键：菜单 exec 全程保持失焦抑制（旧实现提前释放，菜单弹出时
        # 编辑框 FocusOut 会把本次编辑提交关掉，导致后续格式应用落空）。
        self._suppress_focusout += 1
        try:
            menu.exec(event.globalPos())
        finally:
            self._suppress_focusout -= 1
        menu.deleteLater()

    def _on_format_edit_action(self, menu, anchor, end, had_sel):
        """点「格式编辑…」：先收起菜单，再打开独立编辑模块。"""
        menu.close()
        self._open_format_editor(anchor, end, had_sel)

    # -- 鼠标 / 键盘 --------------------------------------------------------

    def mousePressEvent(self, event):
        # 右键点在当前选区之外时，取消选择并把光标移到该处，
        # 保证「格式设置」始终作用于用户右键的那段字符。
        # PySide6 6.x 的 cursorForPosition 仅接受 QPoint(QPointF 会抛
        # TypeError 让编辑框"碰一下就死"), 用 toPoint() 转一下。
        if event.button() == Qt.MouseButton.RightButton:
            click_cur = self.cursorForPosition(event.position().toPoint())
            cur = self.textCursor()
            inside = (cur.hasSelection() and
                      cur.selectionStart() <= click_cur.position() <=
                      cur.selectionEnd())
            if not inside:
                click_cur.clearSelection()
                self.setTextCursor(click_cur)
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.sync_typing_format_from_cursor()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.submitRequested.emit()
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self.cancelRequested.emit()
            event.accept()
            return
        if event.text() and self.textCursor().hasSelection():
            self.sync_typing_format_from_cursor()
        super().keyPressEvent(event)

    def insertFromMimeData(self, source):
        # 单行约束：粘贴内容丢弃换行与富文本样式
        if source.hasText():
            txt = source.text().replace("\r\n", " ").replace("\n", " ") \
                                .replace("\r", " ")
            self.insertPlainText(txt)
        else:
            super().insertFromMimeData(source)


class PdfRowEditBox(RichEditBox):
    """PDF 行的输入层：光标、选区与鼠标命中共用 PDF 字符坐标。

    QTextDocument 只负责文本、格式和输入法，不用其替代字体的排版结果
    定位。位置表以 Unicode 字符为单位，交给 QTextCursor 前转换为 UTF-16。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pdf_ranges = []
        self._pdf_positions = [0]
        self._pdf_top = 0.0
        self._pdf_bottom = 12.0
        self._pdf_empty_x = 0.0
        self._pdf_dragging = False
        self._caret_on = True
        self._preedit = ""
        self._caret_timer = QTimer(self)
        self._caret_timer.setInterval(500)
        self._caret_timer.timeout.connect(self._blink_caret)
        self._caret_timer.start()
        self.cursorPositionChanged.connect(self._cursor_updated)
        self.selectionChanged.connect(self._cursor_updated)

    def set_pdf_layout(self, text, ranges, top, bottom, empty_x=0.0):
        self._pdf_ranges = list(ranges)
        self._pdf_positions = [0]
        for ch in text:
            self._pdf_positions.append(self._pdf_positions[-1] +
                                       (2 if ord(ch) > 0xFFFF else 1))
        self._pdf_top, self._pdf_bottom = top, bottom
        self._pdf_empty_x = empty_x
        self._cursor_updated()

    def _cursor_updated(self):
        self._caret_on = True
        self.viewport().update()

    def _blink_caret(self):
        self._caret_on = not self._caret_on
        self.viewport().update()

    def cursorForPosition(self, pos):
        cur = QTextCursor(self.document())
        boundaries = [r[0] for r in self._pdf_ranges]
        if self._pdf_ranges:
            boundaries.append(self._pdf_ranges[-1][1])
        else:
            boundaries = [self._pdf_empty_x]
        index = min(range(len(boundaries)), key=lambda i: abs(boundaries[i] - pos.x()))
        index = min(index, len(self._pdf_positions) - 1)
        cur.setPosition(min(self._pdf_positions[index], self.document().characterCount() - 1))
        return cur

    def cursorRect(self, cursor=None):
        cur = self.textCursor() if cursor is None else cursor
        index = max(0, sum(p <= cur.position() for p in self._pdf_positions) - 1)
        if index < len(self._pdf_ranges):
            x = self._pdf_ranges[index][0]
        elif self._pdf_ranges:
            x = self._pdf_ranges[-1][1]
        else:
            x = self._pdf_empty_x
        return QRectF(x, self._pdf_top, 1.0,
                      max(1.0, self._pdf_bottom - self._pdf_top)).toAlignedRect()

    def inputMethodQuery(self, query):
        if query == Qt.InputMethodQuery.ImCursorRectangle:
            return self.cursorRect()
        return super().inputMethodQuery(query)

    def inputMethodEvent(self, event):
        self._preedit = event.preeditString()
        super().inputMethodEvent(event)
        self.viewport().update()

    def paintEvent(self, event):
        # 不调用 QTextEdit.paintEvent：它会按 Qt 字宽画出另一套光标/选区。
        painter = QPainter(self.viewport())
        cur = self.textCursor()
        for i, (left, right) in enumerate(self._pdf_ranges):
            if i + 1 >= len(self._pdf_positions):
                break
            if (cur.hasSelection() and self._pdf_positions[i] < cur.selectionEnd()
                    and self._pdf_positions[i + 1] > cur.selectionStart()):
                painter.fillRect(QRectF(left, self._pdf_top, max(1.0, right - left),
                                        self._pdf_bottom - self._pdf_top), QColor(0, 110, 220, 80))
        if self.hasFocus() and self._caret_on:
            r = self.cursorRect()
            painter.setPen(QPen(QColor(20, 90, 180), 1))
            painter.drawLine(r.topLeft(), r.bottomLeft())
        if self._preedit:
            painter.setFont(self.font())
            painter.setPen(QColor(20, 90, 180))
            r = self.cursorRect()
            painter.drawText(QPointF(r.left(), r.bottom()), self._preedit)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            hit = self.cursorForPosition(event.position())
            cur = self.textCursor()
            inside = (cur.hasSelection() and cur.selectionStart() <= hit.position()
                      < cur.selectionEnd())
            if event.button() == Qt.MouseButton.LeftButton:
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    cur.setPosition(hit.position(), QTextCursor.MoveMode.KeepAnchor)
                    hit = cur
                self.setTextCursor(hit)
                self.sync_typing_format_from_cursor()
                self._pdf_dragging = True
            elif not inside:
                self.setTextCursor(hit)
                self.sync_typing_format_from_cursor()
            self.setFocus()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pdf_dragging:
            cur = self.textCursor()
            cur.setPosition(self.cursorForPosition(event.position()).position(),
                            QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cur)
            event.accept()
            return
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pdf_dragging = False
        event.accept()

    def mouseDoubleClickEvent(self, event):
        cur = self.cursorForPosition(event.position())
        cur.select(QTextCursor.SelectionType.WordUnderCursor)
        self.setTextCursor(cur)
        self._pdf_dragging = False
        event.accept()


class VisibleArrowFontComboBox(QFontComboBox):
    """始终绘制清晰下拉三角的字体框。

    Windows 主题或全局 QSS 有时会把原生 QComboBox 箭头隐藏；箭头直接画在
    控件前景层，不依赖主题图片，同时保留原生下拉按钮的点击行为。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setToolTip("选择文字字体；点击右侧三角展开字体列表")
        self.setMinimumHeight(34)
        self.setStyleSheet(
            "QFontComboBox { padding-right: 30px; }"
            "QFontComboBox::drop-down { width: 30px; border: none; }"
            "QFontComboBox::down-arrow { image: none; width: 0; height: 0; }")

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = self.palette()
        group = (QPalette.ColorGroup.Active if self.isEnabled()
                 else QPalette.ColorGroup.Disabled)
        color = QColor(palette.color(group, QPalette.ColorRole.Text))
        if not color.isValid() or color.alpha() < 80:
            color = QColor("#f5f7fa" if palette.color(
                QPalette.ColorRole.Base).lightness() < 128 else "#20252d")
        background = palette.color(QPalette.ColorRole.Base)
        # 前景随主题变化；反差描边取相反明暗，深色主题显示亮箭头，
        # 浅色主题显示深箭头。
        outline = QColor(0, 0, 0, 210) if color.lightness() > 150 \
            else QColor(255, 255, 255, 220)
        divider = QColor(palette.color(QPalette.ColorRole.Mid))
        divider.setAlpha(150)
        painter.setPen(QPen(divider, 1.0))
        painter.drawLine(self.width() - 30, 6,
                         self.width() - 30, self.height() - 6)
        painter.setBrush(QBrush(color))
        cx = float(self.width() - 14)
        cy = float(self.height()) / 2.0 + 1.0
        painter.setPen(QPen(outline, 1.2, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.drawPolygon(QPolygonF([
            QPointF(cx - 6.5, cy - 4.0),
            QPointF(cx + 6.5, cy - 4.0),
            QPointF(cx, cy + 4.5),
        ]))


class FormatDialog(QDialog):
    """独立的「格式编辑」模块：仅含 字体/粗细/斜体/字号/颜色 五项。

    由 RichEditBox 右键菜单「格式编辑…」入口打开，结果只应用到打开时
    选中的字符（无选中则作用于光标处的后续输入）。不混入下划线、上下标
    等重复或无关功能，保持交互聚焦。
    """

    def __init__(self, fmt, parent=None):
        super().__init__(parent)
        self.setWindowTitle("格式编辑")
        self.setModal(True)
        self.setMinimumWidth(360)
        fmt = fmt or {}
        self._color = fmt.get("color")
        if not isinstance(self._color, QColor):
            self._color = QColor(0, 0, 0)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        # 第一行：字体
        row_font = QHBoxLayout()
        row_font.setSpacing(8)
        lbl_font = QLabel("字体")
        row_font.addWidget(lbl_font)
        self.font_combo = VisibleArrowFontComboBox()
        self.font_combo.setObjectName("textFormatFont")
        self.font_combo.setEditable(True)
        fam = (fmt.get("family") or "").strip()
        # 自维护字族字符串：QFontComboBox 在系统注册名不匹配（如英文环境
        # 下的中文字体）时会回退成 "Sans Serif"，必须保留用户请求/选择
        # 的原字族名，避免格式模块悄悄丢掉字体。
        if fam:
            idx = self.font_combo.findText(fam)
            if idx >= 0:
                self.font_combo.setCurrentIndex(idx)
            else:
                self.font_combo.setCurrentText(fam)
        self._family = fam or self.font_combo.currentText().strip() \
            or "Microsoft YaHei"
        self.font_combo.editTextChanged.connect(self._sync_family)
        self.font_combo.currentFontChanged.connect(
            lambda f: self._sync_family(f.family()))
        self.font_combo.activated.connect(lambda _index: self._sync_family())
        row_font.addWidget(self.font_combo, 1)
        lay.addLayout(row_font)

        # 第二行：字号 + 加粗/斜体 + 颜色
        row_fmt = QHBoxLayout()
        row_fmt.setSpacing(8)
        lbl_size = QLabel("字号")
        row_fmt.addWidget(lbl_size)
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setObjectName("textFormatSize")
        self.size_spin.setRange(1.0, 400.0)
        self.size_spin.setDecimals(1)
        self.size_spin.setSingleStep(0.5)
        self.size_spin.setValue(float(fmt.get("size") or 12.0))
        self.size_spin.setSuffix(" pt")
        self.size_spin.setFixedSize(84, 34)
        row_fmt.addWidget(self.size_spin)
        row_fmt.addSpacing(6)

        self.bold_btn = QPushButton("B")
        self.bold_btn.setObjectName("textFormatToggle")
        self.bold_btn.setCheckable(True)
        self.bold_btn.setChecked(bool(fmt.get("bold", False)))
        self.bold_btn.setToolTip("加粗")
        # 与 size_spin(34)/color_btn(34) 同高，宽度放宽到 44 让 14pt
        # B/I 字形在 padding:0 下也不会被压扁——之前 40×30 比旁边的
        # 控件矮且窄，italic 的 "I" 渲染成斜杠后只剩 "/"，看起来像被裁。
        self.bold_btn.setFixedSize(44, 34)
        bold_f = QFont(self.bold_btn.font())
        bold_f.setBold(True)
        bold_f.setPointSize(13)
        self.bold_btn.setFont(bold_f)
        row_fmt.addWidget(self.bold_btn)

        self.italic_btn = QPushButton("I")
        self.italic_btn.setObjectName("textFormatToggle")
        self.italic_btn.setCheckable(True)
        self.italic_btn.setChecked(bool(fmt.get("italic", False)))
        self.italic_btn.setToolTip("斜体")
        self.italic_btn.setFixedSize(44, 34)
        italic_f = QFont(self.italic_btn.font())
        italic_f.setItalic(True)
        italic_f.setPointSize(13)
        self.italic_btn.setFont(italic_f)
        row_fmt.addWidget(self.italic_btn)

        self.color_btn = QPushButton("颜色")
        self.color_btn.setObjectName("textFormatColor")
        self.color_btn.setFixedSize(92, 34)
        self.color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        row_fmt.addWidget(self.color_btn)
        row_fmt.addStretch(1)
        lay.addLayout(row_fmt)
        self._style_color_button()

        # 按钮行
        row_btn = QHBoxLayout()
        row_btn.addStretch(1)
        self.ok_btn = QPushButton("确定")
        self.ok_btn.setObjectName("textFormatOk")
        self.ok_btn.setDefault(True)
        self.ok_btn.setFixedWidth(88)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("textFormatCancel")
        self.cancel_btn.setFixedWidth(88)
        row_btn.addWidget(self.ok_btn)
        row_btn.addWidget(self.cancel_btn)
        lay.addLayout(row_btn)

        self.color_btn.clicked.connect(self._pick_color)
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

    def _style_color_button(self):
        r, g, b = (self._color.red(), self._color.green(), self._color.blue())
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        fg = "#101014" if lum > 170 else "#ffffff"
        self.color_btn.setStyleSheet(
            "QPushButton#textFormatColor{"
            "background: rgb(%d,%d,%d); color: %s;"
            "border: 1px solid #b0b0b8; border-radius: 6px;"
            "padding: 3px 6px;}" % (r, g, b, fg))

    def _sync_family(self, *_):
        txt = (self.font_combo.currentText() or "").strip()
        if txt:
            self._family = txt

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self, "选择文字颜色")
        if c.isValid():
            self._color = QColor(c)
            self._style_color_button()

    def result_format(self):
        """返回 {family,size,color,bold,italic}，供调用方应用到选区。"""
        # 可编辑 QFontComboBox 使用键盘输入/输入法后，currentFontChanged 在
        # 个别 Qt/Windows 组合下不会触发；确认时以当前可见文本为最终事实。
        self._sync_family()
        return {
            "family": self._family or "Microsoft YaHei",
            "size": round(self.size_spin.value(), 2),
            "color": QColor(self._color),
            "bold": self.bold_btn.isChecked(),
            "italic": self.italic_btn.isChecked(),
        }
