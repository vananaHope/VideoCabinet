# 임시 진단(#392): 개수 단언 앞에 디스크·상태 출력을 넣는다.
from pathlib import Path
p = Path('scripts/check_web_backup.py')
s = p.read_text(encoding='utf-8')
old = "        assert len(backup_state()['automatic']) == 5"
assert old in s
if 'DIAG disk' not in s:
    s = s.replace(old, "        print('DIAG disk', [p.name for p in core.automatic_backups()], flush=True)\n"
                  "        print('DIAG state', len(backup_state()['automatic']), repr(backup_state()['operation']), flush=True)\n" + old, 1)
# 새로고침 클릭 뒤 작업이 실제로 시작됐는지 본다.
old2 = "        assert button('새로고침')\n        finished()"
assert old2 in s
s = s.replace(old2, "        assert button('새로고침')\n        print('DIAG after-click busy', backup_state()['busy'], repr(backup_state()['operation']), flush=True)\n        finished()", 1)
p.write_text(s, encoding='utf-8')
