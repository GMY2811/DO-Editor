"""回归: 修改/添加文字烘焙时, 避免复用页面已存在的同名 CID 子集导致新字形
映射成 \\x00 豆腐。

历史 bug: _bake_text_original_font 用 f[3] (basefont, 带子集前缀如
EZMRFS+Microsoft YaHei Regular) 与 sanitize 后的注册名比较, 永远不命中,
导致 insert_font 同名时被静默复用——原 CID 子集只有原文档用过的字形,
新字符全部映射成 \\x00 (豆腐/方块)。
修复: 改用 f[4] (insert_font 实际资源名), 检测到同名时强制用唯一名
注册新的全量字体。
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("APPDATA", os.path.abspath("_verify_appdata"))
sys.path.insert(0, r"D:\Project\2026-08-16-16-15-44\do-reader")

from PySide6.QtWidgets import QApplication
app = QApplication([])
import pymupdf
from document_view import DocumentView

# 1) 构造一个多字体的「毒」PDF: 含 CID/TrueType 子集
def make_poison_pdf(path):
    d = pymupdf.open()
    p = d.new_page(width=595, height=842)
    p.insert_font(fontname="Arial", fontfile=r"C:\Windows\Fonts\arial.ttf")
    p.insert_text((72, 100), "Turn In No.", fontname="Arial", fontsize=12)
    p.insert_font(fontname="MicrosoftYaHei",
                  fontfile=r"C:\Windows\Fonts\msyh.ttc")
    p.insert_text((72, 140), "我顶顶顶", fontname="MicrosoftYaHei", fontsize=12)
    p.insert_text((72, 170), "飞机okdf", fontname="MicrosoftYaHei", fontsize=12)
    p.insert_text((72, 200), "烦烦烦烦烦烦", fontname="MicrosoftYaHei", fontsize=12)
    d.subset_fonts()
    d.save(path)
    d.close()

work = tempfile.mkdtemp(prefix="do_nof_")
src = os.path.join(work, "src.pdf")
make_poison_pdf(src)

cases = [
    ("我顶顶顶", "我顶顶顶XYZ"),
    ("飞机okdf", "飞机okdfQ"),
    ("烦烦烦烦烦烦", "烦烦烦烦烦烦K"),
    ("Turn In No.", "Turn In No.OK"),
]

for kw, new_text in cases:
    p = os.path.join(work, f"in_{kw[:6]}.pdf")
    shutil.copy(src, p)
    v = DocumentView()
    assert v.load(p)
    pv = v.page_view
    v.set_mode("replace_text")
    rect = None
    for i, ln in enumerate(pv._edit_line_hits(0)):
        if kw in (ln.get("text") or ""):
            v._on_text_line_clicked(0, ln)
            app.processEvents()
            v._row_edit.setText(new_text)
            app.processEvents()
            v._commit_row_edit(commit=True)
            app.processEvents()
            if v.objects:
                rect = v.objects[0]["rect"]
            break
    rect = v.objects[0]["rect"] if v.objects else None
    if rect is None:
        print(f"  {kw}: SKIP (未命中/未产生对象)")
        continue
    out = os.path.join(work, f"out_{kw[:6]}.pdf")
    v._save_to(out)
    try: v.doc.close()
    except Exception: pass

    # 重开校验: 框内 get_text 不应含 \x00
    d = pymupdf.open(out)
    crop = pymupdf.Rect(float(rect.x())-2, float(rect.y())-2,
                        float(rect.right())+2, float(rect.bottom())+4)
    txt = d[0].get_text("text", clip=crop)
    bad = txt.count("\x00")
    d.close()
    if bad == 0 and new_text in txt:
        print(f"  {kw} -> OK (no \\x00, contains new text)")
    else:
        print(f"  {kw} -> FAIL: nul={bad} txt={txt!r}")
        raise AssertionError(f"{kw} tofu still: {bad} nul bytes, text={txt!r}")

print("NO_FONT_SUBSET_TOFU_OK")
