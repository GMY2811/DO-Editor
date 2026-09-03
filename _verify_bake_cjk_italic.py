"""离屏复现：就地编辑修改原 PDF 中文行 + 整段斜体 → 保存丢斜体。

用户流程: 点文字行就地编辑 → 格式条设斜体 → 提交(_commit_row_edit,
style_changed → _embed_for_style 按新样式重建 embed) → 保存烘焙
(_bake_text_original_font 用 embed 字体文件直写)。

疑点: Windows 无中文字体斜体变体文件(_SYSTEM_FONT_FILES 中
Microsoft YaHei/SimSun/... 的 I/BI 档全回退正体文件), 斜体档 embed
的 file 实际是正体 → 直写丢斜体。此处不实例化 GUI, 直接对构造页
调用与 _bake_objects 相同的 _bake_text_original_font 验证。

输出 _bake_cjk_up.png(正体参考) 与 _bake_cjk_it.png(斜体保存结果),
两者像素 diff 打印在 stdout。
"""
import os
import sys
import pymupdf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from document_view import DocumentView  # noqa: E402

TEXT = "中文斜体保存测试Hello ABC 123"
SIZE = 16.0
FAM = "Microsoft YaHei"


def bake_once(italic, out_png):
    doc = pymupdf.open()
    page = doc.new_page(width=460, height=130)
    view = DocumentView.__new__(DocumentView)   # 跳过 __init__, 方法无状态依赖
    obj = {
        "text": TEXT, "fontsize": SIZE, "baseline": 64.0,
        "fontfamily": FAM, "bold": False, "italic": italic,
    }
    # 与 _commit_row_edit style_changed 分支完全一致: 按新样式重建 embed
    obj["embed"] = view._embed_for_style(FAM, SIZE, False, italic)
    assert obj["embed"], f"{FAM} italic={italic} embed 构建失败"
    fr = pymupdf.Rect(20, 40, 440, 100)
    view._bake_text_original_font(page, fr, obj, (0, 0, 0))
    pix = page.get_pixmap(dpi=150)
    pix.save(out_png)
    return pix


def diff_ratio(p1, p2):
    s1, s2 = p1.samples, p2.samples
    assert len(s1) == len(s2), "pixmap 尺寸不一致"
    n = len(s1)
    diff = sum(1 for i in range(0, n, 3)
               if s1[i] != s2[i] or s1[i + 1] != s2[i + 1] or s1[i + 2] != s2[i + 2])
    return diff / (n / 3.0) * 100.0


if __name__ == "__main__":
    up = bake_once(False, "_bake_cjk_up.png")
    it = bake_once(True, "_bake_cjk_it.png")
    ratio = diff_ratio(up, it)
    print(f"正体 vs 斜体保存 像素 diff = {ratio:.2f}%")
    print("斜体参考: 肉眼检查 _bake_cjk_it.png 是否倾斜")
    print("(diff 接近 0 => 斜体丢失 bug 复现; >5% => 斜体已生效)")
