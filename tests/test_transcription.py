from concurrent.futures import ThreadPoolExecutor
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event
import time

from wait_helpers import CHILD_READY_TIMEOUT

import pytest

from my_video_manager.subtitles import TranscriberCancelled, TranscriberError
from my_video_manager.transcription import FasterWhisperTranscriber


@pytest.mark.parametrize('frozen', [False, True])
def test_child_command_uses_same_executable(monkeypatch, tmp_path, frozen):
    monkeypatch.setattr(sys, 'frozen', frozen, raising=False)
    expected = (sys.executable, 'transcription') if frozen else (sys.executable, '-m', 'my_video_manager.transcription')
    assert FasterWhisperTranscriber(tmp_path).command == expected


def test_gpu_probe_cancellation_terminates_child(tmp_path):
    from threading import Timer
    from my_video_manager.cuda_runtime import cuda_gpu_available, PreparationError
    signal = Event()
    timer = Timer(0.3, signal.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(PreparationError) as caught:
            cuda_gpu_available(command=(sys.executable, '-c', 'import time; time.sleep(30)'), cancellation=signal)
        assert caught.value.kind == 'cancelled'
        assert time.monotonic() - started < 3
    finally:
        timer.join()


def test_application_dispatches_child_before_qt(monkeypatch):
    from my_video_manager import __main__, transcription
    calls = []
    monkeypatch.setattr(sys, 'argv', ['app.exe', 'transcription', '--probe-cuda'])
    monkeypatch.setattr(transcription, 'main', lambda args: calls.append(args) or 7)
    assert __main__.main() == 7
    assert calls == [['--probe-cuda']]


def adapter(tmp_path, script):
    worker = tmp_path / "가짜 받아쓰기.py"
    worker.write_text(script, encoding="utf-8")
    return FasterWhisperTranscriber(tmp_path / "models", command=(sys.executable, str(worker)))


def wait_file(path):
    # 낮은 우선순위의 자식 준비는 xdist 부하에서 늦을 수 있다.
    # 성공 경로의 준비와 종료에는 공용 부하 대기 한도를 적용한다.
    deadline = time.monotonic() + CHILD_READY_TIMEOUT
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size:
            return path.read_text()
        time.sleep(0.02)
    pytest.fail(f"프로세스 준비 신호 없음: {path}")


def process_alive(pid):
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = api.OpenProcess(0x100000, False, pid)
    if not handle:
        return False
    try:
        return api.WaitForSingleObject(handle, 0) == 258
    finally:
        api.CloseHandle(handle)


def assert_processes_exited(pids):
    deadline = time.monotonic() + CHILD_READY_TIMEOUT
    while any(process_alive(pid) for pid in pids) and time.monotonic() < deadline:
        time.sleep(0.02)  # Job 종료는 전체 트리에 비동기로 적용된다.
    assert not any(process_alive(pid) for pid in pids)


def test_child_json_and_arguments_are_decoded(tmp_path):
    transcriber = adapter(tmp_path, """
import json, sys
assert sys.argv[1].endswith('영상.mkv')
assert sys.argv[3] == 'ko'
print(json.dumps({'spoken_language':'ko', 'language_probability':0.9, 'model':'custom-model',
                  'segments':[{'start':0.5, 'end':1.25, 'text':'안녕'}]}, ensure_ascii=False))
""")
    result = transcriber.transcribe(tmp_path / "영상.mkv", "ko")
    assert result.spoken_language == "ko" and result.language_probability == 0.9
    assert result.segments[0].text == "안녕"
    assert result.segments[0].start == 0.5
    assert result.model == "custom-model"


@pytest.mark.parametrize("model", [None, 1, True, [], {}, "", " \t\n"])
def test_invalid_model_in_child_response_is_format_error(tmp_path, model):
    payload = {"spoken_language": "en", "segments": [], "model": model}
    transcriber = adapter(tmp_path, f"print({json.dumps(payload)!r})")
    with pytest.raises(TranscriberError) as caught:
        transcriber.transcribe(tmp_path / "video", None)
    assert caught.value.kind == "other"
    assert "받아쓰기 응답 형식 오류" in caught.value.detail


def test_missing_model_in_child_response_is_format_error(tmp_path):
    transcriber = adapter(tmp_path, 'print(\'{"spoken_language":"en","segments":[]}\')')
    with pytest.raises(TranscriberError) as caught:
        transcriber.transcribe(tmp_path / "video", None)
    assert "받아쓰기 응답 형식 오류" in caught.value.detail


@pytest.mark.parametrize("model", ["large-v3", "future-model"])
@pytest.mark.parametrize("no_speech", [False, True])
def test_child_entry_point_reports_the_downloaded_model(tmp_path, model, no_speech):
    transcriber = adapter(tmp_path, f'''
import sys
from types import SimpleNamespace
from my_video_manager import transcription
transcription.TRANSCRIPTION_MODEL = {model!r}
transcription.prepare_cuda_runtime = lambda *_: None
sys.modules['ctranslate2'] = SimpleNamespace(get_cuda_device_count=lambda: 1)
def download_model(name, **kwargs):
    assert name == {model!r}
    return 'fake-model-path'
def make_model(path, **kwargs):
    assert path == 'fake-model-path'
    segments = [] if {no_speech!r} else [SimpleNamespace(start=1, end=2, text='hello')]
    return SimpleNamespace(transcribe=lambda *a, **kw: (
        iter(segments), SimpleNamespace(language='en', language_probability=0.9)))
sys.modules['faster_whisper'] = SimpleNamespace(WhisperModel=make_model)
sys.modules['faster_whisper.audio'] = SimpleNamespace(decode_audio=lambda _: [])
sys.modules['faster_whisper.utils'] = SimpleNamespace(download_model=download_model)
raise SystemExit(transcription.main())
''')
    result = transcriber.transcribe(tmp_path / "video", None)
    assert result.model == model
    assert result.spoken_language == "en"
    assert bool(result.segments) is not no_speech


@pytest.mark.parametrize("kind, message", [("gpu_unavailable", "GPU"), ("decode", "음성"),
                                          ("model_download", "모델"), ("other", "받아쓰기")])
def test_nonzero_exit_uses_short_error_and_separate_detail(tmp_path, kind, message):
    transcriber = adapter(tmp_path, f"""
import json, sys
print('library warning', file=sys.stderr)
print(json.dumps({{'kind':{kind!r}, 'detail':'specific failure detail'}}), file=sys.stderr)
sys.exit(7)
""")
    with pytest.raises(TranscriberError) as caught:
        transcriber.transcribe(tmp_path / "video", None)
    assert caught.value.kind == kind
    assert message in str(caught.value)
    assert "specific failure detail" not in str(caught.value)
    assert caught.value.detail == "specific failure detail"


def test_native_failure_without_json_is_still_an_error(tmp_path):
    transcriber = adapter(tmp_path, "import sys; print('native crash', file=sys.stderr); sys.exit(99)")
    with pytest.raises(TranscriberError) as caught:
        transcriber.transcribe(tmp_path / "video", None)
    assert caught.value.kind == "other"
    assert caught.value.detail == "native crash"


@pytest.mark.parametrize("response", ["not json", "{}", '{"spoken_language":"en","segments":null}'])
def test_malformed_success_response_is_rejected(tmp_path, response):
    transcriber = adapter(tmp_path, f"print({response!r})")
    with pytest.raises(TranscriberError, match="받아쓰기"):
        transcriber.transcribe(tmp_path / "video", None)


def test_cancel_before_launch_does_not_start_child(tmp_path):
    signal = Event()
    signal.set()
    marker = tmp_path / "started"
    transcriber = adapter(tmp_path, "from pathlib import Path; import sys; Path(sys.argv[1]).touch()")
    with pytest.raises(TranscriberCancelled):
        transcriber.transcribe(marker, None, cancellation=signal)
    assert not marker.exists()


TREE_SCRIPT = """
import json, os, subprocess, sys, time
from pathlib import Path
marker = Path(sys.argv[1])
grandchild = subprocess.Popen([sys.executable, '-c',
    'import os,sys,time; from pathlib import Path; Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)',
    str(marker) + '.grandchild'])
marker.write_text(json.dumps([os.getpid(), grandchild.pid]))
time.sleep(60)
""".replace("time.sleep(60)", f"time.sleep({CHILD_READY_TIMEOUT * 2})")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job 프로세스 트리")
def test_cancel_terminates_child_and_grandchild(tmp_path):
    transcriber = adapter(tmp_path, TREE_SCRIPT)
    marker = tmp_path / "started"
    signal = Event()
    with ThreadPoolExecutor() as pool:
        result = pool.submit(transcriber.transcribe, marker, None, cancellation=signal)
        try:
            pids = json.loads(wait_file(marker))
            pids.append(int(wait_file(Path(str(marker) + ".grandchild"))))
        finally:
            signal.set()
        with pytest.raises(TranscriberCancelled):
            result.result(timeout=CHILD_READY_TIMEOUT)
    assert_processes_exited(pids)


@pytest.mark.skipif(sys.platform != "win32", reason="부모 강제 종료 시 Windows Job 정리")
def test_killing_only_parent_leaves_no_transcriber_processes(tmp_path):
    worker = tmp_path / "worker.py"
    worker.write_text(TREE_SCRIPT)
    parent_script = tmp_path / "parent.py"
    parent_script.write_text("""
import os, sys
from pathlib import Path
from my_video_manager.transcription import FasterWhisperTranscriber
Path(sys.argv[1] + '.parent').write_text(str(os.getpid()))
FasterWhisperTranscriber(Path(sys.argv[2]), command=(sys.executable, sys.argv[3])).transcribe(Path(sys.argv[1]), None)
""")
    marker = tmp_path / "ready"
    parent = subprocess.Popen([sys.executable, str(parent_script), str(marker), str(tmp_path), str(worker)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        parent_pid = int(wait_file(Path(str(marker) + ".parent")))
        pids = json.loads(wait_file(marker))
        pids.append(int(wait_file(Path(str(marker) + ".grandchild"))))
        # 트리 종료 옵션 없이 앱의 실제 interpreter 하나만 강제 종료한다.
        subprocess.run(["taskkill", "/PID", str(parent_pid), "/F"], check=True, capture_output=True)
        parent.communicate(timeout=CHILD_READY_TIMEOUT)
        assert_processes_exited(pids)
    finally:
        if parent.poll() is None:
            subprocess.run(["taskkill", "/PID", str(parent.pid), "/T", "/F"], capture_output=True)
        parent.communicate(timeout=CHILD_READY_TIMEOUT)
