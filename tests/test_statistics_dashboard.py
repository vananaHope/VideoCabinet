"""확장 통계는 AppCore의 저장·복습·자막 공개 시나리오로 검증한다."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from my_video_manager.core import AppCore, MediaInfo
from test_statistics import library, watch, NOW, KST, UTC
from test_translation import setup, source


@pytest.mark.parametrize('days', [7, 30, 90, 365])
def test_dashboard_activity_assigns_whole_session_to_local_start_hour(library, days):
    core, clock, (a, b, c) = library
    start = datetime.combine(NOW.date() - timedelta(days=days - 1), datetime.min.time(), KST)
    clock.now = start - timedelta(seconds=1)
    watch(core, a.id, 20)  # 이전 기간
    clock.now = NOW.replace(hour=23, minute=59, second=59).astimezone(UTC)
    core.playback.start(a.id, 0)
    clock.now += timedelta(seconds=95)  # 자정과 정시를 넘어도 시작일 23시에 넣는다.
    core.playback.report(95)
    core.playback.end()
    clock.now = NOW
    watch(core, b.id, 1)  # 틀어보기는 이력만 남는다.
    core.playback.start(c.id, 0, record_viewing=False)
    core.playback.report(95)
    core.playback.end()
    result = core.statistics_dashboard(days, tz=KST)
    assert result.period == core.viewing_statistics(days, tz=KST)
    assert sum(result.weekday_seconds) == sum(result.hourly_seconds) == result.period.watched_seconds == 95
    assert result.hourly_seconds[23] == 95
    assert result.weekday_seconds[(NOW.weekday() + 1) % 7] == 95
    assert result.inventory.all_watched_seconds == 115
    assert result.inventory.never_played_count == 1


def test_dashboard_inventory_deduplicates_copies_and_keeps_unknown_sizes(library, tmp_path):
    core, _, (a, b, c) = library
    copy = tmp_path / 'copy.mkv'
    copy.write_bytes(a.locations[0].path.read_bytes())
    core.add_file(copy)
    watch(core, a.id, 90)
    watch(core, b.id, 10)
    core.add_video_tag(b.id, '태그')
    core.request_subtitles(b.id)
    core.process_next_subtitle()
    core.playback.start(b.id, 1, record_viewing=False)
    core.execute_highlight_command(core.command_for_key('Insert'))
    core.playback.end()
    before = core.statistics_dashboard(7)
    assert before.inventory.video_count == 3
    assert before.inventory.known_size_bytes == 3
    assert before.inventory.unknown_size_count == 0
    core.exclude_video(a.id)
    b.locations[0].path.unlink()
    core.scan()
    result = core.statistics_dashboard(7)
    inventory = result.inventory
    assert inventory.video_count == 2
    assert inventory.duration_seconds == 200
    assert inventory.known_size_bytes == 1
    assert inventory.unknown_size_count == 1
    assert inventory.all_watched_seconds == 100  # 제외 영상의 기록도 포함
    assert inventory.korean_subtitled_count == 1
    assert inventory.highlighted_video_count == inventory.tagged_video_count == 1
    assert result.period.library.subtitled_video_count == 1
    assert core.statistics_dashboard(365).inventory == inventory


def test_dashboard_completed_revisit_is_history_but_not_watching(library):
    core, clock, (a, b, c) = library
    watch(core, b.id, 1)
    core.playback.start(a.id, 10, record_viewing=False)
    core.execute_highlight_command(core.command_for_key('Insert'))
    core.playback.end()
    highlight = core.highlights(a.id)[0]
    core.update_highlight(highlight.id, start=10, end=20, note='복습')
    core.start_reel(highlight_id=highlight.id)
    clock.now += timedelta(seconds=4)
    core.playback.report(14)
    core.playback.end()
    result = core.statistics_dashboard(7)
    assert core.viewings(a.id) == ()
    assert result.period.library.unwatched_count == 3
    assert result.inventory.never_played_count == 1
    assert result.inventory.all_watched_seconds == sum(result.hourly_seconds) == 0


def test_dashboard_partial_korean_translation_and_original_language(setup):
    core, _, _, _, _ = setup
    a, b = core.videos()
    source(core, a.id, 'en')
    source(core, b.id, 'ko')
    assert core.statistics_dashboard(7).inventory.korean_subtitled_count == 1
    core.process_next_translation()  # 전체 완료 전 저장된 두 줄도 자막이다.
    assert 0 < core.library_details(a.id).translated_lines < len(core.transcript(a.id).lines)
    assert core.statistics_dashboard(7).inventory.korean_subtitled_count == 2


def test_dashboard_duration_boundaries_and_container_names(tmp_path):
    class Media:
        def read(self, path):
            return MediaInfo(float(path.stem), 'mov,mp4,m4a,3gp,3g2,mj2' if path.stem == '600' else 'matroska,webm')

        def capture(self, path, destination, seconds):
            destination.write_bytes(b'image')

    core = AppCore(media=Media(), clock=lambda: NOW, database=tmp_path / 'db/library.sqlite3')
    for duration in (599, 600, 1799, 1800, 3599, 3600, 7199, 7200):
        path = tmp_path / f'{duration}.mkv'
        path.write_bytes(str(duration).encode())
        core.add_file(path)
    inventory = core.statistics_dashboard(7).inventory
    assert [bucket.video_count for bucket in inventory.duration_distribution] == [1, 2, 2, 2, 1]
    assert {bucket.label: bucket.video_count for bucket in inventory.format_distribution} == {'Matroska / WebM': 7, 'MP4 / QuickTime': 1}
    assert inventory.duration_seconds == sum((599, 600, 1799, 1800, 3599, 3600, 7199, 7200))


def test_dashboard_empty_library_has_zero_buckets(tmp_path):
    core = AppCore(media=None, clock=lambda: NOW, database=tmp_path / 'db/library.sqlite3')
    result = core.statistics_dashboard(7)
    assert result.inventory.video_count == result.inventory.known_size_bytes == result.inventory.unknown_size_count == 0
    assert result.inventory.format_distribution == ()
    assert len(result.inventory.duration_distribution) == 5
    assert result.weekday_seconds == (0,) * 7 and result.hourly_seconds == (0,) * 24


def test_dashboard_query_count_does_not_grow_with_library(library, tmp_path, monkeypatch):
    import sqlite3
    core, _, _ = library
    statements = []
    original_connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(sqlite3, 'connect', traced_connect)
    core.statistics_dashboard(7)
    before = sum(sql.startswith('SELECT') for sql in statements)
    for i in range(20):
        path = tmp_path / f'new{i}.mkv'
        path.write_bytes(str(i).encode())
        core.add_file(path)
    statements.clear()
    core.statistics_dashboard(365)
    assert sum(sql.startswith('SELECT') for sql in statements) == before == 8
