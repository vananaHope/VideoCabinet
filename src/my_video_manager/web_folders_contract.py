"""폴더 관리 페이지 브리지 계약."""

from . import web_folders_data
from .web_contract_types import Argument, BridgeContract, TypeAlias

FOLDERS = BridgeContract(name='folders', interface='FoldersBridge', slots={
    'ready': (), 'snapshot': (),
    'action': (Argument('name', str, 'FolderAction'), Argument('target', str, 'string')),
    'setMinimum': (Argument('seconds', float, 'number'),),
}, signals={'foldersChanged': str, 'foldersFocusRequested': str, 'foldersError': str},
    aliases=(TypeAlias('FolderAction', ('addFolder', 'removeFolder', 'scan', 'addFile',
                                       'restoreExcluded', 'restoreDismissed', 'manageTags')),),
    data_types=(web_folders_data.RestorableVideoData, web_folders_data.FoldersData))
