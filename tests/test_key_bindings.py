from datetime import datetime, timezone

import pytest

from my_video_manager.core import AppCore, Command, CommandType, DEFAULT_KEY_BINDINGS, MediaInfo
from my_video_manager.key_bindings import normalize_key
from my_video_manager.key_display import display_key, display_keys


class Media:
    def read(self, path):
        return MediaInfo(120, "matroska")

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"thumbnail")


def open_core(tmp_path, **kwargs):
    return AppCore(media=Media(), clock=lambda: datetime(2026, 10, 14, tzinfo=timezone.utc),
                   database=tmp_path / "library.sqlite3", **kwargs)


def draft(core):
    return {row.command: row.keys for row in core.key_bindings()}


def test_catalog_includes_all_commands_and_amount_variants(tmp_path):
    core = open_core(tmp_path)
    rows = core.key_bindings()
    assert {row.command.kind for row in rows} == set(CommandType)
    assert set(DEFAULT_KEY_BINDINGS.values()) <= {row.command for row in rows}
    assert all(row.label and any("가" <= char <= "힣" for char in row.label) for row in rows)
    for row in rows:
        assert row.keys == row.default_keys
        for key in row.keys:
            assert core.command_for_key(key) == row.command


def test_translation_toggle_has_korean_label_and_period_default(tmp_path):
    core = open_core(tmp_path)
    command = Command(CommandType.TOGGLE_SUBTITLE_LANGUAGE)
    row = next(row for row in core.key_bindings() if row.command == command)
    assert row.label == "원어 / 번역·다듬은 자막 전환"
    assert row.keys == row.default_keys == (".",)
    assert core.command_for_key(".") == command


def test_reel_repeat_has_korean_label_and_rebinding_survives_restart(tmp_path):
    core = open_core(tmp_path)
    command = Command(CommandType.TOGGLE_REEL_REPEAT)
    row = next(row for row in core.key_bindings() if row.command == command)
    assert row.label == "구간 반복 켜기 / 끄기"
    assert row.keys == row.default_keys == ("\\",)
    bindings = draft(core)
    bindings[command] = ("R",)
    core.save_key_bindings(bindings)
    for app in (core, open_core(tmp_path)):
        assert app.command_for_key("R") == command
        assert app.command_for_key("\\") is None
    core.reset_key_bindings(command)
    assert open_core(tmp_path).command_for_key("\\") == command


@pytest.mark.parametrize(("kind", "key"), [
    (CommandType.TOGGLE_PAUSE, "\\"), (CommandType.TOGGLE_REEL_REPEAT, "Enter"),
])
def test_reel_repeat_conflicts_only_with_a_different_command(tmp_path, kind, key):
    core = open_core(tmp_path)
    bindings = draft(core)
    bindings[Command(kind)] = (key,)
    with pytest.raises(ValueError, match="구간 반복"):
        core.save_key_bindings(bindings)
    assert core.command_for_key("\\") == Command(CommandType.TOGGLE_REEL_REPEAT)
    assert core.command_for_key("Enter") == Command(CommandType.TOGGLE_PAUSE)


@pytest.mark.parametrize(("kind", "key"), [
    (CommandType.TOGGLE_PAUSE, "."),
    (CommandType.TOGGLE_SUBTITLE_LANGUAGE, "Enter"),
])
def test_translation_key_conflict_preserves_both_commands(tmp_path, kind, key):
    core = open_core(tmp_path)
    bindings = draft(core)
    bindings[Command(kind)] = (key,)
    with pytest.raises(ValueError) as error:
        core.save_key_bindings(bindings)
    assert "원어 / 번역·다듬은 자막 전환" in str(error.value)
    assert "재생 / 일시정지" in str(error.value)
    for app in (core, open_core(tmp_path)):
        assert app.command_for_key(".") == Command(CommandType.TOGGLE_SUBTITLE_LANGUAGE)
        assert app.command_for_key("Enter") == Command(CommandType.TOGGLE_PAUSE)


def test_translation_toggle_remapping_persists_and_resets_without_changing_cli(tmp_path):
    core = open_core(tmp_path)
    core.set_translation_cli("claude")
    command = Command(CommandType.TOGGLE_SUBTITLE_LANGUAGE)
    bindings = draft(core)
    bindings[command] = ("T",)
    core.save_key_bindings(bindings)
    for app in (core, open_core(tmp_path)):
        assert app.command_for_key(".") is None
        assert app.command_for_key("T") == command
        assert app.translation_cli == "claude"
    core.reset_key_bindings(command)
    reopened = open_core(tmp_path)
    assert reopened.command_for_key(".") == command
    assert reopened.command_for_key("T") is None
    assert reopened.translation_cli == "claude"


def test_save_changes_immediately_and_survives_restart(tmp_path):
    core = open_core(tmp_path)
    command = Command(CommandType.TOGGLE_PAUSE)
    bindings = draft(core)
    bindings[command] = ("Space",)
    core.save_key_bindings(bindings)
    assert core.command_for_key("Enter") is None
    assert core.command_for_key(" ") == command
    reopened = open_core(tmp_path)
    assert reopened.command_for_key("Space") == command
    assert reopened.command_for_key("Enter") is None
    assert reopened.command_for_key("Left") == Command(CommandType.SEEK, -5)


def test_conflict_reports_both_commands_without_changing_runtime_or_saved_keys(tmp_path):
    core = open_core(tmp_path)
    bindings = draft(core)
    bindings[Command(CommandType.SEEK, -3)] = ("Left",)
    with pytest.raises(ValueError, match="Left.*5초 뒤로.*3초 뒤로"):
        core.save_key_bindings(bindings)
    for app in (core, open_core(tmp_path)):
        assert app.command_for_key(",") == Command(CommandType.SEEK, -3)
        assert app.command_for_key("Left") == Command(CommandType.SEEK, -5)


def test_swap_and_individual_reset_conflict_then_full_reset(tmp_path):
    core = open_core(tmp_path)
    pause = Command(CommandType.TOGGLE_PAUSE)
    point = Command(CommandType.POINT_HIGHLIGHT)
    bindings = draft(core)
    bindings[pause], bindings[point] = ("Insert",), ("Enter",)
    core.save_key_bindings(bindings)
    assert core.command_for_key("Insert") == pause
    assert core.command_for_key("Enter") == point
    with pytest.raises(ValueError, match="Enter"):
        core.reset_key_bindings(pause)
    assert open_core(tmp_path).command_for_key("Insert") == pause
    core.reset_key_bindings()
    for key, command in DEFAULT_KEY_BINDINGS.items():
        assert core.command_for_key(key) == command
        assert open_core(tmp_path).command_for_key(key) == command


def test_individual_reset_preserves_other_changes(tmp_path):
    core = open_core(tmp_path)
    pause = Command(CommandType.TOGGLE_PAUSE)
    point = Command(CommandType.POINT_HIGHLIGHT)
    bindings = draft(core)
    bindings[pause], bindings[point] = ("Space",), ("F6",)
    core.save_key_bindings(bindings)
    core.reset_key_bindings(pause)
    reopened = open_core(tmp_path)
    assert reopened.command_for_key("Enter") == pause
    assert reopened.command_for_key("Space") is None
    assert reopened.command_for_key("F6") == point


@pytest.mark.parametrize("key", ["Esc", "Escape", "Ctrl+Esc", "Shift+Escape", "", "Unknown", "Ctrl", "한"])
def test_invalid_or_reserved_keys_are_rejected_before_save(tmp_path, key):
    core = open_core(tmp_path)
    bindings = draft(core)
    bindings[Command(CommandType.TOGGLE_PAUSE)] = (key,)
    with pytest.raises(ValueError):
        core.save_key_bindings(bindings)
    assert core.command_for_key("Enter") == Command(CommandType.TOGGLE_PAUSE)


def test_key_aliases_conflict_and_modifiers_are_distinct(tmp_path):
    core = open_core(tmp_path)
    bindings = draft(core)
    bindings[Command(CommandType.TOGGLE_PAUSE)] = ("ctrl+a",)
    bindings[Command(CommandType.POINT_HIGHLIGHT)] = ("Ctrl+A",)
    with pytest.raises(ValueError, match="Ctrl\\+A"):
        core.save_key_bindings(bindings)
    bindings[Command(CommandType.POINT_HIGHLIGHT)] = ("A",)
    core.save_key_bindings(bindings)
    assert core.command_for_key("CTRL+a") == Command(CommandType.TOGGLE_PAUSE)
    assert core.command_for_key("a") == Command(CommandType.POINT_HIGHLIGHT)


def test_new_default_command_appears_without_losing_customization(tmp_path, monkeypatch):
    core = open_core(tmp_path)
    bindings = draft(core)
    bindings[Command(CommandType.TOGGLE_PAUSE)] = ("Space",)
    core.save_key_bindings(bindings)
    # 후속 기능이 기본 대응표에 명령을 추가하는 상황을 공개 목록으로 검증한다.
    new_command = Command(CommandType.SEEK, -10)
    monkeypatch.setitem(DEFAULT_KEY_BINDINGS, "F8", new_command)
    reopened = open_core(tmp_path)
    assert reopened.command_for_key("Space") == Command(CommandType.TOGGLE_PAUSE)
    assert reopened.command_for_key("F8") == new_command
    assert new_command in draft(reopened)


def test_replacement_api_persists_and_constructor_override_is_temporary(tmp_path):
    core = open_core(tmp_path)
    core.set_key_bindings({"Space": Command(CommandType.TOGGLE_PAUSE)})
    assert open_core(tmp_path).command_for_key("Enter") is None
    injected = open_core(tmp_path, key_bindings={})
    assert injected.command_for_key("Space") is None
    assert open_core(tmp_path).command_for_key("Space") == Command(CommandType.TOGGLE_PAUSE)


def test_new_default_key_collision_keeps_existing_user_choice(tmp_path, monkeypatch):
    core = open_core(tmp_path)
    pause = Command(CommandType.TOGGLE_PAUSE)
    bindings = draft(core)
    bindings[pause] = ("F8",)
    core.save_key_bindings(bindings)
    new_command = Command(CommandType.SEEK, -10)
    monkeypatch.setitem(DEFAULT_KEY_BINDINGS, "F8", new_command)
    reopened = open_core(tmp_path)
    assert reopened.command_for_key("F8") == pause
    assert draft(reopened)[new_command] == ()
    assert reopened.command_for_key("Enter") is None
    assert reopened.command_for_key("Left") == Command(CommandType.SEEK, -5)


def test_same_command_may_have_aliases_but_different_amounts_conflict(tmp_path):
    core = open_core(tmp_path)
    bindings = draft(core)
    pause = Command(CommandType.TOGGLE_PAUSE)
    bindings[pause] = ("Enter", "Return", "Space")
    core.save_key_bindings(bindings)
    assert core.command_for_key("Return") == core.command_for_key("Space") == pause
    bindings[Command(CommandType.CHANGE_SPEED, -0.25)] = ("Up",)
    with pytest.raises(ValueError, match="Up"):
        core.save_key_bindings(bindings)


def test_remapped_highlight_and_series_commands_keep_context_behavior(tmp_path):
    folder = tmp_path / "videos"
    folder.mkdir()
    for number in (1, 2):
        (folder / f"강의 {number}강.mkv").write_bytes(bytes([number]))
    core = open_core(tmp_path)
    core.add_watched_folder(folder)
    core.scan()
    first, second = core.videos()
    core.switch_to(first.id)
    core.playback.report(10)
    core.execute_highlight_command(core.command_for_key("Insert"))
    core.playback.report(20)
    bindings = draft(core)
    previous = Command(CommandType.PREVIOUS_HIGHLIGHT)
    following = Command(CommandType.NEXT_VIDEO)
    bindings[previous], bindings[following] = ("H",), ("N",)
    core.save_key_bindings(bindings)
    assert core.execute_highlight_command(core.command_for_key("H")) == 10
    assert core.command_for_key("N") == following
    assert core.adjacent_video(first.id, (first.id,), forward=True) == second.id
    assert core.adjacent_video(second.id, (first.id, second.id), forward=True) is None


@pytest.mark.parametrize(("key", "expected"), [("return", "Enter"), (" ", "Space"),
    ("shift+ctrl+a", "Ctrl+Shift+A"), ("Ctrl++", "Ctrl++"), ("PgDown", "PgDn"), ("\\", "\\")])
def test_key_name_normalization(key, expected):
    assert normalize_key(key) == expected


@pytest.mark.parametrize("key", ["Alt+S", "alt+s"])
def test_settings_menu_key_is_reserved_without_changing_saved_bindings(tmp_path, key):
    core = open_core(tmp_path)
    bindings = draft(core)
    bindings[Command(CommandType.TOGGLE_PAUSE)] = (key,)
    with pytest.raises(ValueError, match="설정 메뉴.*예약 키"):
        core.save_key_bindings(bindings)
    assert draft(core) == draft(open_core(tmp_path)) == {
        row.command: row.default_keys for row in core.key_bindings()}


@pytest.mark.parametrize("number", range(1, 9))
def test_sidebar_keys_reject_both_save_apis_and_preserve_custom_keys(tmp_path, number):
    core = open_core(tmp_path)
    pause = Command(CommandType.TOGGLE_PAUSE)
    bindings = draft(core)
    bindings[pause] = ("Space",)
    core.save_key_bindings(bindings)
    invalid = dict(bindings)
    invalid[pause] = (f"ctrl+{number}",)
    with pytest.raises(ValueError, match="페이지.*예약 키"):
        core.save_key_bindings(invalid)
    with pytest.raises(ValueError, match="페이지.*예약 키"):
        core.set_key_bindings({f"Ctrl+{number}": pause})
    for app in (core, open_core(tmp_path)):
        assert draft(app) == bindings
        assert app.command_for_key(f"Ctrl+{number}") is None
        assert app.command_for_key("Space") == pause


@pytest.mark.parametrize("number", range(1, 9))
def test_old_saved_sidebar_keys_use_existing_invalid_settings_fallback(tmp_path, number):
    core = open_core(tmp_path)
    core.settings.set("keys.bindings", {"toggle_pause:0": [f"Ctrl+{number}"]})
    reopened = open_core(tmp_path)
    assert all(row.keys == row.default_keys for row in reopened.key_bindings())
    assert reopened.command_for_key(f"Ctrl+{number}") is None


@pytest.mark.parametrize("stored", [
    "garbage", ["Enter"], {"gone:0": ["F8"]},
    {"toggle_pause:0": ["Invalid"]}, {"toggle_pause:0": ["Esc"]},
    {"toggle_pause:0": "Space"}, {"toggle_pause:0": [5]},
    {"toggle_pause:0": ["Alt+S"]},
    {"toggle_pause:0": ["Space"], "point_highlight:0": ["Space"]},
    {"toggle_pause:0": ["ctrl+a"], "point_highlight:0": ["Ctrl+A"]},
])
def test_corrupt_saved_key_bindings_fall_back_to_defaults(tmp_path, stored):
    core = open_core(tmp_path)
    core.settings.set("keys.bindings", stored)
    reopened = open_core(tmp_path)
    for row in reopened.key_bindings():
        assert row.keys == row.default_keys
        for key in row.keys:
            assert reopened.command_for_key(key) == row.command


@pytest.mark.parametrize(("key", "expected"), [
    ("Left", "←"), ("Right", "→"), ("Up", "↑"), ("Down", "↓"),
    ("Ctrl+Shift+Left", "Ctrl+Shift+←"), ("PgUp", "Page Up"), ("PgDn", "Page Down"),
    ("Enter", "Enter"), ("Space", "Space"), ("F8", "F8"), ("Ctrl++", "Ctrl++"),
    (".", ". (마침표)"), ("'", "' (작은따옴표)"), ("Ctrl+/", "Ctrl+/ (빗금)"), ("Meta+T", "Win+T"),
])
def test_display_key_names(key, expected):
    assert display_key(key) == expected


@pytest.mark.parametrize(("keys", "expected"), [
    ((), "키 미할당"), (("Left", "Ctrl+T"), "← / Ctrl+T"),
])
def test_display_multiple_or_unassigned_keys(keys, expected):
    assert display_keys(keys) == expected


def test_fullscreen_default_label_rebinding_and_reset(tmp_path):
    core = open_core(tmp_path)
    assert core.key_bindings()[0].command.kind == CommandType.TOGGLE_PAUSE
    # 재생 명령(기본 키 없는 무작위 이어 재생 켜기/끄기 포함) 뒤에 재생 밖에서도 동작하는 긴급 탈출이 온다.
    assert [row.command.kind for row in core.key_bindings()][-4:] == [
        CommandType.TOGGLE_FULLSCREEN, CommandType.TOGGLE_RANDOM_CONTINUOUS,
        CommandType.EMERGENCY_HIDE, CommandType.RANDOM_PLAY]
    command = Command(CommandType.TOGGLE_FULLSCREEN)
    row = next(row for row in core.key_bindings() if row.command == command)
    assert row.label == "전체 화면 켜기 / 끄기"
    assert row.keys == row.default_keys == ("'",)
    assert core.command_for_key("'") == command
    bindings = draft(core)
    bindings[command] = ("F11",)
    core.save_key_bindings(bindings)
    for app in (core, open_core(tmp_path)):
        assert app.command_for_key("F11") == command
        assert app.command_for_key("'") is None
    core.reset_key_bindings(command)
    assert open_core(tmp_path).command_for_key("'") == command


def test_fullscreen_old_custom_apostrophe_wins_and_reset_reports_conflict(tmp_path):
    core = open_core(tmp_path)
    core.settings.set("keys.bindings", {"toggle_pause:0": ["'"], "point_highlight:0": ["H"]})
    reopened = open_core(tmp_path)
    command = Command(CommandType.TOGGLE_FULLSCREEN)
    assert reopened.command_for_key("'") == Command(CommandType.TOGGLE_PAUSE)
    assert reopened.command_for_key("H") == Command(CommandType.POINT_HIGHLIGHT)
    assert draft(reopened)[command] == ()
    with pytest.raises(ValueError, match="전체 화면"):
        reopened.reset_key_bindings(command)
    assert draft(open_core(tmp_path))[command] == ()


def test_fullscreen_conflict_does_not_save(tmp_path):
    core = open_core(tmp_path)
    bindings = draft(core)
    bindings[Command(CommandType.TOGGLE_FULLSCREEN)] = ("Enter",)
    with pytest.raises(ValueError, match="전체 화면"):
        core.save_key_bindings(bindings)
    assert open_core(tmp_path).command_for_key("'") == Command(CommandType.TOGGLE_FULLSCREEN)


def test_help_f1_is_reserved_and_legacy_binding_uses_existing_fallback(tmp_path):
    core = open_core(tmp_path)
    bindings = draft(core)
    bindings[Command(CommandType.TOGGLE_PAUSE)] = ("F1",)
    with pytest.raises(ValueError, match="키 안내.*예약 키"):
        core.save_key_bindings(bindings)
    with pytest.raises(ValueError, match="키 안내.*예약 키"):
        core.set_key_bindings({"F1": Command(CommandType.TOGGLE_PAUSE)})
    core.settings.set("keys.bindings", {"toggle_pause:0": ["F1"], "point_highlight:0": ["H"]})
    reopened = open_core(tmp_path)
    assert reopened.command_for_key("F1") is None
    assert reopened.command_for_key("Enter") == Command(CommandType.TOGGLE_PAUSE)
    assert reopened.command_for_key("H") == Command(CommandType.POINT_HIGHLIGHT)


def test_highlight_list_key_registers_saves_and_respects_existing_customization(tmp_path):
    core = open_core(tmp_path)
    command = Command(CommandType.TOGGLE_HIGHLIGHT_LIST)
    row = next(row for row in core.key_bindings() if row.command == command)
    assert row.label == '하이라이트 패널 접기 / 펴기'
    assert row.keys == row.default_keys == (';',)
    assert core.command_for_key(';') == command
    bindings = draft(core)
    bindings[command] = ('L',)
    core.save_key_bindings(bindings)
    assert open_core(tmp_path).command_for_key('L') == command
    assert open_core(tmp_path).command_for_key(';') is None
    core.settings.set('keys.bindings', {'toggle_pause:0': [';']})
    reopened = open_core(tmp_path)
    assert reopened.command_for_key(';') == Command(CommandType.TOGGLE_PAUSE)
    assert draft(reopened)[command] == ()
    with pytest.raises(ValueError, match='하이라이트 패널'):
        reopened.reset_key_bindings(command)


def test_emergency_hide_default_label_note_rebinding_and_reset(tmp_path):
    core = open_core(tmp_path)
    command = Command(CommandType.EMERGENCY_HIDE)
    row = next(row for row in core.key_bindings() if row.command == command)
    assert row.label == "긴급 탈출(창 숨기기)"
    assert row.keys == row.default_keys == ("Ctrl+Shift+H",)
    assert "재생 화면 밖" in row.note
    assert all(not other.note for other in core.key_bindings()
               if other.command.kind not in (CommandType.EMERGENCY_HIDE, CommandType.RANDOM_PLAY))
    assert core.command_for_key("ctrl+shift+h") == command
    assert core.command_for_key("Ctrl+H") is None
    bindings = draft(core)
    bindings[command] = ("Ctrl+Alt+B",)
    core.save_key_bindings(bindings)
    for app in (core, open_core(tmp_path)):
        assert app.command_for_key("Ctrl+Alt+B") == command
        assert app.command_for_key("Ctrl+Shift+H") is None
    core.reset_key_bindings(command)
    assert open_core(tmp_path).command_for_key("Ctrl+Shift+H") == command
    bindings = draft(core)
    bindings[command] = ("Alt+F9",)
    core.save_key_bindings(bindings)
    core.reset_key_bindings()
    assert open_core(tmp_path).command_for_key("Ctrl+Shift+H") == command
    assert open_core(tmp_path).command_for_key("Alt+F9") is None


@pytest.mark.parametrize("key, message", [("Ctrl+P", "재생 / 일시정지"), ("Ctrl+3", "예약 키"),
                                          ("Alt+S", "예약 키"), ("Esc", "Esc")])
def test_emergency_hide_conflicting_or_reserved_keys_are_rejected(tmp_path, key, message):
    core = open_core(tmp_path)
    bindings = draft(core)
    bindings[Command(CommandType.TOGGLE_PAUSE)] = ("Enter", "Ctrl+P")
    bindings[Command(CommandType.EMERGENCY_HIDE)] = (key,)
    with pytest.raises(ValueError, match=message):
        core.save_key_bindings(bindings)
    assert open_core(tmp_path).command_for_key("Ctrl+Shift+H") == Command(CommandType.EMERGENCY_HIDE)


def test_emergency_hide_is_unassigned_when_existing_user_already_uses_its_key(tmp_path):
    core = open_core(tmp_path)
    core.settings.set("keys.bindings", {"toggle_subtitles:0": ["Ctrl+Shift+H"]})
    reopened = open_core(tmp_path)
    command = Command(CommandType.EMERGENCY_HIDE)
    assert reopened.command_for_key("Ctrl+Shift+H") == Command(CommandType.TOGGLE_SUBTITLES)
    assert draft(reopened)[command] == ()
    with pytest.raises(ValueError, match="긴급 탈출"):
        reopened.reset_key_bindings(command)
    assert draft(open_core(tmp_path))[command] == ()


@pytest.mark.parametrize("key", ["H", "Shift+H", "Enter", "F9", "Shift+F9", "Space"])
def test_emergency_hide_rejects_keys_without_ctrl_alt_or_meta(tmp_path, key):
    core = open_core(tmp_path)
    command = Command(CommandType.EMERGENCY_HIDE)
    bindings = draft(core)
    bindings[Command(CommandType.TOGGLE_PAUSE)] = ("P",)
    bindings[command] = (key,)
    with pytest.raises(ValueError, match="Ctrl·Alt·Win 중 하나"):
        core.save_key_bindings(bindings)
    with pytest.raises(ValueError, match="Ctrl·Alt·Win 중 하나"):
        core.set_key_bindings({key: command})
    reopened = open_core(tmp_path)
    assert reopened.command_for_key("Ctrl+Shift+H") == command
    assert reopened.command_for_key("P") is None


@pytest.mark.parametrize("key", ["Ctrl+H", "Alt+F9", "Meta+H", "Ctrl+Alt+Shift+Space"])
def test_emergency_hide_accepts_ctrl_alt_or_meta_combinations(tmp_path, key):
    core = open_core(tmp_path)
    command = Command(CommandType.EMERGENCY_HIDE)
    bindings = draft(core)
    bindings[command] = (key,)
    core.save_key_bindings(bindings)
    assert open_core(tmp_path).command_for_key(key) == command


def test_other_commands_still_accept_keys_without_modifiers(tmp_path):
    core = open_core(tmp_path)
    bindings = draft(core)
    bindings[Command(CommandType.TOGGLE_FULLSCREEN)] = ("Shift+F",)
    core.save_key_bindings(bindings)
    assert open_core(tmp_path).command_for_key("Shift+F") == Command(CommandType.TOGGLE_FULLSCREEN)


def test_stored_emergency_hide_key_without_modifier_loads_as_unassigned(tmp_path):
    core = open_core(tmp_path)
    core.settings.set("keys.bindings", {"emergency_hide:0": ["H"], "point_highlight:0": ["J"]})
    reopened = open_core(tmp_path)
    assert draft(reopened)[Command(CommandType.EMERGENCY_HIDE)] == ()
    assert reopened.command_for_key("H") is None
    assert reopened.command_for_key("Ctrl+Shift+H") is None
    assert reopened.command_for_key("J") == Command(CommandType.POINT_HIGHLIGHT)
    reopened.reset_key_bindings(Command(CommandType.EMERGENCY_HIDE))
    assert open_core(tmp_path).command_for_key("Ctrl+Shift+H") == Command(CommandType.EMERGENCY_HIDE)


def test_random_play_default_rebinding_restart_and_resets(tmp_path):
    core = open_core(tmp_path)
    command = Command(CommandType.RANDOM_PLAY)
    row = next(row for row in core.key_bindings() if row.command == command)
    assert row.keys == row.default_keys == ("Ctrl+Shift+R",)
    assert row.note
    assert core.command_for_key("shift+ctrl+r") == command
    bindings = draft(core)
    bindings[command] = ("alt+f9",)
    core.save_key_bindings(bindings)
    for app in (core, open_core(tmp_path)):
        assert app.command_for_key("Alt+F9") == command
        assert app.command_for_key("Ctrl+Shift+R") is None
    core.reset_key_bindings(command)
    assert open_core(tmp_path).command_for_key("Ctrl+Shift+R") == command
    core.save_key_bindings(bindings)
    core.reset_key_bindings()
    assert draft(open_core(tmp_path)) == {row.command: row.default_keys for row in core.key_bindings()}


@pytest.mark.parametrize("key", ["Ctrl+Shift+H", "Enter", "Esc", "Alt+S", "F1",
                                     *(f"Ctrl+{i}" for i in range(1, 9)), "R", "Shift+R", "F9"])
def test_random_play_conflicts_reserved_and_unmodified_keys_do_not_save(tmp_path, key):
    core = open_core(tmp_path)
    original = draft(core)
    bindings = dict(original)
    bindings[Command(CommandType.RANDOM_PLAY)] = (key,)
    with pytest.raises(ValueError):
        core.save_key_bindings(bindings)
    assert draft(core) == draft(open_core(tmp_path)) == original


def test_random_play_default_collision_preserves_existing_user_key(tmp_path):
    core = open_core(tmp_path)
    core.settings.set("keys.bindings", {"emergency_hide:0": ["Ctrl+Shift+R"]})
    reopened = open_core(tmp_path)
    command = Command(CommandType.RANDOM_PLAY)
    assert reopened.command_for_key("Ctrl+Shift+R") == Command(CommandType.EMERGENCY_HIDE)
    assert draft(reopened)[command] == ()
    with pytest.raises(ValueError):
        reopened.reset_key_bindings(command)
    assert draft(open_core(tmp_path))[command] == ()
    reopened.reset_key_bindings()
    assert open_core(tmp_path).command_for_key("Ctrl+Shift+R") == command


def test_random_play_stored_unmodified_key_is_unassigned(tmp_path):
    core = open_core(tmp_path)
    core.settings.set("keys.bindings", {"random_play:0": ["R"]})
    reopened = open_core(tmp_path)
    assert draft(reopened)[Command(CommandType.RANDOM_PLAY)] == ()
    assert reopened.command_for_key("R") is None
