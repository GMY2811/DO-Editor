"""离屏回归：v2.6.6 文字修改模块两处修复。

1) 点击行进入就地编辑：编辑框字号 == 原文字号*zoom（去掉 1.08 放大），
   框内文字不再比原文放大变形、位置贴合原文行。
2) 写回 PDF 时粗/斜样式走对应变体系统字体（bold→arialbd.ttf 等），
   保存后不再丢失斜体/粗细。
3) 字形兜底检测不再设“仅中文”门限：Arial 字体写中文/任意字符
   都会自动回退全量系统字体，杜绝方块。
"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("APPDATA", os.path.abspath("_verify_appdata"))

from PySide6.QtWidgets import QApplication

app = QApplication([])
import document_view as dv
from document_view import DocumentView

view = DocumentView()
assert view.load("sample.pdf"), "load sample failed"
pv = view.page_view

# ---------- 1) 编辑框字号不再放大 ----------
view.set_mode("replace_text")
lines0 = pv._edit_line_hits(0)
assert lines0, "sample.pdf 第 1 页应有可编辑文字行"
ln = lines0[0]
fmt = ln.get("fmt") or {}
size = float(fmt.get("size") or 10.0)
zoom = pv._zoom
view._on_text_line_clicked(0, ln)
app.processEvents()
assert view._row_edit is not None, "点击文字行应就地打开编辑框"
edit = view._row_edit
font_px = edit.font().pixelSize()
expect_px = max(9.0, size * zoom)
print(f"span size={size} zoom={zoom} -> expect {expect_px:.2f}px, "
      f"editbox font={font_px}px")
assert abs(font_px - expect_px) <= 1.0, (
    f"编辑框字号 {font_px} 应等于原文字号*zoom {expect_px:.2f}（不得再放大 1.08 倍）")
view._commit_row_edit(commit=False)

# ---------- 2) _prepare_row_embed 粗斜变体选择 ----------
# 用构造页验证：插入一段 Arial 粗斜文字行，看 embed 是否落到粗斜文件
import pymupdf
import re as _re
doc2 = pymupdf.open()
page2 = doc2.new_page()
_UP = dv.DocumentView

def embed_for(pdf_font, size_, bbox, bold, italic):
    emb, base = view._prepare_row_embed(
        page2, pdf_font, size_, bbox, bold=bold, italic=italic)
    return emb, base

# Arial 常规
e_n, _ = embed_for("ArialMT", 12.0, (10, 10, 100, 25), False, False)
print("Arial regular ->", (e_n or {}).get("file"))
assert (e_n or {}).get("file", "").lower().endswith("arial.ttf"), \
    f"常规 Arial 应指向 arial.ttf, got {e_n}"
# Arial 粗
e_b, _ = embed_for("Arial-BoldMT", 12.0, (10, 10, 100, 25), True, False)
print("Arial bold    ->", (e_b or {}).get("file"), "| name:", (e_b or {}).get("name"))
assert (e_b or {}).get("file", "").lower().endswith("arialbd.ttf"), \
    f"粗体 Arial 应指向 arialbd.ttf, got {e_b}"
# Arial 斜
e_i, _ = embed_for("Arial-ItalicMT", 12.0, (10, 10, 100, 25), False, True)
print("Arial italic  ->", (e_i or {}).get("file"))
assert (e_i or {}).get("file", "").lower().endswith("ariali.ttf"), \
    f"斜体 Arial 应指向 ariali.ttf, got {e_i}"
# 粗斜
e_bi, _ = embed_for("Arial-BoldItalicMT", 12.0, (10, 10, 100, 25), True, True)
print("Arial boldit  ->", (e_bi or {}).get("file"), "| name:", (e_bi or {}).get("name"))
assert (e_bi or {}).get("file", "").lower().endswith("arialbi.ttf"), \
    f"粗斜 Arial 应指向 arialbi.ttf, got {e_bi}"
# 变体注册名不与常规撞名
assert (e_b or {}).get("name") != (e_n or {}).get("name"), "粗体注册名应区别于常规"

# ---------- 3) bake 覆盖检测无门限 ----------
# Arial 常规 embed 写中文：应自动回退到含中文字形的系统字体，不出现方块
obj_cjk = {
    "text": "中文测试ABC", "fontsize": 12.0, "baseline": 20.0,
    "fontfamily": "Arial", "bold": False, "italic": False,
    "embed": e_n,
}
view._bake_text_original_font(page2, pymupdf.Rect(10, 10, 200, 30),
                              obj_cjk, (0, 0, 0))
# 页面应多出文字对象且字体已从 Arial 回退为含中文字形的字体
fonts_p2 = [f[3] for f in page2.get_fonts(full=True)]
print("fonts after cjk bake:", fonts_p2)
assert not any("arial" in (f or "").lower() for f in fonts_p2), \
    "Arial 写中文不应继续用 Arial（缺中文字形会方块）"
txt2 = page2.get_text()
print("page2 text:", repr(txt2.strip()))
assert "中文测试ABC" in txt2, "回退字体写回后中文字符应完整可提取"

# 纯英文在 Arial 下不触发回退（保留原字体族）→ 用全新页验证
doc3 = pymupdf.open()
page3 = doc3.new_page()
obj_en = {
    "text": "Hello World", "fontsize": 12.0, "baseline": 20.0,
    "fontfamily": "Arial", "bold": True, "italic": False,
    "embed": e_b,
}
view._bake_text_original_font(page3, pymupdf.Rect(10, 10, 200, 30),
                              obj_en, (0, 0, 0))
fonts_p3 = [f[3] for f in page3.get_fonts(full=True)]
print("fonts after en bold bake:", fonts_p3)
assert any("Arial" in (f or "") or "arial" in (f or "").lower()
           for f in fonts_p3), "纯英文粗体应保留 Arial 族并带粗体文件"

# 提取写回文本核对不丢内容（PyMuPDF 可能把空格归一化为 \xa0，忽略空白比较）
txt3 = page3.get_text()
print("page3 text:", repr(txt3.strip()))
norm3 = "".join(ch for ch in txt3 if not ch.isspace())
assert "HelloWorld" in norm3, "写回文本应完整保留（含粗体字母）"

print("V266_FIX_OK")
