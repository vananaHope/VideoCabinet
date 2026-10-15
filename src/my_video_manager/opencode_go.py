"""OpenCode Go 구독 API. 선택/대기열/UI 연결 없이 남은 줄 묶음을 번역한다."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
from threading import Event
from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .secret_store import Secret
from .translation import TranslationCancelled, TranslationError
from .translation_cli import (classify_cli_failure, parse_translation_response,
                              translation_prompt, translation_schema)


BASE_URL = "https://opencode.ai/inference/go/v1"
DEFAULT_MODEL = "deepseek-v4.1-flash"
USER_AGENT = "my-video-manager/0.1.0"


@dataclass(frozen=True)
class ModelPolicy:
    model_id: str
    training: bool | None = None
    retention_days: int | None = None
    checked_on: date | None = None
    valid_until: date | None = None
    source: str = "https://opencode.ai/docs/en/go/"

    def needs_warning(self, on: date) -> bool:
        # 기본 모델에도 동일 규칙. 만료/미확인 정책을 안전하다고 표시하지 않는다.
        return (self.training is not False or self.retention_days is None or self.checked_on is None
                or on < self.checked_on or (self.valid_until is not None and on > self.valid_until))


# Go 문서의 chat/completions 모델만 허용한다. 알 수 없는 신규 모델은 확인 후 추가한다.
CHAT_MODELS = (
    "deepseek-v4.1-flash", "deepseek-v4-pro", "glm-5.3-flash", "glm-5.3", "glm-5.2",
    "kimi-k3", "kimi-k2.7-code", "kimi-k2.6", "longcat-2.0", "mimo-v2.6-flash",
    "mimo-v2.6-pro", "mimo-v2.5", "mimo-v2.5-pro", "hy4-preview", "hy3", "space-bunny",
    "longcat-2.5-preview-free", "step-5-preview-free", "cat-jam-free",
)
MODEL_POLICIES = tuple(ModelPolicy(
    model_id, training=False, retention_days=30 if model_id == "cat-jam-free" else 0,
    checked_on=date(2026, 10, 15),
    valid_until=date(2026, 10, 31) if model_id.startswith("deepseek-") else None,
) for model_id in CHAT_MODELS)


@dataclass(frozen=True)
class GoModel:
    id: str
    policy: ModelPolicy


@dataclass(frozen=True)
class KeyCheckResult:
    status: str
    retry_at: datetime | None = None


class OpenCodeGoError(TranslationError):
    """현재 보류 분류와 호환되며 후속 연결에서 사용할 UTC retry_at을 제공한다."""

    def __init__(self, kind: str, *, retry_at: datetime | None = None):
        messages = {
            "missing_key": "OpenCode Go 키가 등록되지 않았습니다.",
            "authentication": "OpenCode Go 키 또는 접근 권한을 확인하세요.",
            "connection": "OpenCode Go에 연결하지 못했습니다.",
            "format": "OpenCode Go 응답 형식이 올바르지 않습니다.",
            "usage_limit": "OpenCode Go 구독 사용량 한도로 보류했습니다.",
            "key_storage": "OpenCode Go 저장된 키를 읽지 못했습니다.",
            "other": "OpenCode Go 요청에 실패했습니다.",
        }
        detail = messages.get(kind, messages["other"])
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
                body: bytes | None, timeout: float) -> HTTPResponse: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrllibTransport:
    """자격증명/자막이 다른 주소로 따라가지 않도록 리다이렉트를 거절한다."""

    def request(self, method, url, *, headers, body, timeout):
        request = Request(url, data=body, headers=dict(headers), method=method)
        opener = build_opener(_NoRedirect())
        try:
            response = opener.open(request, timeout=timeout)
        except HTTPError as error:
            response = error
        with response:
            data = response.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise OpenCodeGoError("format")
            return HTTPResponse(response.status, dict(response.headers), data)


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
                 timeout: float = 180, clock=None, policies=MODEL_POLICIES):
        if not isinstance(session_id, str) or not session_id or not session_id.isascii() or any(
                c.isspace() or ord(c) < 33 or ord(c) > 126 for c in session_id):
            raise ValueError("세션 ID는 공백 없는 ASCII 문자열이어야 합니다.")
        if model not in CHAT_MODELS:
            raise ValueError("확인된 chat/completions 모델만 지원합니다.")
        if timeout <= 0:
            raise ValueError("요청 제한 시간은 양수여야 합니다.")
        self._key_provider, self.session_id, self.model = key_provider, session_id, model
        self._transport = transport if transport is not None else UrllibTransport()
        self._timeout = timeout
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._policies = {policy.model_id: policy for policy in policies}

    def model_policy(self, model_id: str | None = None) -> ModelPolicy:
        model_id = model_id or self.model
        return self._policies.get(model_id, ModelPolicy(model_id))

    def _request(self, path, payload=None, *, cancellation=None):
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
        try:
            response = self._transport.request(
                "GET" if payload is None else "POST", BASE_URL + path,
                headers={"Authorization": "Bearer " + key.reveal(), "User-Agent": USER_AGENT,
                         "x-opencode-session": self.session_id, "Content-Type": "application/json"},
                body=None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                timeout=self._timeout,
            )
        except TranslationCancelled:
            raise
        except OpenCodeGoError:
            failure = "format"
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
            if response.status in (401, 403):
                kind = "authentication"
            elif response.status == 429:
                kind = "usage_limit"
            else:
                error = data.get("error", {}) if isinstance(data, dict) else {}
                kind = classify_cli_failure(json.dumps(error))
            raise OpenCodeGoError(kind, retry_at=_retry_at(response.headers, data, self._clock())
                                  if kind == "usage_limit" else None)
        if not 200 <= response.status < 300:
            raise OpenCodeGoError("other")
        if not isinstance(data, dict):
            raise OpenCodeGoError("format")
        return data

    def models(self, *, cancellation=None) -> tuple[GoModel, ...]:
        """공개 목록의 지원 모델과 정책. 성공 자체는 키 인증의 증거가 아니다."""
        data = self._request("/models", cancellation=cancellation)
        rows = data.get("data")
        if not isinstance(rows, list) or any(not isinstance(row, dict) or
                not isinstance(row.get("id"), str) or not row["id"] for row in rows):
            raise OpenCodeGoError("format")
        ids = dict.fromkeys(row["id"] for row in rows if row["id"] in CHAT_MODELS)
        return tuple(GoModel(model_id, self.model_policy(model_id)) for model_id in ids)

    def translate(self, lines, spoken_language, *, cancellation=None):
        lines = tuple(lines)
        if cancellation is not None and cancellation.is_set():
            raise TranslationCancelled
        if not lines:
            return ()
        # Go의 strict JSON Schema 지원은 미확인. 계약을 프롬프트에 첨부하고 로컬에서 검증한다.
        prompt = translation_prompt(lines, spoken_language)
        prompt += "\nOUTPUT_JSON_SCHEMA:\n" + json.dumps(translation_schema(lines), ensure_ascii=False)
        data = self._request("/chat/completions", {
            "model": self.model, "messages": [{"role": "user", "content": prompt}], "stream": False,
        }, cancellation=cancellation)
        result = None
        try:
            choice = data["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError
            result = parse_translation_response(choice["message"]["content"], lines)
        except (TranslationError, ValueError, TypeError, KeyError, IndexError, AttributeError):
            pass
        if result is None:
            raise OpenCodeGoError("format")
        return result

    def check_key(self, *, cancellation=None) -> KeyCheckResult:
        """사용자의 명시적 키 확인 때만 호출한다. 유료 기본 모델에 요청 한 번을 보낸다."""
        try:
            data = self._request("/chat/completions", {
                "model": DEFAULT_MODEL, "messages": [{"role": "user", "content": "Reply OK."}],
                "max_tokens": 1, "stream": False,
            }, cancellation=cancellation)
        except OpenCodeGoError as error:
            status = error.kind if error.kind in (
                "missing_key", "authentication", "usage_limit", "connection") else "other"
            return KeyCheckResult(status, error.retry_at)
        choices = data.get("choices")
        if (not isinstance(choices, list) or not choices or not isinstance(choices[0], dict)
                or not isinstance(choices[0].get("message"), dict) or "error" in data):
            return KeyCheckResult("other")
        return KeyCheckResult("valid")
