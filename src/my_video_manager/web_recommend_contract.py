"""추천 페이지 브리지 계약."""

from . import web_recommend_data
from .recommendation import ROW_LIMIT
from .web_contract_types import Argument, BridgeContract, Constant

RECOMMEND = BridgeContract(name='recommend', interface='RecommendBridge', slots={
    'ready': (), 'snapshot': (),
    'play': (Argument('videoId', int, 'number'),),
    'dismiss': (Argument('videoId', int, 'number'),),
    'restore': (Argument('videoId', int, 'number'),),
    'showDismissed': (),
}, signals={'changed': str, 'focusRequested': str, 'error': str},
    # 줄마다 보이는 최대 개수. 첫 데이터 전에도 머리글 설명이 같은 문구·줄 수로 보인다(#262).
    constants=(Constant('recommendRowLimit', ROW_LIMIT, 'number'),),
    data_types=(web_recommend_data.RecommendationItemData, web_recommend_data.RecommendationRowData,
                web_recommend_data.RecommendData))
