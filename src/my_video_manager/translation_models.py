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
