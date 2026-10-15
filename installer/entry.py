"""PyInstaller 진입점. 패키지 상대 import는 정상 모듈 이름에서 수행한다."""
from my_video_manager.__main__ import main

raise SystemExit(main())
