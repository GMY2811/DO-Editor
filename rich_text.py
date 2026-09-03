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

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QColorDialog, QDialog, QDoubleSpinBox,
                               QFontComboBox, QFrame, QHBoxLayout, QLabel,
                               QMenu, QPushButton, QTextEdit, QVBoxLayout)

# Qt 中 1pt 按逻辑 DPI(96) 渲染为 4/3 逻辑像素。编辑器以「pt*scale
# 逻辑像素」精确显示（与页面位图文字等大），故写入字符格式的点阵值 =
# 目标像素 / (96/72)；读回时再乘回。scale 由 set_scale 传入（=页面 zoom
# 或带 1.08 输入放大系数）。
_PX_PER_PT = 96.0 / 72.0


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
        # 空字族会生成「无字体」fragment，后续 fontFamily()/fontFamilies()
        # 读取在本机 PySide/Qt 上触发原生访问违例（不可被 try 捕获），
        # 故一律兜底为非空字族。
        family = (run.get("family") or self._base_fmt.get("family")
                  or "Microsoft YaHei")
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

    # -- 右键「格式编辑…」独立模块 --------------------------------------

    def _format_at_position(self, pos):
        """取文档 pos 处字符格式为 {family,size,color,bold,italic}。"""
        doc = self.document()
        last = max(0, doc.characterCount() - 1)
        tc = QTextCursor(doc)
        tc.setPosition(min(max(0, int(pos)), last))
        cf = tc.charFormat()
        return {
            "family": self._fmt_family(cf),
            "size": self._fmt_size_pt(cf),
            "color": QColor(cf.foreground().color()),
            "bold": self._fmt_bold(cf),
            "italic": bool(cf.fontItalic()),
        }

    def _open_format_editor(self, anchor, end, had_selection):
        """弹出独立「格式编辑」模块；确认后应用到右键时的选区/光标。

        anchor/end/had_selection 在弹出右键菜单时捕获。菜单与对话框
        exec 期间编辑框会失焦，调用方须保证 _suppress_focusout 生效，
        避免上层把编辑提交关掉导致改动无处可落。
        """
        snap = self._format_at_position(anchor)
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
        self.font_combo = QFontComboBox()
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
        self.size_spin.setFixedWidth(84)
        row_fmt.addWidget(self.size_spin)
        row_fmt.addSpacing(6)

        self.bold_btn = QPushButton("B")
        self.bold_btn.setObjectName("textFormatToggle")
        self.bold_btn.setCheckable(True)
        self.bold_btn.setChecked(bool(fmt.get("bold", False)))
        self.bold_btn.setToolTip("加粗")
        self.bold_btn.setFixedSize(40, 32)
        bold_f = QFont(self.bold_btn.font())
        bold_f.setBold(True)
        bold_f.setPointSize(14)
        self.bold_btn.setFont(bold_f)
        row_fmt.addWidget(self.bold_btn)

        self.italic_btn = QPushButton("I")
        self.italic_btn.setObjectName("textFormatToggle")
        self.italic_btn.setCheckable(True)
        self.italic_btn.setChecked(bool(fmt.get("italic", False)))
        self.italic_btn.setToolTip("斜体")
        self.italic_btn.setFixedSize(40, 32)
        italic_f = QFont(self.italic_btn.font())
        italic_f.setItalic(True)
        italic_f.setPointSize(14)
        self.italic_btn.setFont(italic_f)
        row_fmt.addWidget(self.italic_btn)

        self.color_btn = QPushButton("颜色")
        self.color_btn.setObjectName("textFormatColor")
        self.color_btn.setFixedWidth(92)
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
        return {
            "family": self._family or "Microsoft YaHei",
            "size": round(self.size_spin.value(), 2),
            "color": QColor(self._color),
            "bold": self.bold_btn.isChecked(),
            "italic": self.italic_btn.isChecked(),
        }
