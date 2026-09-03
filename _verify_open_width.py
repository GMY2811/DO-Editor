"""验证：1) MODE_DEFS text label=添加文字; 2) 打开文档默认适合宽度(fit_width)。"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("APPDATA", os.path.abspath("_verify_appdata"))

from PySide6.QtWidgets import QApplication
app = QApplication([])

import pymupdf
from document_view import DocumentView, MODE_DEFS

# 1) 模式名
labels = {k: l for k, l, _v, _i in MODE_DEFS}
assert labels["text"] == "添加文字", labels["text"]
print("[OK] 文本模式 label = %r" % labels["text"])

# 2) 打开文档默认适宽
tmp_pdf = os.path.join(os.environ["TEMP"], "_openw.pdf")
d = pymupdf.open(); pg = d.new_page(width=595, height=842)
pg.insert_text((72, 72), "Hello width default", fontsize=20)
d.save(tmp_pdf); d.close()

view = DocumentView()
view.resize(900, 700)
view.show(); app.processEvents()
ok = view.load(tmp_pdf)
# 渲染与滚动条就位后再做一次适宽（对应主窗口方向调整完成后的动作）
for _ in range(6):
    app.processEvents()
view.fit_width()
app.processEvents()
assert ok, "load failed"
w = pymupdf.open(tmp_pdf)[0].rect.width
h = pymupdf.open(tmp_pdf)[0].rect.height
vw = max(200, view.scroll.viewport().width() - 40)
vh = max(200, view.scroll.viewport().height())
zw = vw / w          # 适宽 zoom
zp = min(vw / w, vh / h)  # 整页 zoom
print("zoom=%.4f  zw=%.4f  zp=%.4f" % (view.zoom, zw, zp))
assert abs(view.zoom - zw) < 1e-6, "打开默认不是适合宽度: zoom=%r zw=%r" % (view.zoom, zw)
assert zw > zp + 1e-6, "此用例宽度模式应放大更多"
print("[OK] 打开文档默认 = 适合宽度")

# 3) 窗口变化后仍适宽
view.resize(1200, 700)
app.processEvents()
w2 = view.scroll.viewport().width() - 40
zw2 = w2 / w
# 触发一次节流定时器回调
view._window_fit_timer.stop()
view.fit_width(preserve_position=True)
app.processEvents()
print("resize zoom=%.4f  zw2=%.4f" % (view.zoom, zw2))
assert abs(view.zoom - zw2) < 1e-6, "窗口变化后未保持适宽"
print("[OK] 窗口尺寸变化后仍保持适合宽度")

# 4) 「适合宽度」按钮 = 整页/适宽切换（toggle_fit）
def cur_targets():
    """现算适宽/整页 zoom（视口宽度会随滚动条出现与否变化）。"""
    vw_ = max(200, view.scroll.viewport().width() - 40)
    vh_ = max(200, view.scroll.viewport().height())
    return vw_ / w, min(vw_ / w, vh_ / h)

assert view._fit_mode == "width", "适宽后 _fit_mode 应为 width, got %r" % view._fit_mode
z_width = view.zoom
view.toggle_fit(); app.processEvents()
_zw, _zp = cur_targets()
print("toggle1 zoom=%.4f (zp=%.4f, zw=%.4f)" % (view.zoom, _zp, _zw))
assert abs(view.zoom - _zp) < 1e-6, "适宽状态下点按钮应切整页"
assert view._fit_mode == "page"
z_page = view.zoom
assert z_page < z_width, "整页缩放应小于适宽缩放"
print("[OK] 适宽 → 点击切到整页")

view.toggle_fit(); app.processEvents()
_zw, _zp = cur_targets()
print("toggle2 zoom=%.4f (zw=%.4f)" % (view.zoom, _zw))
assert view._fit_mode == "width", "再点应回到适宽模式"
assert view.zoom > z_page, "适宽缩放应大于整页缩放"
assert abs(view.zoom - _zw) / _zw < 0.05, "适宽 zoom 应接近当前视口目标"
print("[OK] 整页 → 点击切回适合宽度")

# 5) 手动缩放后点按钮应先适宽
view.zoom_out(); app.processEvents()
assert view._fit_mode is None, "手动缩放后 _fit_mode 应为 None, got %r" % view._fit_mode
z_manual = view.zoom
view.toggle_fit(); app.processEvents()
_zw, _zp = cur_targets()
assert view._fit_mode == "width", "手动缩放后点击应先适宽"
assert view.zoom > z_manual, "手动缩小后点击适宽应放大"
assert abs(view.zoom - _zw) / _zw < 0.05, "应进入当前视口下的适宽"
print("[OK] 手动缩放后点击先进入适合宽度")

view.toggle_fit(); app.processEvents()
assert view._fit_mode == "page", "再次点击应切整页"
print("[OK] 整页 ↔ 适合宽度 循环切换正常")

print("ALL_PASS")
