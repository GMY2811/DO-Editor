"""干净的方向对比：三种斜体方式各画一张图，无叠加。"""
import os, sys, pymupdf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from document_view import DocumentView  # noqa

TEXT = "斜体方向判断ABCxyz"
SIZE = 28.0
FAM = "Microsoft YaHei"


def render(out, mode):
    doc = pymupdf.open()
    page = doc.new_page(width=560, height=150)
    view = DocumentView.__new__(DocumentView)
    embed = view._embed_for_style(FAM, SIZE, False, True)
    page.insert_font(fontname=embed["name"], fontfile=embed["file"])
    y = 80.0
    x0 = 30.0
    if mode == "neg":
        pivot = pymupdf.Point(x0, y)
        skew = pymupdf.Matrix(1, 0, -0.2493, 1, 0, 0)
        page.insert_text((x0, y), TEXT, fontname=embed["name"], fontsize=SIZE,
                         color=(0, 0, 0), morph=(pivot, skew))
    elif mode == "pos":
        pivot = pymupdf.Point(x0, y)
        skew = pymupdf.Matrix(1, 0, 0.2493, 1, 0, 0)
        page.insert_text((x0, y), TEXT, fontname=embed["name"], fontsize=SIZE,
                         color=(0, 0, 0), morph=(pivot, skew))
    else:  # real
        page.insert_text((x0, y), TEXT, fontname="heit", fontsize=SIZE,
                         color=(0, 0, 0))
    pix = page.get_pixmap(dpi=150)
    pix.save(out)


if __name__ == "__main__":
    render("dir_neg.png", "neg")
    render("dir_pos.png", "pos")
    render("dir_real.png", "real")
    print("OK 三张图: dir_neg / dir_pos / dir_real")