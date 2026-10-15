from dataclasses import replace
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Event, Thread
import sys
import traceback

import pytest

from my_video_manager.opencode_go import (
    BASE_URL, DEFAULT_MODEL, HTTPResponse, ModelPolicy, OpenCodeGoError,
    OpenCodeGoTranslator, UrllibTransport, USER_AGENT,
)
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
        assert json.loads(prompt.split("OUTPUT_JSON_SCHEMA:\n")[1]) == translation_schema(LINES)
        assert payload["stream"] is False
        assert "response_format" not in payload  # 서버 지원을 가정하지 않는다.
    http.response = HTTPResponse(200, {}, json.dumps(completion(
        json.dumps({"lines": [{"id": "two", "text": "남은 줄"}]}))).encode())
    assert translator.translate(LINES[1:], "en")[0].id == "two"
    assert '"id": "one"' not in json.loads(http.calls[-1][2]["body"])["messages"][0]["content"]


@pytest.mark.parametrize("status,payload,kind", [
    (429, {}, "usage_limit"), (401, {"error": KEY}, "authentication"),
    (403, {"error": "usage_limit " + KEY}, "authentication"),
    (402, {"error": {"code": "quota_exceeded"}}, "usage_limit"),
    (503, {"error": KEY}, "other"), (400, {"error": "bad request " + KEY}, "other"),
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
    assert [model.id for model in translator.models()] == [DEFAULT_MODEL, "glm-5.2"]
    policy = translator.model_policy()
    assert policy.training is False and policy.retention_days == 0
    assert not policy.needs_warning(date(2026, 10, 31))
    assert policy.needs_warning(date(2026, 11, 1))
    changed = replace(policy, training=True)
    models = adapter(FakeHTTP({"data": rows}), policies=(changed,)).models()
    assert models[0].policy.needs_warning(date(2026, 10, 15))
    assert models[1].policy.needs_warning(date(2026, 10, 15))
    assert ModelPolicy("unknown").needs_warning(date.today())


@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": [None]}, {"data": [{"id": 1}]}])
def test_bad_model_list_is_format_error(payload):
    with pytest.raises(OpenCodeGoError) as raised:
        adapter(FakeHTTP(payload)).models()
    assert raised.value.kind == "format"


@pytest.mark.parametrize("status,expected", [(200, "valid"), (401, "authentication"),
    (403, "authentication"), (429, "usage_limit"), (500, "other")])
def test_key_check_is_one_explicit_minimal_paid_model_request(status, expected):
    http = FakeHTTP(completion("", finish="length"), status=status)
    translator = adapter(http, model="glm-5.2")
    assert not http.calls
    assert translator.check_key().status == expected
    assert len(http.calls) == 1
    assert json.loads(http.calls[0][2]["body"]) == {
        "model": DEFAULT_MODEL, "messages": [{"role": "user", "content": "Reply OK."}],
        "max_tokens": 1, "stream": False,
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


@pytest.mark.parametrize("model", ["claude-haiku-5-5", "gpt-6-luna", "unknown"])
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
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)
        do_GET = do_POST
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.requests = []
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
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


def test_real_transport_connection_failure_and_redirect_does_not_forward_key(server):
    server.reply = 307, {"Location": f"http://127.0.0.1:{server.server_port}/stolen"}, b""
    with pytest.raises(OpenCodeGoError) as raised:
        adapter(LocalTransport(server.server_port)).models()
    assert raised.value.kind == "other" and len(server.requests) == 1
    server.shutdown()
    server.server_close()
    with pytest.raises(OpenCodeGoError) as raised:
        adapter(LocalTransport(server.server_port), timeout=1).models()
    assert raised.value.kind == "connection"


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
