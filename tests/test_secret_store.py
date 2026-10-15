import logging
import sys
import traceback

import pytest

from my_video_manager.secret_store import Secret, SecretStore, SecretStoreError, WindowsDPAPI
from pathlib import Path


KEY = "test-subscription-key-never-in-output-1234"


def test_saved_key_survives_staging_cleanup_failure(tmp_path, monkeypatch, caplog):
    class Protector:
        def protect(self, value):
            return b'encrypted-new'
    store = SecretStore(tmp_path, protector=Protector())
    rmdir = Path.rmdir
    def denied(path):
        if path.name.startswith('.key-'):
            raise PermissionError(KEY)
        return rmdir(path)
    monkeypatch.setattr(Path, 'rmdir', denied)
    store.save(KEY)
    assert store.path.read_bytes() == b'encrypted-new'
    assert '임시 폴더' in caplog.text
    assert KEY not in caplog.text


def test_denied_staging_directory_is_attempted_once_and_preserves_previous_key(tmp_path, monkeypatch):
    class Protector:
        def protect(self, value):
            return b'encrypted'
    store = SecretStore(tmp_path, protector=Protector())
    store.path.parent.mkdir()
    store.path.write_bytes(b'previous')
    mkdir = Path.mkdir
    attempts = []
    def denied(path, *args, **kwargs):
        if path.name.startswith('.key-'):
            attempts.append(path)
            raise PermissionError('denied')
        return mkdir(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'mkdir', denied)
    with pytest.raises(SecretStoreError):
        store.save(KEY)
    assert len(attempts) == 1
    assert store.path.read_bytes() == b'previous'
    assert list(store.path.parent.iterdir()) == [store.path]


@pytest.mark.skipif(sys.platform != "win32", reason="실제 Windows 사용자 DPAPI")
def test_dpapi_store_roundtrip_replace_delete_and_no_plaintext(tmp_path, caplog):
    store = SecretStore(tmp_path)
    assert store.read() is None and store.masked() is None
    store.save(KEY)
    secret = SecretStore(tmp_path).read()
    assert secret.reveal() == KEY
    assert store.masked() == "****1234"
    assert WindowsDPAPI().unprotect(store.path.read_bytes()).decode() == KEY
    with caplog.at_level(logging.INFO):
        logging.getLogger(__name__).info("%s %r %r", secret, secret, store)
    assert KEY not in caplog.text + repr(secret) + str(secret) + repr(store)
    files = list(tmp_path.rglob("*"))
    assert [p for p in files if p.is_file()] == [store.path]
    assert KEY.encode() not in store.path.read_bytes()
    assert KEY.encode("utf-16-le") not in store.path.read_bytes()
    assert not list(tmp_path.rglob("*.db")) and not list(tmp_path.rglob("*.json"))
    store.save(Secret("replacement-key-9876"))
    assert SecretStore(tmp_path).read().reveal() == "replacement-key-9876"
    assert store.masked() == "****9876"
    store.delete()
    store.delete()
    assert store.read() is None


class FailingProtector:
    def protect(self, value):
        raise OSError(KEY)
    def unprotect(self, value):
        raise OSError(KEY)


def test_storage_failures_never_chain_sensitive_errors_or_overwrite_saved_key(tmp_path, caplog):
    store = SecretStore(tmp_path, protector=FailingProtector())
    store.path.parent.mkdir()
    store.path.write_bytes(b"previous-encrypted-value")
    for operation in (lambda: store.save(KEY), store.read, store.masked):
        with pytest.raises(SecretStoreError) as raised:
            operation()
        assert raised.value.__context__ is None
        assert KEY not in repr(raised.value) + str(raised.value)
        assert KEY not in "".join(traceback.format_exception(raised.value)) + caplog.text
    assert store.path.read_bytes() == b"previous-encrypted-value"
    assert list(store.path.parent.iterdir()) == [store.path]


@pytest.mark.skipif(sys.platform != "win32", reason="실제 Windows 사용자 DPAPI")
def test_corrupt_encrypted_file_is_not_treated_as_missing(tmp_path):
    store = SecretStore(tmp_path)
    store.save(KEY)
    store.path.write_bytes(b"damaged ciphertext")
    with pytest.raises(SecretStoreError):
        store.read()
    store.delete()
    store.save(KEY)
    assert store.read().reveal() == KEY


@pytest.mark.parametrize("key", ["", " ", "key\r\nAuthorization: injected", None, 123,
                               "키값-1234", "a\x00b", "a\x7fb", "a b"])
def test_invalid_key_is_rejected_without_echo(key):
    with pytest.raises(SecretStoreError):
        Secret(key)


@pytest.mark.parametrize("key,expected", [("abcd", "****"), ("x", "****"), ("abcde", "****bcde")])
def test_mask_never_displays_entire_short_key(key, expected):
    assert Secret(key).masked() == expected


@pytest.mark.skipif(sys.platform != "win32", reason="실제 Windows 사용자 DPAPI")
def test_atomic_replace_failure_preserves_key_and_cleans_encrypted_temp(tmp_path, monkeypatch):
    import my_video_manager.secret_store as module
    store = SecretStore(tmp_path)
    store.save(KEY)
    previous = store.path.read_bytes()
    def fail_replace(*args):
        raise OSError(KEY)
    monkeypatch.setattr(module.os, "replace", fail_replace)
    with pytest.raises(SecretStoreError) as raised:
        store.save("new-secret-5678")
    assert raised.value.__context__ is None
    assert KEY not in repr(raised.value)
    assert store.path.read_bytes() == previous
    assert list(store.path.parent.iterdir()) == [store.path]


@pytest.mark.skipif(sys.platform != "win32", reason="실제 Windows 사용자 DPAPI")
def test_pasted_key_is_trimmed_and_validation_message_is_preserved(tmp_path):
    store = SecretStore(tmp_path)
    store.save(" \r\n" + KEY + "\r\n\t")
    assert store.read().reveal() == KEY
    for value in ("한글키", "inside space", "a\x00b", "\r\n"):
        with pytest.raises(SecretStoreError) as direct:
            Secret(value)
        with pytest.raises(SecretStoreError) as saved:
            store.save(value)
        assert str(saved.value) == str(direct.value)
        assert "ASCII" in str(saved.value)
        assert saved.value.__context__ is None
        assert store.read().reveal() == KEY
