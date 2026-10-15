"""OpenCode Go 구독 API. 선택/대기열/UI 연결 없이 남은 줄 묶음을 번역한다."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import http.client
import io
from importlib import metadata
import json
import re
import socket
from threading import Event, Lock, Thread
import time
from typing import Callable, Mapping, Protocol
from uuid import uuid4
from urllib.error import HTTPError
from urllib.request import HTTPHandler, HTTPSHandler, HTTPRedirectHandler, Request, build_opener

from .secret_store import Secret
from .translation import TranslationCancelled, TranslationError
from .translation_cli import (classify_cli_failure, parse_translation_response,
                              translation_prompt, translation_schema)
from .translation_models import (ModelPolicy, TranslationModelChoice, DEFAULT_MODEL,
                                 MODEL_CHOICES, MODEL_POLICIES, CHAT_MODELS, NON_CHAT_MODELS)


BASE_URL = "https://opencode.ai/inference/go/v1"
def _user_agent():
    try:
        version = metadata.version("my-video-manager")
    except Exception:
        version = "0.1.0"
    return "my-video-manager/" + version


USER_AGENT = _user_agent()




@dataclass(frozen=True)
class KeyCheckResult:
    status: str
    retry_at: datetime | None = None


class OpenCodeGoError(TranslationError):
    """현재 보류 분류와 호환되며 후속 연결에서 사용할 UTC retry_at을 제공한다."""

    def __init__(self, kind: str, *, retry_at: datetime | None = None, diagnostic: str | None = None):
        messages = {
            "missing_key": "OpenCode Go 키가 등록되지 않았습니다.",
            "authentication": "OpenCode Go 키 또는 접근 권한을 확인하세요.",
            "connection": "OpenCode Go에 연결하지 못했습니다.",
            "format": "OpenCode Go 응답 형식이 올바르지 않습니다.",
            "usage_limit": "OpenCode Go 구독 사용량 한도로 보류했습니다.",
            "key_storage": "OpenCode Go 저장된 키를 읽지 못했습니다.",
            "other": "OpenCode Go 요청에 실패했습니다.",
            "request_rejected": "OpenCode Go가 요청을 거부했습니다.",
        }
        detail = messages.get(kind, messages["other"])
        if diagnostic == "json_required":
            detail += " JSON 모드의 프롬프트에는 json 안내가 필요합니다."
        elif diagnostic == "schema_rejected":
            detail += " 모델이 JSON Schema 형식을 거부했습니다."
        super().__init__(kind, detail)
        self.args = (detail,)
        self.retry_at = retry_at


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    body: bytes = field(default=b"", repr=False)


class HTTPTransport(Protocol):
    def request(self, method: str, url: str, *, headers: Mapping[str, str],
                body: bytes | None, timeout: float, cancellation: Event) -> HTTPResponse: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrllibTransport:
    """취소 시 소켓을 shutdown한다. 프록시/TLS 검증은 urllib 기본 정책을 유지한다."""

    def __init__(self, *, connect_timeout=10, read_timeout=30):
        if connect_timeout <= 0 or read_timeout <= 0:
            raise ValueError("연결/읽기 제한 시간은 양수여야 합니다.")
        self.connect_timeout, self.read_timeout = connect_timeout, read_timeout

    def request(self, method, url, *, headers, body, timeout, cancellation):
        if cancellation.is_set():
            raise TranslationCancelled
        done, stopped, lock = Event(), Event(), Lock()
        sockets, result = [], []
        read_timeout = min(timeout, self.read_timeout)

        def close(sock):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

        def track(sock):
            with lock:
                if not stopped.is_set():
                    sockets.append(sock)
                    return sock
            close(sock)
            raise TranslationCancelled

        class ResponseReader(io.RawIOBase):
            """Windows select 대기도 짧게 끊어 취소한다. timeout은 버퍼 밖으로 내보내지 않는다."""

            def __init__(self, sock):
                self.sock = sock
                sock.settimeout(0.05)

            def readable(self):
                return True

            def readinto(self, buffer):
                deadline = time.monotonic() + read_timeout
                while not cancellation.is_set() and not stopped.is_set():
                    try:
                        return self.sock.recv_into(buffer)
                    except socket.timeout:
                        if time.monotonic() >= deadline:
                            raise TimeoutError
                raise TranslationCancelled

        class ResponseSocket:
            def __init__(self, sock):
                self.sock = sock

            def __getattr__(self, name):
                return getattr(self.sock, name)

            def makefile(self, mode, buffering=None):
                return io.BufferedReader(ResponseReader(self.sock))

            def close(self):
                # urllib가 헤더 뒤 connection을 닫아도 본문 reader는 필요하다.
                # 실제 소켓의 소유/닫기는 이 transport의 finally가 담당한다.
                pass

        class Connection(http.client.HTTPConnection):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                create = self._create_connection
                self._create_connection = lambda *a, **kw: track(create(*a, **kw))

            def connect(self):
                super().connect()
                self.sock.settimeout(read_timeout)
                self.sock = ResponseSocket(self.sock)

        class TLSConnection(http.client.HTTPSConnection, Connection):
            def connect(self):
                # 프록시 CONNECT와 TLS handshake도 추적한 소켓으로 중단할 수 있게 한다.
                http.client.HTTPConnection.connect(self)
                self.sock = track(self._context.wrap_socket(
                    self.sock, server_hostname=self._tunnel_host or self.host,
                    do_handshake_on_connect=False))
                self.sock.do_handshake()
                self.sock.settimeout(read_timeout)
                self.sock = ResponseSocket(self.sock)

        class PlainHandler(HTTPHandler):
            def http_open(self, req):
                return self.do_open(Connection, req)

        class TLSHandler(HTTPSHandler):
            def https_open(self, req):
                return self.do_open(TLSConnection, req, context=self._context)

        def run():
            try:
                request = Request(url, data=body, headers=dict(headers), method=method)
                opener = build_opener(_NoRedirect(), PlainHandler(), TLSHandler())
                try:
                    response = opener.open(request, timeout=min(timeout, self.connect_timeout))
                except HTTPError as error:
                    response = error
                with response:
                    data = response.read(4 * 1024 * 1024 + 1)
                    if len(data) > 4 * 1024 * 1024:
                        result.append("format")
                    else:
                        result.append(HTTPResponse(response.status, dict(response.headers), data))
            except Exception:
                # 스레드 밖으로 원래 예외/traceback/키를 전달하지 않는다.
                result.append("connection")
            finally:
                done.set()

        worker = Thread(target=run, name="opencode-go-http", daemon=True)
        deadline = time.monotonic() + timeout
        worker.start()
        try:
            while True:
                if cancellation.is_set():
                    raise TranslationCancelled
                if done.wait(0.02):
                    if cancellation.is_set():
                        raise TranslationCancelled
                    if isinstance(result[0], str):
                        raise OpenCodeGoError(result[0])
                    return result[0]
                if time.monotonic() >= deadline:
                    raise OpenCodeGoError("connection")
        finally:
            with lock:
                stopped.set()
                active = tuple(sockets)
            for sock in active:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            # DNS 해석 자체는 OS 소유다. 늦게 만들어진 소켓도 track에서 즉시 닫는다.
            worker.join(timeout=0.1)
            for sock in active:
                sock.close()


def _retry_at(headers, payload, now):
    value = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
    if value is not None:
        try:
            seconds = int(value)
            if seconds >= 0:
                return now + timedelta(seconds=seconds)
        except (ValueError, TypeError, OverflowError):
            pass
        try:
            result = parsedate_to_datetime(value)
            if result.tzinfo is not None:
                return max(now, result.astimezone(timezone.utc))
        except (ValueError, TypeError, OverflowError):
            pass
    # 명시적인 절대 시각만 읽고 숫자 단위나 자연어 시각은 추측하지 않는다.
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    if isinstance(error, dict):
        for name in ("retry_at", "reset_at"):
            value = error.get(name)
            if isinstance(value, str):
                try:
                    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if result.tzinfo is not None:
                        return max(now, result.astimezone(timezone.utc))
                except ValueError:
                    pass
    return None


class OpenCodeGoTranslator:
    """session_id는 한 번역 대화/작업 동안 재시도와 묶음 사이에 같은 값을 전달한다.

    키 공급자는 요청 직전 호출하므로 저장/삭제/교체가 다음 요청부터 적용된다.
    자체 재시도는 없으며, 남은 줄과 취소/재시도 정책은 호출자가 소유한다.
    """

    def __init__(self, key_provider: Callable[[], Secret | None], *, session_id: str,
                 model: str = DEFAULT_MODEL, transport: HTTPTransport | None = None,
                 timeout: float = 60, clock=None, choices=MODEL_CHOICES, effort=""):
        if not isinstance(session_id, str) or not session_id or not session_id.isascii() or any(
                c.isspace() or ord(c) < 33 or ord(c) > 126 for c in session_id):
            raise ValueError("세션 ID는 공백 없는 ASCII 문자열이어야 합니다.")
        if model in NON_CHAT_MODELS:
            raise ValueError("확인된 chat/completions 모델만 지원합니다.")
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", model):
            raise ValueError("모델 ID 형식이 올바르지 않습니다.")
        if timeout <= 0:
            raise ValueError("요청 제한 시간은 양수여야 합니다.")
        self._key_provider, self.session_id, self.model = key_provider, session_id, model
        self._transport = transport if transport is not None else UrllibTransport()
        self._timeout = timeout
        self.effort = effort
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._choices = {choice.model_id: choice for choice in choices if choice.provider == "opencode_go"}

    def model_choice(self, model_id: str | None = None) -> TranslationModelChoice:
        model_id = model_id or self.model
        return self._choices.get(model_id, TranslationModelChoice(
            "opencode_go", model_id, model_id, policy=ModelPolicy(model_id)))

    def model_policy(self, model_id: str | None = None) -> ModelPolicy:
        model_id = model_id or self.model
        return self.model_choice(model_id).policy

    def _request(self, path, payload=None, *, cancellation=None, session_id=None):
        cancellation = cancellation if cancellation is not None else Event()
        if cancellation.is_set():
            raise TranslationCancelled
        failure = None
        try:
            key = self._key_provider()
        except Exception:
            failure = "key_storage"
        if failure:
            raise OpenCodeGoError(failure)
        if key is None:
            raise OpenCodeGoError("missing_key")
        if not isinstance(key, Secret):
            raise OpenCodeGoError("key_storage")
        headers = {"Authorization": "Bearer " + key.reveal(), "User-Agent": USER_AGENT,
                   "Content-Type": "application/json"}
        if payload is not None:
            headers["x-opencode-session"] = session_id or self.session_id
        try:
            response = self._transport.request(
                "GET" if payload is None else "POST", BASE_URL + path,
                headers=headers,
                body=None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                timeout=self._timeout, cancellation=cancellation,
            )
        except TranslationCancelled:
            raise
        except OpenCodeGoError as error:
            failure = "format" if error.kind == "format" else "connection"
        except Exception:
            failure = "connection"
        if cancellation.is_set():
            raise TranslationCancelled
        if failure:
            raise OpenCodeGoError(failure)
        data = None
        try:
            data = json.loads(response.body)
        except (ValueError, TypeError):
            pass
        # HTTP 실패의 진단만 분류한다. 성공한 번역 속 '429' 같은 문구는 읽지 않는다.
        if response.status >= 400:
            diagnostic = None
            if response.status in (401, 403):
                kind = "authentication"
            elif response.status == 429:
                kind = "usage_limit"
            else:
                error = data.get("error", data) if isinstance(data, dict) else None
                detail = response.body.decode("utf-8", errors="replace").lower()
                kind = classify_cli_failure(json.dumps(error) if error is not None else detail)
                if response.status == 400 and kind != "usage_limit":
                    kind = "request_rejected"
                    if "json_schema" in detail or "json schema" in detail:
                        diagnostic = "schema_rejected"
                    elif "json" in detail and ("prompt" in detail or "word" in detail):
                        diagnostic = "json_required"
            raise OpenCodeGoError(kind, retry_at=_retry_at(response.headers, data, self._clock())
                                  if kind == "usage_limit" else None, diagnostic=diagnostic)
        if not 200 <= response.status < 300:
            raise OpenCodeGoError("other")
        if not isinstance(data, dict):
            raise OpenCodeGoError("format")
        return data

    def models(self, *, cancellation=None) -> tuple[TranslationModelChoice, ...]:
        """공개 목록의 지원 모델과 정책. 성공 자체는 키 인증의 증거가 아니다."""
        data = self._request("/models", cancellation=cancellation)
        rows = data.get("data")
        if not isinstance(rows, list) or any(not isinstance(row, dict) or
                not isinstance(row.get("id"), str) or not row["id"] for row in rows):
            raise OpenCodeGoError("format")
        ids = dict.fromkeys(row["id"] for row in rows if row["id"] not in NON_CHAT_MODELS)
        return tuple(self.model_choice(model_id) for model_id in ids)

    def _model_payload(self, model, prompt, **extra):
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
                   "stream": False, **extra}
        if self.model_choice(model).structured_output == "json_object":
            payload["response_format"] = {"type": "json_object"}
        return payload

    def translate(self, lines, spoken_language, *, cli=None, cancellation=None):
        lines = tuple(lines)
        if cancellation is not None and cancellation.is_set():
            raise TranslationCancelled
        if not lines:
            return ()
        # Go의 strict JSON Schema 지원은 미확인. 계약을 프롬프트에 첨부하고 로컬에서 검증한다.
        prompt = translation_prompt(lines, spoken_language)
        prompt += "\nOUTPUT_JSON_SCHEMA:\n" + json.dumps(translation_schema(lines), ensure_ascii=False)
        prompt += '\nReturn a json object only. Example: {"lines": [{"id": "target id", "text": "번역"}]}.'
        extra = {}
        if self.effort and self.effort in (self.model_choice().reasoning_efforts or ()):
            extra["reasoning_effort"] = self.effort
        data = self._request("/chat/completions", self._model_payload(self.model, prompt, **extra),
                             cancellation=cancellation)
        result = None
        try:
            choice = data["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError
            content = choice["message"]["content"]
            if isinstance(content, str):
                fenced = re.fullmatch(r"\s*```(?:json)?[ \t]*\r?\n(.*?)\r?\n```\s*", content, re.DOTALL)
                if fenced:
                    content = fenced[1]
            result = parse_translation_response(content, lines)
        except (TranslationError, ValueError, TypeError, KeyError, IndexError, AttributeError):
            pass
        if result is None:
            raise OpenCodeGoError("format")
        return result

    def check_key(self, *, cancellation=None) -> KeyCheckResult:
        """사용자의 명시적 키 확인 때만 호출한다. 유료 기본 모델에 요청 한 번을 보낸다."""
        try:
            data = self._request("/chat/completions", self._model_payload(
                DEFAULT_MODEL, 'Return a json object. Example: {"ok": true}.', max_tokens=1),
                cancellation=cancellation, session_id=str(uuid4()))
        except OpenCodeGoError as error:
            status = error.kind if error.kind in (
                "missing_key", "authentication", "usage_limit", "connection") else "other"
            return KeyCheckResult(status, error.retry_at)
        choices = data.get("choices")
        if (not isinstance(choices, list) or not choices or not isinstance(choices[0], dict)
                or not isinstance(choices[0].get("message"), dict) or "error" in data):
            return KeyCheckResult("other")
        return KeyCheckResult("valid")
