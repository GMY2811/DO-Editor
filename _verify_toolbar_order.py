# -*- coding: utf-8 -*-
"""验证快捷按钮栏默认顺序(v4)。"""
import os, sys, tempfile
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings
app = QApplication([])

tmp = tempfile.mkdtemp(prefix="do-editor-order-")
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat,
                  QSettings.Scope.UserScope, tmp)
import app_config as _cfg
_cfg.ORG_NAME = "DOEditorOrderTest"

from main_window import MainWindow

# 场景1：全新无历史设置 → 应显示新默认顺序
win = MainWindow()
tb1 = [a.property("do_key") for a in win.tb1.actions()
       if not a.isSeparator() and a.property("do_key")]
tb2 = [a.property("do_key") for a in win.tb2.actions()
       if not a.isSeparator() and a.property("do_key")]
print("TB1:", tb1)
print("TB2:", tb2)

expect_file = ["save", "sidebar", "fit_width", "slideshow"]
expect_edit = ["text_select", "text", "replace_text", "watermark",
               "sign", "sign_lib",
               "highlight", "underline", "strikeout", "rect", "line",
               "ink", "edit_color", "image", "annotation",
               "ocr_toolbar", "delete_page"]
print("FILE_OK" if tb1 == expect_file else "FILE_FAIL: %s" % tb1)
print("EDIT_OK" if tb2 == expect_edit else "EDIT_FAIL: %s" % tb2)

# 场景2：模拟用户拖动后保存 → 重启应尊重保存顺序
win._save_toolbar_order()
win.close()
win2 = MainWindow()
tb2b = [a.property("do_key") for a in win2.tb2.actions()
        if not a.isSeparator() and a.property("do_key")]
print("RESAVE_KEPT" if tb2b == expect_edit else "RESAVE_FAIL: %s" % tb2b)

# 场景3：v3 旧顺序 + version=3 → 应迁移到新默认
QSettings(_cfg.ORG_NAME, _cfg.APP_NAME).setValue(
    "toolbar_order_version", 3)
QSettings(_cfg.ORG_NAME, _cfg.APP_NAME).setValue(
    "toolbar_order",
    '{"file": ["save","fit_width","sidebar","slideshow"],'
    ' "edit": ["text_select","replace_text","sign","sign_lib",'
    '"highlight","underline","strikeout","rect","line","ink",'
    '"watermark","text","edit_color","image","annotation",'
    '"ocr_toolbar","delete_page"]}')
win2.close()
win3 = MainWindow()
tb1c = [a.property("do_key") for a in win3.tb1.actions()
        if not a.isSeparator() and a.property("do_key")]
tb2c = [a.property("do_key") for a in win3.tb2.actions()
        if not a.isSeparator() and a.property("do_key")]
print("V3_MIGRATE_FILE" +
      ("_OK" if tb1c == expect_file else "_FAIL: %s" % tb1c))
print("V3_MIGRATE_EDIT" +
      ("_OK" if tb2c == expect_edit else "_FAIL: %s" % tb2c))
print("DONE")
