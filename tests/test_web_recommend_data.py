"""동일 종류 추천 줄의 공개 JSON 식별 계약."""
from dataclasses import replace

from my_video_manager.core import LibrarySnapshot
from my_video_manager.recommendation import Recommendation, RecommendationRow
from my_video_manager.viewing import ViewingStatus
from my_video_manager.web_recommend_data import rows_data
from test_recommendation import series_video


def test_same_kind_and_title_rows_keep_distinct_stable_keys():
    videos = tuple(series_video(i) for i in (1, 2, 3))
    snapshot = LibrarySnapshot(videos, {v.id: ViewingStatus() for v in videos}, {}, ())
    rows = tuple(RecommendationRow('because_watched', '같은 제목',
                                  (Recommendation(video, '공유 태그'),), source_video_id=video.id + 10)
                 for video in videos)
    data = rows_data(rows, snapshot)
    assert [row['kind'] for row in data] == ['because_watched'] * 3
    assert len({row['key'] for row in data}) == 3
    renamed = rows_data(tuple(replace(row, title='바뀐 제목') for row in reversed(rows)), snapshot)
    assert [row['key'] for row in renamed] == [row['key'] for row in reversed(data)]
    assert [row['items'][0]['video']['id'] for row in renamed] == [3, 2, 1]
