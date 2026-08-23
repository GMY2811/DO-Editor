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
    "outline": ("目录", "Contents"),
    "outline_empty": ("（此 PDF 没有自带目录）", "(This PDF has no built-in outline)"),
    "outline_page": ("第 {p} 页", "p. {p}"),
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
    "watermark_type": ("水印类型：", "Watermark Type: "),
    "watermark_type_text": ("文字水印", "Text Watermark"),
    "watermark_type_image": ("图片水印", "Image Watermark"),
    "watermark_image": ("选择图片…", "Choose Image…"),
    "watermark_image_label": ("水印图片：", "Watermark Image: "),
    "watermark_scale": ("大小(占页宽)：", "Size (% of page width): "),
    "watermark_image_empty": ("请先选择水印图片", "Please choose a watermark image first."),
    "watermark_image_invalid": ("无法读取该图片", "Cannot read this image."),
    "edit_image": ("编辑图片", "Edit Image"),
    "image_width": ("宽度：", "Width: "),
    "image_edited": ("图片已更新", "Image updated"),
    "paste_text_done": ("已在第 {p} 页粘贴文字", "Pasted text on page {p}"),
    "note_added": ("已在第 {p} 页添加批注，可拖动调整位置",
                   "Note added on page {p}, drag to move"),
    "note_updated": ("批注内容已更新", "Note updated"),
    "image_inserted": ("已在第 {p} 页插入图片", "Image inserted on page {p}"),
    "image_read_failed": ("无法读取该图片", "Cannot read this image"),
    "need_open_pdf": ("请先打开一个 PDF 文件", "Please open a PDF file first"),
    "print_settings": ("打印设置", "Print Settings"),
    "print_orientation": ("方向：", "Orientation: "),
    "orientation_auto": ("自动", "Auto"),
    "orientation_portrait": ("纵向", "Portrait"),
    "orientation_landscape": ("横向", "Landscape"),
    "print_scale": ("缩放：", "Scale: "),
    "print_scale_mode": ("缩放：", "Scale: "),
    "scale_fit": ("适合页面", "Fit to page"),
    "scale_actual": ("实际大小", "Actual size"),
    "scale_custom": ("自定义", "Custom"),
    "print_copies": ("份数：", "Copies: "),
    "print_job_sent": ("已发送打印任务", "Print job sent"),
    "print_failed": ("无法启动打印", "Failed to start printing"),
    "print_dialog_title": ("打印", "Print"),
    "print_printer": ("打印机：", "Printer: "),
    "print_to_pdf": ("打印到 PDF", "Print to PDF"),
    "print_default": ("默认打印机", "Default printer"),
    "print_paper": ("纸张：", "Paper: "),
    "print_range": ("范围：", "Range: "),
    "print_all": ("全部", "All"),
    "print_current": ("当前页", "Current"),
    "print_pages": ("页面", "Pages"),
    "print_page_from": ("从", "From"),
    "print_page_to": ("至", "To"),
    "print_pages_per_sheet": ("排版：", "Layout: "),
    "print_pps_1": ("1 页/张", "1 per sheet"),
    "print_pps_2": ("2 页/张", "2 per sheet"),
    "print_pps_4": ("4 页/张", "4 per sheet"),
    "print_align": ("页面位置：", "Page position: "),
    "align_center": ("居中", "Center"),
    "align_top_left": ("左上", "Top left"),
    "align_top_right": ("右上", "Top right"),
    "align_bottom_left": ("左下", "Bottom left"),
    "align_bottom_right": ("右下", "Bottom right"),
    "print_properties": ("属性", "Properties"),
    "print_advanced": ("高级", "Advanced"),
    "print_help": ("帮助", "Help"),
    "print_grayscale": ("以灰度(黑白) 打印", "Print in grayscale"),
    "print_save_ink": ("节省墨水/墨粉", "Save ink/toner"),
    "print_pages_to_print": ("要打印的页面", "Pages to print"),
    "print_more_options": ("更多选项", "More options"),
    "print_reverse_order": ("逆序打印", "Reverse order"),
    "print_collate": ("自动分页", "Collate"),
    "print_adjust_group": ("调整页面大小和处理页面", "Page size & handling"),
    "print_tab_size": ("大小", "Size"),
    "print_tab_nup": ("多页", "Multiple"),
    "print_tab_poster": ("海报", "Poster"),
    "print_tab_booklet": ("小册子", "Booklet"),
    "print_nup_label": ("每张纸页数", "Pages per sheet"),
    "print_shrink_large": ("缩小过大的页面", "Shrink oversized pages"),
    "print_pdf_paper_source": ("按照 PDF 页面大小选择纸张来源",
                                "Choose paper source by PDF page size"),
    "print_align": ("位置：", "Position: "),
    "print_position": ("位置：", "Position: "),
    "position_center": ("居中", "Center"),
    "position_top_center": ("靠上居中", "Top center"),
    "position_bottom_center": ("靠下居中", "Bottom center"),
    "print_poster_hint": ("将一页放大打印到多张纸上，拼接后形成海报。",
                          "Print one page across multiple sheets to assemble a poster."),
    "print_poster_split": ("分割份数", "Split into"),
    "print_booklet_hint": ("小册子模式：将文档装订成册（暂未实现）。",
                           "Booklet mode: print as booklet (not yet implemented)."),
    "print_comments_forms": ("注释和表单", "Comments & Forms"),
    "print_ann_doc_mark": ("文档和标记", "Document and marks"),
    "print_ann_doc": ("仅文档", "Document only"),
    "print_ann_mark": ("仅标记", "Marks only"),
    "print_ann_none": ("无", "None"),
    "print_summarize_comments": ("小结注释", "Summarize comments"),
    "print_page_setup": ("页面设置...", "Page Setup..."),
    "print_page_label": ("第", "Page"),
    "print_preview_title": ("打印预览", "Print Preview"),
    "print_pos_label": ("位置：", "Position: "),
    "print_scale_label": ("缩放：", "Scale: "),
    "print_preview_page_label": ("预览页", "Preview page"),
    "print_paper_label": ("纸张：", "Paper: "),
    "print_pps_suffix": ("页/张", "per sheet"),
    "insert_pdf_file": ("插入 PDF 文件…", "Insert PDF file..."),
    "insert_pdf_to_end": ("插入 PDF 到文档末尾…", "Insert PDF at end..."),
    "move_up": ("上移一页", "Move up"),
    "move_down": ("下移一页", "Move down"),
    "insert_empty": ("该 PDF 没有可插入的页面", "The PDF has no pages to insert"),
    "insert_done": ("已插入", "Inserted"),
    "insert_pages_hint": ("页", "pages"),
    "print_orient_label": ("方向：", "Orientation: "),
    "print_orient_portrait": ("纵向", "Portrait"),
    "print_orient_landscape": ("横向", "Landscape"),
    "print_orient_auto": ("自动", "Auto"),
    "print_rotate": ("旋转：", "Rotate: "),
    "print_color_mode": ("颜色：", "Color: "),
    "print_color_color": ("彩色", "Color"),
    "print_color_gray": ("黑白", "Grayscale"),
    "print_custom": ("自定义", "Custom"),
    "print_preview_page": ("预览页：", "Preview page: "),
    "print": ("打印", "Print"),
    "image_file_filter": ("图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.webp)",
                          "Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.webp)"),
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
    "delete": ("删除", "Delete"),
    "use": ("使用", "Use"),
    "text_sign_placeholder": ("输入文字签名，如 BOSL TRUCKING", "Enter text, e.g. BOSL TRUCKING"),
    # 打赏作者
    "reward_title": ("支持作者", "Support the Author"),
    "reward_message": ("感谢您使用DO编辑器!\n如用的顺手，可请作者喝杯咖啡。",
                       "Thanks for using DO Editor!\nIf it helps, buy the author a coffee."),
    "reward_dont_show": ("以后不再弹出", "Don't show this again"),
    "reward_close": ("好的", "OK"),
    "reward_image_missing": ("赞赏码图片缺失", "Reward QR image missing"),
    "star_us": ("给个 Star", "Star Us"),
    "feedback": ("反馈建议", "Send Feedback"),
    "check_update": ("检查更新", "Check for Updates"),
    "update_available": ("发现新版本 {ver}", "New version available: {ver}"),
    "update_dialog_title": ("软件更新", "Update"),
    "update_checking": ("正在检查更新…", "Checking for updates…"),
    "update_none": ("已是最新版本", "You are up to date"),
    "update_failed": ("检查更新失败：{err}", "Update check failed: {err}"),
    "update_open_release": ("前往下载", "Open Release"),
    "update_later": ("稍后", "Later"),
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
