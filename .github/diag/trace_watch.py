"""임시: 폴더 감시 묶음과 검사 안내 변경을 찍으며 검사 스크립트를 돌린다."""
import runpy
import sys
import time

from my_video_manager import folder_watch_controls, library_operations

start = time.monotonic()
_enqueue = folder_watch_controls.FolderWatchControls.enqueue
_completed = library_operations.LibraryOperations.scan_completed


def enqueue(self, folders):
    print(f'[watch {time.monotonic() - start:.2f}] batch {[str(f)[-30:] for f in folders]}', flush=True)
    return _enqueue(self, folders)


def scan_completed(self, result):
    print(f'[scan {time.monotonic() - start:.2f}] quiet={self._quiet_scan} added={result.added} issues={len(result.issues)}', flush=True)
    return _completed(self, result)


folder_watch_controls.FolderWatchControls.enqueue = enqueue
library_operations.LibraryOperations.scan_completed = scan_completed
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
