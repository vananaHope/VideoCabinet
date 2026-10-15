"""빌드 입력을 준비한다. 버전 override는 Release DryRun 전용이며 소스는 바꾸지 않는다."""
import argparse
import json
from pathlib import Path
import struct

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPolygon
from PySide6.QtCore import QPoint

from bundle_ffmpeg import prepare_bundle
from my_video_manager.web_tokens import web_tokens


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = root / 'build/bundle-assets'
    target.mkdir(parents=True, exist_ok=True)
    (target / 'build-version.txt').write_text(args.version, encoding='utf-8')
    tools = target / 'ffmpeg'
    prepare_bundle(tools)
    # 기존 재생 삼각형 아이콘을 공유 색 토큰으로 그린다. ICO 안의 PNG는 Windows가 지원한다.
    colors = web_tokens()['colors']
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(colors['background']))
    painter.drawRoundedRect(0, 0, 256, 256, 48, 48)
    painter.setBrush(QColor(colors['primary']))
    painter.drawPolygon(QPolygon([QPoint(90, 60), QPoint(200, 128), QPoint(90, 196)]))
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    png = bytes(buffer.data())
    (target / 'app.ico').write_bytes(struct.pack('<HHHBBBBHHII', 0, 1, 1, 0, 0, 0, 0, 1, 32, len(png), 22) + png)
    print(json.dumps({'version': args.version, 'assets': str(target)}))


if __name__ == '__main__':
    main()
