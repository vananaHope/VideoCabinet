"""웹 셸 공통 브리지 계약."""

from . import web_shell_data, web_update_data
from .web_contract_types import Argument, BridgeContract, Constant, TypeAlias
from .web_tabs import TABS

SHELL = BridgeContract(
    name='shell', interface='ShellBridge',
    slots={'ready': (), 'shellSnapshot': (), 'navigate': (Argument('tab', str, 'Tab'),),
           'updateSnapshot': (),
           'updateChoice': (Argument('name', str, 'UpdateChoice'), Argument('version', str, 'string')),
           'updateAction': (Argument('name', str, 'UpdateAction'),), 'keyGuide': ()},
    signals={'shellChanged': str, 'shellStatusChanged': str, 'shellFocusRequested': str,
             'shellUpdateChanged': str, 'shellUpdateInstallChanged': str, 'shellKeyGuideRequested': str},
    aliases=(TypeAlias('Tab', tuple(name for name, _ in TABS)),
             TypeAlias('UpdateChoice', ('update', 'later', 'skip', 'unskip')),
             TypeAlias('UpdateAction', ('cancel', 'install', 'later', 'retry', 'dismiss'))),
    constants=(Constant('tabs', TABS),),
    data_types=(web_shell_data.ShellData, web_shell_data.KeyGuideEntryData, web_shell_data.KeyGuideData,
                web_update_data.UpdateNoticeData, web_update_data.UpdateInstallResultData,
                web_update_data.UpdateInstallData, web_update_data.ShellUpdateData),
)
