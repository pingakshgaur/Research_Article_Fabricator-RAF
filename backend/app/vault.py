"""Encryption for secrets RAF has to keep on disk (the API keys of cloud language models).

* Windows — the Data Protection API (DPAPI). The key that decrypts belongs to the Windows account, so the stored text is
  useless on another computer or under another account, and nothing that unlocks it lies in the data folder.
* Elsewhere — Fernet (AES-128-CBC + HMAC) with a key file next to the data, readable by the owner only. That protects
  against the file being read out of a backup or a shared folder, not against someone who can read the whole data folder.

Neither protects against a program running as the same user: it can ask for the secret exactly as RAF does.
"""
from __future__ import annotations

import base64
import os
import sys

from .config import settings

_ENTROPY = b"RAF language-model keys"
KEY_FILE = settings.data_dir / ".vault.key"
METHOD = "Windows data protection (tied to your Windows account)" if sys.platform == "win32" else "AES key file in the data folder"


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(raw: bytes) -> Blob:
        return Blob(len(raw), ctypes.cast(ctypes.create_string_buffer(raw, len(raw)), ctypes.POINTER(ctypes.c_char)))

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    source, entropy, out = blob(data), blob(_ENTROPY), Blob()
    call = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not call(ctypes.byref(source), None, ctypes.byref(entropy), None, None, 0x01, ctypes.byref(out)):   # 0x01: never show a prompt
        raise OSError("Windows could not " + ("protect" if protect else "unlock") + " the secret")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def _fernet():
    from cryptography.fernet import Fernet

    if not KEY_FILE.exists():
        KEY_FILE.write_bytes(Fernet.generate_key())
        try:
            os.chmod(KEY_FILE, 0o600)
        except OSError:
            pass
    return Fernet(KEY_FILE.read_bytes().strip())


def seal(secret: str) -> str:
    """Encrypt a secret for storage."""
    raw = secret.encode("utf-8")
    if sys.platform == "win32":
        return "dpapi:" + base64.b64encode(_dpapi(raw, True)).decode("ascii")
    return "fernet:" + _fernet().encrypt(raw).decode("ascii")


def unseal(stored: str) -> str:
    """Decrypt a stored secret. Raises ValueError when it cannot be read here (another computer, account or key file)."""
    method, _, body = stored.partition(":")
    try:
        if method == "dpapi":
            return _dpapi(base64.b64decode(body), False).decode("utf-8")
        if method == "fernet":
            return _fernet().decrypt(body.encode("ascii")).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - whatever went wrong, the secret is not readable here
        raise ValueError("This key was saved on another computer or account and cannot be read here. Enter it again.") from exc
    raise ValueError("Unknown key format. Enter the key again.")
