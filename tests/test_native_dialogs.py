"""Windows 기본 파일 창 어댑터: Qt와 같은 키 이름, 가짜 Win32 경계로 훅 수명과 긴급 탈출.

Qt Windows 키 매퍼와의 실제 대조는 실창을 띄우므로 기본 실행에서 빠진다. 켤 때는 pytest 전체를 데스크톱 잠금
래퍼로 감싼다. 탐침은 잠금을 잡거나 풀지 않고, 잠금 pid가 자기 조상일 때만 창을 만든다.

    $env:MVM_REAL_WINDOW_TESTS = '1'
    python $HOME/.agent-orchestra/bin/desktop_lock.py run --owner <이름> -- .venv/Scripts/python -m pytest tests/test_native_dialogs.py -q
    Remove-Item Env:MVM_REAL_WINDOW_TESTS

기본 실행은 그 탐침이 기록한 Qt 이름과 키보드 배열 글자(`fixtures/windows_key_names.json`)로 이름 규칙을 대조한다.
기록을 새로 만들 때도 같은 래퍼로 감싼다:
`python $HOME/.agent-orchestra/bin/desktop_lock.py run --owner <이름> -- .venv/Scripts/python tests/windows_key_probe.py --record tests/fixtures/windows_key_names.json`
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest

import windows_key_probe
from my_video_manager.native_dialogs import NativeDialogEscape, windows_key_name
from test_emergency_hide_ui import app, open_window, play_to_twenty_seconds
from qt_wait import wait_for

RECORDED = Path(__file__).with_name("fixtures") / "windows_key_names.json"
# 리뷰에서 어긋났던 Shift 적용 기호가 대조 대상에 들어 있다.
SHIFTED_SYMBOLS = {"Ctrl+Shift+:", "Ctrl+Shift+!", "Ctrl+Shift+_", "Ctrl+Alt+Shift+?"}


def test_native_key_names_match_recorded_qt_capture_names():
    """실제 Qt Windows 키 매퍼가 만든 이름과, 같은 키에서 키보드 배열이 돌려준 글자로 만든 네이티브 이름을 대조한다.

    문자·숫자·기호(Shift 적용 글자 포함)·숫자 패드·기능키·방향키, Ctrl·Alt·Shift·Win 조합.
    """
    rows = json.loads(RECORDED.read_text(encoding="utf-8"))["rows"]
    assert len(rows) > 150 and all(row["qt"] for row in rows)

    def native(row):
        texts = row["translate"]
        return windows_key_name(row["vk"], lambda shift, ctrl, alt: texts[f"{int(shift)}{int(ctrl)}{int(alt)}"], row["base"],
                                ctrl=row["ctrl"], alt=row["alt"], shift=row["shift"], meta=row["meta"])
    assert [(row["qt"], native(row)) for row in rows if native(row) != row["qt"]] == []
    assert SHIFTED_SYMBOLS <= {row["qt"] for row in rows}


def fake_parent_chain(monkeypatch):
    """현재 프로세스의 부모를 4242, 그 부모를 1로 만든다(실제 프로세스 조회 없이)."""
    monkeypatch.setattr(windows_key_probe, "parent_pid", lambda pid: {os.getpid(): 4242, 4242: 1}.get(pid))


def write_lock(path, *, owner="issue-183", pid=4242, since=None):
    path.write_text(json.dumps({"owner": owner, "pid": pid, "since": time.time() if since is None else since}),
                    encoding="utf-8")


def lock_state(path):
    return (path.read_bytes(), path.stat().st_mtime_ns) if path.exists() else None


@pytest.fixture
def probe_lock(tmp_path, monkeypatch):
    """임시 잠금 파일과 창 생성 경계 대역. 창을 만들면 created에 남고 기록 행은 비어 있다."""
    lock = tmp_path / "desktop.lock"
    created = []
    monkeypatch.setattr(windows_key_probe, "LOCK", lock)
    fake_parent_chain(monkeypatch)
    monkeypatch.setattr(windows_key_probe, "create_window", lambda: created.append(True) or ("app", "widget"))
    monkeypatch.setattr(windows_key_probe, "collect_rows", lambda app, widget: [{"qt": "Ctrl+H", "native": "Ctrl+H"}])
    return lock, created


@pytest.mark.parametrize("case", ["missing", "foreign", "same-owner-foreign", "invalid-pid"])
@pytest.mark.parametrize("argv", [[], ["--record", "out.json"]], ids=["direct", "record"])
def test_probe_stops_before_window_unless_an_ancestor_holds_the_lock(probe_lock, tmp_path, monkeypatch, case, argv):
    """잠금 없음/계통 밖 pid(같은 owner 이름 포함)/무효 pid면 창도 기록 파일도 만들지 않고 실행 방법을 안내한다.

    잠금 파일은 읽기만 한다.
    """
    lock, created = probe_lock
    if case == "foreign":
        write_lock(lock, owner="another-worker", pid=987654321)
    elif case == "same-owner-foreign":
        write_lock(lock, owner="issue-183", pid=987654321)
    elif case == "invalid-pid":
        write_lock(lock, pid=0)
    before = lock_state(lock)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as stopped:
        windows_key_probe.main(argv)
    assert "desktop_lock.py run --owner" in str(stopped.value.code)
    assert created == [] and not (tmp_path / "out.json").exists()
    assert lock_state(lock) == before


@pytest.mark.parametrize("argv", [[], ["--record", "out.json"]], ids=["direct", "record"])
def test_probe_runs_under_an_ancestor_lock_even_when_it_is_old(probe_lock, tmp_path, monkeypatch, argv):
    """조상(래퍼)이 잡은 잠금이면 오래돼도 창을 만들고, 잠금은 그대로 둔다."""
    lock, created = probe_lock
    write_lock(lock, since=time.time() - 24 * 60 * 60)
    before = lock_state(lock)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(windows_key_probe, "user32_api", lambda: type("User32", (), {"GetKeyboardLayout": staticmethod(lambda _: 0x04120412)}))
    windows_key_probe.main(argv)
    assert created == [True]
    assert lock_state(lock) == before
    if argv:
        assert json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))["rows"] == [{"qt": "Ctrl+H"}]


def real_window_rows(probe=None):
    """opt-in 실창 대조: 이 pytest가 잠금 래퍼 안에 있는지 확인한 뒤 탐침을 하위 프로세스로 실행하고 그 stdout만 읽는다.

    래퍼(desktop_lock.py run)는 pytest 바깥에 있으므로 그 획득·해제 로그는 탐침 stdout에 섞이지 않는다.
    """
    problem = windows_key_probe.desktop_lock_problem()
    if problem:
        pytest.fail(problem)
    # 자식 출력(한글 stderr 포함)이 로캘 기본(cp949)이 아니라 부모 해석과 같은 UTF-8로 나가게 한다.
    env = dict(os.environ, QT_QPA_PLATFORM="windows", PYTHONPATH=os.pathsep.join(sys.path), PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, str(probe or windows_key_probe.PROBE)], capture_output=True, text=True,
                            encoding="utf-8", env=env, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_real_window_check_fails_clearly_outside_the_lock_wrapper(probe_lock):
    lock, _ = probe_lock
    write_lock(lock, pid=987654321)
    before = lock_state(lock)
    with pytest.raises(pytest.fail.Exception, match="desktop_lock.py run --owner"):
        real_window_rows()
    assert lock_state(lock) == before


def test_real_window_check_reads_only_the_probe_output_under_the_wrapper(probe_lock, tmp_path):
    """래퍼 안에서는 탐침만 직접 실행하고(다시 감싸지 않음), 래퍼 로그 없이 탐침 stdout의 결과를 읽는다."""
    lock, _ = probe_lock
    write_lock(lock)
    before = lock_state(lock)
    probe = tmp_path / "fake_probe.py"
    probe.write_text("import json, sys\nprint('탐침 진행', file=sys.stderr)\nprint(json.dumps([{'qt': 'Ctrl+H'}]))\n",
                     encoding="utf-8")
    assert real_window_rows(probe) == [{"qt": "Ctrl+H"}]
    assert lock_state(lock) == before


@pytest.mark.skipif(os.environ.get("MVM_REAL_WINDOW_TESTS") != "1", reason="실창 검사: MVM_REAL_WINDOW_TESTS=1로 잠금 래퍼 안에서 연다")
@pytest.mark.skipif(sys.platform != "win32", reason="Windows 키 매퍼 대조")
def test_native_key_names_match_qt_capture_names_in_real_windows():
    """같은 가상 키·수정자를 실제 Qt Windows 키 매퍼(qt_keys.key_name)와 지금 키보드 배열의 네이티브 이름으로 만들어 대조한다."""
    rows = real_window_rows()
    assert len(rows) > 150 and all(row["qt"] for row in rows)
    assert [row for row in rows if row["qt"] != row["native"]] == []
    assert SHIFTED_SYMBOLS <= {row["qt"] for row in rows}


class FakeWin32:
    """Win32Dialogs와 같은 공개 메서드를 가진 가짜 경계. 훅 콜백으로 키를 누르고 대화상자를 연다·닫는다."""

    def __init__(self, *, install_fails=False):
        self.install_fails = install_fails
        self.installs, self.removed, self.cancelled = [], [], []
        self.pressed = None
        self.dialog = None
        self.name = None
        self.open = set()

    def install_hook(self, pressed):
        self.installs.append(pressed)
        if self.install_fails:
            return None
        self.pressed = pressed
        return f"hook-{len(self.installs)}"

    def remove_hook(self, hook):
        self.removed.append(hook)
        self.pressed = None

    def owned_dialog(self, owner):
        return self.dialog

    def key_name(self, vk):
        return self.name

    def cancel(self, dialog):
        self.cancelled.append(dialog)

    def is_window(self, dialog):
        return dialog in self.open

    def show_dialog(self, dialog="dialog-1"):
        self.dialog = dialog
        self.open.add(dialog)

    def close_dialog(self):
        self.open.discard(self.dialog)
        self.dialog = None

    def press(self, name, *, repeat=False):
        self.name = name
        return self.pressed(0x48, repeat)


@pytest.fixture
def fake(tmp_path, app, monkeypatch, request):
    system = FakeWin32(**getattr(request, "param", {}))
    opened = open_window(tmp_path, app, monkeypatch,
                         native_dialogs_factory=lambda window, is_emergency, escaped:
                         NativeDialogEscape(window, is_emergency, escaped, system))
    window = next(opened)
    yield window, system
    next(opened, None)  # close()는 yield 뒤 정리(완전 종료)를 건너뛰어 보이는 창을 남긴다.


def test_emergency_key_in_owned_native_dialog_cancels_then_hides_after_it_closes(fake):
    window, system = fake
    _, player = play_to_twenty_seconds(window)
    assert window.native_dialogs.installed and len(system.installs) == 1
    system.show_dialog()
    assert system.press("Ctrl+Shift+H") is True  # 대화상자에 넘기지 않는다.
    assert system.cancelled == ["dialog-1"]
    QTest.qWait(100)
    # 대화상자가 아직 닫히는 중이면 숨기지 않는다.
    assert window.isVisible() and not player.paused
    assert system.press("Ctrl+Shift+H", repeat=True) is True and system.cancelled == ["dialog-1"]
    system.close_dialog()
    wait_for(lambda: not window.isVisible())
    assert player.paused and window.balloons == []


def test_other_keys_and_unowned_windows_pass_through(fake):
    window, system = fake
    assert system.press("Ctrl+Shift+H") is False  # 앱 창이 소유한 기본 대화상자가 없다.
    system.show_dialog()
    assert system.press("Ctrl+Shift+J") is False and system.press(None) is False
    assert system.cancelled == [] and window.isVisible()


def test_install_is_idempotent_and_quit_removes_the_hook(fake):
    window, system = fake
    escape = window.native_dialogs
    assert escape.install() and escape.install()
    assert len(system.installs) == 1
    window.tray.quit()
    assert system.removed == ["hook-1"] and not escape.installed
    escape.uninstall()
    assert system.removed == ["hook-1"]


def test_quit_while_waiting_for_dialog_to_close_does_not_hide_later(fake):
    window, system = fake
    escaped = []
    escape = window.native_dialogs
    escape.escaped = lambda: escaped.append(True)
    system.show_dialog()
    assert system.press("Ctrl+Shift+H")
    escape.uninstall()  # 앱 종료 중
    system.close_dialog()
    QTest.qWait(100)
    assert escaped == [] and system.removed == ["hook-1"] and system.pressed is None


@pytest.mark.parametrize("fake", [{"install_fails": True}], indirect=True)
def test_failed_install_leaves_the_app_working(fake):
    window, system = fake
    escape = window.native_dialogs
    assert not escape.installed and len(system.installs) == 1
    # Qt 경로의 긴급 탈출은 그대로 동작하고, 종료 때 풀 훅이 없다.
    from test_emergency_hide_ui import emergency_key
    emergency_key(window)
    assert not window.isVisible()
    window.tray.open()
    window.tray.quit()
    assert system.removed == []
