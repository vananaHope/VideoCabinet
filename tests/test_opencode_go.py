from dataclasses import replace
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Event, Thread, enumerate as threads
import sys
import time
import socket
from importlib.metadata import version
import traceback
from urllib.error import URLError

import pytest

from my_video_manager.opencode_go import (
    BASE_URL, DEFAULT_MODEL, HTTPResponse, OpenCodeGoError,
    OpenCodeGoTranslator, UrllibTransport, USER_AGENT,
)
from my_video_manager.translation_models import ModelPolicy, TranslationModelChoice
from my_video_manager.secret_store import Secret, SecretStore
from my_video_manager.subtitles import TranscriptLine
from my_video_manager.translation import TranslationCancelled, TranslationError
from my_video_manager.translation_cli import translation_prompt, translation_schema


KEY = "test-secret-must-not-leak-1234"
LINES = (TranscriptLine("one", 0, 1, "Hello"), TranscriptLine("two", 1, 2, "World"))
NOW = datetime(2026, 10, 15, 2, tzinfo=timezone.utc)


def completion(content=None, finish="stop"):
    if content is None:
        content = json.dumps({"lines": [{"id": "two", "text": "세계"}, {"id": "one", "text": "안녕"}]})
    return {"choices": [{"finish_reason": finish, "message": {"content": content}}]}


class FakeHTTP:
    def __init__(self, payload=None, *, status=200, headers=None, error=None):
        self.response = HTTPResponse(status, headers or {}, json.dumps(
            completion() if payload is None else payload).encode())
        self.error = error
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.error:
            raise self.error
        return self.response


def adapter(http, key=Secret(KEY), **kwargs):
    return OpenCodeGoTranslator(lambda: key, session_id="translation-job-42", transport=http,
                                clock=lambda: NOW, **kwargs)


def test_remaining_batch_reuses_contract_headers_and_stable_session():
    http = FakeHTTP()
    translator = adapter(http)
    result = translator.translate(LINES, "en")
    assert [(line.id, line.text) for line in result] == [("one", "안녕"), ("two", "세계")]
    translator.translate(LINES, "en")
    for method, url, request in http.calls:
        assert (method, url) == ("POST", BASE_URL + "/chat/completions")
        assert request["headers"]["Authorization"] == "Bearer " + KEY
        assert request["headers"]["User-Agent"] == USER_AGENT
        assert request["headers"]["x-opencode-session"] == "translation-job-42"
        payload = json.loads(request["body"])
        assert payload["model"] == DEFAULT_MODEL
        prompt = payload["messages"][0]["content"]
        assert prompt.startswith(translation_prompt(LINES, "en"))
        assert json.JSONDecoder().raw_decode(prompt.split("OUTPUT_JSON_SCHEMA:\n")[1])[0] == translation_schema(LINES)
        assert payload["stream"] is False
        assert payload["response_format"] == {"type": "json_object"}
        assert "json" in prompt and "Example:" in prompt
    http.response = HTTPResponse(200, {}, json.dumps(completion(
        json.dumps({"lines": [{"id": "two", "text": "남은 줄"}]}))).encode())
    assert translator.translate(LINES[1:], "en")[0].id == "two"
    assert '"id": "one"' not in json.loads(http.calls[-1][2]["body"])["messages"][0]["content"]


def test_translation_defaults_allow_ten_minutes_but_checks_stay_short():
    http = FakeHTTP()
    translator = adapter(http)
    translator.translate(LINES, "en")
    assert http.calls[-1][2]["timeout"] == 600
    assert UrllibTransport().read_timeout == 600
    assert UrllibTransport().connect_timeout == 10
    translator.check_key()
    assert 0 < http.calls[-1][2]["timeout"] <= 60
    http.response = HTTPResponse(200, {}, b'{"data":[]}')
    translator.models()
    assert 0 < http.calls[-1][2]["timeout"] <= 60


@pytest.mark.parametrize("failure", [TimeoutError(KEY), socket.timeout(KEY), URLError(TimeoutError(KEY))])
def test_injected_timeout_is_safe_shrinkable_and_logged_once(failure, caplog):
    with pytest.raises(OpenCodeGoError) as raised:
        adapter(FakeHTTP(error=failure)).translate(LINES, "en")
    assert raised.value.kind == "response_timeout"
    assert str(raised.value) == "OpenCode Go 응답 시간이 초과되었습니다."
    assert str(TranslationError("response_timeout", "safe detail")) == str(raised.value)
    assert raised.value.shrinkable
    assert raised.value.__context__ is None
    assert KEY not in "".join(traceback.format_exception(raised.value)) + caplog.text
    assert len(caplog.records) == 1


@pytest.mark.parametrize("status,payload,kind", [
    (429, {}, "usage_limit"), (401, {"error": KEY}, "authentication"),
    (403, {"error": "usage_limit " + KEY}, "authentication"),
    (402, {"error": {"code": "quota_exceeded"}}, "billing"),
    (503, {"error": KEY}, "server"), (400, {"error": "bad request " + KEY}, "request_rejected"),
    (302, {}, "other"),
])
def test_http_errors_are_safe_and_usage_limit_matches_queue(status, payload, kind, caplog):
    http = FakeHTTP(payload, status=status)
    with pytest.raises(TranslationError) as raised:
        adapter(http).translate(LINES, "en")
    error = raised.value
    assert error.kind == kind
    assert KEY not in str(error) + repr(error) + error.detail + caplog.text
    assert error.__context__ is None
    assert len(http.calls) == 1
    assert len(caplog.records) == 1


@pytest.mark.parametrize("headers,payload,expected", [
    ({"Retry-After": "120"}, {}, datetime(2026, 10, 15, 2, 2, tzinfo=timezone.utc)),
    ({"retry-after": "Thu, 15 Oct 2026 03:00:00 GMT"}, {}, datetime(2026, 10, 15, 3, tzinfo=timezone.utc)),
    ({}, {"error": {"retry_at": "2026-10-15T12:00:00+09:00"}}, datetime(2026, 10, 15, 3, tzinfo=timezone.utc)),
    ({"Retry-After": "nonsense"}, {"error": {"reset_at": "2026-10-15T03:00:00Z"}}, datetime(2026, 10, 15, 3, tzinfo=timezone.utc)),
    ({"Retry-After": "-1"}, {}, None),
    ({"Retry-After": "9" * 100}, {}, None),
    ({}, {"error": {"retry_at": "2026-10-15T03:00:00"}}, None),
])
def test_usage_retry_time(headers, payload, expected):
    with pytest.raises(OpenCodeGoError) as raised:
        adapter(FakeHTTP(payload, status=429, headers=headers)).translate(LINES, "en")
    assert raised.value.retry_at == expected


@pytest.mark.parametrize("payload", [
    [], {}, {"choices": []}, {"choices": [None]}, completion("not json " + KEY),
    completion('{"lines":[]}'), completion('{"lines":[{"id":"one","text":"안녕"}]}'),
    completion('{"lines":[{"id":"one","text":"안녕"},{"id":"one","text":"중복"}]}'),
    completion('{"lines":[{"id":"one","text":""},{"id":"two","text":"세계"}]}'),
    completion(f'{{"lines":[{{"id": "one", "text":"안녕", "{KEY}":1}}]}}'),
    completion(finish="length"), completion(finish="tool_calls"),
])
def test_malformed_responses_are_safe(payload):
    http = FakeHTTP(payload)
    with pytest.raises(OpenCodeGoError) as raised:
        adapter(http).translate(LINES, "en")
    assert raised.value.kind == "format"
    assert KEY not in "".join(traceback.format_exception(raised.value))
    assert raised.value.__context__ is None
    assert len(http.calls) == 1


def test_missing_key_connection_and_provider_errors_are_distinct():
    http = FakeHTTP()
    with pytest.raises(OpenCodeGoError, match="등록") as raised:
        adapter(http, None).models()
    assert raised.value.kind == "missing_key" and not http.calls
    with pytest.raises(OpenCodeGoError) as raised:
        adapter(FakeHTTP(error=OSError(KEY))).models()
    assert raised.value.kind == "connection"
    assert raised.value.__context__ is None and KEY not in repr(raised.value)
    def broken():
        raise RuntimeError(KEY)
    with pytest.raises(OpenCodeGoError) as raised:
        OpenCodeGoTranslator(broken, session_id="42").models()
    assert raised.value.kind == "key_storage"
    assert raised.value.__context__ is None


def test_models_filter_other_api_families_and_apply_updated_policy_to_default():
    rows = [{"id": model} for model in (DEFAULT_MODEL, "glm-5.2", "claude-haiku-5-5", "new-unknown", DEFAULT_MODEL)]
    translator = adapter(FakeHTTP({"data": rows}))
    assert [model.id for model in translator.models()] == [DEFAULT_MODEL, "glm-5.2", "new-unknown"]
    policy = translator.model_policy()
    assert policy.training is False and policy.retention_days == 0
    assert not policy.needs_warning(date(2026, 10, 31))
    assert policy.needs_warning(date(2026, 11, 1))
    changed = replace(policy, training=True)
    choice = replace(translator.model_choice(), policy=changed)
    models = adapter(FakeHTTP({"data": rows}), choices=(choice,)).models()
    assert models[0].policy.needs_warning(date(2026, 10, 15))
    assert models[1].policy.needs_warning(date(2026, 10, 15))
    assert ModelPolicy("unknown").needs_warning(date.today())


@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": [None]}, {"data": [{"id": 1}]}])
def test_bad_model_list_is_format_error(payload):
    with pytest.raises(OpenCodeGoError) as raised:
        adapter(FakeHTTP(payload)).models()
    assert raised.value.kind == "format"


@pytest.mark.parametrize("status,expected", [(200, "valid"), (401, "authentication"),
    (403, "authentication"), (429, "usage_limit"), (500, "server")])
def test_key_check_is_one_explicit_minimal_paid_model_request(status, expected):
    http = FakeHTTP(completion("", finish="length"), status=status)
    translator = adapter(http, model="glm-5.2")
    assert not http.calls
    assert translator.check_key().status == expected
    assert len(http.calls) == 1
    assert json.loads(http.calls[0][2]["body"]) == {
        "model": DEFAULT_MODEL, "messages": [{"role": "user", "content": 'Reply OK.'}],
        "max_tokens": 16, "stream": False,
    }
    assert adapter(FakeHTTP(error=OSError(KEY))).check_key().status == "connection"
    assert adapter(FakeHTTP({})).check_key().status == "other"
    assert adapter(FakeHTTP(), None).check_key().status == "missing_key"


def test_cancel_before_and_after_request_and_empty_batch():
    event, http = Event(), FakeHTTP()
    event.set()
    for operation in (lambda: adapter(http).translate(LINES, "en", cancellation=event),
                      lambda: adapter(http).models(cancellation=event),
                      lambda: adapter(http).check_key(cancellation=event)):
        with pytest.raises(TranslationCancelled):
            operation()
    assert not http.calls
    event.clear()
    class Cancels(FakeHTTP):
        def request(self, *args, **kwargs):
            event.set()
            return super().request(*args, **kwargs)
    with pytest.raises(TranslationCancelled):
        adapter(Cancels()).translate(LINES, "en", cancellation=event)
    assert adapter(http).translate((), "en") == () and not http.calls


@pytest.mark.parametrize("model", ["claude-haiku-5-5", "gpt-6-luna"])
def test_non_chat_models_rejected_without_network(model):
    with pytest.raises(ValueError):
        adapter(FakeHTTP(), model=model)


@pytest.fixture
def server():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.server.requests.append((self.path, dict(self.headers), self.rfile.read(
                int(self.headers.get("Content-Length", 0)))))
            status, headers, body = self.server.reply
            if getattr(self.server, "delay", None) == "headers":
                self.server.waiting.set()
                self.server.release.wait(5)
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            if getattr(self.server, "delay", None) == "body":
                self.wfile.write(body[:1])
                self.wfile.flush()
                self.server.waiting.set()
                self.server.release.wait(5)
                body = body[1:]
            try:
                if getattr(self.server, "delay", None) == "drip":
                    for byte in body:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        if self.server.release.wait(0.05):
                            break
                else:
                    self.wfile.write(body)
            except OSError:
                pass
        do_GET = do_POST
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.requests = []
    server.waiting, server.release = Event(), Event()
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.release.set()
        server.shutdown()
        server.server_close()
        thread.join()


class LocalTransport:
    def __init__(self, port):
        self.port = port
    def request(self, method, url, **kwargs):
        assert url.startswith(BASE_URL)
        return UrllibTransport().request(method, url.replace(BASE_URL,
            f"http://127.0.0.1:{self.port}/v1", 1), **kwargs)


@pytest.mark.parametrize("status,body,kind", [
    (200, json.dumps(completion()).encode(), None), (429, b"{}", "usage_limit"),
    (401, KEY.encode(), "authentication"), (200, b"not-json", "format"),
])
def test_real_http_transport_with_local_fake_server(server, status, body, kind):
    server.reply = status, {"Retry-After": "30"}, body
    translator = adapter(LocalTransport(server.server_port))
    if kind:
        with pytest.raises(OpenCodeGoError) as raised:
            translator.translate(LINES, "en")
        assert raised.value.kind == kind
    else:
        assert translator.translate(LINES, "en")[0].text == "안녕"
    assert len(server.requests) == 1
    assert server.requests[0][0] == "/v1/chat/completions"


@pytest.mark.parametrize("timeout", [1, 10])
def test_real_transport_connection_failure_and_redirect_does_not_forward_key(server, caplog, timeout):
    server.reply = 307, {"Location": f"http://127.0.0.1:{server.server_port}/stolen"}, b""
    with pytest.raises(OpenCodeGoError) as raised:
        adapter(LocalTransport(server.server_port)).models()
    assert raised.value.kind == "other" and len(server.requests) == 1
    server.shutdown()
    server.server_close()
    caplog.clear()
    with pytest.raises(OpenCodeGoError) as raised:
        adapter(LocalTransport(server.server_port), timeout=timeout).models()
    assert raised.value.kind == "connection"
    assert not raised.value.shrinkable
    assert len(caplog.records) == 1


@pytest.mark.skipif(sys.platform != "win32", reason="실제 Windows 사용자 DPAPI")
def test_key_rotation_and_deletion_apply_to_next_request_without_caching(tmp_path):
    store, http = SecretStore(tmp_path), FakeHTTP()
    translator = OpenCodeGoTranslator(store.read, session_id="same-job", transport=http)
    assert translator.check_key().status == "missing_key"
    store.save(KEY)
    assert translator.check_key().status == "valid"
    store.save("replacement-5678")
    assert translator.check_key().status == "valid"
    assert http.calls[0][2]["headers"]["Authorization"] == "Bearer " + KEY
    assert http.calls[1][2]["headers"]["Authorization"] == "Bearer replacement-5678"
    store.delete()
    assert translator.check_key().status == "missing_key"
    assert len(http.calls) == 2


def test_successful_subtitle_limit_words_are_never_classified_as_failure():
    content = json.dumps({"lines": [{"id": "one", "text": "HTTP 429 사용량 한도"},
                                   {"id": "two", "text": "authentication"}]})
    assert adapter(FakeHTTP(completion(content))).translate(LINES, "en")[0].text == "HTTP 429 사용량 한도"


def test_model_response_and_key_check_objects_do_not_repr_sensitive_server_data():
    http = FakeHTTP({"data": [{"id": DEFAULT_MODEL, "secret": KEY}]})
    translator = adapter(http)
    assert KEY not in repr(translator.models()) + repr(translator) + repr(http.response)
    assert KEY not in repr(adapter(FakeHTTP({"error": KEY}, status=401)).check_key())


@pytest.mark.parametrize("phase", ["headers", "body"])
@pytest.mark.parametrize("operation", ["translate", "models", "check_key"])
def test_cancellation_during_delayed_request_returns_in_under_one_second(server, phase, operation):
    body = json.dumps(completion()).encode()
    server.reply = 200, {"Content-Length": str(len(body))}, body
    server.delay = phase
    cancel, finished, errors = Event(), Event(), []
    translator = adapter(LocalTransport(server.server_port))
    def run():
        try:
            if operation == "translate":
                translator.translate(LINES, "en", cli="opencode_go", cancellation=cancel)
            else:
                getattr(translator, operation)(cancellation=cancel)
        except Exception as error:
            errors.append(error)
        finally:
            finished.set()
    thread = Thread(target=run, daemon=True)
    thread.start()
    assert server.waiting.wait(2)
    started = time.monotonic()
    cancel.set()
    assert finished.wait(0.9), "취소 후 호출이 1초 이내 반환해야 한다"
    assert time.monotonic() - started < 1
    assert len(errors) == 1 and isinstance(errors[0], TranslationCancelled)
    thread.join(0.1)
    remaining = [thread for thread in threads() if thread.name == "opencode-go-http"]
    assert not remaining, "".join(traceback.format_stack(sys._current_frames()[remaining[0].ident])[-5:])


@pytest.mark.parametrize("wrap", [lambda text: text, lambda text: "```json\n" + text + "\n```",
                                 lambda text: "\n```\r\n" + text + "\r\n```\n"])
def test_exact_single_outer_fence_uses_existing_parser(wrap):
    text = completion()["choices"][0]["message"]["content"]
    assert adapter(FakeHTTP(completion(wrap(text)))).translate(LINES, "en", cli="ignored")[0].text == "안녕"


@pytest.mark.parametrize("wrap", [lambda text: "설명\n```json\n" + text + "\n```",
                                 lambda text: "```json\n" + text + "\n```\n설명",
                                 lambda text: "```json\n```json\n" + text + "\n```\n```"])
def test_explanations_and_nested_fences_remain_format_errors(wrap):
    text = completion()["choices"][0]["message"]["content"]
    with pytest.raises(OpenCodeGoError) as raised:
        adapter(FakeHTTP(completion(wrap(text)))).translate(LINES, "en")
    assert raised.value.kind == "format"


def test_model_choice_represents_other_providers_unknown_policy_and_capabilities():
    cli_choice = TranslationModelChoice("codex", "custom-model", "직접 입력")
    assert cli_choice.policy is None and not cli_choice.needs_warning(date.today())
    assert cli_choice.reasoning_supported is None and cli_choice.source is None
    assert cli_choice.reasoning_efforts is None
    supported = replace(cli_choice, reasoning_efforts=("low", "medium", "high"))
    assert supported.reasoning_supported is True
    assert supported.reasoning_efforts == ("low", "medium", "high")
    assert replace(cli_choice, reasoning_efforts=()).reasoning_supported is False
    http = FakeHTTP()
    translator = adapter(http, model="custom-model")
    assert translator.model_choice().needs_warning(date.today())
    translator.translate(LINES, "en")
    payload = json.loads(http.calls[0][2]["body"])
    assert payload["model"] == "custom-model" and "response_format" not in payload
    assert "reasoning_effort" not in payload and "reasoning" not in payload
    default = adapter(http).model_choice()
    assert default.provider == "opencode_go" and default.is_default and default.label == "DeepSeek V4.1 Flash"
    assert default.source and default.policy.source
    custom = replace(default, model_id="custom-json", is_default=False)
    adapter(http, model="custom-json", choices=(custom,)).translate(LINES, "en")
    assert json.loads(http.calls[-1][2]["body"])["response_format"] == {"type": "json_object"}


def test_session_headers_are_scoped_to_model_requests_and_independent_key_checks():
    http = FakeHTTP()
    translator = adapter(http)
    translator.translate(LINES, "en")
    translator.translate(LINES, "en")
    translator.check_key()
    translator.check_key()
    other = OpenCodeGoTranslator(lambda: Secret(KEY), session_id="another-job", transport=http)
    other.translate(LINES, "en")
    sessions = [call[2]["headers"]["x-opencode-session"] for call in http.calls]
    assert sessions[0] == sessions[1]
    assert len(set(sessions)) == 4
    http.response = HTTPResponse(200, {}, b'{"data": []}')
    translator.models()
    assert "x-opencode-session" not in http.calls[-1][2]["headers"]
    assert USER_AGENT == "my-video-manager/" + version("my-video-manager")


@pytest.mark.parametrize("status,payload,kind,diagnostic", [
    (400, {"error": "json_schema unsupported " + KEY}, "request_rejected", "JSON Schema"),
    (400, {"error": "Prompt must contain the word 'json' " + KEY}, "request_rejected", "json 안내"),
    (400, {"model": DEFAULT_MODEL}, "request_rejected", "요청을 거부"),
    (402, {"error": "usage_limit reached " + KEY}, "billing", "결제"),
    (429, {"error": KEY}, "usage_limit", "한도"),
])
def test_local_server_request_rejections_and_limits_are_not_retried(server, status, payload, kind, diagnostic):
    server.reply = status, {"Retry-After": "30"}, json.dumps(payload).encode()
    with pytest.raises(OpenCodeGoError) as raised:
        adapter(LocalTransport(server.server_port)).translate(LINES, "en")
    assert raised.value.kind == kind and diagnostic in raised.value.detail
    assert KEY not in raised.value.detail + repr(raised.value)
    assert len(server.requests) == 1 and server.requests[0][0] == "/v1/chat/completions"
    if kind == "usage_limit":
        assert raised.value.retry_at == datetime(2026, 10, 15, 2, 0, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize("stop", ["cancel", "deadline", "connect_timeout"])
def test_tls_handshake_stop_closes_socket_without_sending_credentials(stop, caplog):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(3)
    received, closed, finished, cancel = Event(), Event(), Event(), Event()
    traffic, errors = [], []
    def serve():
        with listener.accept()[0] as peer:
            peer.settimeout(3)
            traffic.append(peer.recv(8192))  # ClientHello 뒤 서버 handshake 응답을 지연한다.
            received.set()
            try:
                while peer.recv(8192):
                    pass
            except ConnectionResetError:
                pass
            closed.set()
    server_thread = Thread(target=serve, daemon=True)
    server_thread.start()
    def request():
        try:
            transport = UrllibTransport(connect_timeout=0.2 if stop == "connect_timeout" else 10)
            transport.request("POST", f"https://127.0.0.1:{listener.getsockname()[1]}/v1/test",
                headers={"Authorization": "Bearer " + KEY}, body=b"subtitle",
                timeout=0.5 if stop == "deadline" else 60, cancellation=cancel)
        except Exception as error:
            errors.append(error)
        finally:
            finished.set()
    worker = Thread(target=request, daemon=True)
    worker.start()
    try:
        assert received.wait(2)
        started = time.monotonic()
        if stop == "cancel":
            cancel.set()
        assert finished.wait(0.9)
        assert time.monotonic() - started < 1
        assert closed.wait(0.5)
        if stop == "cancel":
            assert isinstance(errors[0], TranslationCancelled)
            assert not caplog.records
        else:
            assert isinstance(errors[0], OpenCodeGoError)
            assert errors[0].kind == "connection"
            assert not errors[0].shrinkable
            assert len(caplog.records) == 1
        assert KEY.encode() not in b"".join(traffic)
        assert not any(thread.name == "opencode-go-http" for thread in threads())
    finally:
        cancel.set()
        listener.close()
        worker.join(1)
        server_thread.join(1)


@pytest.mark.parametrize("phase", ["headers", "body", "drip"])
def test_delayed_server_respects_total_deadline_without_retries(server, phase, caplog):
    server.reply = 200, {}, json.dumps(completion()).encode()
    server.delay = phase
    started = time.monotonic()
    with pytest.raises(OpenCodeGoError) as raised:
        adapter(LocalTransport(server.server_port), timeout=0.2).translate(LINES, "en")
    assert raised.value.kind == "response_timeout"
    assert raised.value.shrinkable
    assert time.monotonic() - started < 1
    assert len(server.requests) == 1
    assert len(caplog.records) == 1
    assert not any(thread.name == "opencode-go-http" for thread in threads())


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_read_timeout_is_distinct_from_connection_and_logs_once(server, phase, tmp_path):
    import logging
    from my_video_manager.app_logging import file_log_handler

    class ShortReadTransport:
        def request(self, method, url, **kwargs):
            return UrllibTransport(read_timeout=0.1).request(
                method, url.replace(BASE_URL, f"http://127.0.0.1:{server.server_port}"), **kwargs)

    server.reply = 200, {}, json.dumps(completion()).encode()
    server.delay = phase
    path = tmp_path / "app.log"
    handler = file_log_handler(path)
    logger = logging.getLogger("my_video_manager")
    logger.addHandler(handler)
    try:
        with pytest.raises(OpenCodeGoError) as raised:
            adapter(ShortReadTransport()).translate(LINES, "en")
        assert raised.value.kind == "response_timeout"
        assert raised.value.shrinkable
        assert raised.value.__context__ is None
        assert not any(thread.name == "opencode-go-http" for thread in threads())
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert "OpenCode Go 응답 시간이 초과되었습니다." in lines[0]
        assert KEY not in lines[0]
    finally:
        logger.removeHandler(handler)
        handler.close()

@pytest.mark.parametrize('status,payload,kind', [
    (400, {'error': {'message': 'bad request'}}, 'request_rejected'),
    (402, {'error': 'payment required'}, 'billing'),
    (404, {'error': 'not found'}, 'other'),
    (500, {'error': 'temporary failure'}, 'server'),
    (200, {'error': {'message': 'subscription expired'}}, 'billing'),
    (200, {}, 'other'),
])
def test_key_diagnostics_reach_result_and_app_log(tmp_path, status, payload, kind):
    import logging
    from my_video_manager.app_logging import file_log_handler
    path = tmp_path / 'logs/app.log'
    handler = file_log_handler(path)
    logger = logging.getLogger('my_video_manager')
    logger.addHandler(handler)
    try:
        result = adapter(FakeHTTP(payload, status=status)).check_key()
        assert result.status == kind
        assert result.error.status == status
        assert f'HTTP {status}' in result.message
        assert result.message in path.read_text(encoding='utf-8')
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_diagnostics_redact_before_truncation_and_repr(caplog):
    from pathlib import Path
    raw = f'{KEY} sk-other-secret hf_PrivateToken {Path.home()} Authorization: Basic abcdef\n' + 'x' * 200
    http = FakeHTTP({'error': {'message': raw}}, status=400)
    result = adapter(http).check_key()
    assert len(result.error.server_message) == 160
    with pytest.raises(OpenCodeGoError) as raised:
        adapter(http).translate(LINES, 'en')
    assert raised.value.detail == result.message
    output = repr(result) + repr(raised.value) + caplog.text
    for secret in (KEY, 'sk-other-secret', 'hf_PrivateToken', str(Path.home()), 'abcdef'):
        assert secret not in output


def test_key_storage_failure_has_own_guidance_and_log(caplog):
    def broken():
        raise OSError('sk-storage-secret')
    result = OpenCodeGoTranslator(broken, session_id='test', transport=FakeHTTP()).check_key()
    assert result.status == 'key_storage'
    assert '키를 다시 입력' in result.message
    assert result.message in caplog.text
    assert 'sk-storage-secret' not in caplog.text + repr(result)
