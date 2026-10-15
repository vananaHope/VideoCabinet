"""통계 dataclass를 그대로 JSON에 싣는 페이지 상태 계약."""
from typing import TypedDict

from .statistics import StatisticsDashboard


class StatisticsData(TypedDict):
    days: int
    loading: bool
    message: str
    result: StatisticsDashboard | None
