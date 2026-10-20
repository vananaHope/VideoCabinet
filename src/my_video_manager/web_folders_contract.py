"""폴더 관리 페이지 브리지 계약."""

from . import web_folders_data
from .web_contract_types import Argument, BridgeContract, TypeAlias

FOLDERS = BridgeContract(name='folders', interface='FoldersBridge', slots={
    'ready': (), 'snapshot': (),
    'action': (Argument('name', str, 'FolderAction'), Argument('target', str, 'string')),
    'setMinimum': (Argument('seconds', float, 'number'),),
    'dismissReport': (Argument('revision', int, 'number'), Argument('group', str, 'ScanNoticeGroup')),
}, signals={'foldersChanged': str, 'foldersFocusRequested': str, 'foldersError': str},
    aliases=(TypeAlias('FolderAction', ('addFolder', 'removeFolder', 'scan', 'addFile',
                                       'restoreExcluded', 'restoreDismissed', 'manageTags')),
             TypeAlias('ScanNoticeGroup', web_folders_data.SCAN_NOTICE_GROUPS)),
    data_types=(web_folders_data.RestorableVideoData, web_folders_data.ScanIssueData,
                web_folders_data.ScanReportData, web_folders_data.FoldersData))
