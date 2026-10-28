from importlib import metadata
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from my_video_manager import adapters, cuda_runtime, transcription


@pytest.mark.parametrize("name", ["ffmpeg", "ffprobe"])
@pytest.mark.parametrize("frozen,bundled", [(False, True), (True, True), (True, False)])
def test_ffmpeg_resolution_preserves_source_and_prefers_installed_copy(tmp_path, monkeypatch, name, frozen, bundled):
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))
    monkeypatch.setattr(adapters.shutil, "which", lambda _: "from-path.exe")
    expected = tmp_path / "ffmpeg" / f"{name}.exe"
    if bundled:
        expected.parent.mkdir()
        expected.touch()
    assert adapters.executable(name) == (str(expected) if frozen and bundled else "from-path.exe")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DLL 탐색(os.add_dll_directory)과 winget")
def test_missing_bundle_falls_back_to_winget(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(adapters.shutil, "which", lambda _: None)
    candidate = tmp_path / "Microsoft/WinGet/Packages/Gyan.FFmpeg_test/bin/ffmpeg.exe"
    candidate.parent.mkdir(parents=True)
    candidate.touch()
    assert adapters.executable("ffmpeg") == str(candidate)
    with pytest.raises(RuntimeError, match="ffprobe"):
        adapters.executable("ffprobe")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DLL 탐색(os.add_dll_directory)과 winget")
@pytest.mark.parametrize("frozen", [False, True])
def test_mpv_directory_registration(tmp_path, monkeypatch, frozen):
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))
    monkeypatch.setattr(adapters, "__file__", str(tmp_path / "src/my_video_manager/adapters.py"))
    runtime = tmp_path / ("mpv" if frozen else ".runtime/mpv")
    runtime.mkdir(parents=True)
    registered = []
    monkeypatch.setattr(os, "add_dll_directory", lambda path: registered.append(path) or path)
    monkeypatch.setenv("PATH", "original")
    adapters._prepare_mpv_runtime.cache_clear()
    try:
        assert adapters._prepare_mpv_runtime() == str(runtime)
        assert registered == [str(runtime)]
        assert os.environ["PATH"].startswith(str(runtime) + os.pathsep)
    finally:
        adapters._prepare_mpv_runtime.cache_clear()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DLL 탐색(os.add_dll_directory)과 winget")
@pytest.mark.parametrize("frozen", [False, True])
def test_cuda_loader_uses_source_packages_or_explicit_data_directory(tmp_path, monkeypatch, frozen):
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    source = tmp_path / "venv/cuda.dll"
    data = tmp_path / "custom-data"
    installed = (data / "runtime/cuda/a", data / "runtime/cuda/b")
    monkeypatch.setattr(metadata, "distribution", lambda _: SimpleNamespace(files=[source], locate_file=lambda f: f))
    seen = []
    monkeypatch.setattr(cuda_runtime, "cuda_runtime_directories", lambda directory: seen.append(directory) or installed)
    monkeypatch.setattr(os, "add_dll_directory", lambda path: path)
    monkeypatch.setenv("PATH", "original")
    transcription.prepare_cuda_runtime.cache_clear()
    try:
        result = transcription.prepare_cuda_runtime(data)
        assert result == (tuple(map(str, installed)) if frozen else (str(source.parent),) * 2)
        assert seen == ([data] if frozen else [])
    finally:
        transcription.prepare_cuda_runtime.cache_clear()


@pytest.mark.parametrize("frozen", [False, True])
def test_transcription_model_path_keeps_source_cache_and_uses_prepared_installation(tmp_path, monkeypatch, frozen):
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    calls = []
    model_directory = tmp_path / "models"
    prepared_path = model_directory / "large-v3-turbo/pinned"
    monkeypatch.setattr(transcription, "prepare_cuda_runtime", lambda data: calls.append(("cuda", data)))
    monkeypatch.setitem(sys.modules, "ctranslate2", SimpleNamespace(get_cuda_device_count=lambda: 1))
    class Model:
        def __init__(self, path, **kwargs):
            calls.append(("model", path))
        def transcribe(self, audio, **kwargs):
            return [], SimpleNamespace(language="ko", language_probability=1)
    def download(name, *, cache_dir, revision):
        calls.append(("download", name, cache_dir, revision))
        return "source-cache"
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Model))
    monkeypatch.setitem(sys.modules, "faster_whisper.audio", SimpleNamespace(decode_audio=lambda path: []))
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", SimpleNamespace(download_model=download))
    class Preparation:
        def __init__(self, data):
            calls.append(("prepare", data))
        def prepared(self):
            return SimpleNamespace(model_directory=prepared_path)
    monkeypatch.setattr(cuda_runtime, "SubtitlePreparation", Preparation)
    result = transcription.transcribe_on_gpu(tmp_path / "video.mkv", model_directory, "ko")
    assert result.spoken_language == "ko"
    assert result.model == "large-v3-turbo"
    assert ("cuda", tmp_path) in calls
    if frozen:
        assert ("prepare", tmp_path) in calls
        assert ("model", str(prepared_path)) in calls
        assert not any(call[0] == "download" for call in calls)
    else:
        assert ("download", "large-v3-turbo", str(model_directory), transcription.WHISPER_REVISION) in calls
        assert ("model", "source-cache") in calls
        assert not any(call[0] == "prepare" for call in calls)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DLL 탐색(os.add_dll_directory)과 winget")
def test_missing_bundled_mpv_keeps_system_search(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))
    monkeypatch.setenv("PATH", "original")
    monkeypatch.setattr(os, "add_dll_directory", lambda path: pytest.fail("없는 폴더 등록"))
    adapters._prepare_mpv_runtime.cache_clear()
    try:
        assert adapters._prepare_mpv_runtime() is None
        assert os.environ["PATH"] == "original"
    finally:
        adapters._prepare_mpv_runtime.cache_clear()


def test_unprepared_frozen_transcription_never_downloads(tmp_path, monkeypatch):
    from my_video_manager.subtitles import TranscriberError
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(cuda_runtime.SubtitlePreparation, "prepare", lambda *a, **kw: pytest.fail("자식 다운로드"))
    monkeypatch.setattr(transcription, "prepare_cuda_runtime", lambda *a: pytest.fail("준비 전 CUDA 등록"))
    with pytest.raises(TranscriberError) as caught:
        transcription.transcribe_on_gpu(tmp_path / "video.mkv", tmp_path / "models", "ko")
    assert caught.value.kind == "preparation_required"
    assert "준비" in str(caught.value)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('frozen', [False, True])
def test_application_starts_model_cleanup_once_only_for_installation(tmp_path, monkeypatch, frozen):
    from my_video_manager import __main__
    calls = []
    signal = SimpleNamespace(connect=lambda callback: None)
    app = SimpleNamespace(setWindowIcon=lambda icon: None, setQuitOnLastWindowClosed=lambda value: None,
                          aboutToQuit=signal, exec=lambda: calls.append('exec') or 0,
                          property=lambda name: False)
    window = SimpleNamespace(tray=SimpleNamespace(open=lambda: None), show=lambda: calls.append('show'))
    instance = SimpleNamespace(start=lambda: True, close=lambda: None, activated=signal)
    monkeypatch.setattr(sys, 'frozen', frozen, raising=False)
    monkeypatch.setattr(sys, 'argv', ['app.exe', '--data-dir', str(tmp_path)])
    modules = {
        'PySide6.QtWidgets': SimpleNamespace(QApplication=lambda args: app, QMessageBox=SimpleNamespace(
            critical=lambda *args: pytest.fail(str(args)))),
        'PySide6.QtGui': SimpleNamespace(QIcon=lambda path: None),
        'my_video_manager.ui': SimpleNamespace(MainWindow=lambda core: window),
        'my_video_manager.single_instance': SimpleNamespace(SingleInstance=lambda *args: instance),
        'my_video_manager.web_thumbnail': SimpleNamespace(register_thumbnail_scheme=lambda: None),
        'my_video_manager.theme': SimpleNamespace(apply_theme=lambda app: None),
        'my_video_manager.app_logging': SimpleNamespace(configure_app_logging=lambda directory: None),
        'my_video_manager.backup_recovery': SimpleNamespace(open_with_backup_recovery=lambda *args: object()),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(cuda_runtime.SubtitlePreparation, 'start_cleanup_if_ready',
                        lambda self: calls.append(('cleanup', self.data_directory)))
    assert __main__.main() == 0
    assert calls == (['show', ('cleanup', tmp_path), 'exec'] if frozen else ['show', 'exec'])
