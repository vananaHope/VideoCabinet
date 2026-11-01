"""Windows 내장 OCR을 화면 자막 엔진 경계에 연결한다."""

import asyncio
import re
from threading import local

from .onscreen_subtitles import RegionImage, onscreen_language_name


# 한자(확장 영역 포함), 히라가나·가타카나 사이의 OCR 단어 구분만 없앤다.
_CJK = r"\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f\U00020000-\U000323af"
_CJK_SPACE = re.compile(rf"(?<=[{_CJK}])[^\S\r\n]+(?=[{_CJK}])")


def normalize_ocr_text(text: str, language: str) -> str:
    """일본어·중국어의 글자 사이 공백만 붙이고 라틴 단어와 줄바꿈은 보존한다."""
    if language == "ja" or language.startswith("ja-") or language.startswith("zh-"):
        return _CJK_SPACE.sub("", text)
    return text


class _ThreadState:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.engines = {}

    def __del__(self):
        # QThread가 끝나면 그 스레드의 루프도 닫는다.
        self.loop.close()


class WindowsOcrEngine:
    def __init__(self):
        self._local = local()

    @staticmethod
    def _language_tag(language: str) -> str | None:
        from winrt.windows.media.ocr import OcrEngine

        return next((item.language_tag for item in OcrEngine.available_recognizer_languages
                     if item.language_tag == language or item.language_tag.startswith(language + "-")), None)

    def language_available(self, language: str) -> bool:
        try:
            return self._language_tag(language) is not None
        except ImportError:
            return False

    def missing_language_guidance(self, language: str) -> str:
        return ("Windows 설정 > 시간 및 언어 > 언어 및 지역 > 언어 추가에서 "
                f"{onscreen_language_name(language)} 언어 팩을 설치하고"
                "(광학 문자 인식 포함) 다시 시도하세요.")

    def read_text(self, image: RegionImage, language: str) -> str:
        try:
            from winrt.windows.globalization import Language
            from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
            from winrt.windows.media.ocr import OcrEngine
            from winrt.windows.storage.streams import DataWriter
        except ImportError as exc:
            raise RuntimeError("Windows OCR 구성 요소(pywinrt)가 설치되어 있지 않습니다.") from exc

        if max(image.width, image.height) > OcrEngine.max_image_dimension:
            raise ValueError(f"영역 이미지의 가로·세로는 {OcrEngine.max_image_dimension}픽셀 이하여야 합니다.")
        state = getattr(self._local, "state", None)
        if state is None:
            state = self._local.state = _ThreadState()
        engine = state.engines.get(language)
        if engine is None:
            tag = self._language_tag(language)
            if tag is None:
                raise RuntimeError(self.missing_language_guidance(language))
            engine = OcrEngine.try_create_from_language(Language(tag))
            if engine is None:
                raise RuntimeError(self.missing_language_guidance(language))
            state.engines[language] = engine

        writer = DataWriter()
        try:
            writer.write_bytes(image.pixels)
            buffer = writer.detach_buffer()
        finally:
            writer.close()
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            buffer, BitmapPixelFormat.GRAY8, image.width, image.height)
        try:
            async def recognize():
                return await engine.recognize_async(bitmap)

            result = state.loop.run_until_complete(recognize())
            text = "\n".join(" ".join(word.text for word in line.words) for line in result.lines)
            return normalize_ocr_text(text, language)
        finally:
            bitmap.close()
