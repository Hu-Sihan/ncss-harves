from __future__ import annotations

import base64
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ncss_harves.credentials import CredentialStore, Credentials, WindowsDpapiBackend


class ReversibleBackend:
    def encrypt(self, plaintext: bytes) -> bytes:
        return b"encrypted:" + base64.urlsafe_b64encode(plaintext[::-1])

    def decrypt(self, ciphertext: bytes) -> bytes:
        if not ciphertext.startswith(b"encrypted:"):
            raise ValueError("bad ciphertext")
        return base64.urlsafe_b64decode(ciphertext.removeprefix(b"encrypted:"))[::-1]


@pytest.fixture
def credential_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "ncss-credentials.key"


@pytest.fixture
def store(credential_path: Path) -> CredentialStore:
    return CredentialStore(credential_path, ReversibleBackend())


def test_credentials_are_not_stored_as_plaintext(store: CredentialStore, credential_path: Path) -> None:
    store.save(Credentials("user@example", "secret-value"))

    raw = credential_path.read_bytes()
    assert b"user@example" not in raw
    assert b"secret-value" not in raw
    assert store.load() == Credentials("user@example", "secret-value")


def test_failed_atomic_save_keeps_existing_credentials(
    store: CredentialStore, credential_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.save(Credentials("old", "working"))

    def fail_encrypt(_plaintext: bytes) -> bytes:
        raise RuntimeError("encryption failed")

    monkeypatch.setattr(store.backend, "encrypt", fail_encrypt)
    with pytest.raises(RuntimeError, match="encryption failed"):
        store.save(Credentials("new", "replacement"))

    assert credential_path.exists()
    monkeypatch.undo()
    assert store.load() == Credentials("old", "working")


def test_missing_file_returns_none(store: CredentialStore) -> None:
    assert store.load() is None


def test_empty_fields_are_rejected(store: CredentialStore) -> None:
    with pytest.raises(ValueError, match="username"):
        store.save(Credentials("", "password"))
    with pytest.raises(ValueError, match="password"):
        store.save(Credentials("username", ""))


def test_corrupt_ciphertext_is_reported(store: CredentialStore, credential_path: Path) -> None:
    credential_path.parent.mkdir(parents=True)
    credential_path.write_bytes(b"not-encrypted")

    with pytest.raises(ValueError, match="bad ciphertext"):
        store.load()


def test_temporary_file_is_removed_after_replace_failure(
    store: CredentialStore, credential_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr("ncss_harves.credentials.os.replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        store.save(Credentials("username", "password"))

    assert not credential_path.with_suffix(".key.tmp").exists()


@pytest.mark.parametrize(
    ("protected", "expected"),
    [
        (b"direct-ciphertext", b"direct-ciphertext"),
        (("description", b"tuple-ciphertext"), b"tuple-ciphertext"),
    ],
)
def test_windows_dpapi_encrypt_accepts_both_pywin32_return_shapes(
    monkeypatch: pytest.MonkeyPatch, protected: object, expected: bytes
) -> None:
    fake = SimpleNamespace(CryptProtectData=lambda *_args: protected)
    monkeypatch.setitem(sys.modules, "win32crypt", fake)

    assert WindowsDpapiBackend().encrypt(b"plaintext") == expected


@pytest.mark.parametrize(
    ("unprotected", "expected"),
    [
        (b"direct-plaintext", b"direct-plaintext"),
        (("description", b"tuple-plaintext"), b"tuple-plaintext"),
    ],
)
def test_windows_dpapi_decrypt_accepts_both_pywin32_return_shapes(
    monkeypatch: pytest.MonkeyPatch, unprotected: object, expected: bytes
) -> None:
    fake = SimpleNamespace(CryptUnprotectData=lambda *_args: unprotected)
    monkeypatch.setitem(sys.modules, "win32crypt", fake)

    assert WindowsDpapiBackend().decrypt(b"ciphertext") == expected
