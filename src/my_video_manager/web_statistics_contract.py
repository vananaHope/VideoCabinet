"""통계 페이지 브리지 계약."""

from . import web_statistics_data
from .statistics import DailyViewingStatistics, TopViewedVideo, LibraryStatistics, ViewingStatistics
from .statistics import DistributionBucket, LibraryInventory, StatisticsDashboard
from .web_contract_types import Argument, BridgeContract

STATISTICS = BridgeContract(name='statistics', interface='StatisticsBridge', slots={
    'ready': (), 'snapshot': (), 'setPeriod': (Argument('days', int, 'number'),),
    'playVideo': (Argument('videoId', int, 'number'),),
}, signals={'statisticsChanged': str, 'statisticsFocusRequested': str},
    data_types=(DailyViewingStatistics, TopViewedVideo, LibraryStatistics, ViewingStatistics,
                DistributionBucket, LibraryInventory, StatisticsDashboard,
                web_statistics_data.StatisticsData))
