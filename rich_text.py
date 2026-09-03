# -*- coding: utf-8 -*-
"""就地富文本编辑控件与文字段(runs)工具。

文字段(runs)模型：一段文字的内容由若干连续样式段组成
    {"text": str, "family": str, "size": float(pt), "color": QColor,
     "bold": bool, "italic": bool}
同一段内样式一致；相邻同格式段在落库前合并，保证 runs 最少化。

RichEditBox：仿 QLineEdit 的单行就地编辑控件，内容却是富文本：
- 可以用鼠标拖动选中部分字符（局部高亮）；
- 右键菜单在系统标准项之上提供「格式设置」（粗体/斜体/字体/字号/颜色），
  仅作用于选中的字符，实现字符级混排；
- 回车 = 提交（submitRequested）、Esc = 取消（cancelRequested）；
- 粘贴自动过滤换行，控件始终保持单行。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QColorDialog, QFrame, QMenu, QTextEdit

# Qt 中 1pt 按逻辑 DPI(96) 渲染为 4/3 逻辑像素。编辑器以「pt*scale
# 逻辑像素」精确显示（与页面位图文字等大），故写入字符格式的点阵值 =
# 目标像素 / (96/72)；读回时再乘回。scale 由 set_scale 传入（=页面 zoom
# 或带 1.08 输入放大系数）。
_PX_PER_PT = 96.0 / 72.0

# 右键菜单常用的字体/字号/颜色候选
_POP_FONTS = [
    "Microsoft YaHei", "SimSun", "SimHei", "KaiTi", "FangSong", "DengXian",
    "Arial", "Times New Roman", "Courier New", "Segoe UI",
]
_POP_SIZES = [6, 7, 8, 9, 10, 10.5, 11, 12, 14, 16, 18, 20, 22,
              24, 26, 28, 32, 36, 48, 60, 72]
_POP_COLORS = [
    ("黑色", (0, 0, 0)), ("灰色", (90, 90, 90)), ("白色", (255, 255, 255)),
    ("红色", (192, 0, 0)), ("深红", (136, 0, 21)), ("橙色", (191, 90, 10)),
    ("黄色", (191, 144, 0)), ("绿色", (0, 97, 0)), ("青色", (0, 115, 115)),
    ("蓝色", (0, 40, 158)), ("紫色", (104, 33, 122)),
]


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

    def set_content(self, text, fmt=None):
        """以统一格式载入纯文本；fmt 形如 {family,size,color,bold,italic}。"""
        runs = single_run(
            text,
            (fmt or {}).get("family", ""),
            (fmt or {}).get("size", 12.0),
            (fmt or {}).get("color"),
            (fmt or {}).get("bold", False),
            (fmt or {}).get("italic", False))
        self.set_runs(runs)

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
        self.document().clearUndoRedoStacks()

    def text(self):
        """与 QLineEdit 语义兼容：返回纯文本。"""
        return self.toPlainText()

    def hasSelectedText(self):
        """与 QLineEdit 语义兼容：当前是否存在选中文字。"""
        return self.textCursor().hasSelection()

    def selectedText(self):
        """与 QLineEdit 语义兼容：返回选中文字。"""
        return self.textCursor().selectedText()

    def cursorPosition(self):
        """与 QLineEdit 语义兼容：当前光标位置（0..len(纯文本)）。"""
        return self.textCursor().position()

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

    def sync_typing_format_from_cursor(self):
        """把光标处字符格式同步为后续输入格式。

        就地编辑在彩色/斜体等行内中间继续输入时，若不设置，新键入字符
        会退化为控件默认样式。空文档则沿用 set_default_format 的基准格式。
        """
        if not self.toPlainText():
            self.set_default_format(self._base_fmt)
            return
        try:
            cf = self.textCursor().charFormat()
        except Exception:
            return
        self.setCurrentCharFormat(cf)

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

    def plain_text(self):
        return self.toPlainText()

    # -- 格式工具 ----------------------------------------------------------

    def _fmt_family(self, cf):
        """安全读取字符格式的字体族（fontFamilies 在空文档默认格式上
        可能触发原生崩溃，统一走 fontFamily()）。"""
        try:
            fam = cf.fontFamily()
            if fam:
                return fam
        except Exception:
            pass
        return ""

    def _fmt_size_pt(self, cf):
        """字符格式中存储的点数 → PDF pt（去除 scale 与 Qt 96dpi 换算）。"""
        ps = cf.fontPointSize()
        if ps > 0 and self._scale > 0:
            return round(ps * _PX_PER_PT / self._scale, 2)
        return 12.0

    def _fmt_bold(self, cf):
        return cf.fontWeight() >= QFont.Weight.Bold

    def _char_format(self, run):
        cf = QTextCharFormat()
        family = run.get("family") or ""
        if family:
            cf.setFontFamilies([family])
        # 存点阵值 = 目标像素 / (96/72)，使 Qt 渲染像素 ≈ pt*scale
        size = float(run.get("size") or 12.0)
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

    def _selection_char_format(self):
        """取选区首字符格式（无选区取光标处字符格式）。"""
        cur = QTextCursor(self.textCursor())
        if cur.hasSelection():
            cur.setPosition(cur.selectionStart())
        return cur.charFormat()

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
        if size_pt is not None:
            cf.setFontPointSize(max(
                1.0, float(size_pt) * self._scale / _PX_PER_PT))
        if color is not None:
            cf.setForeground(QBrush(QColor(color)))
        # mergeCurrentCharFormat：有选区时并入选中字符，
        # 无选区时并入当前字符格式——均同步为后续输入样式，不会整体替换
        self.mergeCurrentCharFormat(cf)

    # -- 右键格式菜单 -------------------------------------------------------

    def _menu_font_submenu(self, parent, cur_family):
        m = QMenu("字体", parent)
        fams = list(_POP_FONTS)
        if cur_family and cur_family not in fams:
            fams.insert(0, cur_family)
        for fam in fams:
            act = m.addAction(fam)
            act.setCheckable(True)
            act.setChecked((cur_family or "").lower() == fam.lower())
            act.triggered.connect(
                lambda _c=False, f=fam: self._apply_char(family=f))
        return m

    def _menu_size_submenu(self, parent, cur_size):
        m = QMenu("字号", parent)
        sizes = list(_POP_SIZES)
        if cur_size and not any(abs(s - cur_size) < 0.01 for s in sizes):
            sizes = sorted(sizes + [float(cur_size)])
        for s in sizes:
            label = ("%g" % s) + (" pt" if s == sizes[0] else "")
            act = m.addAction("%g" % s)
            act.setCheckable(True)
            act.setChecked(abs(float(s) - float(cur_size)) < 0.01)
            act.triggered.connect(
                lambda _c=False, sz=s: self._apply_char(size_pt=float(sz)))
        return m

    def _menu_color_submenu(self, parent, cur_color):
        m = QMenu("颜色", parent)
        cur_rgb = (cur_color.red(), cur_color.green(), cur_color.blue())
        for name, rgb in _POP_COLORS:
            act = m.addAction(name)
            act.setCheckable(True)
            act.setChecked(rgb == cur_rgb)
            act.triggered.connect(
                lambda _c=False, t=rgb: self._apply_char(color=QColor(*t)))
        m.addSeparator()
        act = m.addAction("自定义…")
        act.triggered.connect(self._pick_custom_color)
        return m

    def _pick_custom_color(self):
        cur = self._selection_char_format()
        c = QColorDialog.getColor(cur.foreground().color(), self, "选择文字颜色")
        if c.isValid():
            self._apply_char(color=c)

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        cur = self.textCursor()
        # 仅当确实选中了字符才提供「格式设置」入口（符合常规编辑习惯）
        if cur.hasSelection() and cur.selectedText():
            self._suppress_focusout += 1
            try:
                first = self._selection_char_format()
                fmt_menu = QMenu("格式设置", menu)
                act = fmt_menu.addAction("粗体")
                act.setCheckable(True)
                act.setChecked(self._fmt_bold(first))
                act.triggered.connect(
                    lambda _c=False: self._apply_char(
                        bold=not self._fmt_bold(
                            self._selection_char_format())))
                act = fmt_menu.addAction("斜体")
                act.setCheckable(True)
                act.setChecked(first.fontItalic())
                act.triggered.connect(
                    lambda _c=False: self._apply_char(
                        italic=not self._selection_char_format().fontItalic()))
                fmt_menu.addSeparator()
                fmt_menu.addMenu(self._menu_font_submenu(
                    fmt_menu, self._fmt_family(first)))
                fmt_menu.addMenu(self._menu_size_submenu(
                    fmt_menu, self._fmt_size_pt(first)))
                fmt_menu.addMenu(self._menu_color_submenu(
                    fmt_menu, QColor(first.foreground().color())))
                if menu.actions():
                    menu.insertMenu(menu.actions()[0], fmt_menu)
                    menu.insertSeparator(menu.actions()[1])
                else:
                    menu.addMenu(fmt_menu)
            finally:
                self._suppress_focusout -= 1
        menu.exec(event.globalPos())
        menu.deleteLater()

    # -- 鼠标 / 键盘 --------------------------------------------------------

    def mousePressEvent(self, event):
        # 右键点在当前选区之外时，取消选择并把光标移到该处，
        # 保证「格式设置」始终作用于用户右键的那段字符。
        if event.button() == Qt.MouseButton.RightButton:
            click_cur = self.cursorForPosition(event.position())
            cur = self.textCursor()
            inside = (cur.hasSelection() and
                      cur.selectionStart() <= click_cur.position() <=
                      cur.selectionEnd())
            if not inside:
                click_cur.clearSelection()
                self.setTextCursor(click_cur)
        super().mousePressEvent(event)

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
        super().keyPressEvent(event)

    def insertFromMimeData(self, source):
        # 单行约束：粘贴内容丢弃换行与富文本样式
        if source.hasText():
            txt = source.text().replace("\r\n", " ").replace("\n", " ") \
                                .replace("\r", " ")
            self.insertPlainText(txt)
        else:
            super().insertFromMimeData(source)
