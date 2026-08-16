"""生成 DO阅读器 应用图标 icon.ico（文档 + 折角，纯图形无文字）。"""
import os
import struct
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QImage, QPainter, QColor, QPen, QPolygonF
from PySide6.QtCore import Qt, QRectF, QPointF, QBuffer, QIODevice, QByteArray


def render(size):
    s = float(size)
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # 蓝色圆角底
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(37, 99, 235))
    p.drawRoundedRect(QRectF(0, 0, s, s), s * 0.2, s * 0.2)

    # 白色纸张
    page = QRectF(s * 0.22, s * 0.18, s * 0.56, s * 0.64)
    p.setBrush(QColor(255, 255, 255))
    p.drawRoundedRect(page, s * 0.04, s * 0.04)

    # 右上折角（浅蓝三角）
    x0, y0 = page.right(), page.top()
    fold = s * 0.14
    p.setBrush(QColor(191, 219, 254))
    p.drawPolygon(QPolygonF([QPointF(x0 - fold, y0), QPointF(x0, y0 + fold),
                             QPointF(x0, y0)]))

    # 纸张内的灰色文字线
    pen = QPen(QColor(148, 163, 184), max(2, int(s * 0.035)),
               Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    y = s * 0.30
    for _ in range(3):
        p.drawLine(QPointF(s * 0.28, y), QPointF(s * 0.66, y))
        y += s * 0.14
    p.end()
    return img


def to_png_bytes(img):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def build_ico(sizes=(16, 24, 32, 48, 64, 128, 256)):
    images = [(s, to_png_bytes(render(s))) for s in sizes]
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    entries = b""
    blobs = b""
    offset = 6 + 16 * count
    for s, data in images:
        b = s if s < 256 else 0
        entries += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    return header + entries + blobs


if __name__ == "__main__":
    data = build_ico()
    with open("icon.ico", "wb") as f:
        f.write(data)
    print("icon.ico written:", len(data), "bytes")
