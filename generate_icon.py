"""从选定的高清应用图生成 Windows 多尺寸 icon.ico。"""
import os
import struct
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt, QBuffer, QIODevice, QByteArray


SOURCE_ICON = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "app-icon.png")


def render(size):
    source = QImage(SOURCE_ICON)
    if source.isNull():
        raise FileNotFoundError(f"找不到图标源文件：{SOURCE_ICON}")

    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    scaled = source.scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawImage((size - scaled.width()) // 2,
                (size - scaled.height()) // 2, scaled)
    p.end()
    return img


def to_png_bytes(img):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def build_ico(sizes=(16, 20, 24, 32, 40, 48, 64, 128, 256)):
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
