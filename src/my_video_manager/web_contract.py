"""웹 공개 계약 등록부. 생성기와 셸이 읽고, merge=union으로 합치므로 한 줄에 한 항목만 둔다.

계약 본문은 `web_<name>_contract.py`, 공통 선언은 `web_contract_types.py`, 탭은 `web_tabs.py`가 소유한다.
"""

from .web_tabs import TABS
from .web_shell_contract import SHELL
from .web_library_contract import LIBRARY
from .web_queue_contract import QUEUE
from .web_reel_contract import REEL
from .web_search_contract import SEARCH
from .web_statistics_contract import STATISTICS
from .web_dialogs_contract import DIALOGS
from .web_folders_contract import FOLDERS
from .web_settings_contract import SETTINGS

CONTRACTS = (
    SHELL,
    LIBRARY,
    QUEUE,
    REEL,
    SEARCH,
    STATISTICS,
    DIALOGS,
    FOLDERS,
    SETTINGS,
)
