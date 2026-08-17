"""国际化：中文/英文界面切换（默认中文）。"""

_LANG = "zh"

# key: (中文, English)
_STRINGS = {
    # 菜单栏
    "menu_file": ("文件", "File"),
    "menu_edit": ("编辑", "Edit"),
    "menu_tools": ("工具", "Tools"),
    "menu_sign": ("签名", "Signature"),
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
    "fullscreen": ("全屏", "Fullscreen"),
    # 工具
    "delete_page": ("删除当前页", "Delete Page"),
    "merge": ("合并 PDF", "Merge PDF"),
    "split_every": ("每 N 页拆分", "Split Every N"),
    "split_ranges": ("按页码范围拆分", "Split by Ranges"),
    "extract": ("提取指定页", "Extract Pages"),
    "copy_all": ("复制本页全部文字", "Copy Page Text"),
    "image": ("插入图片", "Insert Image"),
    "edit_color": ("编辑颜色", "Edit Color"),
    "sign": ("手写签名", "Signature"),
    "sign_lib": ("签名库", "Signature Library"),
    "about": ("关于", "About"),
    # 主题
    "theme_light": ("浅色", "Light"),
    "theme_dark": ("深色", "Dark"),
    "theme_system": ("跟随系统", "System"),
    # 语言
    "lang_zh": ("中文", "中文"),
    "lang_en": ("English", "English"),
    # 编辑模式
    "view": ("选择", "Select"),
    "text_select": ("选择文字", "Select Text"),
    "replace_text": ("修改文字", "Replace Text"),
    "highlight": ("高亮", "Highlight"),
    "underline": ("下划线", "Underline"),
    "strikeout": ("删除线", "Strikethrough"),
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
    "select_text": ("选取文字", "Select Text"),
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
    "add_watermark": ("添加水印", "Add Watermark"),
    "watermark_text": ("水印文字：", "Watermark Text: "),
    "watermark_rotate": ("旋转角度：", "Rotate: "),
    "watermark_opacity": ("透明度：", "Opacity: "),
    "tiled": ("平铺水印", "Tiled"),
    "watermark_default": ("机密", "CONFIDENTIAL"),
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


def get_lang():
    return _LANG


def tr(key, default=None):
    item = _STRINGS.get(key)
    if item:
        return item[0] if _LANG == "zh" else item[1]
    return default if default is not None else key
