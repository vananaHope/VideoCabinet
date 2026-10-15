"""번역 방식에 독립적인 모델 선택과 개인정보 정책 값 객체."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ModelPolicy:
    model_id: str
    training: bool | None = None
    retention_days: int | None = None
    checked_on: date | None = None
    valid_until: date | None = None
    source: str | None = None

    def needs_warning(self, on: date) -> bool:
        # 기본 모델에도 동일 규칙. 만료/미확인 정책을 안전하다고 표시하지 않는다.
        return (self.training is not False or self.retention_days is None or self.checked_on is None
                or on < self.checked_on or (self.valid_until is not None and on > self.valid_until))


@dataclass(frozen=True)
class TranslationModelChoice:
    provider: str
    model_id: str
    label: str
    is_default: bool = False
    policy: ModelPolicy | None = None
    source: str | None = None
    # None: 미확인, (): 미지원, 나머지: 선택 가능한 명시적 강도 목록.
    # UI의 '기본'은 목록 값이 아니라 실행 시 추론 강도 인자를 생략하는 선택이다.
    reasoning_efforts: tuple[str, ...] | None = None
    structured_output: str | None = None

    @property
    def reasoning_supported(self) -> bool | None:
        return None if self.reasoning_efforts is None else bool(self.reasoning_efforts)

    @property
    def id(self):
        return self.model_id

    def needs_warning(self, on: date) -> bool:
        return self.policy is not None and self.policy.needs_warning(on)


DEFAULT_MODEL = "deepseek-v4.1-flash"
# Go 문서에서 확인한 chat/completions 모델. 직접 입력 모델의 정책은 미확인으로 둔다.
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
    source="https://opencode.ai/docs/en/go/",
) for model_id in CHAT_MODELS)


MODEL_CHOICES = tuple(TranslationModelChoice(
    provider="opencode_go", model_id=policy.model_id,
    label={"deepseek-v4.1-flash": "DeepSeek V4.1 Flash", "deepseek-v4-pro": "DeepSeek V4 Pro"}.get(
        policy.model_id, policy.model_id),
    is_default=policy.model_id == DEFAULT_MODEL, policy=policy,
    source=("https://github.com/ucx0204/CarrotMangaTranslator/blob/"
            "721e709d3706f15ed1ef62270460d4b8ab5d5312/docs/custom-api-profiles-20261005.md"
            if policy.model_id == DEFAULT_MODEL else policy.source),
    # 참고 실측은 이 모델에만 있다. 다른 모델의 JSON 모드는 추측하지 않는다.
    structured_output="json_object" if policy.model_id == DEFAULT_MODEL else None,
) for policy in MODEL_POLICIES)

NON_CHAT_MODELS = frozenset((
    "grok-4.7", "grok-4.6", "gpt-6-luna", "gpt-5.6-luna", "claude-haiku-5-5",
    "gemini-4-argon-contributor", "minimax-m3", "minimax-m2.7",
    "muse-spark-1.3-contributor", "muse-spark-1.2-contributor", "qwen3.8-max", "qwen3.8-flash", "qwen3.7-plus",
))


@dataclass(frozen=True)
class TranslationProvider:
    id: str
    label: str
    models: tuple[TranslationModelChoice, ...]
    external_notice: str
    batch_size: int

    @property
    def default_model(self):
        return next(m.model_id for m in self.models if m.is_default)


EXPENSIVE_EFFORTS = ("xhigh", "max")
CLI_EFFORTS = ("low", "medium", "high", "xhigh", "max")
PROVIDERS = (
    TranslationProvider("codex", "Codex (CLI)", (
        TranslationModelChoice("codex", "gpt-5.6-terra", "GPT-5.6 Terra", True, reasoning_efforts=CLI_EFFORTS),
    ), "Codex를 고르면 자막 텍스트가 OpenAI 서버로 전송됩니다. CLI 설치와 구독 로그인이 필요합니다.", 120),
    TranslationProvider("claude", "Claude (CLI)", (
        TranslationModelChoice("claude", "claude-sonnet-5-5", "Claude Sonnet 5.5", True, reasoning_efforts=CLI_EFFORTS),
    ), "Claude를 고르면 자막 텍스트가 Anthropic 서버로 전송됩니다. CLI 설치와 구독 로그인이 필요합니다.", 120),
    TranslationProvider("opencode_go", "OpenCode Go (API)", MODEL_CHOICES,
        "OpenCode Go를 고르면 자막 텍스트가 OpenCode 서버로 전송됩니다. 자막 번역은 공식 허용이 확인되지 않아 계정 제한 위험이 있습니다.", 100),
)
DEFAULT_PROVIDER = PROVIDERS[0].id
TRANSLATION_CHOICES = tuple((p.id, p.label) for p in PROVIDERS)


def provider(identifier):
    for item in PROVIDERS:
        if item.id == identifier:
            return item
    raise ValueError("지원하지 않는 번역 방식입니다.")


def model_choice(identifier, model):
    selected = provider(identifier)
    return next((m for m in selected.models if m.model_id == model), TranslationModelChoice(
        identifier, model, model or "기본(CLI 기본값)",
        policy=ModelPolicy(model) if identifier == "opencode_go" else None,
        reasoning_efforts=None if identifier == "opencode_go" else CLI_EFFORTS))
