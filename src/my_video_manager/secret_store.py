"""설정/DB와 분리한 Windows 사용자 단위 구독 키 저장소."""

import ctypes
from ctypes import wintypes
from pathlib import Path
import os
import sys
from tempfile import NamedTemporaryFile


class SecretStoreError(RuntimeError):
    """키나 OS의 원래 진단을 포함하지 않는 저장소 오류."""


class Secret:
    """평문은 전송 직전 reveal()로만 꺼낸다. 일반 표시에는 노출하지 않는다."""

    __slots__ = ("_value",)

    def __init__(self, value: str):
        if isinstance(value, str):
            value = value.strip()
        if not isinstance(value, str) or not value or any(not 33 <= ord(c) <= 126 for c in value):
            raise SecretStoreError("키는 공백 없는 출력 가능한 ASCII 문자(33~126)여야 합니다.")
        self._value = value

    def reveal(self) -> str:
        return self._value

    def masked(self) -> str:
        return "****" + (self._value[-4:] if len(self._value) > 4 else "")

    def __repr__(self):
        return "Secret(<redacted>)"

    __str__ = __repr__


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class WindowsDPAPI:
    def __init__(self):
        if sys.platform != "win32":
            raise SecretStoreError("키 저장소는 Windows 사용자 암호화가 필요합니다.")
        self._crypt = ctypes.WinDLL("crypt32", use_last_error=True)
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        blob = ctypes.POINTER(_Blob)
        self._crypt.CryptProtectData.argtypes = [blob, wintypes.LPCWSTR, blob, ctypes.c_void_p,
                                                ctypes.c_void_p, wintypes.DWORD, blob]
        self._crypt.CryptUnprotectData.argtypes = [blob, ctypes.c_void_p, blob, ctypes.c_void_p,
                                                  ctypes.c_void_p, wintypes.DWORD, blob]
        self._crypt.CryptProtectData.restype = self._crypt.CryptUnprotectData.restype = wintypes.BOOL
        self._kernel.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel.LocalFree.restype = ctypes.c_void_p

    def _convert(self, data: bytes, *, protect: bool) -> bytes:
        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        source, target = _Blob(len(data), buffer), _Blob()
        function = self._crypt.CryptProtectData if protect else self._crypt.CryptUnprotectData
        try:
            # UI_FORBIDDEN only: LOCAL_MACHINE must never be set.
            if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
                raise SecretStoreError("Windows 사용자 키 암호화 작업에 실패했습니다.")
            return ctypes.string_at(target.pbData, target.cbData)
        finally:
            ctypes.memset(buffer, 0, len(data))
            if target.pbData:
                ctypes.memset(target.pbData, 0, target.cbData)
                self._kernel.LocalFree(target.pbData)

    def protect(self, data: bytes) -> bytes:
        return self._convert(data, protect=True)

    def unprotect(self, data: bytes) -> bytes:
        return self._convert(data, protect=False)


class SecretStore:
    """한 데이터 폴더에 OpenCode Go 키 하나. 파일에는 DPAPI 암호문만 쓴다.

    protector 주입은 실패/복구 테스트용이다. 기본 구현은 평문 저장으로 폴백하지 않는다.
    """

    def __init__(self, data_directory: Path, *, protector=None):
        self.path = Path(data_directory) / "secrets" / "opencode-go.dpapi"
        self._protector = protector if protector is not None else WindowsDPAPI()

    def save(self, key: Secret | str) -> None:
        key = key if isinstance(key, Secret) else Secret(key)
        temporary = None
        failed = False
        try:
            encrypted = self._protector.protect(key.reveal().encode("utf-8"))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=self.path.parent, prefix=".key-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except Exception:
            failed = True
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    failed = True
        # Raise outside except: even exception chaining must not retain raw key diagnostics.
        if failed:
            raise SecretStoreError("키를 암호화해 저장하지 못했습니다.")

    def read(self) -> Secret | None:
        try:
            encrypted = self.path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            encrypted = None
        if encrypted is not None:
            try:
                return Secret(self._protector.unprotect(encrypted).decode("utf-8"))
            except Exception:
                pass
        raise SecretStoreError("저장된 키를 읽지 못했습니다. 키를 다시 등록하세요.")

    def delete(self) -> None:
        failed = False
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            failed = True
        if failed:
            raise SecretStoreError("저장된 키를 지우지 못했습니다.")

    def masked(self) -> str | None:
        key = self.read()
        return key.masked() if key is not None else None
