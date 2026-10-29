"""앱 아이콘 원본(assets/icon)에서 ICO·웹 이미지·출처 매니페스트를 만들고, 산출물만 읽어 검사한다.

    python scripts/app_icon.py           원본에서 산출물을 다시 만든다.
    python scripts/app_icon.py --check   산출물이 최신이고 픽셀 규칙을 지키는지 확인한다.

산출물은 저장소에 커밋한다. 벡터 렌더링 결과가 PySide6 버전에 묶여 PC마다 다시 만들면 흔들릴 수 있고,
개발 실행(src/my_video_manager/app.ico)과 웹 빌드(frontend/src/assets/app-icon.png)가 같은 파일을 바로 읽어야 해서다.
낡음은 파일 수정 시각이 아니라 매니페스트에 적은 원본 내용 해시로 판정한다(git checkout이 시각을 바꾼다).
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import sys

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORY = 'assets/icon'
VECTOR_SOURCE = f'{SOURCE_DIRECTORY}/app-icon.svg'
MANIFEST = f'{SOURCE_DIRECTORY}/build-manifest.json'
ICO = 'src/my_video_manager/app.ico'
WEB_IMAGE = 'frontend/src/assets/app-icon.png'
WEB_IMAGE_SIZE = 128  # 설정의 버전 정보 구역 40px을 화면 배율 300%까지 줄여서만 보인다.
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 256)
# 작업 표시줄·트레이·창 모서리 크기. 벡터를 그대로 줄이지 않고 픽셀에 맞춰 손본 PNG를 원본으로 쓴다.
TUNED_SIZES = (16, 20, 24, 32)

# Windows 11 기본 작업 표시줄 색.
TASKBAR_BACKGROUNDS = {'밝은': '#f3f3f3', '어두운': '#202020'}
MIN_CONTRAST = 3.0
# 실루엣 가장자리 띠(바깥 1px, 32px은 2px)의 불투명 픽셀 중 배경과 3:1 이상인 비율의 하한.
# 둥근 모서리 몇 픽셀이 빠져도 윤곽이 끊김 없이 읽히는 정도다. 손본 원본은 모두 100%다.
MIN_EDGE_CONTRAST_SHARE = 0.9
# 보이는 픽셀 중 반투명(0<alpha<255) 픽셀 비율의 상한. 손본 원본은 0%이고, 벡터를 그대로 16px로 줄이면
# 둥근 모서리만으로 이 값을 넘는다. 가장자리가 번진(흐린) 아이콘을 막는다.
MAX_SEMITRANSPARENT_SHARE = 0.02
# 글자 마크(판과 3:1 이상 구별되는 안쪽 픽셀)가 캔버스에서 차지하는 비율. 너무 작으면 안 보이고 크면 덩어리다.
MARK_SHARE_RANGE = (0.12, 0.45)
# 실루엣(alpha 합)이 캔버스에서 차지하는 비율의 하한.
MIN_SILHOUETTE_SHARE = 0.5
# 다른 프레임을 Qt로 늘이거나 줄인 결과와 채널 차이가 이 값 이하인 픽셀이 전부면 그 프레임을 복사본으로 본다.
SCALED_COPY_TOLERANCE = 2

_PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def source_for(size):
    return f'{SOURCE_DIRECTORY}/app-icon-{size}.png' if size in TUNED_SIZES else VECTOR_SOURCE


def content_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rgba(image):
    return image.convertToFormat(QImage.Format.Format_RGBA8888)


def pixel_digest(image):
    image = rgba(image)
    return hashlib.sha256(f'{image.width()}x{image.height()}:'.encode() + _pixels(image)).hexdigest()


def _pixels(image):
    return bytes(image.constBits())[:image.sizeInBytes()]


def read_png(path):
    image = QImage(str(path))
    if image.isNull():
        raise ValueError(f'이미지를 읽지 못했습니다: {path}')
    return rgba(image)


def render_vector(path, size):
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        raise ValueError(f'SVG를 읽지 못했습니다: {path}')
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return rgba(image)


def _png_bytes(image):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    rgba(image).save(buffer, 'PNG')
    return bytes(data)


def encode_ico(frames):
    """256px은 PNG, 그보다 작은 크기는 설치 프로그램·실행 파일 리소스가 모두 읽는 32비트 BMP로 넣는다."""
    images = []
    for size in sorted(frames):
        image = rgba(frames[size])
        if size >= 256:
            images.append(_png_bytes(image))
            continue
        pixels = _pixels(image)
        stride = size * 4
        rows = [pixels[y * stride:(y + 1) * stride] for y in reversed(range(size))]
        color = b''.join(bytes(row[i + j] for i in range(0, stride, 4) for j in (2, 1, 0, 3)) for row in rows)
        mask_stride = (size + 31) // 32 * 4
        mask = b''
        for row in rows:
            bits = bytearray(mask_stride)
            for x in range(size):
                if row[x * 4 + 3] == 0:
                    bits[x // 8] |= 0x80 >> (x % 8)
            mask += bytes(bits)
        header = struct.pack('<IiiHHIIiiII', 40, size, size * 2, 1, 32, 0, len(color) + len(mask), 0, 0, 0, 0)
        images.append(header + color + mask)
    offset = 6 + 16 * len(images)
    directory = struct.pack('<HHH', 0, 1, len(images))
    for size, data in zip(sorted(frames), images):
        side = 0 if size >= 256 else size
        directory += struct.pack('<BBBBHHII', side, side, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return directory + b''.join(images)


def decode_ico(data):
    """ICO의 각 프레임을 크기별 RGBA 이미지로 읽는다. 같은 크기가 둘이면 거부한다."""
    reserved, kind, count = struct.unpack_from('<HHH', data)
    if reserved != 0 or kind != 1:
        raise ValueError('ICO 파일이 아닙니다')
    frames = {}
    for index in range(count):
        width, height, _, _, _, bits, length, offset = struct.unpack_from('<BBBBHHII', data, 6 + 16 * index)
        size = width or 256
        payload = data[offset:offset + length]
        if size in frames:
            raise ValueError(f'ICO에 {size}px 프레임이 둘 있습니다')
        if payload.startswith(_PNG_SIGNATURE):
            image = QImage.fromData(payload, 'PNG')
            if image.isNull():
                raise ValueError(f'{size}px PNG 프레임을 읽지 못했습니다')
            frames[size] = rgba(image)
            continue
        _, dib_width, dib_height, _, dib_bits = struct.unpack_from('<IiiHH', payload)
        if (dib_width, dib_height, dib_bits) != (size, size * 2, 32) or bits != 32:
            raise ValueError(f'{size}px 프레임이 32비트 BMP가 아닙니다')
        stride = size * 4
        color = payload[40:40 + stride * size]
        rows = [color[y * stride:(y + 1) * stride] for y in reversed(range(size))]
        pixels = b''.join(bytes(row[i + j] for i in range(0, stride, 4) for j in (2, 1, 0, 3)) for row in rows)
        frames[size] = QImage(pixels, size, size, stride, QImage.Format.Format_RGBA8888).copy()
    return frames


def build_frames(root=ROOT):
    return {size: (read_png(root / source_for(size)) if size in TUNED_SIZES else
                   render_vector(root / VECTOR_SOURCE, size)) for size in ICON_SIZES}


def build(root=ROOT):
    frames = build_frames(root)
    web = render_vector(root / VECTOR_SOURCE, WEB_IMAGE_SIZE)
    (root / ICO).write_bytes(encode_ico(frames))
    (root / WEB_IMAGE).parent.mkdir(parents=True, exist_ok=True)
    (root / WEB_IMAGE).write_bytes(_png_bytes(web))
    manifest = {
        'frames': {str(size): {'source': source_for(size), 'source_sha256': content_digest(root / source_for(size)),
                               'pixels_sha256': pixel_digest(image)} for size, image in frames.items()},
        'web': {'path': WEB_IMAGE, 'size': WEB_IMAGE_SIZE, 'source': VECTOR_SOURCE,
                'source_sha256': content_digest(root / VECTOR_SOURCE), 'pixels_sha256': pixel_digest(web)},
    }
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return manifest


def relative_luminance(color):
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(color[0]) + 0.7152 * channel(color[1]) + 0.0722 * channel(color[2])


def contrast(first, second):
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _grid(image):
    image = rgba(image)
    size = image.width()
    data = _pixels(image)
    return size, [[tuple(data[(y * size + x) * 4:(y * size + x) * 4 + 4]) for x in range(size)] for y in range(size)]


def edge_band(size, pixels, width):
    """실루엣 바깥쪽 width px의 불투명 픽셀. 캔버스 밖과 덜 불투명한 픽셀을 바깥으로 보고 8방향으로 깎아 낸다."""
    remaining = {(x, y) for y in range(size) for x in range(size) if pixels[y][x][3] == 255}
    band = set()
    for _ in range(width):
        removed = {(x, y) for x, y in remaining
                   if any((x + dx, y + dy) not in remaining for dx in (-1, 0, 1) for dy in (-1, 0, 1))}
        band |= removed
        remaining -= removed
    return band, remaining


def frame_problems(size, image):
    """작업 표시줄 크기 프레임 하나의 픽셀 규칙 위반을 사람이 읽는 문장으로 돌려준다."""
    size, pixels = _grid(image)
    problems = []
    band, inner = edge_band(size, pixels, max(1, size // 16))
    if not band:
        return [f'{size}px: 불투명한 실루엣이 없습니다']
    for name, background in TASKBAR_BACKGROUNDS.items():
        rgb = QColor(background).getRgb()[:3]
        share = sum(contrast(pixels[y][x][:3], rgb) >= MIN_CONTRAST for x, y in band) / len(band)
        if share < MIN_EDGE_CONTRAST_SHARE:
            problems.append(f'{size}px: 가장자리가 {name} 작업 표시줄({background})과 {MIN_CONTRAST}:1 이상인 비율 '
                            f'{share:.0%} < {MIN_EDGE_CONTRAST_SHARE:.0%}')
    visible = [pixel for row in pixels for pixel in row if pixel[3]]
    semitransparent = sum(pixel[3] < 255 for pixel in visible) / max(1, len(visible))
    if semitransparent > MAX_SEMITRANSPARENT_SHARE:
        problems.append(f'{size}px: 반투명 가장자리 픽셀 비율 {semitransparent:.1%} > {MAX_SEMITRANSPARENT_SHARE:.0%}(흐림)')
    silhouette = sum(pixel[3] for row in pixels for pixel in row) / 255 / size ** 2
    if silhouette < MIN_SILHOUETTE_SHARE:
        problems.append(f'{size}px: 실루엣 면적 {silhouette:.0%} < {MIN_SILHOUETTE_SHARE:.0%}(너무 작음)')
    plate = Counter(pixels[y][x][:3] for x, y in inner).most_common(1)
    mark = sum(contrast(pixels[y][x][:3], plate[0][0]) >= MIN_CONTRAST for x, y in inner) / size ** 2 if plate else 0
    low, high = MARK_SHARE_RANGE
    if not low <= mark <= high:
        problems.append(f'{size}px: 판과 {MIN_CONTRAST}:1 이상 구별되는 글자 마크 면적 {mark:.0%}가 '
                        f'{low:.0%}~{high:.0%} 밖입니다({"너무 작음" if mark < low else "꽉 참"})')
    return problems


def _scaled_copy(image, other):
    size = image.width()
    data = _pixels(rgba(image))
    for mode in (Qt.TransformationMode.SmoothTransformation, Qt.TransformationMode.FastTransformation):
        scaled = _pixels(rgba(other.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, mode)))
        if all(abs(a - b) <= SCALED_COPY_TOLERANCE for a, b in zip(data, scaled)):
            return True
    return False


def icon_problems(root=ROOT, ico=ICO, manifest=MANIFEST):
    """산출물(ICO·웹 이미지·매니페스트)과 지금 원본을 대조하고 픽셀 규칙을 검사한다. 문제가 없으면 빈 목록."""
    root = Path(root)
    try:
        frames = decode_ico((root / ico).read_bytes())
        record = json.loads((root / manifest).read_text(encoding='utf-8'))
    except (OSError, ValueError, struct.error) as error:
        return [f'산출물을 읽지 못했습니다: {error}']
    problems = [f'{size}px 프레임이 없습니다(크기 누락)' for size in ICON_SIZES if size not in frames]
    entries = record.get('frames', {})
    for size in (size for size in ICON_SIZES if size in frames):
        entry = entries.get(str(size), {})
        if entry.get('source') != source_for(size):
            problems.append(f'{size}px 프레임의 원본이 {entry.get("source")}입니다. {source_for(size)}여야 합니다')
            continue
        if entry.get('pixels_sha256') != pixel_digest(frames[size]):
            problems.append(f'{size}px 프레임이 매니페스트의 픽셀과 다릅니다')
        source = root / source_for(size)
        if not source.is_file() or entry.get('source_sha256') != content_digest(source):
            problems.append(f'낡은 산출물: {source_for(size)}가 {size}px 프레임을 만든 뒤 바뀌었습니다. '
                            'python scripts/app_icon.py로 다시 만드세요')
        elif size in TUNED_SIZES and pixel_digest(read_png(source)) != pixel_digest(frames[size]):
            problems.append(f'{size}px 프레임이 손본 원본 {source_for(size)}와 다릅니다')
    for size, image in frames.items():
        for other_size, other in frames.items():
            if other_size != size and _scaled_copy(image, other):
                problems.append(f'{size}px 프레임이 {other_size}px 프레임을 늘이거나 줄인 것입니다')
                break
    for size in (size for size in TUNED_SIZES if size in frames):
        problems += frame_problems(size, frames[size])
    web = record.get('web', {})
    web_path = root / web.get('path', WEB_IMAGE)
    if not web_path.is_file() or web.get('pixels_sha256') != pixel_digest(read_png(web_path)):
        problems.append(f'웹 이미지 {WEB_IMAGE}가 매니페스트와 다릅니다')
    if web.get('source') != VECTOR_SOURCE or web.get('source_sha256') != content_digest(root / VECTOR_SOURCE):
        problems.append(f'낡은 산출물: {VECTOR_SOURCE}가 웹 이미지를 만든 뒤 바뀌었습니다')
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check', action='store_true', help='다시 만들지 않고 산출물만 검사한다')
    args = parser.parse_args(argv)
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication(['app_icon', '-platform', 'offscreen'])
    if not args.check:
        build()
    problems = icon_problems()
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print(f'앱 아이콘 산출물 최신·픽셀 규칙 통과: {ICO} ({", ".join(map(str, ICON_SIZES))}px)')
    del app
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
