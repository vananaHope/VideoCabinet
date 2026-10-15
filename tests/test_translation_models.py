import subprocess
import sys


def test_model_types_import_without_loading_translation_adapters():
    result = subprocess.run([sys.executable, "-c", """
import sys
from my_video_manager.translation_models import ModelPolicy, TranslationModelChoice
choice = TranslationModelChoice('codex', 'custom', '직접 입력')
assert choice.policy is None and choice.reasoning_efforts is None
assert ModelPolicy('unknown').training is None
assert not any(name in sys.modules for name in (
    'my_video_manager.opencode_go', 'my_video_manager.translation_cli',
    'my_video_manager.translation', 'my_video_manager.secret_store'))
"""], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
