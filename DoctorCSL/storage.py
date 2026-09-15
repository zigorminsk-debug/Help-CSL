# -*- coding: utf-8 -*-
"""Сохранение учётных данных. Удаление — только через Сервис → Выход."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


def app_data_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        path = root / "CSL" / "DoctorCSL"
    else:
        path = Path.home() / ".config" / "csl-doctor"
    path.mkdir(parents=True, exist_ok=True)
    return path


PROFILE_FILE = "profile.bin"


def _machine_key() -> bytes:
    parts = [
        os.environ.get("COMPUTERNAME") or os.uname().nodename,
        os.environ.get("USERNAME") or os.environ.get("USER") or "",
        "CSL.Doctor.v1",
    ]
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            ) as key:
                guid, _ = winreg.QueryValueEx(key, "MachineGuid")
                parts.append(str(guid))
        except Exception:
            pass
    return hashlib.sha256("|".join(parts).encode("utf-8")).digest()


def _xor_stream(data: bytes, key: bytes) -> bytes:
    stream = hashlib.sha256(key).digest()
    while len(stream) < len(data):
        stream += hashlib.sha256(stream[-32:]).digest()
    return bytes(a ^ b for a, b in zip(data, stream))


def _dpapi_protect(data: bytes) -> bytes | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        blob_in = DATA_BLOB(len(data), ctypes.create_string_buffer(data, len(data)))
        blob_out = DATA_BLOB()
        if not crypt32.CryptProtectData(
            ctypes.byref(blob_in),
            "DoctorCSL",
            None,
            None,
            None,
            0,
            ctypes.byref(blob_out),
        ):
            return None
        try:
            raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
        return raw
    except Exception:
        return None


def _dpapi_unprotect(data: bytes) -> bytes | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        blob_in = DATA_BLOB(len(data), ctypes.create_string_buffer(data, len(data)))
        blob_out = DATA_BLOB()
        if not crypt32.CryptUnprotectData(
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(blob_out),
        ):
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None


def encrypt_payload(payload: dict[str, Any]) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    protected = _dpapi_protect(raw)
    if protected is not None:
        return b"DP1:" + protected
    return b"OB1:" + base64.urlsafe_b64encode(_xor_stream(raw, _machine_key()))


def decrypt_payload(blob: bytes) -> dict[str, Any]:
    if blob.startswith(b"DP1:"):
        raw = _dpapi_unprotect(blob[4:])
        if raw is None:
            raise ValueError("dpapi")
        return json.loads(raw.decode("utf-8"))
    if blob.startswith(b"OB1:"):
        raw = _xor_stream(base64.urlsafe_b64decode(blob[4:]), _machine_key())
        return json.loads(raw.decode("utf-8"))
    raise ValueError("format")


def profile_path() -> Path:
    return app_data_dir() / PROFILE_FILE


def load_profile() -> dict[str, Any]:
    path = profile_path()
    if not path.exists():
        return {}
    try:
        return decrypt_payload(path.read_bytes())
    except Exception:
        return {}


def save_profile(data: dict[str, Any]) -> None:
    path = profile_path()
    path.write_bytes(encrypt_payload(data))
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def wipe_profile() -> None:
    path = profile_path()
    if path.exists():
        try:
            # overwrite then delete
            size = path.stat().st_size
            with path.open("wb") as fh:
                fh.write(os.urandom(max(size, 64)))
                fh.flush()
                os.fsync(fh.fileno())
        except Exception:
            pass
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
    # leftover files in the folder
    folder = app_data_dir()
    for item in folder.glob("*"):
        try:
            if item.is_file():
                item.unlink()
        except Exception:
            pass
