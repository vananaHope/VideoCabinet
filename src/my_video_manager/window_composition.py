"""Windows 창 합성 경계. offscreen과 다른 플랫폼에서는 대기하지 않는다."""
import sys

from PySide6.QtGui import QGuiApplication


def wait_for_composition():
    if sys.platform != 'win32' or QGuiApplication.platformName() != 'windows':
        return
    import ctypes
    flush = ctypes.WinDLL('dwmapi').DwmFlush
    flush.argtypes = []
    flush.restype = ctypes.c_long
    # 고정 시간 지연 대신 호출 앱이 제출한 DirectX 변경의 다음 present를 기다린다.
    result = flush()
    if result < 0:
        raise OSError(f'창 합성 대기 실패: HRESULT 0x{result & 0xffffffff:08X}')
