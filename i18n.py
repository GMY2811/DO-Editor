"""国际化：中文/英文界面切换（默认中文）。"""

_LANG = "zh"
_QT_TRANSLATOR = None

# key: (中文, English)
_STRINGS = {
    "app_name": ("DO编辑器", "DO Editor"),
    "untitled": ("未命名", "Untitled"),
    "pages": ("页面", "Pages"),
    "page_status": ("第 {p} / {t} 页", "Page {p} / {t}"),
    "start_open": ("打开文档", "Open Document"),
    "start_hint": ("支持 PDF、DOCX、DOC  ·  Ctrl+O 快速打开",
                   "PDF, DOCX and DOC supported  ·  Ctrl+O to open"),
    # 菜单栏
    "menu_file": ("文件", "File"),
    "menu_edit": ("编辑", "Edit"),
    "menu_tools": ("工具", "Tools"),
    "menu_sign": ("安全", "Security"),
    "menu_view": ("视图", "View"),
    "menu_theme": ("主题", "Theme"),
    "menu_lang": ("语言", "Language"),
    "menu_help": ("帮助", "Help"),
    # 文件
    "open": ("打开", "Open"),
    "save": ("保存", "Save"),
    "save_as": ("另存为", "Save As"),
    "print": ("打印", "Print"),
    "close": ("关闭标签页", "Close Tab"),
    "exit": ("退出", "Exit"),
    # 视图
    "zoom_in": ("放大", "Zoom In"),
    "zoom_out": ("缩小", "Zoom Out"),
    "fit_width": ("适合宽度", "Fit Width"),
    "sidebar": ("侧边栏", "Sidebar"),
    "sidebar_default": ("启动时显示侧边栏", "Show Sidebar by Default"),
    "fullscreen": ("全屏", "Fullscreen"),
    "more_tools": ("更多工具", "More Tools"),
    "slideshow": ("幻灯片", "Slideshow"),
    "slideshow_open_first": ("请先打开 PDF 文件", "Open a PDF file first"),
    # 工具
    "delete_page": ("删除当前页", "Delete Page"),
    "delete_this_page": ("删除本页", "Delete This Page"),
    "delete_selected_pages": ("删除所选页", "Delete Selected Pages"),
    "delete_selected_pages_confirm": ("确定删除所选的 {n} 页吗？", "Delete the {n} selected pages?"),
    "keep_one_page": ("文档至少需要保留一页，无法删除全部页面", "A document must keep at least one page."),
    "merge": ("合并 PDF", "Merge PDF"),
    "split_every": ("每 N 页拆分", "Split Every N"),
    "split_ranges": ("按页码范围拆分", "Split by Ranges"),
    "extract": ("提取指定页", "Extract Pages"),
    "copy_all": ("复制本页全部文字", "Copy Page Text"),
    "undo": ("撤销", "Undo"),
    "undo_done": ("已撤销上一步操作", "Last action undone"),
    "nothing_to_undo": ("没有可撤销的操作", "Nothing to undo"),
    "undo_failed": ("撤销失败：", "Undo failed:"),
    "image": ("插入图片", "Insert Image"),
    "edit_color": ("编辑颜色", "Edit Color"),
    "sign": ("签名设计", "Signature Design"),
    "sign_lib": ("签名库", "Signature Library"),
    "about": ("关于", "About"),
    "about_title": ("关于 {app}", "About {app}"),
    "about_version": ("版本 {version}", "Version {version}"),
    "about_summary": ("轻巧、专注的 PDF 阅读与编辑工具", "A lightweight, focused PDF reader and editor"),
    "about_developer": ("开发者", "Developer"),
    "about_email": ("联系邮箱", "Email"),
    "about_framework": ("技术框架", "Framework"),
    "dialog_close": ("关闭", "Close"),
    # 主题
    "theme_light": ("浅色", "Light"),
    "theme_dark": ("深色", "Dark"),
    "theme_system": ("跟随系统", "System"),
    # 语言
    "lang_zh": ("中文", "中文"),
    "lang_en": ("English", "English"),
    # 编辑模式
    "view": ("选择", "Select"),
    "text_select": ("快捷复制", "Quick Copy"),
    "replace_text": ("修改文字", "Replace Text"),
    "highlight": ("高亮", "Highlight"),
    "underline": ("下划线", "Underline"),
    "strikeout": ("删除线", "Strikethrough"),
    "annotation": ("批注", "Comment"),
    "annotation_title": ("添加批注", "Add Comment"),
    "annotation_prompt": ("请输入批注内容：", "Enter comment text:"),
    "annotation_place": ("请在页面上点击批注位置", "Click the page to place the comment"),
    "edit_annotation": ("编辑批注", "Edit Comment"),
    "rect": ("矩形", "Rectangle"),
    "line": ("直线", "Line"),
    "ink": ("手绘", "Ink"),
    "text": ("文本", "Text"),
    # 搜索
    "search_placeholder": ("搜索文字…", "Search text…"),
    "search": ("搜索", "Search"),
    "search_prev": ("上一条", "Previous"),
    "search_next": ("下一条", "Next"),
    # 关闭确认
    "discard": ("不保存", "Don't Save"),
    "unsaved_changes": ("文档有未保存的修改，是否保存？", "The document has unsaved changes. Save?"),
    "unsaved_changes_file": ("「{f}」有未保存的修改，是否保存？", "\"{f}\" has unsaved changes. Save?"),
    "hint": ("提示", "Info"),
    # 右键菜单
    "copy_selected": ("复制所选文字", "Copy Selection"),
    "select_text": ("快捷复制", "Quick Copy"),
    "copy_page": ("复制本页全部文字", "Copy Page Text"),
    "paste_text": ("粘贴文字", "Paste Text"),
    "edit_text": ("编辑文字", "Edit Text"),
    "change_color": ("更改颜色", "Change Color"),
    "delete_object": ("删除选中的对象", "Delete Selected"),
    "cancel_place": ("取消放置", "Cancel Placement"),
    "fit_width2": ("适合宽度", "Fit Width"),
    # 页面
    "page_of": ("第 {p} / {t} 页", "Page {p} / {t}"),
    # 修改文字对话框
    "new_text": ("新文字：", "New Text: "),
    "font_family": ("字体：", "Font: "),
    "font_size": ("字号：", "Font Size: "),
    "bold": ("加粗", "Bold"),
    "italic": ("斜体", "Italic"),
    # 水印
    "watermark": ("添加水印", "Add Watermark"),
    "add_watermark": ("添加水印", "Add Watermark"),
    "watermark_text": ("水印文字：", "Watermark Text: "),
    "watermark_rotate": ("旋转角度：", "Rotate: "),
    "watermark_opacity": ("透明度：", "Opacity: "),
    "tiled": ("平铺水印", "Tiled"),
    "watermark_default": ("机密", "CONFIDENTIAL"),
    "watermark_empty": ("水印文字不能为空", "Watermark text cannot be empty."),
    "watermark_added": ("已添加水印", "Watermark added"),
    # OCR
    "menu_ocr": ("OCR 文字识别", "OCR Text Recognition"),
    "ocr_current": ("识别当前页面", "Recognize Current Page"),
    "ocr_all": ("识别全部页面", "Recognize All Pages"),
    "ocr_toolbar": ("OCR识别", "OCR"),
    "ocr_progress": ("正在识别第 {p} / {t} 页…", "Recognizing page {p} / {t}…"),
    # PDF 安全
    "menu_security": ("PDF 安全", "PDF Security"),
    "security_set": ("设置密码", "Set Password"),
    "security_remove": ("删除密码", "Remove Password"),
    "security_status": ("查看加密状态", "Encryption Status"),
    # 签名
    "sign_title": ("签名", "Signature"),
    "text_sign": ("文字签名", "Text Signature"),
    "gen_text_sign": ("生成文字签名", "Generate"),
    "import_image": ("导入图片", "Import Image"),
    "clear": ("清空", "Clear"),
    "save_to_lib": ("保存到签名库", "Save to Library"),
    "confirm": ("确定", "OK"),
    "cancel": ("取消", "Cancel"),
    "pen_width": ("笔触粗细：", "Pen Width: "),
    "color": ("颜色：", "Color: "),
    "sign_lib_title": ("签名库", "Signature Library"),
    "delete_selected": ("删除选中", "Delete"),
    "use": ("使用", "Use"),
    "text_sign_placeholder": ("输入文字签名，如 BOSL TRUCKING", "Enter text, e.g. BOSL TRUCKING"),
}


def set_lang(lang):
    global _LANG
    _LANG = lang if lang in ("zh", "en") else "zh"
    _sync_qt_translator()


def _sync_qt_translator():
    """让 QColorDialog 等 Qt 标准界面跟随软件的中英文设置。"""
    global _QT_TRANSLATOR
    try:
        from PySide6.QtCore import (QCoreApplication, QLibraryInfo,
                                    QTranslator)
        app = QCoreApplication.instance()
        if app is None:
            return
        if _QT_TRANSLATOR is not None:
            app.removeTranslator(_QT_TRANSLATOR)
            _QT_TRANSLATOR = None
        if _LANG == "zh":
            translator = QTranslator(app)
            translations_path = QLibraryInfo.path(
                QLibraryInfo.LibraryPath.TranslationsPath)
            if translator.load("qtbase_zh_CN", translations_path):
                app.installTranslator(translator)
                # 必须持有引用，否则 Python 回收后标准界面会恢复英文。
                _QT_TRANSLATOR = translator
    except Exception:
        # 缺少可选翻译文件时不影响程序主体启动。
        _QT_TRANSLATOR = None


def get_lang():
    return _LANG


def tr(key, default=None):
    item = _STRINGS.get(key)
    if item:
        return item[0] if _LANG == "zh" else item[1]
    return default if default is not None else key
