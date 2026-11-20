# 임시 진단(#392): 개수 단언 앞에 디스크·상태 출력을 넣는다.
from pathlib import Path
p = Path('scripts/check_web_backup.py')
s = p.read_text(encoding='utf-8')
old = "        assert len(backup_state()['automatic']) == 5"
assert old in s
if 'DIAG disk' not in s:
    s = s.replace(old, "        print('DIAG disk', [p.name for p in core.automatic_backups()], flush=True)\n"
                  "        print('DIAG state', len(backup_state()['automatic']), repr(backup_state()['operation']), flush=True)\n" + old, 1)
p.write_text(s, encoding='utf-8')
