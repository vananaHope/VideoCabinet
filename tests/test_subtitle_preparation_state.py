from pathlib import Path
from types import SimpleNamespace

import pytest

from my_video_manager.subtitle_preparation_state import PreparationHistory


@pytest.mark.parametrize('failure', ['denied', 'collision'])
def test_history_creation_is_attempted_once_and_preserves_existing_files(tmp_path, monkeypatch, failure):
    import my_video_manager.subtitle_preparation_state as state
    history = PreparationHistory(tmp_path)
    history.save('cancelled', 'previous')
    previous = history.path.read_bytes()
    candidate = tmp_path / '.subtitle-preparation-fixed.tmp'
    monkeypatch.setattr(state, 'uuid4', lambda: SimpleNamespace(hex='fixed'))
    if failure == 'collision':
        candidate.write_bytes(b'other writer')
    original_open = Path.open
    attempts = []
    def open_once(path, *args, **kwargs):
        if path == candidate:
            attempts.append(path)
            if failure == 'denied':
                raise PermissionError('denied')
        return original_open(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'open', open_once)
        with pytest.raises(PermissionError if failure == 'denied' else FileExistsError):
            history.save('ready')
    assert len(attempts) == 1
    assert history.path.read_bytes() == previous
    if failure == 'collision':
        assert candidate.read_bytes() == b'other writer'
    else:
        assert not candidate.exists()


def test_history_replace_failure_preserves_previous_and_cleans_temp(tmp_path, monkeypatch):
    history = PreparationHistory(tmp_path)
    history.save('cancelled', 'previous')
    previous = history.read()
    def denied(*args):
        raise PermissionError('denied')
    monkeypatch.setattr(Path, 'replace', denied)
    with pytest.raises(PermissionError):
        history.save('ready')
    assert history.read() == previous
    assert list(tmp_path.iterdir()) == [history.path]
