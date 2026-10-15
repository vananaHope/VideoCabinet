from datetime import datetime
import errno
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread
import zipfile

import pytest

from my_video_manager.core import AppCore
from my_video_manager.cuda_runtime import PreparationError, RuntimeDownloadAdapter, SubtitlePreparation
from my_video_manager.runtime_assets import CUDA_WHEELS, DownloadAsset


def wheel_bytes(files=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as wheel:
        for name, content in (files or {"nvidia/cublas/bin/test.dll": b"dll" * 800000,
                                       "nvidia/cublas/include/test.h": b"not installed"}).items():
            wheel.writestr(name, content)
    return output.getvalue()


@pytest.fixture
def server():
    class Handler(BaseHTTPRequestHandler):
        bodies = {"/cuda.whl": wheel_bytes(), "/model.bin": b"fake whisper"}
        requests = []
        interrupted = False
        status = 200
        stall = None
        unstalled = Event()

        def log_message(self, *args):
            pass

        def do_GET(self):
            self.requests.append(self.path)
            if self.stall == "headers":
                self.unstalled.wait(2)
                return
            if self.status != 200:
                self.send_error(self.status)
                return
            body = self.bodies[self.path]
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.stall == "body":
                self.unstalled.wait(2)
                return
            self.wfile.write(body[:len(body) // 2] if self.interrupted else body)
            self.close_connection = True

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    def asset(name):
        body = Handler.bodies["/" + name]
        return DownloadAsset(name, f"http://127.0.0.1:{httpd.server_port}/{name}",
                             hashlib.sha256(body).hexdigest(), len(body))
    yield Handler, asset
    Handler.unstalled.set()
    httpd.shutdown()
    thread.join()
    httpd.server_close()


def preparation(tmp_path, server, **kwargs):
    _, asset = server
    return SubtitlePreparation(tmp_path, gpu_available=lambda: True,
                               cuda_assets=(asset("cuda.whl"),), model_assets=(asset("model.bin"),),
                               model_revision="test-revision", **kwargs)


def test_prepare_and_reuse_via_public_core_api(tmp_path, server):
    core = AppCore(media=None, clock=datetime.now, database=tmp_path / "library.sqlite3")
    events = []
    service = preparation(core.database.parent, server)
    ready = core.prepare_subtitle_support(preparation=service, progress=events.append)
    assert (ready.cuda_directories[0] / "test.dll").read_bytes() == b"dll" * 800000
    assert not list(ready.cuda_directories[0].rglob("*.h"))
    assert (ready.model_directory / "model.bin").read_bytes() == b"fake whisper"
    assert ready.model_directory.is_relative_to(tmp_path / "models")
    assert {event.phase for event in events} == {"probe", "download", "verify", "extract", "ready"}
    assert all(0 <= event.completed <= event.total for event in events)
    requests = server[0].requests[:]
    events.clear()
    assert core.prepare_subtitle_support(preparation=preparation(tmp_path, server), progress=events.append) == ready
    assert server[0].requests == requests
    assert {event.phase for event in events} == {"probe", "reuse", "ready"}


def test_network_disconnect_keeps_partial_then_retry_cleans_it(tmp_path, server):
    server[0].interrupted = True
    service = preparation(tmp_path, server)
    with pytest.raises(PreparationError) as caught:
        service.prepare()
    assert caught.value.kind == "network"
    assert list(tmp_path.rglob("*.part"))
    assert not list(tmp_path.rglob("ready.json"))
    stale = next(tmp_path.rglob("*.partial")) / "stale.dll"
    stale.write_bytes(b"incomplete")
    server[0].interrupted = False
    ready = service.prepare()
    assert not list(tmp_path.rglob("*.partial"))
    assert not (ready.cuda_directories[0] / "stale.dll").exists()


@pytest.mark.parametrize("phase", ["download", "verify", "extract"])
def test_cancellation_during_each_cuda_phase_then_retry(tmp_path, server, phase):
    signal = Event()
    def cancel(event):
        if event.phase == phase and event.completed:
            signal.set()
    service = preparation(tmp_path, server)
    with pytest.raises(PreparationError) as caught:
        service.prepare(cancellation=signal, progress=cancel)
    assert caught.value.kind == "cancelled"
    assert not list(tmp_path.rglob("ready.json"))
    signal.clear()
    assert service.prepare(cancellation=signal).cuda_directories


def test_model_cancel_preserves_ready_cuda_and_retries_model(tmp_path, server):
    signal = Event()
    def cancel(event):
        if event.asset == "model.bin" and event.phase == "download" and event.completed:
            signal.set()
    service = preparation(tmp_path, server)
    with pytest.raises(PreparationError, match="취소"):
        service.prepare(cancellation=signal, progress=cancel)
    assert len(list(tmp_path.rglob("ready.json"))) == 1
    signal.clear()
    service.prepare(cancellation=signal)
    assert server[0].requests.count("/cuda.whl") == 1
    assert server[0].requests.count("/model.bin") == 2


@pytest.mark.parametrize("which", ["cuda_assets", "model_assets"])
def test_hash_mismatch_never_publishes_failed_group(tmp_path, server, which):
    service = preparation(tmp_path, server)
    name = "/" + getattr(service, which)[0].name
    original = server[0].bodies[name]
    server[0].bodies[name] = original[:-1] + bytes([original[-1] ^ 1])
    with pytest.raises(PreparationError) as caught:
        service.prepare()
    assert caught.value.kind == "hash_mismatch"
    assert len(list(tmp_path.rglob("ready.json"))) == (which == "model_assets")
    server[0].bodies[name] = original
    assert service.prepare().model_directory.is_dir()
    assert not list(tmp_path.rglob("*.partial"))


@pytest.mark.parametrize("method", ["download", "verify", "extract"])
def test_disk_full_in_each_adapter_operation(tmp_path, server, method):
    adapter = RuntimeDownloadAdapter()
    def fail(*args):
        raise OSError(errno.ENOSPC, "disk full")
    setattr(adapter, method, fail)
    with pytest.raises(PreparationError) as caught:
        preparation(tmp_path, server, adapter=adapter).prepare()
    assert caught.value.kind == "disk_full"
    assert not list(tmp_path.rglob("ready.json"))


def test_space_preflight_and_cancel_before_io(tmp_path, server):
    class NoSpace(RuntimeDownloadAdapter):
        def require_space(self, target, size):
            raise PreparationError("disk_full")
    with pytest.raises(PreparationError, match="저장 공간"):
        preparation(tmp_path, server, adapter=NoSpace()).prepare()
    signal = Event()
    signal.set()
    with pytest.raises(PreparationError, match="취소"):
        preparation(tmp_path, server).prepare(cancellation=signal)
    assert server[0].requests == []


@pytest.mark.parametrize("available", [False, RuntimeError("driver missing")])
def test_no_gpu_does_not_start_download(tmp_path, server, available):
    service = preparation(tmp_path, server)
    def probe():
        if isinstance(available, Exception):
            raise available
        return available
    service.gpu_available = probe
    with pytest.raises(PreparationError) as caught:
        service.prepare()
    assert caught.value.kind == "gpu_unavailable"
    assert not server[0].requests


@pytest.mark.parametrize("files", [{"../outside.dll": b"bad"}, {"a.dll": b"a", "sub/a.dll": b"b"},
                                   {"include/test.h": b"header"}])
def test_invalid_wheel_is_not_published(tmp_path, server, files):
    server[0].bodies["/cuda.whl"] = wheel_bytes(files)
    with pytest.raises(PreparationError) as caught:
        preparation(tmp_path, server).prepare()
    assert caught.value.kind == "invalid_archive"
    assert not list(tmp_path.rglob("ready.json"))
    assert not (tmp_path / "outside.dll").exists()


def test_missing_ready_dll_triggers_download_again(tmp_path, server):
    service = preparation(tmp_path, server)
    ready = service.prepare()
    (ready.cuda_directories[0] / "test.dll").unlink()
    service.prepare()
    assert server[0].requests.count("/cuda.whl") == 2
    assert server[0].requests.count("/model.bin") == 1


@pytest.mark.parametrize("status", [404, 500, 503])
def test_http_error_distinguishes_server_failure(tmp_path, server, status):
    server[0].status = status
    with pytest.raises(PreparationError) as caught:
        preparation(tmp_path, server).prepare()
    kind = 'server' if status >= 500 else 'network'
    assert caught.value.kind == kind
    assert str(status) in caught.value.detail
    assert 'cuda.whl' in caught.value.detail
    restarted = preparation(tmp_path, server)
    assert restarted.status()['kind'] == kind
    assert str(status) in restarted.status()['detail']
    log = (tmp_path / 'logs/subtitle-preparation.log').read_text(encoding='utf-8')
    assert str(status) in log and 'cuda.whl' in log


@pytest.mark.parametrize("stall", ["headers", "body"])
def test_unresponsive_server_is_network(tmp_path, server, monkeypatch, stall):
    from my_video_manager import cuda_runtime
    original = cuda_runtime.urllib.request.urlopen
    timeouts = []
    def short_timeout(url, *, timeout):
        timeouts.append(timeout)
        return original(url, timeout=0.05)
    monkeypatch.setattr(cuda_runtime.urllib.request, "urlopen", short_timeout)
    server[0].stall = stall
    with pytest.raises(PreparationError) as caught:
        preparation(tmp_path, server).prepare()
    assert caught.value.kind == "network"
    assert timeouts == [10]


def test_matching_hf_cache_is_hashed_and_reused_without_model_download(tmp_path, server):
    service = preparation(tmp_path, server)
    cached = tmp_path / "models/models--Systran--faster-whisper-large-v3/snapshots/test-revision"
    cached.mkdir(parents=True)
    (cached / "model.bin").write_bytes(server[0].bodies["/model.bin"])
    partial = tmp_path / 'models/large-v3/test-revision.partial'
    partial.mkdir(parents=True)
    (partial / 'model.bin.part').write_bytes(b'incomplete')
    events = []
    result = service.prepare(progress=events.append)
    assert result.model_directory == cached
    assert not partial.exists()
    assert (cached / "ready.json").is_file()
    assert any(event.phase == "verify" and event.asset == "model.bin" for event in events)
    assert "/model.bin" not in server[0].requests
    assert service.prepared() == result
    events.clear()
    assert service.prepare(progress=events.append) == result
    assert not any(event.phase == "verify" for event in events)


@pytest.mark.parametrize("wrong", [b"x", b"bad whisper!"])
def test_invalid_hf_cache_is_preserved_and_model_downloaded(tmp_path, server, wrong):
    service = preparation(tmp_path, server)
    cached = tmp_path / "models/models--Systran--faster-whisper-large-v3/snapshots/test-revision"
    cached.mkdir(parents=True)
    (cached / "model.bin").write_bytes(wrong)
    result = service.prepare()
    assert result.model_directory != cached
    assert (cached / "model.bin").read_bytes() == wrong
    assert "/model.bin" in server[0].requests
    assert not (cached / "ready.json").exists()


@pytest.mark.parametrize("script,expected", [("print('{\"available\": true}')", True),
                                            ("print('{\"available\": false}')", False)])
def test_gpu_probe_is_child_only(script, expected):
    from my_video_manager.cuda_runtime import cuda_gpu_available
    assert cuda_gpu_available(command=(sys.executable, "-c", script)) is expected


@pytest.mark.parametrize("script,timeout", [("raise SystemExit(99)", 5), ("print('broken')", 5),
                                           ("import time; time.sleep(10)", 0.1)])
def test_gpu_probe_failure_is_isolated(script, timeout):
    from my_video_manager.cuda_runtime import cuda_gpu_available
    with pytest.raises(PreparationError) as caught:
        cuda_gpu_available(command=(sys.executable, "-c", script), timeout=timeout)
    assert caught.value.kind == "gpu_unavailable"


def test_native_cuda_imports_are_confined_to_transcription_child():
    import ast
    root = Path(__file__).parents[1] / "src"
    imports = []
    for source in root.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            native_modules = {"ctranslate2", "faster_whisper"}
            native_import = ((isinstance(node, ast.Import) and any(alias.name.split(".")[0] in native_modules for alias in node.names))
                             or (isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in native_modules))
            if native_import:
                imports.append(source.name)
                assert any(isinstance(function, ast.FunctionDef)
                           and function.name in ("transcribe_on_gpu", "probe_cuda_device")
                           and node in ast.walk(function) for function in tree.body)
    assert imports and set(imports) == {"transcription.py"}


def test_cuda_pins_match_pyproject_versions():
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    for dependency, asset in zip(project["project"]["optional-dependencies"]["cuda"], CUDA_WHEELS):
        package, version = dependency.split(";")[0].split("==")
        assert asset.name == f"{package.replace('-', '_')}-{version}-py3-none-win_amd64.whl"
        assert asset.url.startswith("https://files.pythonhosted.org/")
        assert len(asset.sha256) == 64


def test_two_processes_share_completed_downloads(tmp_path, server):
    from dataclasses import asdict
    _, asset = server
    specification = json.dumps([asdict(asset("cuda.whl")), asdict(asset("model.bin"))])
    script = """
import json, sys
from pathlib import Path
from my_video_manager.cuda_runtime import SubtitlePreparation
from my_video_manager.runtime_assets import DownloadAsset
cuda, model = [DownloadAsset(**item) for item in json.loads(sys.argv[2])]
SubtitlePreparation(Path(sys.argv[1]), gpu_available=lambda: True,
    cuda_assets=(cuda,), model_assets=(model,), model_revision='test-revision').prepare()
"""
    processes = [subprocess.Popen([sys.executable, "-c", script, str(tmp_path), specification],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    try:
        for process in processes:
            _, error = process.communicate(timeout=30)
            assert process.returncode == 0, error.decode(errors="replace")
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate()
    assert server[0].requests.count("/cuda.whl") == 1
    assert server[0].requests.count("/model.bin") == 1


def test_overall_progress_and_file_order_include_reused_assets(tmp_path, server):
    events = []
    service = preparation(tmp_path, server)
    service.prepare(progress=events.append)
    total = sum(asset.size for asset in service.cuda_assets + service.model_assets)
    assert all(event.overall_total == total and event.file_count == 2 for event in events)
    amounts = [event.overall_completed for event in events]
    assert amounts == sorted(amounts)
    first_model = next(e for e in events if e.phase == 'download' and e.asset == 'model.bin')
    assert first_model.file_index == 2
    assert first_model.overall_completed == service.cuda_assets[0].size
    assert events[-1].overall_completed == total
    events.clear()
    service.prepare(progress=events.append)
    assert [e.file_index for e in events if e.phase == 'reuse'] == [1, 2]
    assert events[-1].overall_completed == total
    assert preparation(tmp_path, server).status()['kind'] == 'ready'


def test_cancel_is_durable_and_explicit_retry_clears_it(tmp_path, server):
    cancellation = Event()
    cancellation.set()
    with pytest.raises(PreparationError, match='취소'):
        preparation(tmp_path, server).prepare(cancellation=cancellation)
    restarted = preparation(tmp_path, server)
    assert restarted.status()['kind'] == 'cancelled'
    assert server[0].requests == []
    restarted.prepare()
    assert preparation(tmp_path, server).status()['kind'] == 'ready'


def test_log_preserves_long_detail_but_redacts_credentials_and_home(tmp_path, server):
    from my_video_manager.subtitle_preparation_ui import failure_message
    detail = f'{Path.home()}/model.bin\nhttps://example.org/model?token=secret-url Authorization: Bearer secret-auth\n' + '원인' * 300
    service = preparation(tmp_path, server)
    def fail():
        raise PreparationError('network', detail)
    service.gpu_available = fail
    with pytest.raises(PreparationError):
        service.prepare()
    log = (tmp_path / 'logs/subtitle-preparation.log').read_text(encoding='utf-8')
    status = service.status()
    screen = failure_message(**status)
    for content in (log, status['detail'], screen):
        assert 'secret-url' not in content and 'secret-auth' not in content
        assert str(Path.home()) not in content
        assert '~/model.bin' in content
    assert '원인' * 300 in log
    assert '원인' * 300 not in screen and screen.endswith('…')


def test_log_failure_does_not_replace_preparation_error(tmp_path, server):
    (tmp_path / 'logs').write_text('not a directory')
    server[0].status = 503
    with pytest.raises(PreparationError) as caught:
        preparation(tmp_path, server).prepare()
    assert caught.value.kind == 'server'
    assert preparation(tmp_path, server).status()['kind'] == 'server'


def test_preparation_log_is_rotated_and_excluded_from_backup(tmp_path, server):
    service = preparation(tmp_path, server)
    def fail():
        raise PreparationError('network', 'long detail ' * 10000)
    service.gpu_available = fail
    for _ in range(7):
        with pytest.raises(PreparationError):
            service.prepare()
    logs = list((tmp_path / 'logs').iterdir())
    assert len(logs) == 3
    assert all(path.stat().st_size <= 256 * 1024 for path in logs)
    core = AppCore(media=None, clock=datetime.now, database=tmp_path / 'library.sqlite3')
    archive = tmp_path / 'backup.zip'
    core.create_backup(archive, include_thumbnails=True)
    with zipfile.ZipFile(archive) as bundle:
        assert all(not name.startswith('logs/') and not name.endswith('.log') for name in bundle.namelist())

@pytest.mark.parametrize('location', ['runtime/cuda/old.partial', 'models/large-v3/old.partial'])
def test_upgrade_partial_waits_for_retry(tmp_path, server, location):
    (tmp_path / location).mkdir(parents=True)
    service = preparation(tmp_path, server)
    assert service.status()['kind'] == 'interrupted'
    assert server[0].requests == []
    service.prepare()
    assert service.status()['kind'] == 'ready'


@pytest.mark.parametrize('history', ['{broken', '[]', '{"kind":"cancelled","message":"","detail":""}'])
def test_ready_manifest_wins_over_bad_history(tmp_path, server, history):
    service = preparation(tmp_path, server)
    service.prepare()
    requests = server[0].requests[:]
    (tmp_path / 'subtitle-preparation.json').write_text(history)
    assert service.status()['kind'] == 'ready'
    assert server[0].requests == requests


def test_ready_history_write_failure_preserves_success(tmp_path, server, monkeypatch):
    from my_video_manager.subtitle_preparation_state import PreparationHistory
    save = PreparationHistory.save
    def fail_ready(self, kind, *args, **kwargs):
        if kind == 'ready':
            raise PermissionError(errno.EACCES, 'denied', str(Path.home() / 'ready.json'))
        return save(self, kind, *args, **kwargs)
    monkeypatch.setattr(PreparationHistory, 'save', fail_ready)
    service = preparation(tmp_path, server)
    assert service.prepare() == service.prepared()
    assert service.status()['kind'] == 'ready'
    log = (tmp_path / 'logs/subtitle-preparation.log').read_text(encoding='utf-8')
    assert 'ERROR' in log and '~' in log and str(Path.home()) not in log


def test_oserror_paths_redacted_in_banner_history_and_log(tmp_path, server):
    from my_video_manager.subtitle_preparation_ui import failure_message
    class Denied(RuntimeDownloadAdapter):
        def download(self, *args):
            raise PermissionError(errno.EACCES, 'denied', str(Path.home() / 'private-model.bin'))
    service = preparation(tmp_path, server, adapter=Denied())
    with pytest.raises(PreparationError) as caught:
        service.prepare()
    banner = failure_message(caught.value.kind, str(caught.value), caught.value.detail)
    history = json.loads((tmp_path / 'subtitle-preparation.json').read_text(encoding='utf-8'))
    log = (tmp_path / 'logs/subtitle-preparation.log').read_text(encoding='utf-8')
    for content in (banner, history['detail'], log):
        assert str(Path.home()) not in content
        assert str(Path.home()).replace('\\', '\\\\') not in content
        assert '~' in content and 'private-model.bin' in content


def test_userinfo_and_bare_hf_token_redacted(tmp_path, server):
    from my_video_manager.subtitle_preparation_ui import failure_message
    service = preparation(tmp_path, server)
    def fail():
        raise PreparationError('network', 'https://alice:password@host/model?secret=query hf_AbC123secret')
    service.gpu_available = fail
    with pytest.raises(PreparationError):
        service.prepare()
    status = service.status()
    log = (tmp_path / 'logs/subtitle-preparation.log').read_text(encoding='utf-8')
    for content in (failure_message(**status), status['detail'], log):
        assert 'host/model' in content
        assert all(secret not in content for secret in ('alice', 'password', 'query', 'hf_AbC123secret'))


@pytest.mark.parametrize('interrupted', [False, True])
def test_cancel_reason_is_durable_and_logged_as_one_info_line(tmp_path, server, interrupted):
    from my_video_manager.cuda_runtime import PreparationCancellation
    signal = PreparationCancellation()
    signal.interrupt() if interrupted else signal.set()
    service = preparation(tmp_path, server)
    with pytest.raises(PreparationError):
        service.prepare(cancellation=signal)
    expected = 'interrupted' if interrupted else 'cancelled'
    assert preparation(tmp_path, server).status()['kind'] == expected
    lines = (tmp_path / 'logs/subtitle-preparation.log').read_text(encoding='utf-8').splitlines()
    assert len(lines) == 1 and 'INFO' in lines[0] and 'ERROR' not in lines[0]


def test_abrupt_exit_marker_prevents_automatic_retry(tmp_path, server):
    service = preparation(tmp_path, server)
    def abrupt_exit():
        raise SystemExit(1)
    service.gpu_available = abrupt_exit
    with pytest.raises(SystemExit):
        service.prepare()
    assert preparation(tmp_path, server).status()['kind'] == 'interrupted'
    assert server[0].requests == []


def test_cache_verification_uses_bytes_and_redownload_resets_progress(tmp_path, server, monkeypatch):
    from my_video_manager import cuda_runtime
    monkeypatch.setattr(cuda_runtime, '_CHUNK', 4)
    service = preparation(tmp_path, server)
    cached = tmp_path / 'models/models--Systran--faster-whisper-large-v3/snapshots/test-revision'
    cached.mkdir(parents=True)
    (cached / 'model.bin').write_bytes(b'x' * service.model_assets[0].size)
    events = []
    service.prepare(progress=events.append)
    model = [event for event in events if event.asset == 'model.bin']
    baseline = service.cuda_assets[0].size
    assert model[0].phase == 'verify' and model[0].overall_completed == baseline
    assert model[1].overall_completed == baseline + 4
    downloads = [event for event in model if event.phase == 'download']
    assert downloads[0].overall_completed == baseline
    assert downloads[1].overall_completed == baseline + 4
    assert downloads[-1].overall_completed == baseline + service.model_assets[0].size
