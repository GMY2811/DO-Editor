import os, tempfile, traceback
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['APPDATA'] = tempfile.mkdtemp()
import app_config as _cfg; _cfg.ORG_NAME = 'DOEditorAlphaSaveTest'
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
from PySide6.QtCore import QRectF
app = QApplication([])
import pymupdf
from sign_dialog import qimage_to_png_bytes
tmp_dir = tempfile.mkdtemp()
pdf = os.path.join(tmp_dir, 't.pdf')
img = QImage(200, 100, QImage.Format.Format_ARGB32)
img.fill(QColor(255, 0, 0, 255))
from document_view import DocumentView
v = DocumentView(); v.resize(1000, 700)
print('load:', v.load(pdf), flush=True)
v.objects.append({'id': 1, 'page': 0, 'rect': QRectF(50, 50, 200, 100),
                  'img': img, 'png': qimage_to_png_bytes(img),
                  'kind': 'image', 'opacity': 0.5})
v.begin_undo_step(document_change=True)
v._render_objects_to_doc()
v.modified = True
v._save_to(pdf)
d = pymupdf.open(pdf)
page = d[0]
pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
cx, cy = pix.width//2, pix.height//2
idx = cy * pix.stride + cx * pix.n
if pix.n >= 4:
    print('alpha:', pix.samples[idx+3], flush=True)
else:
    print('红:', pix.samples[idx], flush=True)
print('OK', flush=True)
