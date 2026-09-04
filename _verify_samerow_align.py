"""回归: 修改文字后, 同行内不同字号/字体的 run 共享基线, 不再被 htmlbox
折到下一行。

历史 bug: insert_rich_text_auto 走 insert_htmlbox 路径, 行框高度按原
行高固定, 当某 run 字号大于行高时会被 htmlbox 当作溢出而折到下一行,
用户观感"同行文字拆分成两行"。
修复: 字号不一致时改走直接 page.insert_text 路径, 所有 run 共享按
最大字号算出的 y_baseline (视觉底部对齐)。
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("APPDATA", os.path.abspath("_verify_appdata"))
sys.path.insert(0, r"D:\Project\2026-08-16-16-15-44\do-reader")

from PySide6.QtWidgets import QApplication
app = QApplication([])
import pymupdf
from document_view import DocumentView
from PySide6.QtGui import QTextCursor

# 构造源: 一行 "我顶顶顶XYZ" 全部 10pt (后续把中间放大)
src = os.path.join(tempfile.mkdtemp(prefix="do_sa_"), "s.pdf")
doc = pymupdf.open()
p = doc.new_page(width=595, height=200)
p.insert_font(fontname="m", fontfile=r"C:\Windows\Fonts\msyh.ttc")
p.insert_text((72, 100), "我顶顶顶XYZ", fontname="m", fontsize=10)
doc.subset_fonts(); doc.save(src); doc.close()

# 模拟用户: 改文字 + 选中间放大字号
work = tempfile.mkdtemp(prefix="do_sar_")
shutil.copy(src, os.path.join(work, "in.pdf"))
s = os.path.join(work, "in.pdf")
v = DocumentView(); v.load(s)
pv = v.page_view
v.set_mode("replace_text")
for i, ln in enumerate(pv._edit_line_hits(0)):
    if "我顶顶顶" in (ln.get("text") or ""):
        v._on_text_line_clicked(0, ln); app.processEvents()
        v._row_edit.setText("我顶顶顶XYZ"); app.processEvents()
        # 选中间 2 字符放大到 24pt
        c = QTextCursor(v._row_edit.document())
        c.setPosition(1); c.setPosition(3, QTextCursor.MoveMode.KeepAnchor)
        v._row_edit.setTextCursor(c); app.processEvents()
        v._row_edit._apply_char(size_pt=24.0); app.processEvents()
        v._commit_row_edit(commit=True); app.processEvents()
        break

assert v.objects, "应生成编辑对象"
obj = v.objects[0]
runs = obj.get("runs") or []
assert len(runs) == 3, f"期望 3 段 runs, 实际 {len(runs)}: {runs}"
sizes = [r.get("size") for r in runs]
assert sizes == [10.0, 24.0, 10.0], f"字号结构错: {sizes}"
print(f"runs: {[r.get('text') for r in runs]} sizes={sizes}")

# 保存后渲染: 修改行 bbox 内应只看到一行(高度 ~max_size),
# 不应有折到下方第二行的字形
out = os.path.join(work, "out.pdf")
v._save_to(out)
try: v.doc.close()
except Exception: pass

d = pymupdf.open(out)
clip = pymupdf.Rect(60, 80, 220, 130)
pix = d[0].get_pixmap(dpi=150, clip=clip)
# 计算字形竖直分布: 每行水平方向上检测黑色像素 y 范围
from PIL import Image
import io
img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
W, H = img.size
black_rows = []
for y in range(H):
    has_black = False
    for x in range(W):
        r, g, b = img.getpixel((x, y))
        if r < 100 and g < 100 and b < 100:
            has_black = True; break
    if has_black:
        black_rows.append(y)
d.close()
if not black_rows:
    raise AssertionError("渲染图中无字形")
y_min, y_max = min(black_rows), max(black_rows)
print(f"黑色像素 y 范围: {y_min}..{y_max} (高度 {y_max-y_min+1}px)")
# 阈值: 单行内字形竖直跨度 < 50px (24pt 字符约 50px 高, 10pt 约 20px 高)
assert (y_max - y_min) < 50, f"字形竖直跨度 {y_max-y_min+1}px 过大, 疑似拆行"
print("SAME_ROW_ALIGN_OK")
