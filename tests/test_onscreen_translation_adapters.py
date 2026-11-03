"""실제 CLI 하위 프로세스는 가짜 스크립트로, HTTP는 가짜 전송으로 화면 번역 계약을 확인한다."""
import json

import pytest

from my_video_manager.translation import ContextLine, TranslationError
from my_video_manager.translation_cli import parse_translation_response
from my_video_manager.translation_glossary import GlossaryEntry
from my_video_manager.translation_source import ONSCREEN, OnScreenTranslationSourceLine
from test_translation_cli import fake_cli
from wait_helpers import CHILD_READY_TIMEOUT


LINES = (OnScreenTranslationSourceLine('one', 1, 2, 'Jon', 1, 'en'),
         OnScreenTranslationSourceLine('two', 1, 2, 'ジョン', 2, 'ja'))


@pytest.mark.parametrize('cli', ['codex', 'claude'])
def test_onscreen_cli_uses_task_instructions_region_languages_context_and_settings(tmp_path, cli):
    script = '''
import json, sys
from pathlib import Path
from my_video_manager.translation_kind import ONSCREEN_TRANSLATION
instructions, raw = sys.stdin.read().split('\\nSUBTITLE_DATA_JSON:\\n')
assert instructions == ONSCREEN_TRANSLATION.instructions
data = json.loads(raw)
assert [line['language'] for line in data['targets']] == ['en', 'ja']
assert data['context'] == [{'text': 'speech', 'translation': '말소리'}]
assert data['glossary'] == [{'source': 'Jon', 'target': '존'}]
result = {'lines': [{'id': line['id'], 'text': '존'} for line in data['targets']], 'glossary': []}
if 'exec' in sys.argv:
    assert sys.argv[sys.argv.index('-m')+1] == 'test-model'
    assert 'model_reasoning_effort=high' in sys.argv
    Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text(json.dumps(result), encoding='utf-8')
else:
    assert Path(sys.argv[sys.argv.index('--system-prompt-file')+1]).read_text(encoding='utf-8') == instructions
    assert sys.argv[sys.argv.index('--model')+1] == 'test-model'
    assert sys.argv[sys.argv.index('--effort')+1] == 'high'
    print(json.dumps({'structured_output': result}))
'''
    adapter = fake_cli(tmp_path, script, cli, timeout=CHILD_READY_TIMEOUT)
    result = adapter.translate(LINES, 'en', cli=cli, source=ONSCREEN, model='test-model', effort='high',
                               context=(ContextLine('speech-id', 'speech', '말소리'),), glossary=(GlossaryEntry('Jon', '존'),))
    assert [(line.id, line.text) for line in result] == [('one', '존'), ('two', '존')]
    assert list(adapter.directory.iterdir()) == []


def test_onscreen_never_uses_korean_refinement_blank_fallback():
    with pytest.raises(TranslationError):
        parse_translation_response(json.dumps({'lines': [{'id': 'one', 'text': ''}, {'id': 'two', 'text': '존'}]}),
                                   LINES, spoken_language='ko', source=ONSCREEN)
