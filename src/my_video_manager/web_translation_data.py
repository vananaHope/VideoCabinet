"""번역 선택의 공개 표시 계약. 키 원문은 응답에 포함하지 않는다."""
from typing import TypedDict


class TranslationSelectionData(TypedDict):
    provider: str
    model: str
    effort: str


class TranslationModelData(TypedDict):
    id: str
    label: str
    efforts: list[str]
    policy: str
    valid_until: str | None
    policy_warning: str
    warning: bool
    training_warning: bool
    expired_warning: bool


class TranslationProviderData(TypedDict):
    id: str
    label: str
    default_model: str
    notice: str
    models: list[TranslationModelData]
    custom_efforts: list[str]
    cli_default: bool
    unknown_model: TranslationModelData
    expensive_efforts: list[str]
    effort_notice: str


class TranslationSettingsData(TypedDict):
    provider: str
    selections: list[TranslationSelectionData]
    providers: list[TranslationProviderData]
    key_masked: str
    key_error: str
    fallback: bool
    fallback_notice: str
