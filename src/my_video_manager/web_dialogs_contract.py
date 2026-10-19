"""웹 대화상자 층 브리지 계약."""

from . import web_dialogs_data, web_translation_data
from .web_contract_types import Argument, BridgeContract

DIALOGS = BridgeContract(
    name='dialogs', interface='DialogsBridge',
    slots={'snapshot': (),
           'modalState': (Argument('open', int, 'number'),),
           'popupState': (Argument('id', str, 'string'),),
           'contentSize': (Argument('id', str, 'string'), Argument('width', int, 'number'), Argument('height', int, 'number')),
           'act': (Argument('id', str, 'string'), Argument('action', str, 'string'), Argument('payload', str, 'string')),
           'candidates': (Argument('prefix', str, 'string'),)},
    signals={'dialogsChanged': str, 'popupRestore': str},
    data_types=(web_translation_data.TranslationSelectionData, web_translation_data.TranslationModelData,
                web_translation_data.TranslationProviderData, web_translation_data.TranslationSettingsData,
                web_dialogs_data.DialogRow, web_dialogs_data.DialogValues,
                web_dialogs_data.DialogData, web_dialogs_data.DialogSnapshot),
)
