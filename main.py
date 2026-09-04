"""DO编辑器 程序入口。"""
import os
import sys
import faulthandler

# 崩溃诊断：段错误/原生异常时把调用栈写入日志文件。
# all_threads=True 覆盖渲染等工作线程（GUI 崩在子线程默认抓不到）。
_FAULT_LOG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_crash_trace.log")
try:
    with open(_FAULT_LOG, "a", encoding="utf-8") as _f:
        _f.write("\n===== %s =====\n" % __import__("time").strftime("%Y-%m-%d %H:%M:%S"))
    _fh = open(_FAULT_LOG, "a", encoding="utf-8")
    faulthandler.enable(file=_fh, all_threads=True)
except Exception:
    pass

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication
import app_config as cfg
from main_window import MainWindow
from sign_dialog import remove_default_signatures


def main():
    # 使用 Qt FreeType 灰阶渲染，避免 Windows ClearType 在浅色背景和
    # 分数缩放下产生彩边、断笔。保留测试环境显式指定的平台插件。
    if sys.platform == "win32" and os.environ.get("QT_QPA_PLATFORM", "") in ("", "windows"):
        os.environ["QT_QPA_PLATFORM"] = "windows:fontengine=freetype"
    app = QApplication(sys.argv)
    # 分数缩放下只约束垂直方向：完整 Hinting 会把中文横向笔画强行
    # 对齐到像素网格，容易出现残缺、粘连和粗细不均。
    ui_font = QFont("Microsoft YaHei UI", 10)
    ui_font.setHintingPreference(QFont.HintingPreference.PreferVerticalHinting)
    ui_font.setStyleStrategy(
        QFont.StyleStrategy.PreferAntialias |
        QFont.StyleStrategy.NoSubpixelAntialias)
    ui_font.setKerning(True)
    app.setFont(ui_font)
    app.setApplicationName(cfg.APP_NAME)
    app.setApplicationVersion(cfg.APP_VERSION)
    app.setOrganizationName(cfg.ORG_NAME)
    remove_default_signatures()
    win = MainWindow()

    # 从命令行打开文档（支持“打开方式”关联）。
    # 在窗口显示前加载：方向调整直接生效，窗口首次出现即目标形态，
    # 避免先显示横屏默认窗口再切换成竖屏的瞬间跳变。
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.lower().endswith((".pdf", ".docx", ".doc")):
                win.open_file(arg)
    win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
