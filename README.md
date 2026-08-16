# DO编辑器（DO Editor）

[![Download](https://img.shields.io/badge/Download-v2.2.3-0a84ff?style=for-the-badge&logo=github)](https://github.com/GMY2811/DO-Editor/releases/download/v2.2.3/DO-Editor-Setup-v2.2.3.exe)
[![Release](https://img.shields.io/github/v/release/GMY2811/DO-Editor?style=for-the-badge&logo=github)](https://github.com/GMY2811/DO-Editor/releases/latest)
[![License](https://img.shields.io/badge/License-AGPL--3.0-blue?style=for-the-badge)](LICENSE)

[English](README_EN.md)

一款面向 Windows 的轻量 PDF 阅读与编辑工具，基于 Python + PySide6 + PyMuPDF 构建。支持阅读、标注、合并、拆分、签名、水印等常用 PDF 操作，并可读取 Word 文档。

开发者：RAY <gmy.2811@gmail.com>

## 下载安装（推荐）

**Windows 用户无需安装 Python，直接下载安装包即可使用。**

前往 [Releases](../../releases) 页面，下载最新版本的 `DO编辑器-Setup-v*.exe` 安装程序，双击安装即可。

- 支持 Windows 10 / 11
- 安装包约 35MB，安装后磁盘占用约 105MB
- 安装时可选「将 PDF 文件关联到 DO编辑器」
- 自带卸载程序（控制面板或开始菜单均可卸载）

### 从源码运行（开发者）

需 Python 3.9+，安装依赖后运行：

```bash
pip install PySide6 PyMuPDF pywin32
python main.py
```

## 功能

- **阅读**：连续滚动、缩放、翻页、书签目录、缩略图侧栏、多标签页、全屏纯净模式
- **编辑**：高亮、下划线、删除线、矩形、直线、手绘、文本（字体/字号/颜色）、修改文字、插入图片
- **合并 / 拆分**：多文件合并、按页码/每 N 页拆分、提取指定页
- **签名**：手写签名、文字签名、签名库（保存/调用）
- **水印**：文字水印（字号/颜色/透明度/旋转/平铺）
- **复制 / 搜索**：滑动选取文字复制、Ctrl+C/Ctrl+V、搜索高亮定位
- **读取 Word**：借助本机 Microsoft Word 把 .docx/.doc 转为 PDF 查看
- **多语言**：中文 / English 界面切换
- **打印**：逐页打印

## 技术栈

- [PySide6](https://pypi.org/project/PySide6/)（Qt 界面）
- [PyMuPDF](https://pypi.org/project/PyMuPDF/)（PDF 渲染与编辑核心）
- [pywin32](https://pypi.org/project/pywin32/)（Word 转换，可选）

## 打包

```bash
# 打包成 onedir
python -m PyInstaller --noconfirm "DO编辑器.spec"

# 用 Inno Setup 编译安装程序（可选，需安装 Inno Setup 6）
ISCC.exe installer.iss
```

## 目录结构

```
main.py          程序入口
main_window.py   主窗口（多标签页、工具栏、菜单）
document_view.py 单文档视图（连续滚动、编辑逻辑）
page_view.py     页面画布（渲染、选择、标注交互）
backend.py       PDF 核心逻辑（渲染/合并/拆分/标注/水印/Word 转换）
sign_dialog.py   签名画板、签名库
i18n.py          中英文切换
theme.py         浅色/深色主题
icons.py         矢量图标
```

## 许可证

本项目采用 **GNU Affero General Public License v3.0（AGPL-3.0）** 许可。

> 核心引擎 MuPDF 采用 AGPL 协议，因此本项目同样以 AGPL-3.0 开源。
> 个人及内部使用免费；如需闭源商业分发，请联系 Artifex 购买 MuPDF 商业授权。
