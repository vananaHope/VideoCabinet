import json

import pytest

from my_video_manager.subtitles import TranscriptLine
from my_video_manager.translation_kind import translation_task
from my_video_manager.translation_cli import translation_prompt
from my_video_manager.translation import ContextLine
from my_video_manager.translation_glossary import GlossaryEntry
from test_translation_cli import fake_cli
from test_opencode_go import adapter, HTTPResponse


@pytest.mark.parametrize('cli', ['codex', 'claude'])
def test_refinement_uses_shared_cli_arguments_and_system_instructions(tmp_path, cli):
    script = '''
import sys, json
from pathlib import Path
from my_video_manager.translation_kind import translation_task
prompt = sys.stdin.read()
instructions, raw = prompt.split('\\nSUBTITLE_DATA_JSON:\\n')
assert instructions == translation_task('ko').instructions
data = json.loads(raw)
assert data['spoken_language'] == 'ko'
assert data['context'][0]['translation'] == '앞 맥락'
assert data['glossary'][0]['target'] == '한빛'
result = {'lines':[{'id':l['id'], 'text':l['text']} for l in data['targets']], 'glossary':[]}
if 'exec' in sys.argv:
    assert sys.argv[sys.argv.index('-m')+1] == 'test-model'
    assert 'model_reasoning_effort=high' in sys.argv
    Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text(json.dumps(result),encoding='utf-8')
else:
    assert Path(sys.argv[sys.argv.index('--system-prompt-file')+1]).read_text(encoding='utf-8') == instructions
    assert sys.argv[sys.argv.index('--model')+1] == 'test-model'
    assert sys.argv[sys.argv.index('--effort')+1] == 'high'
    print(json.dumps({'structured_output':result}))
'''
    translator = fake_cli(tmp_path, script, cli, timeout=30)
    lines = (TranscriptLine('one', 0, 1, '음'),)
    response = translator.translate(lines, 'ko', cli=cli, model='test-model', effort='high',
        context=(ContextLine('before', '맥락', '앞 맥락'),), glossary=(GlossaryEntry('한빛', '한빛'),))
    assert response[0].text == '음'
    assert list(translator.directory.iterdir()) == []


def test_opencode_uses_identical_refinement_prompt_without_network():
    lines = (TranscriptLine('one', 0, 1, '음'),)
    class Transport:
        def request(self, method, url, **kwargs):
            request = json.loads(kwargs['body'])
            assert request['messages'][-1]['content'].startswith(translation_prompt(lines, 'ko'))
            assert translation_task('ko').instructions in request['messages'][-1]['content']
            return HTTPResponse(200, {}, json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
                'lines': [{'id': 'one', 'text': '음'}], 'glossary': []})}}]}).encode())
    assert adapter(Transport()).translate(lines, 'ko')[0].text == '음'
