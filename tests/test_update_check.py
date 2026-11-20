"""Public update checks with signed synthetic releases and no network access."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from urllib import error, request, response

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from my_video_manager.app_version import RELEASES_URL, current_version
from my_video_manager.core import AppCore
from my_video_manager import update_check, update_manifest
from my_video_manager.update_check import (
    AUTO_CHECK_KEY, LAST_CHECK_KEY, LATEST_RELEASE_URL, InstalledUpdateInfo,
)
from my_video_manager.update_http import UpdateCheckError, UrllibUpdateHttp


NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
FINGERPRINT = 'a' * 64
BASE = 'https://github.com/vananaHope/VideoCabinet/releases/download/v1.2.3'


class FakeClock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class FakeHttp:
    def __init__(self, key, *, version='1.2.3', patch=True):
        self.calls = []
        self.release = {'tag_name': f'v{version}', 'draft': False, 'prerelease': False}
        self.document = {
            'schema_version': 1, 'version': version, 'runtime_fingerprint': FINGERPRINT,
            'previous_runtime_fingerprint': FINGERPRINT if patch else None,
            'patch_available': patch,
            'patch': {'filename': 'patch.exe', 'size': 12, 'sha256': 'b' * 64} if patch else None,
            'full': {'filename': 'full.exe', 'size': 100, 'sha256': 'c' * 64},
        }
        self.key = key
        self.sign()
        self.failure = None
        self.fail_at = 1

    def sign(self):
        self.data = json.dumps(self.document).encode()
        self.signature = self.key.sign(self.data)

    def get(self, url, *, max_bytes):
        self.calls.append((url, max_bytes))
        if self.failure is not None and len(self.calls) == self.fail_at:
            raise self.failure
        if url == LATEST_RELEASE_URL:
            return json.dumps(self.release).encode()
        if url.endswith('.sig'):
            return self.signature
        return self.data


@pytest.fixture
def clock():
    return FakeClock()


def installed(version='1.0.0', fingerprint=FINGERPRINT):
    return lambda: InstalledUpdateInfo(version, fingerprint)


@pytest.fixture
def core(tmp_path, clock):
    return AppCore(media=object(), clock=clock, database=tmp_path / 'library.sqlite3',
                   update_installation=installed())


def reopen(core, clock, installation=None):
    """Same database, as after an app restart with the same (or a newly installed) app."""
    return AppCore(media=object(), clock=clock, database=core.database,
                   update_installation=installation or core.update_installation)


@pytest.fixture
def key(monkeypatch):
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(update_manifest, 'UPDATE_PUBLIC_KEY', key.public_key().public_bytes_raw())
    return key


@pytest.fixture
def http(key):
    return FakeHttp(key)


def check(core, http, *, version='1.0.0', fingerprint=FINGERPRINT):
    core.update_installation = installed(version, fingerprint)
    return core.check_for_update(http=http)


@pytest.mark.parametrize('version,fingerprint,patch,expected', [
    ('1.0.0', FINGERPRINT, True, 'patch'),  # skipping an intervening version is allowed
    ('1.2.2', FINGERPRINT, True, 'patch'),
    ('1.2.3', FINGERPRINT, True, 'none'),
    ('1.2.4', FINGERPRINT, True, 'none'),
    ('1.10.0', FINGERPRINT, True, 'none'),
    ('2.0.0', None, True, 'none'),
    ('1.0.0', None, True, 'full'),
    ('1.0.0', 'd' * 64, True, 'full'),
    ('1.0.0', FINGERPRINT, False, 'full'),
    ('1.0.0', None, False, 'full'),
])
def test_version_and_installed_runtime_decide_update(core, key, version, fingerprint, patch, expected):
    http = FakeHttp(key, patch=patch)
    result = check(core, http, version=version, fingerprint=fingerprint)
    assert result.kind == expected
    assert result.current_version == version
    assert result.latest_version == '1.2.3'
    assert result.download_size == {'patch': 12, 'full': 100, 'none': None}[expected]
    assert result.failure_reason is None
    assert result.checked_at == NOW
    assert result.release_url.endswith('/tag/v1.2.3')
    assert core.last_update_check() == result


def test_numeric_version_order_not_lexical(core, key):
    assert check(core, FakeHttp(key, version='1.10.0'), version='1.9.99').kind == 'patch'


def test_update_endpoints_use_public_release_repository():
    # 토큰 없는 앱 요청은 공개 Release 저장소(소스 저장소)로 간다.
    assert LATEST_RELEASE_URL == 'https://api.github.com/repos/vananaHope/VideoCabinet/releases/latest'
    assert RELEASES_URL == 'https://github.com/vananaHope/VideoCabinet/releases'


def test_one_tag_pins_both_metadata_requests(core, http):
    check(core, http)
    assert http.calls == [(LATEST_RELEASE_URL, 1024 * 1024),
                          (BASE + '/update-manifest.json', 64 * 1024),
                          (BASE + '/update-manifest.json.sig', 64)]


@pytest.mark.parametrize('damage,reason', [
    ('signature', 'invalid_signature'), ('data', 'invalid_signature'),
    ('short_signature', 'invalid_signature_format'), ('json', 'invalid_json'),
    ('format', 'invalid_format'), ('schema', 'unsupported_schema'),
    ('key', 'invalid_public_key'), ('tag_mismatch', 'release_version_mismatch'),
])
def test_untrusted_release_is_never_presented(core, http, monkeypatch, damage, reason):
    # A previous available update must be replaced, not retained on failure.
    assert check(core, http).kind == 'patch'
    if damage == 'signature':
        http.signature = Ed25519PrivateKey.generate().sign(http.data)
    elif damage == 'data':
        http.data += b' '
    elif damage == 'short_signature':
        http.signature = b'bad'
    elif damage == 'json':
        http.data = b'not JSON'
        http.signature = http.key.sign(http.data)
    elif damage == 'format':
        http.document['full']['size'] = -1
        http.sign()
    elif damage == 'schema':
        http.document['schema_version'] = 2
        http.sign()
    elif damage == 'key':
        monkeypatch.setattr(update_manifest, 'UPDATE_PUBLIC_KEY', b'')
    else:
        http.release['tag_name'] = 'v2.0.0'
    result = check(core, http)
    assert result.kind == 'failed' and result.failure_reason == reason
    assert result.latest_version is result.download_size is result.release_url is None
    assert core.last_update_check() == result


@pytest.mark.parametrize('release', [None, [], {}, {'tag_name': '../../evil'},
                                    {'tag_name': 'v1.2.3', 'draft': True, 'prerelease': False},
                                    {'tag_name': 'v1.2.3', 'draft': False, 'prerelease': True},
                                    {'tag_name': 'v01.2.3', 'draft': False, 'prerelease': False}])
def test_bad_release_metadata_stops_before_asset_fetch(core, http, release):
    http.release = release
    assert check(core, http).failure_reason == 'invalid_release'
    assert len(http.calls) == 1


@pytest.mark.parametrize('failure,reason', [(OSError('secret remote body'), 'network'),
                                          (TimeoutError('secret'), 'timeout'),
                                          (UpdateCheckError('http_403'), 'http_403'),
                                          (RuntimeError('secret adapter detail'), 'check_failed')])
@pytest.mark.parametrize('fail_at', [1, 2, 3])
def test_failed_fetch_is_recorded_and_app_remains_usable(core, clock, http, failure, reason, fail_at):
    http.failure, http.fail_at = failure, fail_at
    result = check(core, http)
    assert result.kind == 'failed' and result.failure_reason == reason
    assert result.checked_at == NOW
    assert core.last_update_check() == result
    assert 'secret' not in json.dumps(core.settings.get(LAST_CHECK_KEY))
    assert core.videos() == ()
    assert core.create_tag('after failure').name == 'after failure'
    reopened = reopen(core, clock)
    assert reopened.last_update_check() == result
    assert not reopened.should_check_for_update()


def test_auto_default_off_persistence_and_manual_override(core, clock, http):
    assert core.last_update_check() is None
    assert core.automatic_update_check_enabled()
    assert core.should_check_for_update()
    core.set_automatic_update_check_enabled(False)
    reopened = reopen(core, clock)
    assert not reopened.automatic_update_check_enabled()
    assert not reopened.should_check_for_update()
    assert check(reopened, http).kind == 'patch'
    assert len(http.calls) == 3
    reopened.set_automatic_update_check_enabled(True)
    assert not reopened.should_check_for_update()
    # Manual confirmation ignores the automatic minimum interval, too.
    assert check(reopened, http).kind == 'patch'
    assert len(http.calls) == 6


@pytest.mark.parametrize('elapsed,expected', [(0, False), (86399, False), (86400, True),
                                            (86401, True), (-1, True)])
def test_startup_interval_boundaries(core, clock, http, elapsed, expected):
    check(core, http)
    clock.now += timedelta(seconds=elapsed)
    assert core.should_check_for_update() is expected


def test_installed_version_change_marks_history_stale_and_allows_startup(core, clock, http):
    assert check(core, http).kind == 'patch'
    assert not core.last_update_check().stale
    clock.now += timedelta(hours=1)
    reopened = reopen(core, clock, installed('1.2.3'))
    history = reopened.last_update_check()
    assert history.stale
    assert history.current_version == '1.0.0'
    assert history.latest_version == '1.2.3'
    assert reopened.should_check_for_update()
    reopened.set_automatic_update_check_enabled(False)
    assert not reopened.should_check_for_update()
    assert check(reopened, http, version='1.2.3').kind == 'none'
    assert not reopened.last_update_check().stale
    reopened.set_automatic_update_check_enabled(True)
    assert not reopened.should_check_for_update()


@pytest.mark.parametrize('reason,hours', [
    ('network', 3), ('timeout', 3), ('http_500', 3), ('http_502', 3), ('http_503', 3),
    ('http_403', 24), ('http_404', 24), ('http_429', 24),
    ('invalid_signature', 24), ('invalid_format', 24),
])
def test_failure_retry_interval_boundaries(core, clock, http, reason, hours):
    http.failure = UpdateCheckError(reason)
    assert check(core, http).failure_reason == reason
    clock.now = NOW + timedelta(hours=hours) - timedelta(seconds=1)
    assert not core.should_check_for_update()
    clock.now += timedelta(seconds=1)
    assert core.should_check_for_update()


def test_empty_public_key_records_failure_without_http(core, http, monkeypatch):
    monkeypatch.setattr(update_manifest, 'UPDATE_PUBLIC_KEY', b'')
    result = check(core, http)
    assert result.kind == 'failed'
    assert result.failure_reason == 'invalid_public_key'
    assert core.last_update_check() == result
    assert not http.calls


def test_timezone_and_naive_clock(core, clock, http):
    clock.now = NOW.astimezone(timezone(timedelta(hours=9)))
    assert check(core, http).checked_at == NOW
    clock.now = datetime(2026, 10, 19, 12)
    assert core.should_check_for_update()
    assert check(core, http).checked_at.tzinfo == timezone.utc


@pytest.mark.parametrize('saved', [None, {}, [], 'broken', {'kind': 'full'},
                                   {'checked_at': 'wrong', 'kind': 'none'},
                                   {'checked_at': NOW.isoformat(), 'kind': 'unknown'},
                                   {'checked_at': NOW.replace(tzinfo=None).isoformat(), 'kind': 'failed'}])
def test_damaged_history_does_not_block_checks(core, saved):
    core.settings.set(LAST_CHECK_KEY, saved)
    assert core.last_update_check() is None
    assert core.should_check_for_update()


def test_invalid_boolean_uses_default_and_rejects_new_bad_value(core):
    core.settings.set(AUTO_CHECK_KEY, 'false')
    assert core.automatic_update_check_enabled()
    with pytest.raises(ValueError):
        core.set_automatic_update_check_enabled('false')


def test_real_installation_adapter_uses_package_version_without_subprocess(core):
    core.update_installation = None
    info = core.installed_update_info()
    assert info.version == current_version()
    assert info.runtime_fingerprint is None  # source checkout


def test_default_installation_is_read_once_per_core(core, http, monkeypatch):
    reads = []

    def counted():
        reads.append(None)
        return InstalledUpdateInfo('1.0.0', FINGERPRINT)

    monkeypatch.setattr(update_check, 'installed_update_info', counted)
    core.update_installation = None
    assert core.check_for_update(http=http).kind == 'patch'
    for _ in range(5):  # 설정 화면의 1초 갱신마다 부르는 경로
        core.installed_update_info()
        assert not core.last_update_check().stale
        core.should_check_for_update()
    assert len(reads) == 1


def test_bad_installed_version_is_failure_without_http(core, http):
    assert check(core, http, version='unknown').failure_reason == 'invalid_installed_version'
    assert not http.calls


def test_installation_read_failure_is_recorded(core, http):
    def unavailable():
        raise OSError('private installation path')
    core.update_installation = unavailable
    result = core.check_for_update(http=http)
    assert result.failure_reason == 'installation_unavailable'
    assert result.stale  # no installed version to compare; startup checks again
    assert core.last_update_check() == result
    assert core.should_check_for_update()
    assert not http.calls


def test_stale_uses_injected_installation_not_running_app(core, http):
    # The fixture's installed version differs from the source checkout's version.
    assert core.installed_update_info().version != current_version()
    result = check(core, http)
    assert not result.stale and not core.last_update_check().stale
    assert not core.should_check_for_update()
    core.update_installation = installed('1.2.3')
    assert core.last_update_check().stale
    assert core.should_check_for_update()


def test_stale_is_not_persisted_and_saved_value_is_ignored(core, http):
    check(core, http)
    saved = core.settings.get(LAST_CHECK_KEY)
    assert 'stale' not in saved
    core.settings.set(LAST_CHECK_KEY, {**saved, 'stale': True})
    assert not core.last_update_check().stale
    core.update_installation = installed('1.2.3')
    core.settings.set(LAST_CHECK_KEY, {**saved, 'stale': False})
    assert core.last_update_check().stale


@pytest.mark.parametrize('version,fingerprint,expected', [
    ('1.0.0', FINGERPRINT, 'patch'), ('1.0.0', None, 'full'), ('1.2.3', None, 'none'),
])
def test_successful_history_survives_reopen(core, clock, http, version, fingerprint, expected):
    result = check(core, http, version=version, fingerprint=fingerprint)
    reopened = reopen(core, clock)
    assert reopened.last_update_check() == result
    assert result.kind == expected


def test_read_only_update_apis_do_not_construct_transport(core, monkeypatch):
    from my_video_manager import update_check
    def forbidden():
        pytest.fail('A settings/startup query must not construct HTTP transport')
    monkeypatch.setattr(update_check, 'UrllibUpdateHttp', forbidden)
    assert core.last_update_check() is None
    assert core.should_check_for_update()
    assert core.automatic_update_check_enabled()
    core.set_automatic_update_check_enabled(False)
    assert not core.should_check_for_update()


def test_pending_network_does_not_lock_ordinary_app_operations(core, http):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    entered, release = Event(), Event()
    class WaitingHttp:
        def get(self, url, *, max_bytes):
            entered.set()
            assert release.wait(10)
            return http.get(url, max_bytes=max_bytes)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(check, core, WaitingHttp())
        try:
            assert entered.wait(10)
            assert core.create_tag('during check').name == 'during check'
            assert core.last_update_check() is None
        finally:
            release.set()
        assert future.result(timeout=10).kind == 'patch'


class FakeOpener:
    def __init__(self, *steps):
        self.steps = iter(steps)
        self.calls = []

    def open(self, req, *, timeout):
        self.calls.append((req, timeout))
        step = next(self.steps)
        if isinstance(step, Exception):
            raise step
        return step


def reply(data=b'ok', *, headers=None, status=200):
    result = response.addinfourl(BytesIO(data), headers or {}, LATEST_RELEASE_URL, status)
    result.msg = 'test response'
    return result


def redirect(url):
    return error.HTTPError(LATEST_RELEASE_URL, 302, 'secret', {'Location': url}, BytesIO())


def test_http_response_limits_headers_timeout_and_cleanup():
    body = reply(b'abc', headers={'Content-Length': '3'})
    opener = FakeOpener(body)
    assert UrllibUpdateHttp(opener=opener).get(LATEST_RELEASE_URL, max_bytes=3) == b'abc'
    req, timeout = opener.calls[0]
    assert 0 < timeout <= 10
    assert req.get_header('User-agent')
    assert req.get_header('Authorization') is None
    assert req.get_header('Accept-encoding') == 'identity'
    assert body.closed


@pytest.mark.parametrize('body,headers,reason', [(b'1234', {}, 'response_too_large'),
                                              (b'', {'Content-Length': '4'}, 'response_too_large'),
                                              (b'a', {'Content-Length': '2'}, 'invalid_response'),
                                              (b'a', {'Content-Length': '-1'}, 'invalid_response')])
def test_http_size_cap_and_truncated_response(body, headers, reason):
    stream = reply(body, headers=headers)
    with pytest.raises(UpdateCheckError, match=f'^{reason}$'):
        UrllibUpdateHttp(opener=FakeOpener(stream)).get(LATEST_RELEASE_URL, max_bytes=3)
    assert stream.closed


@pytest.mark.parametrize('target', ['http://github.com/x', 'file:///C:/secret',
                                    'https://example.org/x', 'https://github.com.evil.test/x',
                                    'https://name:pass@github.com/x', 'https://github.com:444/x'])
def test_http_redirect_rejects_unsafe_destination(target):
    redirected = redirect(target)
    opener = FakeOpener(redirected)
    with pytest.raises(UpdateCheckError, match='^unsafe_redirect$'):
        UrllibUpdateHttp(opener=opener).get(LATEST_RELEASE_URL, max_bytes=100)
    assert len(opener.calls) == 1
    assert redirected.closed


def test_http_redirect_budget():
    opener = FakeOpener(*(redirect('https://github.com/x') for _ in range(4)))
    with pytest.raises(UpdateCheckError, match='^too_many_redirects$'):
        UrllibUpdateHttp(opener=opener).get(LATEST_RELEASE_URL, max_bytes=100)
    assert len(opener.calls) == 4


def test_production_opener_routes_redirects_through_policy(monkeypatch):
    # Exercise urllib's real handler chain entirely in memory, without sockets.
    calls = []
    class OfflineHTTPS(request.HTTPSHandler):
        def https_open(self, req):
            calls.append(req.full_url)
            if len(calls) == 1:
                return reply(headers={'Location': 'https://release-assets.githubusercontent.com/x'}, status=302)
            return reply(b'signed bytes')
    build_opener = request.build_opener
    monkeypatch.setattr(request, 'build_opener', lambda *handlers: build_opener(*handlers, OfflineHTTPS()))
    assert UrllibUpdateHttp().get(LATEST_RELEASE_URL, max_bytes=100) == b'signed bytes'
    assert calls == [LATEST_RELEASE_URL, 'https://release-assets.githubusercontent.com/x']


@pytest.mark.parametrize('exception,reason', [
    (error.HTTPError(LATEST_RELEASE_URL, 404, 'secret', {}, BytesIO()), 'http_404'),
    (error.HTTPError(LATEST_RELEASE_URL, 429, 'secret', {}, BytesIO()), 'http_429'),
    (error.URLError('secret'), 'network'),
    (error.URLError(TimeoutError()), 'timeout'),
    (TimeoutError('secret'), 'timeout'),
])
def test_http_errors_are_stable_sanitized_codes(exception, reason):
    with pytest.raises(UpdateCheckError, match=f'^{reason}$'):
        UrllibUpdateHttp(opener=FakeOpener(exception)).get(LATEST_RELEASE_URL, max_bytes=100)


def test_http_slow_response_deadline_closes_response(monkeypatch):
    from my_video_manager import update_http
    ticks = iter([0, 0, 0, 0, 31])
    monkeypatch.setattr(update_http.time, 'monotonic', lambda: next(ticks))
    stream = reply(b'one slow chunk')
    with pytest.raises(UpdateCheckError, match='^timeout$'):
        UrllibUpdateHttp(opener=FakeOpener(stream)).get(LATEST_RELEASE_URL, max_bytes=100)
    assert stream.closed
