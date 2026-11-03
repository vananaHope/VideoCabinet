"""앱·트레이 아이콘 픽셀 검사: 빌드 산출물(ICO·웹 이미지·매니페스트)만 읽어 크기·출처·대비·흐림·면적·낡음을 본다."""
import importlib
import json
from pathlib import Path
import shutil
import sys

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def icon():
    QApplication.instance() or QApplication([])
    sys.path.insert(0, str(ROOT / 'scripts'))
    try:
        yield importlib.import_module('app_icon')
    finally:
        sys.path.remove(str(ROOT / 'scripts'))


@pytest.fixture
def built(icon, tmp_path):
    """저장소의 원본과 산출물을 복사한 작업 폴더. 산출물을 일부러 망가뜨려도 저장소는 그대로다."""
    for relative in (icon.SOURCE_DIRECTORY, ):
        shutil.copytree(ROOT / relative, tmp_path / relative)
    for relative in (icon.ICO, icon.WEB_IMAGE, icon.TRAY_ICO):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, tmp_path / relative)
    return tmp_path


def frames_of(icon, root):
    return icon.decode_ico((root / icon.ICO).read_bytes())


def replace_frames(icon, root, frames):
    """ICO를 다시 쓰고 매니페스트의 픽셀 해시만 맞춘다. 원본 대조 외의 규칙이 실패를 잡는지 보이기 위해서다."""
    (root / icon.ICO).write_bytes(icon.encode_ico(frames))
    path = root / icon.MANIFEST
    manifest = json.loads(path.read_text(encoding='utf-8'))
    for size, image in frames.items():
        manifest['frames'][str(size)]['pixels_sha256'] = icon.pixel_digest(image)
    path.write_text(json.dumps(manifest), encoding='utf-8')


def tray_frames_of(icon, root):
    return icon.decode_ico((root / icon.TRAY_ICO).read_bytes())


def replace_tray_frames(icon, root, frames):
    """트레이 ICO를 다시 쓰고 매니페스트의 트레이 픽셀 해시만 맞춘다."""
    (root / icon.TRAY_ICO).write_bytes(icon.encode_ico(frames))
    path = root / icon.MANIFEST
    manifest = json.loads(path.read_text(encoding='utf-8'))
    for size, image in frames.items():
        manifest['tray']['frames'][str(size)]['pixels_sha256'] = icon.pixel_digest(image)
    path.write_text(json.dumps(manifest), encoding='utf-8')


def recolor(image, before, after):
    image = image.copy()
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y) == QColor(before):
                image.setPixelColor(x, y, QColor(after))
    return image


def blur(image):
    """캔버스 밖을 투명으로 보고 3×3 상자 흐림을 준다(그림 도구의 흐림 효과처럼 가장자리가 번진다)."""
    size = image.width()
    result = QImage(size, size, QImage.Format.Format_RGBA8888)
    for y in range(size):
        for x in range(size):
            colors = [image.pixelColor(x + dx, y + dy) if 0 <= x + dx < size and 0 <= y + dy < size else QColor(0, 0, 0, 0)
                      for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
            alpha = sum(c.alpha() for c in colors)
            channel = (lambda name: round(sum(getattr(c, name)() * c.alpha() for c in colors) / alpha) if alpha else 0)
            result.setPixelColor(x, y, QColor(channel('red'), channel('green'), channel('blue'), round(alpha / 9)))
    return result


def test_committed_icon_artifacts_are_fresh_and_pass_pixel_rules(icon):
    assert icon.icon_problems() == []
    assert sorted(frames_of(icon, ROOT)) == list(icon.ICON_SIZES)


def test_check_command_passes_on_committed_artifacts(icon, capsys):
    assert icon.main(['--check']) == 0
    assert 'app.ico' in capsys.readouterr().out


def test_small_frames_come_from_hand_tuned_sources_and_large_from_vector(icon):
    manifest = json.loads((ROOT / icon.MANIFEST).read_text(encoding='utf-8'))
    frames = frames_of(icon, ROOT)
    for size in icon.ICON_SIZES:
        expected = f'assets/icon/app-icon-{size}.png' if size <= 32 else 'assets/icon/app-icon.svg'
        assert manifest['frames'][str(size)]['source'] == expected
    for size in (16, 20, 24, 32):
        assert icon.pixel_digest(frames[size]) == icon.pixel_digest(icon.read_png(ROOT / f'assets/icon/app-icon-{size}.png'))


def test_blurred_frame_fails(icon, built):
    frames = frames_of(icon, built)
    frames[24] = blur(frames[24])
    replace_frames(icon, built, frames)
    assert any(problem.startswith('24px: 반투명 가장자리') for problem in icon.icon_problems(built))


def test_rendering_vector_directly_at_taskbar_size_fails(icon, built):
    # 손보지 않고 벡터를 그대로 16px로 줄이면 흐리고 어두운 작업 표시줄에서 테두리가 사라진다.
    frames = frames_of(icon, built)
    frames[16] = icon.render_vector(built / icon.VECTOR_SOURCE, 16)
    replace_frames(icon, built, frames)
    problems = icon.icon_problems(built)
    assert any(problem.startswith('16px: 반투명') for problem in problems)
    assert any(problem.startswith('16px: 가장자리가 어두운 작업 표시줄') for problem in problems)


@pytest.mark.parametrize('background', ['밝은', '어두운'])
def test_low_contrast_outline_fails_on_each_taskbar(icon, built, background):
    # 테두리를 판 색(어두운 배경에 묻힘) 또는 밝은 면 색(밝은 배경에 묻힘)으로 바꾼다.
    frames = frames_of(icon, built)
    frames[32] = recolor(frames[32], '#7c7c85', '#09090b' if background == '어두운' else '#e4e4e7')
    replace_frames(icon, built, frames)
    assert any(problem.startswith(f'32px: 가장자리가 {background} 작업 표시줄') for problem in icon.icon_problems(built))


def test_mark_without_contrast_against_plate_fails_as_too_small(icon, built):
    # 흰 서랍을 테두리 회색으로 바꾸면 인디고 판과 1.7:1이라 마크로 읽히지 않는다.
    frames = frames_of(icon, built)
    frames[20] = recolor(frames[20], '#ffffff', '#7c7c85')
    replace_frames(icon, built, frames)
    assert any(problem.startswith('20px: 판과') and '너무 작음' in problem for problem in icon.icon_problems(built))


def test_mark_filling_plate_fails_as_too_full(icon, built):
    # 테두리와 그 안쪽 한 줄의 판만 남기고 흰 서랍이 판을 다 덮는다.
    frames = frames_of(icon, built)
    frames[16] = frames[16].copy()
    for y in range(2, 14):
        for x in range(2, 14):
            frames[16].setPixelColor(x, y, QColor('#ffffff'))
    replace_frames(icon, built, frames)
    assert any(problem.startswith('16px:') and '꽉 참' in problem for problem in icon.icon_problems(built))


@pytest.mark.parametrize('size', [20, 64])
def test_missing_size_fails(icon, built, size):
    frames = frames_of(icon, built)
    del frames[size]
    replace_frames(icon, built, frames)
    assert f'{size}px 프레임이 없습니다(크기 누락)' in icon.icon_problems(built)


def test_frame_scaled_from_another_size_fails(icon, built):
    frames = frames_of(icon, built)
    frames[48] = frames[256].scaled(48, 48, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    replace_frames(icon, built, frames)
    assert '48px 프레임이 256px 프레임을 늘이거나 줄인 것입니다' in icon.icon_problems(built)


def test_frame_from_wrong_source_fails(icon, built):
    path = built / icon.MANIFEST
    manifest = json.loads(path.read_text(encoding='utf-8'))
    manifest['frames']['24']['source'] = icon.VECTOR_SOURCE
    path.write_text(json.dumps(manifest), encoding='utf-8')
    assert any(problem.startswith('24px 프레임의 원본이') for problem in icon.icon_problems(built))


def test_stale_artifacts_fail_when_vector_source_changes(icon, built):
    # 수정 시각이 아니라 내용 해시로 본다. 내용이 바뀌면 시각과 상관없이 낡은 산출물이다.
    svg = built / icon.VECTOR_SOURCE
    svg.write_bytes(svg.read_bytes().replace(b'#4f46e5', b'#6366f1'))
    problems = icon.icon_problems(built)
    assert any(problem.startswith('낡은 산출물: assets/icon/app-icon.svg가 256px') for problem in problems)
    assert any('웹 이미지를 만든 뒤 바뀌었습니다' in problem for problem in problems)


def test_stale_artifacts_fail_when_tuned_source_changes(icon, built):
    path = built / 'assets/icon/app-icon-16.png'
    image = icon.read_png(path)
    image.setPixelColor(8, 8, QColor('#4f46e5'))
    image.save(str(path))
    assert any(problem.startswith('낡은 산출물: assets/icon/app-icon-16.png') for problem in icon.icon_problems(built))


def test_touching_sources_without_changing_content_keeps_artifacts_fresh(icon, built):
    for path in (built / icon.SOURCE_DIRECTORY).iterdir():
        path.write_bytes(path.read_bytes())
    assert icon.icon_problems(built) == []


def test_rebuild_from_sources_reproduces_committed_frames(icon, built):
    before = {size: icon.pixel_digest(image) for size, image in frames_of(icon, built).items()}
    tray_before = {size: icon.pixel_digest(image) for size, image in tray_frames_of(icon, built).items()}
    icon.build(built)
    assert {size: icon.pixel_digest(image) for size, image in frames_of(icon, built).items()} == before
    assert {size: icon.pixel_digest(image) for size, image in tray_frames_of(icon, built).items()} == tray_before
    assert icon.icon_problems(built) == []


def test_tray_frames_come_from_their_own_hand_tuned_sources(icon):
    manifest = json.loads((ROOT / icon.MANIFEST).read_text(encoding='utf-8'))
    frames = tray_frames_of(icon, ROOT)
    assert manifest['tray']['path'] == 'src/my_video_manager/tray.ico'
    assert sorted(frames) == [16, 20, 24, 32]
    for size, image in frames.items():
        source = f'assets/icon/tray-icon-{size}.png'
        assert manifest['tray']['frames'][str(size)]['source'] == source
        assert icon.pixel_digest(image) == icon.pixel_digest(icon.read_png(ROOT / source))
        # 앱 아이콘 같은 크기 프레임을 그대로 쓰지 않는다(서랍 앞면과 자막 두 줄만 남긴 단순화 모양).
        assert icon.pixel_digest(image) != icon.pixel_digest(frames_of(icon, ROOT)[size])


def test_committed_tray_frames_pass_pixel_rules_on_both_taskbars(icon):
    for size, image in tray_frames_of(icon, ROOT).items():
        assert icon.tray_frame_problems(size, image) == [], size


def test_blurred_tray_frame_fails(icon, built):
    frames = tray_frames_of(icon, built)
    frames[16] = blur(frames[16])
    replace_tray_frames(icon, built, frames)
    assert any(problem.startswith('트레이 16px: 반투명 가장자리') for problem in icon.icon_problems(built))


@pytest.mark.parametrize('background', ['밝은', '어두운'])
def test_low_contrast_tray_outline_fails_on_each_taskbar(icon, built, background):
    frames = tray_frames_of(icon, built)
    frames[20] = recolor(frames[20], '#7c7c85', '#202020' if background == '어두운' else '#f3f3f3')
    replace_tray_frames(icon, built, frames)
    problems = icon.icon_problems(built)
    assert any(problem.startswith(f'트레이 20px: 가장자리가 {background} 작업 표시줄') for problem in problems)


def test_tray_plate_without_border_disappears_on_dark_taskbar(icon, built):
    # 테두리 없는 인디고 판만이면 어두운 작업 표시줄(#202020)과 2.6:1이라 묻힌다. 회색 테두리를 두는 이유다.
    frames = tray_frames_of(icon, built)
    frames[24] = recolor(frames[24], '#7c7c85', 'transparent')
    replace_tray_frames(icon, built, frames)
    problems = icon.icon_problems(built)
    assert any(problem.startswith('트레이 24px: 가장자리가 어두운 작업 표시줄') for problem in problems)
    assert not any(problem.startswith('트레이 24px: 가장자리가 밝은 작업 표시줄') for problem in problems)


def test_tray_drawer_filling_plate_fails_as_too_full(icon, built):
    # 테두리 안쪽 한 줄의 판만 남기고 흰 서랍이 자막 자리와 판을 다 덮으면 흰 덩어리다.
    frames = tray_frames_of(icon, built)
    frames[32] = frames[32].copy()
    for y in range(3, 29):
        for x in range(3, 29):
            frames[32].setPixelColor(x, y, QColor('#ffffff'))
    replace_tray_frames(icon, built, frames)
    assert any(problem.startswith('트레이 32px: 판과') and '꽉 참' in problem
               for problem in icon.icon_problems(built))


@pytest.mark.parametrize('drawer_color', ['#7c7c85', '#4f46e5'])
def test_tray_drawer_without_contrast_fails_as_too_small(icon, built, drawer_color):
    # 흰 서랍을 테두리 회색(인디고 판과 1.7:1)으로 바꾸면 서랍이 있어도 마크로 읽히지 않는다. 판 색이면 서랍이 사라진다.
    frames = tray_frames_of(icon, built)
    frames[16] = recolor(frames[16], '#ffffff', drawer_color)
    replace_tray_frames(icon, built, frames)
    assert any(problem.startswith('트레이 16px: 판과') and '너무 작음' in problem
               for problem in icon.icon_problems(built))


@pytest.mark.parametrize('size', [16, 32])
def test_missing_tray_size_fails(icon, built, size):
    frames = tray_frames_of(icon, built)
    del frames[size]
    replace_tray_frames(icon, built, frames)
    assert f'트레이 {size}px 프레임이 없습니다(크기 누락)' in icon.icon_problems(built)


def test_tray_frame_scaled_from_another_size_fails(icon, built):
    frames = tray_frames_of(icon, built)
    frames[16] = frames[32].scaled(16, 16, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
    replace_tray_frames(icon, built, frames)
    assert '트레이 16px 프레임이 32px 프레임을 늘이거나 줄인 것입니다' in icon.icon_problems(built)


def test_missing_tray_artifact_fails(icon, built):
    (built / icon.TRAY_ICO).unlink()
    assert any(problem.startswith('트레이 산출물을 읽지 못했습니다') for problem in icon.icon_problems(built))


def test_stale_tray_artifact_fails_when_tray_source_changes(icon, built):
    path = built / 'assets/icon/tray-icon-24.png'
    image = icon.read_png(path)
    image.setPixelColor(0, 0, QColor('#7c7c85'))
    image.save(str(path))
    assert any(problem.startswith('낡은 산출물: assets/icon/tray-icon-24.png가 트레이 24px')
               for problem in icon.icon_problems(built))


class _Application:
    """앱 시작 경로가 창 아이콘을 정하는 데까지만 실제로 돈다. 단일 실행 시작에서 멈춘다."""
    icons = []

    def __init__(self, *args):
        pass

    def setWindowIcon(self, value):
        self.icons.append(value)

    def setQuitOnLastWindowClosed(self, value):
        pass


def test_application_window_icon_is_the_built_multi_size_icon(icon, monkeypatch, tmp_path):
    from PySide6 import QtWidgets
    from my_video_manager import __main__, single_instance, theme
    _Application.icons.clear()
    monkeypatch.setattr(sys, 'argv', ['my-video-manager', '--data-dir', str(tmp_path)])
    monkeypatch.setattr(QtWidgets, 'QApplication', _Application)
    monkeypatch.setattr(theme, 'apply_theme', lambda app: None)
    monkeypatch.setattr(single_instance, 'SingleInstance', lambda directory, parent: type(
        'Instance', (), {'start': lambda self: False, 'close': lambda self: None})())
    assert __main__.main() == 0
    [window_icon] = _Application.icons
    assert not window_icon.isNull()
    assert {size.width() for size in window_icon.availableSizes()} >= set(icon.ICON_SIZES)
    built = frames_of(icon, ROOT)
    for size in (16, 32, 48, 256):
        pixmap = window_icon.pixmap(QSize(size, size))
        assert icon.pixel_digest(pixmap.toImage()) == icon.pixel_digest(built[size]), size


def test_icon_colors_are_web_tokens(icon):
    # 색 원본은 web_tokens.json이다. 아이콘 원본이 토큰과 다른 색을 쓰면 앱 화면과 어긋난다.
    import re
    from my_video_manager.web_tokens import web_tokens
    colors = web_tokens()['colors']
    expected = {colors['primary'], colors['primary-foreground'], colors['input']}
    svg = (ROOT / icon.VECTOR_SOURCE).read_text(encoding='utf-8')
    assert set(re.findall(r'(?:fill|stroke)="(#[0-9a-f]{6})"', svg)) == expected
    for size in icon.TUNED_SIZES:
        image = icon.read_png(ROOT / icon.source_for(size))
        used = {image.pixelColor(x, y).name() for y in range(size) for x in range(size) if image.pixelColor(x, y).alpha()}
        assert used == expected, size
    # 트레이도 판(primary)·서랍(primary-foreground)·테두리(input) 세 색만 쓴다.
    for size in icon.TRAY_SIZES:
        image = icon.read_png(ROOT / icon.tray_source_for(size))
        used = {image.pixelColor(x, y).name() for y in range(size) for x in range(size) if image.pixelColor(x, y).alpha()}
        assert used == expected, size
