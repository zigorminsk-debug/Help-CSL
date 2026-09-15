# -*- coding: utf-8 -*-
"""Установка Help CSL на ПК и автозагрузка (HKCU, без прав администратора)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

RUN_VALUE = "HelpCSL"
EXE_NAME = "HelpCSL.exe"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def is_windows() -> bool:
    return sys.platform == "win32"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def current_exe() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve()
    return Path(__file__).resolve()


def local_app_data() -> Path:
    raw = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(raw)


def install_dir() -> Path:
    return local_app_data() / "CSL" / "HelpCSL"


def installed_exe() -> Path:
    return install_dir() / EXE_NAME


def is_installed() -> bool:
    try:
        return current_exe() == installed_exe()
    except Exception:
        return False


def already_on_disk() -> bool:
    return installed_exe().is_file()


def _user_dir(kind: str) -> Path:
    if not is_windows():
        return Path.home()
    try:
        import ctypes
        from ctypes import wintypes

        CSIDL = {"desktop": 0, "programs": 2, "startup": 7}
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL[kind], None, 0, buf)
        return Path(buf.value)
    except Exception:
        home = Path.home()
        if kind == "desktop":
            return home / "Desktop"
        if kind == "startup":
            return home / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        return home / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def desktop_lnk() -> Path:
    return _user_dir("desktop") / "Help CSL.lnk"


def start_menu_lnk() -> Path:
    return _user_dir("programs") / "Help CSL.lnk"


def create_shortcut(lnk: Path, target: Path) -> None:
    lnk.parent.mkdir(parents=True, exist_ok=True)
    target_s = str(target)
    work = str(target.parent)
    lnk_s = str(lnk)
    flags = 0x08000000 if is_windows() else 0
    ps = (
        "$w = New-Object -ComObject WScript.Shell; "
        f"$s = $w.CreateShortcut('{lnk_s.replace(chr(39), chr(39)+chr(39))}'); "
        f"$s.TargetPath = '{target_s.replace(chr(39), chr(39)+chr(39))}'; "
        f"$s.WorkingDirectory = '{work.replace(chr(39), chr(39)+chr(39))}'; "
        f"$s.IconLocation = '{target_s.replace(chr(39), chr(39)+chr(39))},0'; "
        "$s.Description = 'Help CSL уже в пути — заявка в Service Desk'; "
        "$s.WindowStyle = 1; "
        "$s.Save()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            check=False,
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
        if lnk.is_file():
            return
    except Exception:
        pass
    vbs = install_dir() / "_shortcut.vbs"
    try:
        vbs.write_text(
            "Set sh = CreateObject(\"WScript.Shell\")\r\n"
            f"Set s = sh.CreateShortcut(\"{lnk_s}\")\r\n"
            f"s.TargetPath = \"{target_s}\"\r\n"
            f"s.WorkingDirectory = \"{work}\"\r\n"
            f"s.IconLocation = \"{target_s},0\"\r\n"
            "s.Description = \"Help CSL\"\r\n"
            "s.Save\r\n",
            encoding="ascii",
            errors="ignore",
        )
        subprocess.run(
            ["cscript", "//nologo", str(vbs)],
            check=False,
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
    except Exception:
        pass
    try:
        if vbs.exists():
            vbs.unlink()
    except Exception:
        pass


def _run_key(access: int):
    import winreg

    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access)


def is_autostart() -> bool:
    if not is_windows():
        return False
    try:
        import winreg

        with _run_key(winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, RUN_VALUE)
        return bool(val)
    except Exception:
        return False


def set_autostart(enabled: bool, exe: Path | None = None) -> None:
    if not is_windows():
        return
    import winreg

    target = exe or (installed_exe() if already_on_disk() else current_exe())
    if enabled:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, f'"{target}"')
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, RUN_VALUE)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _write_marker(data: dict) -> None:
    path = install_dir() / "installed.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_uninstaller(exe: Path) -> None:
    script = install_dir() / "uninstall.cmd"
    folder = str(install_dir())
    script.write_text(
        "\r\n".join(
            [
                "@echo off",
                "chcp 65001 >nul",
                f'reg delete "HKCU\\{RUN_KEY}" /v {RUN_VALUE} /f >nul 2>&1',
                f'del /f /q "%USERPROFILE%\\Desktop\\Help CSL.lnk" >nul 2>&1',
                f'del /f /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Help CSL.lnk" >nul 2>&1',
                "ping 127.0.0.1 -n 2 >nul",
                f'rmdir /s /q "{folder}"',
            ]
        )
        + "\r\n",
        encoding="utf-8",
    )


def install(
    *,
    desktop: bool = True,
    start_menu: bool = True,
    autostart: bool = True,
    source: Path | None = None,
) -> Path:
    src = source or current_exe()
    dest_dir = install_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = installed_exe()
    if src.resolve() != dest.resolve():
        import shutil

        shutil.copy2(src, dest)
    _write_uninstaller(dest)
    try:
        import config

        version = getattr(config, "VERSION", "")
    except Exception:
        version = ""
    from datetime import datetime

    _write_marker(
        {
            "app": "Help CSL",
            "version": version,
            "exe": str(dest),
            "installed_at": datetime.now().isoformat(timespec="seconds"),
            "autostart": bool(autostart),
        }
    )
    if desktop:
        try:
            create_shortcut(desktop_lnk(), dest)
        except Exception:
            pass
    if start_menu:
        try:
            create_shortcut(start_menu_lnk(), dest)
        except Exception:
            pass
    set_autostart(bool(autostart), dest)
    return dest


def uninstall() -> None:
    set_autostart(False)
    for lnk in (desktop_lnk(), start_menu_lnk()):
        try:
            if lnk.exists():
                lnk.unlink()
        except Exception:
            pass
    folder = install_dir()
    if is_installed():
        # удалить себя после выхода
        cmd = f'cmd /c ping 127.0.0.1 -n 2 >nul & rmdir /s /q "{folder}"'
        subprocess.Popen(cmd, shell=True)
        return
    if folder.exists():
        import shutil

        shutil.rmtree(folder, ignore_errors=True)


def launch_installed() -> None:
    exe = installed_exe()
    if not exe.is_file():
        return
    subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True)


def show_installer() -> str:
    """Окно установки. Возвращает install | skip | quit."""
    import tkinter as tk
    from tkinter import messagebox

    import config

    result = {"action": "quit"}

    root = tk.Tk()
    root.title(f"Установка {config.APP_NAME}")
    root.configure(bg=config.DARK)
    root.resizable(False, False)
    try:
        if config.ICON_ICO.exists():
            root.iconbitmap(default=str(config.ICON_ICO))
    except Exception:
        pass

    wrap = tk.Frame(root, bg=config.DARK, padx=22, pady=18)
    wrap.pack(fill="both", expand=True)
    tk.Label(
        wrap,
        text=config.APP_NAME.upper(),
        fg=config.WHITE,
        bg=config.DARK,
        font=("Segoe UI", 18, "bold"),
    ).pack(anchor="w")
    tk.Label(
        wrap,
        text=config.SLOGAN,
        fg=config.ORANGE,
        bg=config.DARK,
        font=("Segoe UI", 11, "bold"),
    ).pack(anchor="w", pady=(0, 12))
    tk.Label(
        wrap,
        text="Установить на этот компьютер и запускать вместе с Windows.",
        fg="#E5E7EB",
        bg=config.DARK,
        font=("Segoe UI", 10),
        wraplength=420,
        justify="left",
    ).pack(anchor="w")
    tk.Label(
        wrap,
        text=str(install_dir()),
        fg="#9CA3AF",
        bg=config.DARK,
        font=("Segoe UI", 9),
        wraplength=420,
        justify="left",
    ).pack(anchor="w", pady=(4, 12))

    var_desk = tk.BooleanVar(value=True)
    var_menu = tk.BooleanVar(value=True)
    var_auto = tk.BooleanVar(value=True)
    for var, text in (
        (var_desk, "Ярлык на рабочем столе"),
        (var_menu, "Ярлык в меню «Пуск»"),
        (var_auto, "Автозагрузка Windows (вместе с системой)"),
    ):
        tk.Checkbutton(
            wrap,
            text=text,
            variable=var,
            fg=config.WHITE,
            bg=config.DARK,
            activebackground=config.DARK,
            activeforeground=config.WHITE,
            selectcolor=config.DARK2,
            font=("Segoe UI", 10),
            anchor="w",
        ).pack(anchor="w")

    btns = tk.Frame(wrap, bg=config.DARK)
    btns.pack(fill="x", pady=(16, 0))

    def do_install() -> None:
        try:
            dest = install(
                desktop=var_desk.get(),
                start_menu=var_menu.get(),
                autostart=var_auto.get(),
            )
        except Exception as exc:
            messagebox.showerror(config.APP_NAME, f"Не удалось установить.\n{exc}")
            return
        result["action"] = "install"
        messagebox.showinfo(
            config.APP_NAME,
            "Help CSL установлен.\n\n"
            f"{dest}\n\n"
            + ("Добавлен в автозагрузку Windows.\n" if var_auto.get() else "")
            + "Сейчас программа запустится из папки установки.",
        )
        root.destroy()

    def do_skip() -> None:
        result["action"] = "skip"
        root.destroy()

    def do_quit() -> None:
        result["action"] = "quit"
        root.destroy()

    inst = tk.Button(
        btns,
        text="Установить",
        command=do_install,
        bg=config.ORANGE,
        fg=config.WHITE,
        activebackground=config.ORANGE_HOVER,
        activeforeground=config.WHITE,
        relief="flat",
        padx=16,
        pady=7,
        font=("Segoe UI", 10, "bold"),
        cursor="hand2",
    )
    inst.pack(side="left")
    tk.Button(
        btns,
        text="Запустить без установки",
        command=do_skip,
        bg=config.DARK2,
        fg=config.WHITE,
        relief="flat",
        padx=12,
        pady=7,
        font=("Segoe UI", 10),
        cursor="hand2",
    ).pack(side="left", padx=(8, 0))

    root.protocol("WM_DELETE_WINDOW", do_quit)
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    x = max(0, (root.winfo_screenwidth() - w) // 2)
    y = max(0, (root.winfo_screenheight() - h) // 4)
    root.geometry(f"+{x}+{y}")
    inst.focus_set()
    root.mainloop()
    return result["action"]


def bootstrap() -> str:
    """
    Точка входа до главного окна.
    Возвращает 'run' или 'exit'.
    """
    if not is_windows():
        return "run"
    args = [a.lower() for a in sys.argv[1:]]
    if "--uninstall" in args:
        uninstall()
        return "exit"
    if "--portable" in args or "--skip-install" in args:
        return "run"
    if "--install" in args or "--silent-install" in args:
        dest = install(desktop=True, start_menu=True, autostart=True)
        # MSI/CA не должен держать окно в процессе msiexec
        if dest.resolve() != current_exe():
            launch_installed()
        else:
            try:
                flags = 0x00000008 | 0x00000200 if is_windows() else 0
                subprocess.Popen(
                    [str(dest), "--portable"],
                    cwd=str(dest.parent),
                    close_fds=True,
                    creationflags=flags,
                )
            except Exception:
                launch_installed()
        return "exit"
    if is_installed():
        return "run"
    if not is_frozen():
        return "run"
    # HelpCSL-Setup.exe — сразу ставим, без промежуточного ярлыка
    setup_name = current_exe().name.lower()
    if "setup" in setup_name or "install" in setup_name:
        dest = install(desktop=True, start_menu=True, autostart=True)
        if dest.resolve() != current_exe():
            launch_installed()
            return "exit"
        return "run"
    action = show_installer()
    if action == "install":
        launch_installed()
        return "exit"
    if action == "skip":
        return "run"
    return "exit"
