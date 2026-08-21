# -*- mode: python ; coding: utf-8 -*-
# DO编辑器 精简打包配置（onedir 模式，剔除无用模块与 DLL 以减小体积）
import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

_ocr_datas = collect_data_files('rapidocr')
_ocr_binaries = collect_dynamic_libs('onnxruntime')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_ocr_binaries,
    datas=[
        ('icon.ico', '.'),
        ('app-icon.png', '.'),
        ('assets/reward_qr.png', 'assets'),
    ] + _ocr_datas,
    hiddenimports=[
        'win32com', 'win32com.client', 'pythoncom', 'pywintypes',
        'win32api', 'win32gui',
        'rapidocr', 'onnxruntime',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PySide6.QtNetwork', 'PySide6.QtSvg', 'PySide6.QtOpenGL',
        'tkinter', 'unittest', 'pydoc', 'doctest', 'pdb', 'test', 'tests',
        'pythonwin', 'win32ui', 'pywin.framework', 'pywin.dialogs', 'pywin.mfc',
    ],
    noarchive=False,
    optimize=1,
)

# 剔除用不到的 Qt DLL 与插件（软件 OpenGL 渲染器、网络、SVG、多余平台插件）
_DROP = {
    'opengl32sw.dll', 'qt6network.dll', 'qt6svg.dll',
    'qsvg.dll', 'qsvgicon.dll', 'qdirect2d.dll', 'qminimal.dll',
    'win32ui.pyd', 'win32trace.pyd',
}
a.binaries = [b for b in a.binaries
              if os.path.basename(b[0]).lower() not in _DROP]

# 只保留中英文的 Qt 翻译文件，砍掉其余语言（约省 6MB）
def _keep_qm(src):
    base = os.path.basename(src).lower()
    return ('zh' in base) or ('en' in base)

a.datas = [d for d in a.datas
           if not (d[0].endswith('.qm') and not _keep_qm(d[0]))]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DO编辑器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
    icon=['icon.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='DO编辑器',
)
