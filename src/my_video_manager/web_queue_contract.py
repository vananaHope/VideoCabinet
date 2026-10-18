"""자막 대기열 페이지 브리지 계약."""

from . import web_queue_data
from .web_contract_types import Argument, BridgeContract, Constant, TypeAlias

QUEUE = BridgeContract(name='queue', interface='QueueBridge', slots={
    'ready': (), 'snapshot': (), 'rulesSnapshot': (),
    'preparationSnapshot': (), 'preparationAction': (Argument('action', str, 'string'),),
    'action': (Argument('name', str, 'QueueAction'), Argument('videoId', int, 'number')),
    'candidates': (Argument('target', str, 'string'),),
    'saveRule': (Argument('target', str, 'string'), Argument('language', str, 'string'),
                 Argument('includeExisting', bool, 'boolean')),
    'removeRule': (Argument('ruleId', int, 'number'),),
}, signals={'queueChanged': str, 'rulesChanged': str, 'queueFocusRequested': str, 'queueDeactivated': str,
            'preparationChanged': str, 'bulkFinished': str},
    aliases=(TypeAlias('QueueAction', ('promote', 'remove', 'retryFailed', 'retryHeld', 'refineExisting', 'previewRefineExisting')),),
    constants=(Constant('queueStates', tuple(web_queue_data.STATES.items())),),
    data_types=(web_queue_data.PreparationData, web_queue_data.QueueRowData, web_queue_data.QueueCountData, web_queue_data.QueueDeltaData,
                web_queue_data.QueueTargetData, web_queue_data.QueueRuleData, web_queue_data.QueueRulesData))
