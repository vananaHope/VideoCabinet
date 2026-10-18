"""검색 페이지 브리지 계약."""

from . import web_search_data
from .web_contract_types import Argument, BridgeContract

SEARCH = BridgeContract(name='search', interface='SearchBridge', slots={
    'ready': (), 'snapshot': (), 'find': (Argument('query', str, 'string'),),
    'select': (Argument('index', int, 'number'),),
    'play': (Argument('index', int, 'number'),),
}, signals={'changed': str, 'focusRequested': str, 'error': str},
    data_types=(web_search_data.SearchTextData, web_search_data.SearchResultData, web_search_data.SearchData))
