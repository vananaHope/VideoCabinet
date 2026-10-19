from datetime import datetime, timezone

import pytest

from my_video_manager.core import AppCore, MediaInfo
from my_video_manager.tag_editing import move_tag_candidate, resolve_tag_input


class FakeMedia:
    def read(self, path):
        return MediaInfo(120, "matroska")

    def capture(self, path, destination, seconds):
        destination.write_bytes(b"thumbnail")


@pytest.fixture
def core(tmp_path):
    core = AppCore(media=FakeMedia(), clock=lambda: datetime(2026, 10, 14, tzinfo=timezone.utc),
                   database=tmp_path / "data/library.sqlite3")
    folder = tmp_path / "videos"
    folder.mkdir()
    for name in ("first", "second", "third"):
        (folder / f"{name}.mkv").write_bytes(name.encode())
    core.add_watched_folder(folder)
    core.scan()
    for video in core.videos():
        core.playback.start(video.id, 10)
        core.execute_highlight_command(core.command_for_key("Insert"))
        core.playback.end()
    return core


@pytest.mark.parametrize("first, equivalent, display", [
    (" Python ", "pYTHON", "Python"),
    ("  영상\t 공부\n", "영상  공부", "영상 공부"),
    ("Ｐｙｔｈｏｎ", "python", "Ｐｙｔｈｏｎ"),
    ("Straße", "STRASSE", "Straße"),
    ("한글", "한글", "한글"),
    ("CAFÉ", "cafe\u0301", "CAFÉ"),
])
def test_equivalent_names_share_one_tag_across_targets(core, first, equivalent, display):
    video = core.videos()[0]
    highlight = core.highlights(video.id)[0]
    tag = core.add_video_tag(video.id, first)
    assert tag.name == display
    assert core.add_highlight_tag(highlight.id, equivalent) == tag
    assert core.create_tag(equivalent) == tag
    assert core.add_video_tag(video.id, equivalent) == tag
    assert core.tags() == core.video_tags(video.id) == core.highlight_tags(highlight.id) == (tag,)


def test_attach_and_detach_are_independent_and_preserve_tag(core):
    first, second, _ = core.videos()
    highlight = core.highlights(first.id)[0]
    tag = core.add_video_tag(first.id, "주제")
    core.add_video_tag(second.id, "주제")
    core.add_highlight_tag(highlight.id, "주제")
    core.remove_video_tag(first.id, tag.id)
    core.remove_video_tag(first.id, tag.id)
    assert core.video_tags(first.id) == ()
    assert core.video_tags(second.id) == core.highlight_tags(highlight.id) == (tag,)
    core.remove_highlight_tag(highlight.id, tag.id)
    core.remove_highlight_tag(highlight.id, tag.id)
    assert core.highlight_tags(highlight.id) == ()
    assert core.tags() == (tag,)


def test_tag_filter_keeps_video_and_highlight_targets_separate(core):
    first, second, third = core.videos()
    h1, h2 = core.highlights(first.id)[0], core.highlights(second.id)[0]
    tag = core.add_video_tag(third.id, "공통")
    core.add_video_tag(first.id, "공통")
    core.add_highlight_tag(h1.id, "공통")
    core.add_highlight_tag(h2.id, "공통")
    assert core.videos_for_tag(tag.id) == (first, third)
    assert core.highlights_for_tag(tag.id) == (h1, h2)
    empty = core.create_tag("미사용")
    assert core.videos_for_tag(empty.id) == core.highlights_for_tag(empty.id) == ()
    assert core.videos() == (first, second, third)


def test_tag_usage_counts_library_videos_most_used_first(core):
    first, second, third = core.videos()
    highlight = core.highlights(first.id)[0]
    for video in (first, second, third):
        core.add_video_tag(video.id, "흔함")
    for video in (first, second):
        core.add_video_tag(video.id, "나")
        core.add_video_tag(video.id, "Ｇａ")
    core.add_video_tag(third.id, "제외됨")
    core.add_highlight_tag(highlight.id, "하이라이트만")
    core.add_highlight_tag(highlight.id, "흔함")
    core.exclude_video(third.id)
    usage = core.tag_usage()
    # 같은 수는 정규화한 이름순(ga < 나)이고, 제외 영상·하이라이트 연결은 세지 않는다.
    assert [(u.tag.name, u.video_count) for u in usage] == [
        ("Ｇａ", 2), ("나", 2), ("흔함", 2), ("제외됨", 0), ("하이라이트만", 0)]
    assert {u.tag for u in usage} == set(core.tags())
    assert usage[0].key == "ga"


def test_tag_usage_is_empty_without_tags(core):
    assert core.tag_usage() == ()


def test_rename_and_delete_update_every_target_and_survive_restart(core):
    videos = core.videos()
    for video in videos:
        core.add_video_tag(video.id, "이전")
        core.add_highlight_tag(core.highlights(video.id)[0].id, "이전")
    tag, = core.tags()
    renamed = core.rename_tag(tag.id, "  새 이름  ")
    assert renamed.id == tag.id and renamed.name == "새 이름"
    reopened = AppCore(media=FakeMedia(), clock=lambda: None, database=core.database)
    assert reopened.tags() == (renamed,)
    assert reopened.tags("이전") == ()
    for video in videos:
        assert reopened.video_tags(video.id) == (renamed,)
        assert reopened.highlight_tags(core.highlights(video.id)[0].id) == (renamed,)
    reopened.delete_tag(tag.id)
    for video in videos:
        assert core.video_tags(video.id) == ()
        assert core.highlight_tags(core.highlights(video.id)[0].id) == ()
        assert core.highlights(video.id) == reopened.highlights(video.id)
    assert core.tags() == ()
    assert core.videos() == videos
    assert core.create_tag("새 이름").name == "새 이름"


def test_rename_collision_is_rejected_without_changing_either_tags_links(core):
    video = core.videos()[0]
    highlight = core.highlights(video.id)[0]
    first = core.add_video_tag(video.id, "Python")
    second = core.add_highlight_tag(highlight.id, "다른 태그")
    with pytest.raises(ValueError, match="이미 있습니다"):
        core.rename_tag(second.id, " ＰＹＴＨＯＮ ")
    assert core.video_tags(video.id) == (first,)
    assert core.highlight_tags(highlight.id) == (second,)
    assert core.tags() == (first, second)
    assert core.rename_tag(first.id, "PYTHON").name == "PYTHON"
    assert core.create_tag("python").id == first.id


@pytest.mark.parametrize("name", ["", " \t\n", "\u3000\u00a0"])
def test_empty_names_are_rejected_without_changing_tags(core, name):
    video = core.videos()[0]
    highlight = core.highlights(video.id)[0]
    tag = core.create_tag("남김")
    for action in (lambda: core.create_tag(name), lambda: core.rename_tag(tag.id, name),
                   lambda: core.add_video_tag(video.id, name),
                   lambda: core.add_highlight_tag(highlight.id, name)):
        with pytest.raises(ValueError, match="이름을 입력"):
            action()
    assert core.tags() == (tag,)
    assert core.video_tags(video.id) == core.highlight_tags(highlight.id) == ()


def test_autocomplete_uses_normalized_literal_prefix_and_updates_after_changes(core):
    for name in ("Python", "PySide", "Straße", "한글", "%기호", "_기호", "Rust"):
        core.create_tag(name)
    assert [t.name for t in core.tags(" Ｐｙ ")] == ["PySide", "Python"]
    assert [t.name for t in core.tags("STRASS")] == ["Straße"]
    assert [t.name for t in core.tags("한")] == ["한글"]
    assert [t.name for t in core.tags("%")] == ["%기호"]
    assert [t.name for t in core.tags("_")] == ["_기호"]
    assert core.tags("없는 이름") == ()
    tag, = core.tags("Rust")
    core.rename_tag(tag.id, "Ruby")
    assert core.tags("Rust") == ()
    core.delete_tag(tag.id)
    assert core.tags("Ruby") == ()


def test_deleting_tagged_highlight_cascades_links_and_keeps_other_targets(core):
    first, second, _ = core.videos()
    h1, h2 = core.highlights(first.id)[0], core.highlights(second.id)[0]
    tag = core.add_highlight_tag(h1.id, "남는 태그")
    core.add_highlight_tag(h2.id, tag.name)
    core.add_video_tag(first.id, tag.name)
    core.delete_highlight(h1.id)
    assert core.highlights(first.id) == ()
    assert core.highlights_for_tag(tag.id) == (h2,)
    assert core.video_tags(first.id) == core.highlight_tags(h2.id) == core.tags() == (tag,)
    core.playback.start(first.id, 20)
    core.execute_highlight_command(core.command_for_key("Insert"))
    core.playback.end()
    assert core.highlight_tags(core.highlights(first.id)[0].id) == ()


@pytest.mark.parametrize("target", ["video", "highlight"])
def test_unknown_targets_do_not_create_orphan_tags(core, target):
    with pytest.raises(ValueError, match="찾을 수 없습니다"):
        getattr(core, f"add_{target}_tag")(9999, "생기면 안 됨")
    assert core.tags() == ()
    with pytest.raises(ValueError, match="찾을 수 없습니다"):
        getattr(core, f"{target}_tags")(9999)


def test_unknown_tags_are_rejected_by_mutations_and_filters(core):
    video = core.videos()[0]
    highlight = core.highlights(video.id)[0]
    actions = [lambda: core.rename_tag(9999, "없음"), lambda: core.delete_tag(9999),
               lambda: core.videos_for_tag(9999), lambda: core.highlights_for_tag(9999),
               lambda: core.remove_video_tag(video.id, 9999),
               lambda: core.remove_highlight_tag(highlight.id, 9999)]
    for action in actions:
        with pytest.raises(ValueError, match="태그를 찾을 수 없습니다"):
            action()


def test_multiple_tags_survive_detach_delete_and_restart_without_changing_note(core):
    video = core.videos()[0]
    highlight = core.highlights(video.id)[0]
    highlight = core.update_highlight(highlight.id, start=12, end=20, note="보존할 메모")
    first = core.add_video_tag(video.id, "하나")
    second = core.add_video_tag(video.id, "둘")
    core.add_highlight_tag(highlight.id, first.name)
    core.add_highlight_tag(highlight.id, second.name)
    core.remove_video_tag(video.id, first.id)
    reopened = AppCore(media=FakeMedia(), clock=lambda: None, database=core.database)
    assert reopened.video_tags(video.id) == (second,)
    assert {tag.id for tag in reopened.highlight_tags(highlight.id)} == {first.id, second.id}
    reopened.delete_tag(first.id)
    again = AppCore(media=FakeMedia(), clock=lambda: None, database=core.database)
    assert again.tags() == again.video_tags(video.id) == again.highlight_tags(highlight.id) == (second,)
    assert again.highlights(video.id) == (highlight,)


def test_tag_names_are_flat_and_punctuation_is_literal(core):
    root = core.create_tag("언어")
    child_like = core.create_tag("언어/Python")
    punctuation = core.create_tag("quote' % _ ; --")
    video = core.videos()[0]
    core.add_video_tag(video.id, child_like.name)
    core.add_video_tag(video.id, punctuation.name)
    assert core.videos_for_tag(root.id) == ()
    assert core.videos_for_tag(child_like.id) == core.videos_for_tag(punctuation.id) == (video,)
    core.delete_tag(root.id)
    assert set(core.tags()) == {child_like, punctuation}


@pytest.mark.parametrize("entered, selected, expected", [
    ("강의", None, "강의"), ("Py", None, "Py"), ("Rust", None, "Rust"),
    ("Go", None, "Go"), ("강의", "강의 노트", "강의 노트"),
    ("Py", "Python", "Python"), (" Ｐｙ ", None, " Ｐｙ "),
])
def test_enter_uses_typed_name_unless_candidate_was_explicitly_selected(entered, selected, expected):
    assert resolve_tag_input(entered, selected) == expected


@pytest.mark.parametrize("current, count, key, page_size, expected", [
    (None, 0, "Down", 5, None), (None, 20, "Down", 5, 0),
    (None, 20, "Up", 5, 19), (19, 20, "Down", 5, 0), (0, 20, "Up", 5, 19),
    (0, 2, "PageDown", 5, 1), (1, 2, "PageUp", 5, 0),
    (2, 20, "PageDown", 5, 7), (7, 20, "PageUp", 5, 2),
    (18, 20, "PageDown", 5, 19), (1, 20, "PageUp", 5, 0),
    (None, 20, "PageDown", 5, 5), (None, 20, "PageUp", 5, 0),
    (8, 20, "Home", 5, 0), (8, 20, "End", 5, 19),
])
def test_candidate_navigation_selects_visible_row(current, count, key, page_size, expected):
    assert move_tag_candidate(current, count, key, page_size) == expected


@pytest.mark.parametrize("name, equivalent", [
    ("①강", "1강"), ("Brand™", "BrandTM"), ("㈜회사", "(주)회사"),
    ("½", "1⁄2"), ("x²", "x2"), ("ｶﾀｶﾅ", "カタカナ"),
])
def test_display_preserves_compatibility_characters_but_identity_normalizes_them(core, name, equivalent):
    tag = core.create_tag(name)
    assert tag.name == name
    assert core.create_tag(equivalent) == tag
    assert core.tags(equivalent) == (tag,)
    renamed = core.rename_tag(tag.id, f" {name} ")
    assert renamed.name == name and renamed.id == tag.id


@pytest.mark.parametrize("name", ["가" * 51, "a" * 100000], ids=["51-characters", "100000-characters"])
def test_overlong_names_are_rejected_by_all_writes_without_side_effects(core, name):
    video = core.videos()[0]
    highlight = core.highlights(video.id)[0]
    original = core.add_video_tag(video.id, "기존")
    core.add_highlight_tag(highlight.id, original.name)
    for action in (lambda: core.create_tag(name), lambda: core.rename_tag(original.id, name),
                   lambda: core.add_video_tag(video.id, name),
                   lambda: core.add_highlight_tag(highlight.id, name)):
        with pytest.raises(ValueError, match="50자"):
            action()
    assert core.tags() == core.video_tags(video.id) == core.highlight_tags(highlight.id) == (original,)


def test_name_length_counts_cleaned_nfc_display_name(core):
    # 150자 조합형 입력을 완성형 50자로 세며, 비교 키가 늘어나도 표시 길이를 센다.
    tag = core.create_tag("  " + "한" * 50 + " \u200b ")
    assert tag.name == "한" * 50
    assert core.create_tag("™" * 50).name == "™" * 50
    with pytest.raises(ValueError, match="50자"):
        core.create_tag("™" * 51)


@pytest.mark.parametrize("dirty, clean", [
    ("Py\u200bthon", "Python"), ("Python\ufeff", "Python"),
    ("a\x00b", "ab"), ("a\x1fb", "ab"), ("\u202eabc\u202c", "abc"),
    ("a\tb\nc", "abc"), ("가\u200d나", "가나"),
])
def test_control_and_format_characters_are_removed_from_names_and_completion(core, dirty, clean):
    tag = core.create_tag(dirty)
    assert tag.name == clean
    assert core.create_tag(clean) == tag
    assert core.tags(dirty) == (tag,)
    assert core.rename_tag(tag.id, dirty).name == clean


@pytest.mark.parametrize("name", ["\u200b\ufeff", "\x00\x1f", " \u200d\u202e "])
def test_invisible_only_names_are_rejected(core, name):
    with pytest.raises(ValueError, match="이름을 입력"):
        core.create_tag(name)
    assert core.tags() == ()


@pytest.mark.parametrize("target, message", [
    ("video", "영상을 찾을 수 없습니다."), ("highlight", "하이라이트를 찾을 수 없습니다."),
])
def test_missing_target_error_uses_correct_sentence(core, target, message):
    with pytest.raises(ValueError) as error:
        getattr(core, f"add_{target}_tag")(9999, "태그")
    assert str(error.value) == message


def test_tagged_highlights_keep_order_note_and_updated_times(core):
    first, second, _ = core.videos()
    core.playback.start(first.id, 5)
    core.execute_highlight_command(core.command_for_key("Insert"))
    core.playback.end()
    earlier, later = core.highlights(first.id)
    other = core.highlights(second.id)[0]
    for highlight in (other, later, earlier):
        core.add_highlight_tag(highlight.id, "조회")
    tag, = core.tags()
    changed = core.update_highlight(later.id, start=1, end=3, note="수정한 메모")
    assert core.highlights_for_tag(tag.id) == (changed, earlier, other)
