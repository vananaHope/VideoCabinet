"""Qt를 불러오기 전에 WebEngine 테스트의 GPU 경합을 피한다."""
import os

os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')
