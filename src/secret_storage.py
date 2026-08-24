"""
secret_storage.py

Fernet-based symmetric encryption for secrets stored in the SQLite DB
(IMAP / SMTP passwords today; safe to extend). The key lives at
`data/.app_key`, mode 0o600, generated on first call. `data/` is
gitignored so the key never ships with the repo.

Threat model: protects against SQLite-file exfiltration (stolen
backup, leaked container layer, sibling-tenant read). Does **not**
protect against a process compromise — anyone who can read this
module's memory or the key file has plaintext.

Encrypted values carry an `enc:` prefix so the migration is
idempotent: passing an already-encrypted value to `encrypt()` is a
no-op; passing a plaintext value to `decrypt()` returns it
unchanged. That lets legacy rows coexist with new ones until a
single migration pass rewrites them.
"""

import hashlib
import json
import os
import logging
from pathlib import Path
import threading

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from core.platform_compat import safe_chmod
from src.constants import APP_KEY_FILE

logger = logging.getLogger(__name__)

_KEY_PATH = Path(APP_KEY_FILE)
_PREFIX = "enc:"
_fernet: MultiFernet | None = None
_key_lock = threading.RLock()


def _previous_keys_path() -> Path:
    return Path(f"{_KEY_PATH}.previous")


def _atomic_secret_write(path: Path, content: bytes) -> None:
    """Atomically replace a key file and keep its permissions owner-only."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets_token()}.tmp")
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        os.replace(temporary, path)
        safe_chmod(path, 0o600)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def secrets_token() -> str:
    # Imported lazily so this module's startup path remains small.
    import secrets

    return secrets.token_hex(8)


def _load_or_create_key() -> bytes:
    with _key_lock:
        if _KEY_PATH.exists():
            key = _KEY_PATH.read_bytes().strip()
            Fernet(key)  # validate before using corrupt key material
            return key
        _KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        try:
            descriptor = os.open(
                _KEY_PATH,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            # Another worker won the first-start race.
            existing = _KEY_PATH.read_bytes().strip()
            Fernet(existing)
            return existing
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(key)
            handle.flush()
            os.fsync(handle.fileno())
        # POSIX: lock the key to 0o600. Windows: no-op (the user-profile data
        # dir is already ACL-restricted); safe_chmod swallows both cases.
        safe_chmod(_KEY_PATH, 0o600)
        logger.info("Generated a new application master key")
        return key


def _load_previous_keys() -> list[bytes]:
    path = _previous_keys_path()
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError("previous-key file must contain a list")
        keys: list[bytes] = []
        for item in value:
            key = str(item).encode("ascii")
            Fernet(key)
            if key not in keys:
                keys.append(key)
        return keys
    except Exception as exc:
        logger.error("Could not load previous application keys: %s", exc)
        return []


def _get_fernet() -> MultiFernet:
    global _fernet
    with _key_lock:
        if _fernet is None:
            keys = [_load_or_create_key(), *_load_previous_keys()]
            _fernet = MultiFernet([Fernet(key) for key in keys])
        return _fernet


def _key_fingerprint(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:16]


def master_key_status() -> dict:
    """Return non-secret rotation metadata for diagnostics/admin UI."""

    current = _load_or_create_key()
    previous = _load_previous_keys()
    return {
        "current_fingerprint": _key_fingerprint(current),
        "previous_key_count": len(previous),
        "key_path": str(_KEY_PATH),
    }


def rotate_master_key(*, keep_previous: int = 2) -> dict:
    """Install a new master key while retaining bounded decrypt-only keys.

    New writes immediately use the new key. Existing ciphertext remains
    readable through ``MultiFernet`` and is naturally rewrapped whenever an
    ``EncryptedText`` value is updated. ``rewrap`` can migrate a value eagerly.
    The returned fingerprints are safe to log; raw keys never leave this file.
    """

    if isinstance(keep_previous, bool) or not isinstance(keep_previous, int):
        raise ValueError("keep_previous must be an integer")
    if not 1 <= keep_previous <= 8:
        raise ValueError("keep_previous must be between 1 and 8")
    global _fernet
    with _key_lock:
        current = _load_or_create_key()
        previous = _load_previous_keys()
        retained = [current]
        retained.extend(key for key in previous if key != current)
        retained = retained[:keep_previous]
        previous_payload = json.dumps(
            [key.decode("ascii") for key in retained],
            separators=(",", ":"),
        ).encode("utf-8")
        _atomic_secret_write(_previous_keys_path(), previous_payload)
        new_key = Fernet.generate_key()
        _atomic_secret_write(_KEY_PATH, new_key)
        _fernet = None
        logger.info(
            "Rotated application master key old=%s new=%s retained=%d",
            _key_fingerprint(current),
            _key_fingerprint(new_key),
            len(retained),
        )
        return {
            "previous_fingerprint": _key_fingerprint(current),
            "current_fingerprint": _key_fingerprint(new_key),
            "previous_key_count": len(retained),
        }


def rewrap(value: str) -> str:
    """Re-encrypt one ciphertext with the current key.

    This deliberately differs from :func:`encrypt`, whose idempotent behavior
    must remain compatible with legacy migrations.
    """

    if not value:
        return value or ""
    if not value.startswith(_PREFIX):
        return encrypt(value)
    token = value[len(_PREFIX):].encode("ascii")
    try:
        plaintext = _get_fernet().decrypt(token)
    except Exception as exc:
        raise ValueError("Cannot rewrap an invalid encrypted value") from exc
    current = Fernet(_load_or_create_key())
    return _PREFIX + current.encrypt(plaintext).decode("ascii")


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Empty input passes through. Already-encrypted
    values pass through unchanged so re-encrypting is a no-op."""
    if not plaintext:
        return plaintext or ""
    if plaintext.startswith(_PREFIX):
        return plaintext
    token = _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")
    return _PREFIX + token


def decrypt(value: str) -> str:
    """Decrypt an `enc:`-prefixed value. Plaintext (legacy) passes
    through unchanged. Returns "" on decryption failure so a corrupt
    or rotated-key row degrades to "unconfigured" rather than 500."""
    if not value:
        return value or ""
    if not value.startswith(_PREFIX):
        return value
    try:
        return _get_fernet().decrypt(value[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.error("Failed to decrypt stored secret — wrong key or corrupt token")
        return ""
    except Exception as e:
        logger.error(f"Decrypt failure: {e}")
        return ""


def is_encrypted(value: str) -> bool:
    return bool(value) and value.startswith(_PREFIX)
