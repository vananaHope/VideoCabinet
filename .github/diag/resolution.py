"""임시: 러너 화면을 1920×1080으로 바꾼다(기본 1024×768은 1100×720 창이 안 들어간다)."""
import ctypes
from ctypes import wintypes


class DEVMODEW(ctypes.Structure):
    _fields_ = [('dmDeviceName', wintypes.WCHAR * 32), ('dmSpecVersion', wintypes.WORD), ('dmDriverVersion', wintypes.WORD),
                ('dmSize', wintypes.WORD), ('dmDriverExtra', wintypes.WORD), ('dmFields', wintypes.DWORD),
                ('dmPositionX', wintypes.LONG), ('dmPositionY', wintypes.LONG), ('dmDisplayOrientation', wintypes.DWORD),
                ('dmDisplayFixedOutput', wintypes.DWORD), ('dmColor', ctypes.c_short), ('dmDuplex', ctypes.c_short),
                ('dmYResolution', ctypes.c_short), ('dmTTOption', ctypes.c_short), ('dmCollate', ctypes.c_short),
                ('dmFormName', wintypes.WCHAR * 32), ('dmLogPixels', wintypes.WORD), ('dmBitsPerPel', wintypes.DWORD),
                ('dmPelsWidth', wintypes.DWORD), ('dmPelsHeight', wintypes.DWORD), ('dmDisplayFlags', wintypes.DWORD),
                ('dmDisplayFrequency', wintypes.DWORD), ('rest', ctypes.c_byte * 32)]


mode = DEVMODEW()
mode.dmSize = ctypes.sizeof(DEVMODEW)
user32 = ctypes.windll.user32
user32.EnumDisplaySettingsW(None, -1, ctypes.byref(mode))
print('before', mode.dmPelsWidth, mode.dmPelsHeight)
mode.dmPelsWidth, mode.dmPelsHeight = 1920, 1080
mode.dmFields = 0x80000 | 0x100000
print('ChangeDisplaySettingsW', user32.ChangeDisplaySettingsW(ctypes.byref(mode), 0))
print('now', user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
