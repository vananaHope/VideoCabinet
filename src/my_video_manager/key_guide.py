"""키 안내의 '앱 전체' 묶음. 바꿀 수 있는 키는 지금 키 배치에서 읽는다. Qt에 의존하지 않는다."""

from collections.abc import Iterable
from dataclasses import dataclass

from .key_bindings import KeyBinding
from .key_display import display_key

SETTINGS_KEY = "Alt+S"
KEY_GUIDE_KEY = "F1"


@dataclass(frozen=True)
class KeyGuideEntry:
    """keys는 화면에 보일 키 이름이고 하나씩 따로 보인다. 비어 있으면 키가 지정되지 않은 명령이다."""
    keys: tuple[str, ...]
    label: str
    detail: str = ""


def page_keys(tabs: tuple[tuple[str, str], ...]) -> str:
    """페이지 이동 예약 키의 범위. 탭 수에서 구한다."""
    return f"Ctrl+1 ~ Ctrl+{len(tabs)}"


def page_key_targets(tabs: tuple[tuple[str, str], ...]) -> str:
    return " · ".join(f"{index} {label}" for index, (_, label) in enumerate(tabs, 1))


def app_key_guide(bindings: Iterable[KeyBinding], tabs: tuple[tuple[str, str], ...]) -> tuple[KeyGuideEntry, ...]:
    """웹 화면 어느 탭에서나 쓰는 키. 바꿀 수 있는 키는 지금 키 배치에서 읽는다."""
    rows = {row.command.kind.value: row for row in bindings}
    random_play, emergency = rows["random_play"], rows["emergency_hide"]
    return (
        KeyGuideEntry((page_keys(tabs),), "페이지 이동", page_key_targets(tabs)),
        KeyGuideEntry((SETTINGS_KEY,), "설정 열기", "재생 중에는 설정 메뉴를 엽니다."),
        KeyGuideEntry(tuple(map(display_key, random_play.keys)), random_play.label, "영상 전체에서 고릅니다."),
        KeyGuideEntry(tuple(map(display_key, emergency.keys)), emergency.label, "일시정지하고 창을 트레이로 숨깁니다."),
        KeyGuideEntry((KEY_GUIDE_KEY,), "키 안내 열기 / 닫기", "Esc로도 닫습니다."),
        KeyGuideEntry(("Tab", "Shift+Tab"), "다음 / 이전 단추·입력 칸으로 이동"),
    )
