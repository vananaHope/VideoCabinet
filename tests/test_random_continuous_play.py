"""AppCore 공개 동작으로 무작위 이어 재생의 선택·수명주기를 확인한다."""
from datetime import datetime, timezone

import pytest

from my_video_manager.core import AppCore
from my_video_manager.random_continuous_play import RandomPlayScope
from test_random_play import FakeMedia


@pytest.fixture
def core(tmp_path):
    core = AppCore(media=FakeMedia(), clock=lambda: datetime.now(timezone.utc),
                   database=tmp_path / 'data/library.sqlite3', random_choice=min)
    for name in 'abcd':
        path = tmp_path / f'{name}.mkv'
        path.write_bytes(name.encode())
        core.add_file(path)
    return core


def ids(core):
    return tuple(v.id for v in core.videos())


def start(core, scope=None, source=None):
    scope = scope or RandomPlayScope()
    video_id = core.pick_random_video(
        video_ids=scope.video_ids if scope.kind == 'list' else None,
        tag_ids=scope.tag_ids if scope.kind == 'tags' else None)
    assert video_id is not None
    core.switch_to(video_id, playback_video_ids=ids(core) if source is None else source, random_scope=scope)
    return video_id


def move(core, forward=True):
    target = core.execute_video_command(core.command_for_key('PgDn' if forward else 'PgUp'), ())
    if target is not None:
        core.switch_to(target)
    return target


@pytest.mark.parametrize('kind', ['all', 'list', 'tags'])
def test_scope_candidates_and_snapshot(core, kind):
    a, b, c, d = ids(core)
    red = core.add_video_tag(a, 'red')
    core.add_video_tag(b, 'red')
    blue = core.add_video_tag(c, 'blue')
    scope = {'all': RandomPlayScope(), 'list': RandomPlayScope('list', (a, c)),
             'tags': RandomPlayScope('tags', tag_ids=(red.id, blue.id))}[kind]
    expected = {'all': [a, b, c, d], 'list': [a, c], 'tags': [a, b, c]}[kind]
    source = [d, a]
    assert start(core, scope, source) == expected[0]
    source.clear()
    assert core.playback_video_ids == (d, a)
    assert [move(core) for _ in expected[1:]] == expected[1:]
    assert core.random_continuous_scope == scope


def test_cycle_no_repeat_then_restart_without_immediate_repeat(core):
    a, b, c, d = ids(core)
    assert start(core) == a
    assert [move(core) for _ in range(7)] == [b, c, d, a, b, c, d]


def test_single_candidate_restarts_as_a_new_viewing(core):
    a = ids(core)[0]
    start(core, RandomPlayScope('list', (a,)))
    first = core.playback.session
    core.playback.report(20)
    assert move(core) == a
    assert core.playback.session is not first
    assert len(core.viewings(a)) == 2
    assert core.viewings(a)[0].ended_at is not None
    assert core.playback.position == 17


def test_history_back_forward_then_new_choice_and_first_notice(core):
    a, b, c, _ = ids(core)
    start(core)
    first = core.playback.session
    assert move(core, False) is None
    assert core.take_random_continuous_notice()
    assert core.playback.session is first
    assert [move(core), move(core), move(core, False), move(core, False), move(core), move(core)] == [b, c, b, a, b, c]
    assert move(core) == ids(core)[-1]


def test_scope_change_keeps_seen_and_history_and_current_session(core):
    a, b, c, d = ids(core)
    start(core, RandomPlayScope('list', (a, b)))
    assert move(core) == b
    assert move(core, False) == a
    session = core.playback.session
    core.set_random_continuous_scope(RandomPlayScope('list', (a, b, d)))
    assert core.playback.session is session
    assert move(core) == b  # 이미 거친 앞으로 기록을 먼저 쓴다.
    assert move(core) == d  # 범위 변경 전 나온 a, b는 제외한다.
    assert c not in (core.playback.session.video_id,)


def test_tags_stay_or_based_and_use_latest_membership(core):
    a, b, c, d = ids(core)
    red = core.add_video_tag(a, 'red')
    core.add_video_tag(b, 'red')
    blue = core.add_video_tag(c, 'blue')
    start(core, RandomPlayScope('tags', tag_ids=(red.id, blue.id)), source=(d,))
    core.remove_video_tag(b, red.id)
    core.add_video_tag(d, 'blue')
    assert move(core) == c
    assert move(core) == d


@pytest.mark.parametrize('kind', ['all', 'list', 'tags'])
def test_missing_excluded_out_and_finished_in(core, kind):
    a, b, c, d = core.videos()
    tag = core.create_tag('scope')
    for video in core.videos():
        core.add_video_tag(video.id, tag.name)
    a.locations[0].path.unlink()
    core.scan()
    core.exclude_video(b.id)
    core.switch_to(c.id)
    core.playback.report(95)
    core.end_playback()
    scope = {'all': RandomPlayScope(), 'list': RandomPlayScope('list', (a.id, b.id, c.id, d.id)),
             'tags': RandomPlayScope('tags', tag_ids=(tag.id,))}[kind]
    assert start(core, scope) == c.id
    assert move(core) == d.id
    assert move(core) == c.id


def test_zero_candidates_keeps_current_and_notices_without_ending(core):
    start(core)
    core.set_random_continuous_scope(RandomPlayScope('tags'))
    session = core.playback.session
    core.playback.report(100)
    assert core.advance_random_if_due(session, eof=True) is None
    assert core.take_random_continuous_notice()
    assert core.take_random_continuous_notice() is None
    assert core.playback.session is session
    assert core.viewings(session.video_id)[-1].ended_at is None


@pytest.mark.parametrize('missing', [False, True])
def test_unplayable_history_is_skipped_in_both_directions(core, missing):
    a, b, c, d = ids(core)
    start(core)
    move(core)
    move(core)
    if missing:
        core.video(b).locations[0].path.unlink()
        core.scan()
    else:
        core.exclude_video(b)
    assert move(core, False) == a
    assert move(core) == c
    assert move(core) == d


def test_unplayable_forward_history_falls_back_to_new_choice(core):
    a, b, c, d = ids(core)
    start(core)
    move(core)
    move(core, False)
    core.exclude_video(b)
    assert move(core) == c
    core.exclude_video(a)
    assert move(core, False) is None
    assert core.take_random_continuous_notice()


def test_manual_start_enable_disable_and_reenable_use_original_list(core):
    a, b, c, d = ids(core)
    core.switch_to(a, playback_video_ids=(c, a, d))
    assert not core.random_continuous_enabled
    core.set_random_continuous_enabled(True)
    assert core.random_continuous_scope == RandomPlayScope('list', (c, a, d))
    assert move(core) == c
    core.set_random_continuous_scope(RandomPlayScope())
    core.set_random_continuous_enabled(False)
    assert move(core) == a  # 목록 순서 복원, 무작위 기록은 버림.
    core.set_random_continuous_enabled(True)
    assert core.random_continuous_scope == RandomPlayScope('list', (c, a, d))
    assert move(core, False) is None


def test_list_return_discards_state_and_next_manual_play_starts_off(core):
    a, b, c, d = ids(core)
    start(core)
    move(core)
    core.end_playback()
    assert core.playback.session is None
    assert not core.random_continuous_enabled
    assert core.random_continuous_scope is None
    assert core.playback_video_ids == ()
    core.switch_to(c, playback_video_ids=(c, d))
    assert not core.random_continuous_enabled
    core.set_random_continuous_enabled(True)
    assert move(core, False) is None
    assert move(core) == d


def test_each_transition_closes_viewing_and_open_range_and_resumes(core):
    a, b, c, d = ids(core)
    core.switch_to(b)
    core.playback.report(30)
    core.end_playback()
    start(core)
    core.playback.report(10)
    core.execute_highlight_command(core.command_for_key('Delete'))
    core.playback.report(20)
    old = core.playback.session
    assert move(core) == b
    assert core.playback.position == 27
    assert core.highlights(a)[0].end == 20
    assert core.viewings(a)[0].played_seconds == 20
    assert core.viewings(a)[0].ended_at is not None
    assert core.advance_random_if_due(old, eof=True) is None
    assert len(core.viewings(b)) == 2
    assert move(core, False) == a
    assert core.playback.position == 17
    core.end_playback()
    assert len(core.viewings(a)) == 2
    assert all(v.ended_at is not None for v in core.viewings(a) + core.viewings(b))


def test_random_entry_first_pick_keeps_previous_choice_rule(core):
    a, b, c, d = ids(core)
    assert start(core) == a
    core.end_playback()
    assert start(core) == b


def test_history_moves_count_as_seen_after_cycle_reset(core):
    a, b, c, d = ids(core)
    start(core)
    assert [move(core) for _ in range(4)] == [b, c, d, a]
    assert move(core, False) == d
    assert move(core) == a
    core.set_random_continuous_scope(RandomPlayScope('list', (a, d)))
    # a와 d는 새 바퀴에서 모두 보았으므로 바퀴를 비운 뒤 a를 피한다.
    assert move(core) == d
    core.set_random_continuous_scope(RandomPlayScope())
    assert move(core) == a  # 초기화된 집합에는 d만 남아 있다.


def test_history_move_does_not_replace_last_random_pick(core):
    a, b, c, d = ids(core)
    start(core)
    move(core)
    move(core, False)
    core.end_playback()
    assert start(core, RandomPlayScope('list', (a, b))) == a


def test_reel_clears_continuous_and_rejects_enabling(core):
    a = start(core)
    core.playback.report(10)
    core.execute_highlight_command(core.command_for_key('Insert'))
    assert core.start_reel() is not None
    assert not core.random_continuous_enabled
    with pytest.raises(ValueError):
        core.set_random_continuous_enabled(True)


def test_invalid_reel_request_keeps_current_random_play(core):
    first = start(core)
    session = core.playback.session
    with pytest.raises(ValueError):
        core.start_reel(highlight_id=999999)
    assert core.playback.session is session
    assert core.random_continuous_enabled
    assert move(core) != first


def test_off_eof_does_not_advance(core):
    core.switch_to(ids(core)[0], playback_video_ids=ids(core))
    session = core.playback.session
    core.playback.report(100)
    assert core.advance_random_if_due(session, eof=True) is None
    assert core.playback.session is session


def test_subtitle_language_resets_for_each_random_video_and_restart_is_off(tmp_path):
    from test_translation import Transcriber, Translator, source, finish

    core = AppCore(media=FakeMedia(), clock=lambda: datetime.now(timezone.utc),
                   database=tmp_path / 'data/library.sqlite3', random_choice=min,
                   transcriber=Transcriber(), translator=Translator())
    for name in 'ab':
        path = tmp_path / f'{name}.mkv'
        path.write_bytes(name.encode())
        core.add_file(path)
    for video_id in ids(core):
        source(core, video_id)
    finish(core)
    start(core)
    assert core.toggle_subtitle_language()[0]
    assert core.playback_subtitle_language == 'translated'
    assert move(core) == ids(core)[1]
    assert core.playback_subtitle_language == 'original'
    assert core.playback_subtitle(core.playback.session.video_id).exists()
    core.end_playback()
    reopened = AppCore(media=FakeMedia(), clock=lambda: datetime.now(timezone.utc), database=core.database)
    assert not reopened.random_continuous_enabled
    assert reopened.random_continuous_scope is None


def test_enabling_counts_current_video_before_completing_cycle(core):
    a, b, c, d = ids(core)
    core.switch_to(a, playback_video_ids=(a, b, c, d))
    core.set_random_continuous_enabled(True)
    assert [move(core) for _ in range(4)] == [b, c, d, a]


def test_enabling_with_only_current_video_starts_a_new_viewing(core):
    a = ids(core)[0]
    core.switch_to(a, playback_video_ids=(a,))
    core.set_random_continuous_enabled(True)
    session = core.playback.session
    assert move(core) == a
    assert core.playback.session is not session
    assert len(core.viewings(a)) == 2
    assert core.viewings(a)[0].ended_at is not None
