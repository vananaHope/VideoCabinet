"""Qt Windows 키 매퍼(qt_keys.key_name)와 Win32Dialogs.key_name을 같은 가상 키·수정자로 대조한다.

실제 Windows 창을 띄우므로 이 실행이 데스크톱 잠금을 소유했을 때만 창을 만든다. 잠금 파일의 pid가
현재 프로세스의 부모 계통에 있고 잠금이 신선할 때만 통과한다. 잠금이 없거나 다른 작업자가 잡고 있으면
`desktop_lock.py run --owner issue-183-probe -- ...`로 감싸 실행한다. test_native_dialogs.py의 실창
검사는 probe_command()로 그 래퍼를 거치고, `--record 경로`로 실행하면 기본 pytest가 실창 없이 대조할
기대값을 기록한다. 창은 화면 밖 투명 창이고 초점을 옮기지 않는다. 이 스레드의 키보드 상태
(SetKeyboardState)로 수정자를 정하고 키 메시지를 그 Qt 창에 보낸다.
"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QWidget

from my_video_manager import native_dialogs
from my_video_manager.native_dialogs import Win32Dialogs
from my_video_manager.qt_keys import key_name

LOCK = Path.home() / ".agent-orchestra" / "desktop.lock"
LOCK_SCRIPT = Path.home() / ".agent-orchestra" / "bin" / "desktop_lock.py"
OWNER = "issue-183-probe"
PROBE = Path(__file__).resolve()
# desktop_lock.py가 오래된 잠금을 넘겨받는 기준과 같은 값이다.
STALE_SECONDS = 15 * 60

KEYS = [0x48, 0x41, 0x5A, 0x31, 0x30, 0x32, 0x36, 0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xC0, 0xDB, 0xDC, 0xDD, 0xDE,
        0x61, 0x69, 0x6A, 0x6B, 0x6D, 0x6E, 0x6F, 0x74, 0x25, 0x20, 0x2E]
EXTENDED = {0x25, 0x2E, 0x6F}
MODIFIERS = [("Ctrl",), ("Ctrl", "Shift"), ("Alt",), ("Alt", "Shift"), ("Ctrl", "Alt"), ("Ctrl", "Meta"), ("Shift", "Meta"),
             ("Ctrl", "Alt", "Shift")]
VK = {"Ctrl": (0x11, 0xA2), "Shift": (0x10, 0xA0), "Alt": (0x12, 0xA4), "Meta": (0x5B,)}


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def read_lock(path=None):
    """잠금 JSON을 읽는다. 파일이 없거나 JSON이 아니면 None."""
    path = LOCK if path is None else path
    try:
        holder = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return holder if isinstance(holder, dict) else None


def parent_pid(pid):
    """Windows 프로세스의 부모 pid를 돌려준다. 알 수 없으면 None."""
    if sys.platform != "win32":
        return None
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        return None
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return None
        while True:
            if entry.th32ProcessID == pid:
                parent = entry.th32ParentProcessID
                return parent if parent != pid else None
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                return None
    finally:
        kernel32.CloseHandle(snapshot)


def process_chain(pid=None, parent_of=None, limit=32):
    """pid에서 위로 올라가는 부모 계통. 순환·과도한 깊이는 끊는다."""
    parent_of = parent_pid if parent_of is None else parent_of
    chain, current = [], os.getpid() if pid is None else pid
    while current and current not in chain and len(chain) < limit:
        chain.append(current)
        current = parent_of(current)
    return chain


def desktop_lock_problem(path=None, pid=None, parent_of=None, now=None):
    """이 실행이 쓸 수 있는 데스크톱 잠금인지 검사한다. 문제가 없으면 None, 있으면 이유."""
    path = LOCK if path is None else path
    now = time.time() if now is None else now
    holder = read_lock(path)
    if holder is None:
        return f"데스크톱 잠금이 없습니다: {path}. desktop_lock.py run --owner {OWNER} -- 로 실행하세요."
    owner_pid = holder.get("pid")
    if isinstance(owner_pid, bool) or not isinstance(owner_pid, int) or owner_pid <= 0:
        return f"데스크톱 잠금 pid가 무효합니다: {owner_pid!r}"
    since = holder.get("since")
    if isinstance(since, bool) or not isinstance(since, (int, float)) or not 0 <= now - since <= STALE_SECONDS:
        return f"데스크톱 잠금이 오래되었거나 시각이 잘못됐습니다: {since!r}"
    chain = process_chain(pid, parent_of)
    if owner_pid not in chain:
        return (f"데스크톱 잠금 소유자 {owner_pid}({holder.get('owner')!r})이(가) 현재 프로세스 계통 "
                f"{chain}에 없습니다. desktop_lock.py run --owner {OWNER} -- 로 실행하세요.")
    return None


def ensure_desktop_lock_owned(**kwargs):
    """잠금 소유를 확인하고, 아니면 창을 만들기 전에 SystemExit로 막는다."""
    problem = desktop_lock_problem(**kwargs)
    if problem:
        raise SystemExit(problem)
    return read_lock(kwargs.get("path"))


def probe_command(probe=None):
    """실창 검사가 실행할 탐침 명령.

    이미 이 프로세스 계통이 잠금을 소유했으면 그대로 실행하고(중첩 획득·해제 방지),
    아니면 desktop_lock.py가 잠금을 잡은 뒤 탐침을 실행하게 감싼다.
    """
    direct = [sys.executable, str(PROBE if probe is None else probe)]
    if desktop_lock_problem() is None:
        return direct
    return [sys.executable, str(LOCK_SCRIPT), "run", "--owner", OWNER, "--", *direct]


def user32_api():
    user32 = ctypes.windll.user32
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SetKeyboardState.argtypes = [ctypes.c_void_p]
    user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    return user32


class Capture(QObject):
    def __init__(self):
        super().__init__()
        self.names = []

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            self.names.append(key_name(event))
        return False


def set_modifiers(user32, modifiers):
    state = (ctypes.c_ubyte * 256)()
    for modifier in modifiers:
        for vk in VK[modifier]:
            state[vk] = 0x80
    user32.SetKeyboardState(state)


def create_window():
    """실제 Windows 창을 만드는 경계. 잠금 확인 뒤에만 호출된다."""
    os.environ["QT_QPA_PLATFORM"] = "windows"
    app = QApplication([])
    # Qt는 보이지 않는 창에 키 이벤트를 넘기지 않는다. 화면 밖에 투명하고 활성화되지 않는 도구 창으로 띄운다.
    widget = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus)
    widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    widget.setWindowOpacity(0)
    widget.setGeometry(-32000, -32000, 10, 10)
    widget.show()
    app.processEvents()
    return app, widget


def collect_rows(app, widget):
    user32 = user32_api()
    hwnd = int(widget.winId())
    capture = Capture()
    app.installEventFilter(capture)
    native = Win32Dialogs()
    rows = []
    # 네이티브 이름을 만들 때 현재 키보드 배열이 돌려준 글자를 함께 기록한다.
    inputs = []
    windows_key_name = native_dialogs.windows_key_name

    def recording_key_name(vk, translate, base, **modifiers):
        texts = {}

        def recorded(shift, ctrl, alt):
            texts[f"{int(shift)}{int(ctrl)}{int(alt)}"] = text = translate(shift, ctrl, alt)
            return text
        name = windows_key_name(vk, recorded, base, **modifiers)
        inputs.append({"translate": texts, "base": base, **modifiers})
        return name

    native_dialogs.windows_key_name = recording_key_name
    try:
        for modifiers in MODIFIERS:
            for vk in KEYS:
                if vk == 0x20 and "Alt" in modifiers:
                    continue  # Alt+Space는 Windows 창 메뉴를 연다.
                set_modifiers(user32, modifiers)
                scan = user32.MapVirtualKeyW(vk, 0)
                alt = "Alt" in modifiers
                flags = 1 | (scan << 16) | ((1 << 24) if vk in EXTENDED else 0) | ((1 << 29) if alt else 0)
                capture.names.clear()
                user32.PostMessageW(hwnd, 0x0104 if alt else 0x0100, vk, flags)  # WM_SYSKEYDOWN / WM_KEYDOWN
                for _ in range(20):
                    app.processEvents()
                    if capture.names:
                        break
                set_modifiers(user32, modifiers)  # 메시지 처리 뒤의 상태를 다시 맞춘다(훅이 볼 때와 같은 상태).
                rows.append({"vk": vk, "modifiers": list(modifiers), "qt": capture.names[0] if capture.names else None,
                             "native": native.key_name(vk), **inputs.pop()})
                set_modifiers(user32, ())
                user32.PostMessageW(hwnd, 0x0105 if alt else 0x0101, vk, flags | (3 << 30))  # 뗌
                for _ in range(5):
                    app.processEvents()
    finally:
        native_dialogs.windows_key_name = windows_key_name
        set_modifiers(user32, ())
    return rows


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ensure_desktop_lock_owned()
    app, widget = create_window()
    rows = collect_rows(app, widget)
    if argv[0:1] == ["--record"]:
        layout = f"{user32_api().GetKeyboardLayout(0) & 0xFFFFFFFF:08x}"
        with open(argv[1], "w", encoding="utf-8", newline="\n") as file:
            json.dump({"layout": layout, "rows": [{key: row[key] for key in row if key != "native"} for row in rows]},
                      file, ensure_ascii=False, indent=1)
            file.write("\n")
    print(json.dumps(rows, ensure_ascii=False))
    return rows


if __name__ == "__main__":
    main()
