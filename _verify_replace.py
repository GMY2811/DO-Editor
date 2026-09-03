"""离屏验证：修改文字 → 整页文字行框 → 点击行就地编辑（无弹窗）。"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("APPDATA", os.path.abspath("_verify_appdata"))

from PySide6.QtWidgets import QApplication
import pymupdf

app = QApplication([])
from document_view import DocumentView

view = DocumentView()
assert view.load("sample.pdf"), "load sample failed"
pv = view.page_view

# 1) 进入“修改文字”模式 → 行框铺开
view.set_mode("replace_text")
assert view.current_mode == "replace_text"
assert pv._edit_overlay is True
assert pv.mode() == "point"
lines0 = pv._edit_line_hits(0)
print("page0 editable lines:", len(lines0))
assert lines0, "sample.pdf 第 1 页应有可编辑文字行"
assert "fmt" in lines0[0], "行数据应携带 fmt 格式信息"

# 2) 点击第一行 → 就地打开行内编辑框（无浮动工具条/弹窗）
ln = lines0[0]
old_text = ln["text"]
print("editing line text:", repr(old_text))
view._on_text_line_clicked(0, ln)
app.processEvents()
assert view._row_edit is not None, "点击文字行应在原位置就地打开编辑框"
assert getattr(view, "_inline_box", None) is None, "就地编辑不得再弹出工具条/弹窗"
assert getattr(view, "_inline_edit", None) is None
assert view._row_edit.text() == old_text, "就地编辑框应预填原行文字"
assert view._row_edit_meta is not None

# 3) 就地修改文字并回车提交（真实 _commit_row_edit 路径）
new_text = old_text + "【改】"
view._row_edit.setText(new_text)
view._commit_row_edit(commit=True)      # 等价于 returnPressed 提交
app.processEvents()
assert view._row_edit is None, "提交后编辑框应关闭"
assert getattr(view, "_inline_box", None) is None
assert view.objects and view.objects[-1]["kind"] == "text"
assert view.objects[-1]["text"] == new_text
assert view.can_undo()
print("objects after commit:", len(view.objects))

# 4) 再次进入编辑并 Esc 取消 → 不写回
view._on_text_line_clicked(0, lines0[1] if len(lines0) > 1 else lines0[0])
app.processEvents()
assert view._row_edit is not None
before = len(view.objects)
view._commit_row_edit(commit=False)     # Esc 取消
assert view._row_edit is None
assert len(view.objects) == before, "Esc 取消不应产生撤销记录"

# 5) 点击空白处：不弹编辑框、不报错（未在编辑时给出提示由状态栏承载）
view._on_text_line_clicked(0, None)
assert view._row_edit is None
assert getattr(view, "_inline_box", None) is None

# 6) 保存后再打开，新文字确实写入 PDF
print("new text:", repr(new_text))
import tempfile
out = os.path.join(tempfile.gettempdir(), "_do_verify_out.pdf")
if os.path.exists(out):
    os.remove(out)
view._save_to(out)
re = pymupdf.open(out)
page_text = re[0].get_text()
print("saved page text:", repr(page_text[:300]))
assert new_text in page_text, "保存后 PDF 中应能找到新文字"
re.close()

# 7) 撤销能恢复原样（撤回到编辑前），行框随之退出
assert view.undo()
assert not view.objects
assert pv._edit_overlay is False          # undo 内部切回 view 模式

# 8) 再次进入/退出模式，行编辑状态干净
view.set_mode("replace_text")
assert pv._edit_overlay is True
view.set_mode("view")
assert pv._edit_overlay is False
assert view._row_edit is None
assert view._row_edit_meta is None

# 释放句柄后清理临时文件
view.close_doc()
app.processEvents()
if os.path.exists(out):
    os.remove(out)
print("REPLACE_INPLACE_EDIT_OK")
