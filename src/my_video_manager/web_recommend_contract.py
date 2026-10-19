"""추천 페이지 브리지 계약."""

from . import web_recommend_data
from .web_contract_types import Argument, BridgeContract

RECOMMEND = BridgeContract(name='recommend', interface='RecommendBridge', slots={
    'ready': (), 'snapshot': (),
    'play': (Argument('videoId', int, 'number'),),
    'dismiss': (Argument('videoId', int, 'number'),),
    'restore': (Argument('videoId', int, 'number'),),
    'showDismissed': (),
}, signals={'changed': str, 'focusRequested': str, 'error': str},
    data_types=(web_recommend_data.RecommendationItemData, web_recommend_data.RecommendationRowData,
                web_recommend_data.RecommendData))
