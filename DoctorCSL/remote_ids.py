# -*- coding: utf-8 -*-
"""Считывание AnyDesk / RustDesk ID с этого компьютера."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from shutil import which

ANYDESK_ID_RE = re.compile(r"ad\.anynet\.id\s*=\s*([0-9][0-9\s]{5,31})", re.I)
ANYDESK_TRACE_RE = re.compile(r"(?:anynet[_ ]?id|Logged in from id)\s*[:=]\s*([0-9]{6,16})", re.I)
RUSTDESK_ID_RE = re.compile(r"(?im)^\s*id\s*=\s*['\"]?([A-Za-z0-9_-]{6,32})['\"]?")


def _env_path(*names: str) -> Path | None:
    for name in names:
        raw = os.environ.get(name)
        if raw:
            return Path(raw)
    return None


def _read_text(path: Path) -> str:
    try:
        data = path.read_bytes()
    except Exception:
        return ""
    for enc in ("utf-8", "utf-8-sig", "utf-16", "utf-16-le", "cp1251", "latin-1"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode("utf-8", errors="ignore")


def _clean_digits(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def parse_anydesk_conf(text: str) -> str:
    match = ANYDESK_ID_RE.search(text or "")
    if match:
        value = _clean_digits(match.group(1))
        if value.isdigit() and 6 <= len(value) <= 16:
            return value
    match = ANYDESK_TRACE_RE.search(text or "")
    if match:
        value = _clean_digits(match.group(1))
        if value.isdigit() and 6 <= len(value) <= 16:
            return value
    return ""


def parse_rustdesk_toml(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        low = stripped.lower()
        if low.startswith("enc_id") or low.startswith("key") or stripped.startswith("#"):
            continue
        match = RUSTDESK_ID_RE.match(stripped)
        if match:
            return match.group(1)
    return ""


def _create_no_window() -> int:
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return 0


def _run_get_id(command: list[str]) -> str:
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=12,
            creationflags=_create_no_window(),
        )
    except Exception:
        return ""
    blob = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    for line in blob.splitlines():
        value = _clean_digits(line.strip())
        if value.isdigit() and 6 <= len(value) <= 16:
            return value
        raw = line.strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{6,32}", raw) and not raw.lower().startswith("error"):
            return raw
    return ""


def _glob_files(roots: list[Path], patterns: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if not root:
            continue
        try:
            exists = root.exists()
        except OSError:
            continue
        if not exists:
            continue
        if root.is_file():
            key = str(root).lower()
            if key not in seen:
                seen.add(key)
                out.append(root)
            continue
        for pat in patterns:
            try:
                matches = list(root.glob(pat))
            except Exception:
                matches = []
            for path in matches:
                key = str(path).lower()
                if key in seen:
                    continue
                seen.add(key)
                if path.is_file():
                    out.append(path)
    return out


def _windows_anydesk_files() -> list[Path]:
    appdata = _env_path("APPDATA") or Path.home() / "AppData" / "Roaming"
    programdata = _env_path("PROGRAMDATA", "ALLUSERSPROFILE") or Path(r"C:\ProgramData")
    local = _env_path("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    roots = [
        appdata / "AnyDesk",
        programdata / "AnyDesk",
        local / "AnyDesk",
        Path.home() / "AppData" / "Roaming" / "AnyDesk",
    ]
    named = [
        appdata / "AnyDesk" / "system.conf",
        appdata / "AnyDesk" / "service.conf",
        appdata / "AnyDesk" / "user.conf",
        programdata / "AnyDesk" / "system.conf",
        programdata / "AnyDesk" / "service.conf",
        local / "AnyDesk" / "system.conf",
    ]
    found = _glob_files(roots, ("*.conf", "*.trace", "ad.trace"))
    return named + found


def _linux_anydesk_files() -> list[Path]:
    return _glob_files(
        [Path.home() / ".anydesk", Path("/etc/anydesk"), Path.home() / ".config" / "AnyDesk"],
        ("*.conf", "*.trace"),
    )


def _windows_rustdesk_files() -> list[Path]:
    appdata = _env_path("APPDATA") or Path.home() / "AppData" / "Roaming"
    programdata = _env_path("PROGRAMDATA", "ALLUSERSPROFILE") or Path(r"C:\ProgramData")
    windir = _env_path("WINDIR", "SystemRoot") or Path(r"C:\Windows")
    local = _env_path("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    roots = [
        appdata / "RustDesk" / "config",
        programdata / "RustDesk" / "config",
        windir / "ServiceProfiles" / "LocalService" / "AppData" / "Roaming" / "RustDesk" / "config",
        windir / "ServiceProfiles" / "NetworkService" / "AppData" / "Roaming" / "RustDesk" / "config",
        local / "RustDesk" / "config",
        Path.home() / "AppData" / "Roaming" / "RustDesk" / "config",
    ]
    named = [root / name for root in roots for name in ("RustDesk.toml", "RustDesk2.toml")]
    found = _glob_files(roots, ("*.toml",))
    return named + found


def _linux_rustdesk_files() -> list[Path]:
    return _glob_files(
        [Path.home() / ".config" / "rustdesk", Path("/root/.config/rustdesk")],
        ("*.toml",),
    )


def _anydesk_exes() -> list[Path]:
    found: list[Path] = []
    for name in ("anydesk", "AnyDesk", "anydesk.exe", "AnyDesk.exe"):
        w = which(name)
        if w:
            found.append(Path(w))
    if sys.platform == "win32":
        pf = _env_path("ProgramFiles") or Path(r"C:\Program Files")
        pf86 = _env_path("ProgramFiles(x86)") or Path(r"C:\Program Files (x86)")
        local = _env_path("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        found.extend(
            [
                pf86 / "AnyDesk" / "AnyDesk.exe",
                pf86 / "AnyDesk" / "ad.anydesk.exe",
                pf / "AnyDesk" / "AnyDesk.exe",
                pf / "AnyDesk" / "ad.anydesk.exe",
                local / "Programs" / "AnyDesk" / "AnyDesk.exe",
                Path(r"C:\Program Files (x86)\AnyDesk\AnyDesk.exe"),
                Path(r"C:\Program Files\AnyDesk\AnyDesk.exe"),
            ]
        )
        # рядом с Help CSL / на рабочем столе
        try:
            here = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
            found.extend(here.glob("AnyDesk*.exe"))
        except Exception:
            pass
    else:
        found.extend([Path("/usr/bin/anydesk"), Path("/usr/local/bin/anydesk")])
    return found


def _rustdesk_exes() -> list[Path]:
    found: list[Path] = []
    for name in ("rustdesk", "rustdesk.exe", "RustDesk.exe"):
        w = which(name)
        if w:
            found.append(Path(w))
    if sys.platform == "win32":
        pf = _env_path("ProgramFiles") or Path(r"C:\Program Files")
        pf86 = _env_path("ProgramFiles(x86)") or Path(r"C:\Program Files (x86)")
        local = _env_path("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        found.extend(
            [
                pf / "RustDesk" / "rustdesk.exe",
                pf86 / "RustDesk" / "rustdesk.exe",
                local / "Programs" / "RustDesk" / "rustdesk.exe",
                Path(r"C:\Program Files\RustDesk\rustdesk.exe"),
                Path(r"C:\Program Files (x86)\RustDesk\rustdesk.exe"),
            ]
        )
        try:
            here = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
            found.extend(here.glob("rustdesk*.exe"))
            found.extend(here.glob("RustDesk*.exe"))
        except Exception:
            pass
    else:
        found.extend([Path("/usr/bin/rustdesk"), Path("/usr/local/bin/rustdesk")])
    return found


def _first_from_files(paths: list[Path], parser) -> str:
    seen: set[str] = set()
    for path in paths:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        value = parser(_read_text(path))
        if value:
            return value
    return ""


def _first_from_cli(exes: list[Path], flag: str) -> str:
    seen: set[str] = set()
    for exe in exes:
        key = str(exe).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            exists = exe.is_file()
        except OSError:
            exists = False
        if not exists and which(str(exe)) is None:
            continue
        value = _run_get_id([str(exe), flag])
        if value:
            return value
    return ""


def detect_remote_ids() -> dict[str, str]:
    if sys.platform == "win32":
        any_files = _windows_anydesk_files()
        rust_files = _windows_rustdesk_files()
    else:
        any_files = _linux_anydesk_files()
        rust_files = _linux_rustdesk_files()
    anydesk = _first_from_files(any_files, parse_anydesk_conf) or _first_from_cli(
        _anydesk_exes(), "--get-id"
    )
    rustdesk = _first_from_files(rust_files, parse_rustdesk_toml) or _first_from_cli(
        _rustdesk_exes(), "--get-id"
    )
    return {"anydesk": anydesk, "rustdesk": rustdesk}
