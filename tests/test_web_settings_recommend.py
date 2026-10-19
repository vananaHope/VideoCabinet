"""설정의 '추천' 절: 공개 브리지로 기간을 읽고 바꾸고 되돌리며, 추천 탭에 반영되는지 검증한다."""
import json
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

from test_web_library_page import window_factory
from test_web_library_data import Media
from my_video_manager.core import AppCore
from my_video_manager.recommendation import RECOMMENDATION_PERIODS


class Clock:
    def __init__(self):
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def core(tmp_path, clock):
    core = AppCore(media=Media(), clock=clock, database=tmp_path / 'data/library.sqlite3')
    path = tmp_path / '새 영상.mkv'
    path.write_bytes(b'new')
    core.add_file(path)
    return core


@pytest.fixture
def settings(window_factory):
    window = window_factory()
    window.navigate_web_tab('settings')
    return window, window.web_host.controllers['settings'].bridge


def periods(bridge):
    return {row['criterion']: row['days'] for row in json.loads(bridge.snapshot())['recommendationPeriods']}


def test_snapshot_lists_five_periods_from_core_definitions(settings):
    _, bridge = settings
    rows = json.loads(bridge.snapshot())['recommendationPeriods']
    assert [(row['criterion'], row['label'], row['defaultDays'], row['minimumDays'], row['maximumDays'])
            for row in rows] == [(period.criterion, period.label, period.default_days, period.minimum_days,
                                  period.maximum_days) for period in RECOMMENDATION_PERIODS]
    assert all(row['description'] for row in rows)
    assert {row['criterion']: row['days'] for row in rows} == {
        'continue_watching': 30, 'revisit': 30, 'new_arrivals': 14, 'rewatch': 60, 'unwatched': 30}


@pytest.mark.parametrize('criterion', [period.criterion for period in RECOMMENDATION_PERIODS])
def test_valid_text_saves_and_reset_restores_default(settings, core, criterion):
    _, bridge = settings
    default = core.recommendation_period_days()[criterion]
    result = json.loads(bridge.setRecommendationPeriod(criterion, ' 2.5 '))
    assert 'error' not in result
    assert {row['criterion']: row['days'] for row in result['recommendationPeriods']}[criterion] == 2.5
    assert core.recommendation_period_days()[criterion] == 2.5
    assert periods(bridge)[criterion] == 2.5
    assert 'error' not in json.loads(bridge.resetRecommendationPeriod(criterion))
    assert periods(bridge)[criterion] == default
    assert core.recommendation_period_days()[criterion] == default


@pytest.mark.parametrize('text', ['', '   ', 'abc', '30일', '-1', '365001', 'nan', 'inf', '-inf'])
def test_invalid_text_is_rejected_without_saving(settings, core, text):
    _, bridge = settings
    core.set_recommendation_period_days('rewatch', 45)
    before = core.recommendation_period_days()
    result = json.loads(bridge.setRecommendationPeriod('rewatch', text))
    assert result['error']
    assert core.recommendation_period_days() == before
    assert periods(bridge)['rewatch'] == 45


def test_unknown_criterion_is_rejected(settings, core):
    _, bridge = settings
    before = core.recommendation_period_days()
    assert json.loads(bridge.setRecommendationPeriod('unknown', '10'))['error']
    assert json.loads(bridge.resetRecommendationPeriod('unknown'))['error']
    assert core.recommendation_period_days() == before


def test_changed_period_applies_when_returning_to_recommend_tab(settings, clock):
    window, bridge = settings
    recommend = window.web_host.controllers['recommend']

    def kinds():
        window.navigate_web_tab('recommend')
        return [row['kind'] for row in json.loads(recommend.bridge.snapshot())['rows']]

    clock.now += timedelta(days=10)
    assert kinds() == ['new_arrivals']
    window.navigate_web_tab('settings')
    assert 'error' not in json.loads(bridge.setRecommendationPeriod('new_arrivals', '5'))
    assert kinds() == []
    window.navigate_web_tab('settings')
    assert 'error' not in json.loads(bridge.resetRecommendationPeriod('new_arrivals'))
    assert kinds() == ['new_arrivals']


def test_broken_stored_period_keeps_settings_open_and_reset_repairs_it(window_factory, core):
    core.settings.set('recommend.rewatch_days', -5)
    window = window_factory()
    window.navigate_web_tab('settings')
    bridge = window.web_host.controllers['settings'].bridge
    rows = {row['criterion']: row for row in json.loads(bridge.snapshot())['recommendationPeriods']}
    assert rows['rewatch']['days'] is None and rows['rewatch']['error']
    assert all(row['days'] is not None and not row['error'] for key, row in rows.items() if key != 'rewatch')
    assert 'error' not in json.loads(bridge.resetRecommendationPeriod('rewatch'))
    rows = {row['criterion']: row for row in json.loads(bridge.snapshot())['recommendationPeriods']}
    assert rows['rewatch']['days'] == 60 and not rows['rewatch']['error']
