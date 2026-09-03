"""回归：PDF 字体名 → 系统字体映射 + 粗斜体综合推断。"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("APPDATA", os.path.abspath("_verify_appdata"))
from PySide6.QtWidgets import QApplication
app = QApplication([])
import backend
from document_view import DocumentView

m = DocumentView._map_pdf_font
cases = [
    # (字体名, 期望系统字体)
    ("SimSun",                 "SimSun"),
    ("ABCDEF+SimSun",          "SimSun"),      # 子集前缀
    ("Noto Serif CJK SC",      "SimSun"),
    ("Source Han Serif SC",    "SimSun"),
    ("FZXiaoBiaoSong-B05S",    "SimSun"),      # 方正小标宋
    ("KaiTi_GB2312",           "KaiTi"),
    ("FangSong_GB2312",        "FangSong"),
    ("Microsoft YaHei",        "Microsoft YaHei"),
    ("SimHei",                 "SimHei"),
    ("Droid Sans Fallback Regular", "Microsoft YaHei"),
    ("Noto Sans CJK SC",       "Microsoft YaHei"),
    ("PingFang SC",            "Microsoft YaHei"),
    ("ArialMT",                "Arial"),
    ("Arial-BoldMT",           "Arial"),
    ("TimesNewRomanPSMT",      "Times New Roman"),
    ("CourierNewPSMT",         "Courier New"),
    ("HZGB-GB2312",            ""),            # 未知 → 空，由调用方兜底
]
for name, want in cases:
    got = m(name)
    assert got == want, f"map {name!r}: got {got!r}, want {want!r}"
print("MAP_OK", len(cases), "cases")

# 粗斜体推断：flags 缺位时应从字体名补
def st(name, flags=0):
    return backend.font_style_flags(name, flags)
assert st("ArialMT", 0) == (False, False)
assert st("Arial-BoldMT", 0) == (True, False)        # 名字含 Bold
assert st("Arial-ItalicMT", 0) == (False, True)      # 名字含 Italic
assert st("Arial", 16) == (True, False)              # flags bold
assert st("Arial", 2) == (False, True)               # flags italic
assert st("SimSun", 16) == (True, False)
assert st("Droid Sans Fallback Regular", 0) == (False, False)
print("STYLE_OK")

# 端到端：就地编辑一条真实行，保存后 span 的 size/color/字体族规则仍生效
from PySide6.QtCore import QPointF
view = DocumentView()
view.load("sample.pdf")
view.set_mode("replace_text")
ln = view.page_view._edit_line_hits(0)[0]
print("line0 fmt:", ln["fmt"])
view._begin_row_edit(0, ln)
app.processEvents()
view._row_edit.setText("格式保真【改】")
view._commit_row_edit(commit=True)
app.processEvents()
obj = view.objects[-1]
assert obj["kind"] == "text"
assert obj["fontsize"] == 12.0
print("committed obj family/size/color/bold/italic:",
      obj["fontfamily"], obj["fontsize"], obj["color"].name(),
      obj["bold"], obj["italic"])
print("FONT_FIX_OK")
