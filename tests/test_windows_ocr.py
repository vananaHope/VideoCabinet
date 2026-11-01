"""Windows 실제 인식과 운영체제에 무관한 글자 정리 규칙."""

import os
from pathlib import Path
import sys

import pytest

from my_video_manager.onscreen_subtitles import ONSCREEN_LANGUAGES, RegionImage
from my_video_manager.windows_ocr import WindowsOcrEngine, normalize_ocr_text


@pytest.mark.parametrize("language,text,expected", [
    ("ja", "日 本 語 の 字", "日本語の字"),
    ("zh-Hans", "中 文 简 体", "中文简体"),
    ("zh-Hant", "中 文 繁 體", "中文繁體"),
    ("ja", "日 本 Hello world 123 語", "日本 Hello world 123 語"),
    ("ja", "日 本\n語 の 字", "日本\n語の字"),
    ("ja", "カ タ カ ナ ひ ら が な", "カタカナひらがな"),
    ("zh-Hans", "𠀀 中 文", "𠀀中文"),
    ("en", "日 本 Hello world", "日 本 Hello world"),
    ("ko", "한 글 공 백", "한 글 공 백"),
    ("ja", "", ""),
])
def test_normalize_ocr_text(language, text, expected):
    assert normalize_ocr_text(text, language) == expected


def test_missing_language_guidance():
    guidance = WindowsOcrEngine().missing_language_guidance("ja")
    assert "일본어" in guidance
    assert "광학 문자 인식" in guidance
    assert "Windows 설정" in guidance


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 내장 OCR")
def test_language_available_matches_installed_languages():
    from winrt.windows.media.ocr import OcrEngine

    tags = [item.language_tag for item in OcrEngine.available_recognizer_languages]
    adapter = WindowsOcrEngine()
    for code in [language for language, _ in ONSCREEN_LANGUAGES] + tags + ["xx"]:
        assert adapter.language_available(code) == any(
            tag == code or tag.startswith(code + "-") for tag in tags)
    assert not adapter.language_available("xx")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 내장 OCR")
def test_read_grayscale_text(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QFontDatabase, QImage, QPainter
    from winrt.windows.media.ocr import OcrEngine

    adapter = WindowsOcrEngine()
    if not adapter.language_available("en"):
        pytest.skip("영어 OCR 언어 팩 없음")
    image = QImage(400, 100, QImage.Format.Format_Grayscale8)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    painter.setPen(Qt.GlobalColor.black)
    # offscreen 플랫폼은 Windows 시스템 글꼴을 자동 등록하지 않는다.
    font_id = QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"], "Fonts", "arial.ttf")))
    assert font_id >= 0
    font = QFont(QFontDatabase.applicationFontFamilies(font_id)[0])
    font.setPixelSize(36)
    painter.setFont(font)
    painter.drawText(20, 65, "Hello 123")
    painter.end()
    region = RegionImage(image.width(), image.height(), bytes(image.constBits()))
    assert adapter.read_text(region, "en") == "Hello 123"
    # 같은 스레드의 루프·인식기를 재사용해도 다음 장을 읽는다.
    assert adapter.read_text(region, "en") == "Hello 123"
    too_wide = OcrEngine.max_image_dimension + 1
    with pytest.raises(ValueError, match="픽셀"):
        adapter.read_text(RegionImage(too_wide, 1, bytes(too_wide)), "en")
