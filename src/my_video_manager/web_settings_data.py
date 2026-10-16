"""웹 설정의 표시 데이터. 저장 형식은 기존 키 배치·설정 API가 소유한다."""
from typing import TypedDict
from .web_translation_data import TranslationSettingsData


class SettingKeyData(TypedDict):
    id: str
    label: str
    keys: list[str]
    defaults: list[str]
    display: str
    defaultDisplay: str


class SettingsData(TypedDict):
    version: str
    releasesUrl: str
    bindings: list[SettingKeyData]
    minimum: float
    scanning: bool
    automaticDetection: bool
    translationCli: str
    translation: TranslationSettingsData
    heldTranslations: int
    failedTranslations: int


class CapturedKeyData(TypedDict):
    command: str
    key: str
    display: str
    cancelled: bool
    error: str
    continuing: bool
