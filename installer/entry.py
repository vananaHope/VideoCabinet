"""PyInstaller 진입점. 패키지 상대 import는 정상 모듈 이름에서 수행한다."""
import os
import sys

# 탐색기 실행에는 표준 스트림이 없다. 부모가 연결한 자식 JSON 파이프는 그대로 둔다.
for name in ('stdout', 'stderr'):
    if getattr(sys, name) is None:
        setattr(sys, name, open(os.devnull, 'w', encoding='utf-8'))
    elif sys.argv[1:2] == ['transcription']:
        # frozen Python은 PYTHONIOENCODING을 무시한다. 부모의 UTF-8 JSON 계약과 맞춘다.
        getattr(sys, name).reconfigure(encoding='utf-8')

from my_video_manager.__main__ import main

raise SystemExit(main())
