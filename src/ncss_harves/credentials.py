from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import platform
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Credentials:
    username: str
    password: str


class EncryptionBackend(Protocol):
    def encrypt(self, plaintext: bytes) -> bytes: ...

    def decrypt(self, ciphertext: bytes) -> bytes: ...


def _dpapi_bytes(result: object, operation: str) -> bytes:
    if isinstance(result, (bytes, bytearray, memoryview)):
        return bytes(result)
    if isinstance(result, tuple) and len(result) >= 2:
        payload = result[-1]
        if isinstance(payload, (bytes, bytearray, memoryview)):
            return bytes(payload)
    raise TypeError(f"Windows DPAPI {operation} returned an unsupported value")


class WindowsDpapiBackend:
    def encrypt(self, plaintext: bytes) -> bytes:
        try:
            import win32crypt
        except ImportError as exc:  # pragma: no cover - depends on Windows installation
            raise RuntimeError("pywin32 is required for Windows credential encryption") from exc
        result = win32crypt.CryptProtectData(
            plaintext, "ncss-harves credentials", None, None, None, 0
        )
        return _dpapi_bytes(result, "encryption")

    def decrypt(self, ciphertext: bytes) -> bytes:
        try:
            import win32crypt
        except ImportError as exc:  # pragma: no cover - depends on Windows installation
            raise RuntimeError("pywin32 is required for Windows credential encryption") from exc
        result = win32crypt.CryptUnprotectData(ciphertext, None, None, None, 0)
        return _dpapi_bytes(result, "decryption")


class KeyringFernetBackend:
    SERVICE = "ncss-harves"
    ACCOUNT = "credential-encryption-key"

    def __init__(self) -> None:
        try:
            import keyring
            from cryptography.fernet import Fernet
        except ImportError as exc:  # pragma: no cover - installation dependent
            raise RuntimeError("keyring and cryptography are required for credential encryption") from exc
        self._keyring = keyring
        self._fernet_type = Fernet

    def _key(self) -> bytes:
        try:
            encoded = self._keyring.get_password(self.SERVICE, self.ACCOUNT)
            if encoded is None:
                encoded = self._fernet_type.generate_key().decode("ascii")
                self._keyring.set_password(self.SERVICE, self.ACCOUNT, encoded)
            return encoded.encode("ascii")
        except Exception as exc:
            raise RuntimeError("system keyring is unavailable; credentials were not saved") from exc

    def encrypt(self, plaintext: bytes) -> bytes:
        return self._fernet_type(self._key()).encrypt(plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        return self._fernet_type(self._key()).decrypt(ciphertext)


def platform_backend() -> EncryptionBackend:
    if platform.system() == "Windows":
        return WindowsDpapiBackend()
    return KeyringFernetBackend()


class CredentialStore:
    def __init__(self, path: Path, backend: EncryptionBackend | None = None) -> None:
        self.path = Path(path)
        self.backend = backend or platform_backend()

    def save(self, credentials: Credentials) -> None:
        if not credentials.username.strip():
            raise ValueError("username must not be empty")
        if not credentials.password:
            raise ValueError("password must not be empty")
        plaintext = json.dumps(asdict(credentials), ensure_ascii=False).encode("utf-8")
        ciphertext = self.backend.encrypt(plaintext)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_bytes(ciphertext)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def load(self) -> Credentials | None:
        if not self.path.exists():
            return None
        plaintext = self.backend.decrypt(self.path.read_bytes())
        try:
            payload = json.loads(plaintext.decode("utf-8"))
            credentials = Credentials(username=str(payload["username"]), password=str(payload["password"]))
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError("invalid encrypted credential payload") from exc
        if not credentials.username or not credentials.password:
            raise ValueError("invalid encrypted credential payload")
        return credentials
