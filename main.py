"""DO编辑器 程序入口。"""
import os
import sys
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
    win.show()

    # 从命令行打开文档（支持“打开方式”关联）
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.lower().endswith((".pdf", ".docx", ".doc")):
                win.open_file(arg)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
