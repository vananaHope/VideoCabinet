"""설정 페이지 브리지 계약."""

from . import web_backup_data, web_settings_data, web_update_data
from .web_contract_types import Argument, BridgeContract, TypeAlias

SETTINGS = BridgeContract(name='settings', interface='SettingsBridge', slots={
    'ready': (), 'snapshot': (),
    'saveKeys': (Argument('draft', str, 'string'),),
    'beginCapture': (Argument('command', str, 'string'),),
    'captureKey': (Argument('key', str, 'string'),), 'cancelCapture': (),
    'setMinimum': (Argument('seconds', float, 'number'),),
    'setAutomaticDetection': (Argument('enabled', bool, 'boolean'),),
    'setRecommendationPeriod': (Argument('criterion', str, 'string'), Argument('days', str, 'string')),
    'resetRecommendationPeriod': (Argument('criterion', str, 'string'),),
    'checkUpdate': (),
    'setAutomaticUpdateCheck': (Argument('enabled', bool, 'boolean'),),
    'action': (Argument('name', str, 'SettingsAction'),),
    'backupSnapshot': (),
    'backupAction': (Argument('name', str, 'BackupAction'), Argument('target', str, 'string'),
                     Argument('includeThumbnails', bool, 'boolean')),
}, signals={'settingsChanged': str, 'settingsFocusRequested': str,
            'keyCaptured': str, 'settingsError': str, 'backupChanged': str},
    aliases=(TypeAlias('SettingsAction', ('translation', 'quit', 'releases')),
             TypeAlias('BackupAction', ('refresh', 'create', 'choose', 'preview', 'schedule',
                                       'discard', 'cancel', 'restart', 'openFolder'))),
    data_types=(web_update_data.UpdateResultData, web_update_data.UpdateStatusData,
                web_settings_data.SettingKeyData, web_settings_data.RecommendationPeriodData,
                web_settings_data.SettingsData,
                web_settings_data.CapturedKeyData, web_backup_data.BackupMetadataData,
                web_backup_data.AutomaticBackupData, web_backup_data.BackupStartupData,
                web_backup_data.BackupData))
