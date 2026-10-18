"""모아보기 페이지 브리지 계약."""

from . import web_reel_data
from .web_contract_types import Argument, BridgeContract

REEL = BridgeContract(name='reel', interface='ReelBridge', slots={
    'ready': (), 'snapshot': (), 'refresh': (),
    'filter': (Argument('tagId', int, 'number'),),
    'select': (Argument('highlightId', int, 'number'),),
    'play': (Argument('highlightId', int, 'number'),),
}, signals={'changed': str, 'focusRequested': str, 'error': str},
    data_types=(web_reel_data.ReelEntryData, web_reel_data.ReelData))
