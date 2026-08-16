"""DO编辑器 程序入口。"""
import sys
from PySide6.QtWidgets import QApplication
import app_config as cfg
from main_window import MainWindow
from sign_dialog import remove_default_signatures


def main():
    app = QApplication(sys.argv)
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
