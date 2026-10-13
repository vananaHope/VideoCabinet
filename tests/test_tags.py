from datetime import datetime, timezone

import pytest

from my_video_manager.core import AppCore, MediaInfo


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
    ("Ｐｙｔｈｏｎ", "python", "Python"),
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
