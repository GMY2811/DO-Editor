"""离屏回归：修改文字（就地编辑）不得误删相邻行。

行距紧凑的文档（正文/表格）里 PyMuPDF 行 bbox 含字体 ascend/descend，
相邻行 bbox 互相交叠。旧实现按整行 bbox 做 redact 擦除，红act 会删除
与矩形相交的整段文本 → 修改一行时相邻整行文字被吞（严重数据丢失）。

本脚本自造 baseline 间距 10pt、字号 12pt 的 4 行文档（行 bbox 高
~13.3pt → 邻行交叠 ~3.3pt），就地修改第 1 行后断言：
- 第 2/3/4 行文字完整保留（旧实现此处会丢失）；
- 被编辑行原文已擦除、新文字浮层已建立。
"""
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("APPDATA", os.path.abspath("_verify_appdata"))

from PySide6.QtWidgets import QApplication
app = QApplication([])
from document_view import DocumentView
import pymupdf

# 1) 构造紧凑多行 PDF（行 bbox 交叠）写入临时文件
tmp_dir = tempfile.mkdtemp(prefix="do_redact_")
src = os.path.join(tmp_dir, "tight.pdf")
d = pymupdf.open()
pg = d.new_page(width=300, height=200)
y = 40
for i in range(4):
    pg.insert_text((50, y), f"LINE-{i} hello world {i}", fontsize=12,
                   fontname="times", fontfile=r"C:\Windows\Fonts\times.ttf")
    y += 10
d.save(src)
d.close()

# 2) 打开并进入修改文字
view = DocumentView()
assert view.load(src), "load tight.pdf failed"
pv = view.page_view
view.set_mode("replace_text")

lines = pv._edit_line_hits(0)
texts = [ln["text"] for ln in lines]
print("edit lines:", [t.strip()[:16] for t in texts])
assert len(lines) >= 3, "应识别出至少 3 行文字"

# 邻行 bbox 确实交叠（回归前提）
b0 = lines[0]["rect"].getRect()
b1 = lines[1]["rect"].getRect()
assert b0[1] + b0[3] > b1[1], f"回归前提不成立: 邻行 bbox 未交叠 {b0} vs {b1}"
print(f"邻行 bbox 交叠 {b0[1] + b0[3] - b1[1]:.1f}pt —— 复现条件成立")

# 3) 就地修改第 1 行并提交
ln = lines[0]
old0 = ln["text"].strip()
view._on_text_line_clicked(0, ln)
app.processEvents()
assert view._row_edit is not None, "应就地打开编辑框"
view._row_edit.setText(ln["text"].replace("hello", "world") + "!")
view._commit_row_edit(commit=True)
app.processEvents()

# 4) 断言
d2 = pymupdf.open(src)
view.doc.save(os.path.join(tmp_dir, "out.pdf"), garbage=3, deflate=True)
check = pymupdf.open(os.path.join(tmp_dir, "out.pdf"))
raw_txt = check[0].get_text()
page_txt = raw_txt.replace("\xa0", " ").replace("\xad", "-")
print("page text:", repr(page_txt[:160]))
check.close()
d2.close()

for i in (1, 2, 3):
    t = f"hello world {i}"
    assert t in page_txt, f"相邻行 {i} 被误删: {t!r} 不在结果文本中"
    print(f"neighbor line{i}: KEEP ✓")
assert "hello world 0" not in page_txt or "LINE-0 hello" not in page_txt, \
    "被编辑行原文应被擦除"
# 新文字作为浮层对象已建立（保存时才烘焙进 PDF）
floating = [str(o.get("text", "")).replace("\xa0", " ").replace("\xad", "-")
            for o in view.objects]
assert any("world world" in t for t in floating), \
    f"新文字浮层对象应存在, objects={floating!r}"
print("REDACT_NEIGHBOR_OK")
