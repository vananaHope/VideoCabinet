"""웹 및 후속 Qt 재생 화면이 공유하는 디자인 값."""
import json
from pathlib import Path


def web_tokens():
    return json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
