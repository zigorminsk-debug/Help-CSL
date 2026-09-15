# -*- coding: utf-8 -*-
"""Help CSL — клиент подачи заявок в Jira Service Desk. Версия 1.11.17."""

from __future__ import annotations

import sys
import threading
import webbrowser
from pathlib import Path
from datetime import datetime, timedelta, timezone
from tkinter import TclError, filedialog, messagebox, ttk
import tkinter as tk
from typing import Callable

import config
import install_win
import storage
from calendar_by import holiday_title
from jira_client import (
    JiraClient,
    is_valid_phone,
    normalize_phone,
    phone_limit,
    phone_message,
    workstation_info,
)
from remote_ids import detect_remote_ids
from rustdesk_setup import ticket_remote_lines
from scene import HOME, RETURN, WALK_IN, CityScene

MINSK = timezone(timedelta(hours=3))
ATTACH_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
    ".xlsx",
    ".xls",
    ".docx",
    ".doc",
}
ATTACH_MAX_FILES = 10
ATTACH_MAX_MB = 10

try:
    from PIL import Image, ImageTk

    HAS_PIL = True
    try:
        RESAMPLE = Image.Resampling.LANCZOS
    except AttributeError:
        RESAMPLE = Image.LANCZOS
except Exception:
    HAS_PIL = False
    RESAMPLE = None

_TRANSLIT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
    "і": "i",
    "ў": "u",
    "ґ": "g",
}


def translit_slug(text: str) -> str:
    out: list[str] = []
    for ch in (text or "").strip().lower():
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif "a" <= ch <= "z" or ch.isdigit():
            out.append(ch)
        elif ch in "-_.":
            out.append(ch)
    return "".join(out)


def make_user_login(first: str, last: str) -> str:
    first_slug = translit_slug(first)
    last_slug = translit_slug(last)
    if not first_slug or not last_slug:
        return ""
    return f"{first_slug[0]}.{last_slug}"


def windows_version() -> tuple[int, int]:
    if sys.platform != "win32":
        return (10, 0)
    try:
        import ctypes

        class RTL_OSVERSIONINFOW(ctypes.Structure):
            _fields_ = [
                ("dwOSVersionInfoSize", ctypes.c_ulong),
                ("dwMajorVersion", ctypes.c_ulong),
                ("dwMinorVersion", ctypes.c_ulong),
                ("dwBuildNumber", ctypes.c_ulong),
                ("dwPlatformId", ctypes.c_ulong),
                ("szCSDVersion", ctypes.c_wchar * 128),
            ]

        info = RTL_OSVERSIONINFOW()
        info.dwOSVersionInfoSize = ctypes.sizeof(info)
        ctypes.windll.ntdll.RtlGetVersion(ctypes.byref(info))
        return (int(info.dwMajorVersion), int(info.dwMinorVersion))
    except Exception:
        try:
            ver = sys.getwindowsversion()
            return (int(ver.major), int(ver.minor))
        except Exception:
            return (10, 0)


def os_supported() -> bool:
    """Сборка Python 3.12: Windows 8.1 / Server 2012 R2 и новее."""
    if sys.platform != "win32":
        return True
    major, minor = windows_version()
    if major > 6:
        return True
    return major == 6 and minor >= 3


def open_unsupported_portal() -> None:
    url = getattr(config, "JIRA_BASE", "https://h.csl.by")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(
            getattr(config, "APP_NAME", "Help CSL"),
            "Эта версия Windows не поддерживается.\n"
            "Открыт портал Service Desk:\n" + url,
        )
        root.destroy()
    except Exception:
        pass


def enable_dpi() -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                import ctypes

                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def now_minsk() -> datetime:
    return datetime.now(MINSK)


def parse_when(raw: str | None) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    if len(text) >= 5 and text[-5] in "+-" and text[-4:].isdigit() and (len(text) < 6 or text[-3] != ":"):
        text = text[:-2] + ":" + text[-2:]
    iso = text
    if "T" not in iso[:19] and " " in iso:
        iso = iso.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=MINSK)
        return dt.astimezone(MINSK)
    except Exception:
        pass
    blob = text.replace("T", " ", 1)[:19]
    try:
        return datetime.strptime(blob, "%Y-%m-%d %H:%M:%S").replace(tzinfo=MINSK)
    except Exception:
        return None


def format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_clock(moment: datetime | None) -> str:
    """Реальное время Минска, как просили: 12-10."""
    if moment is None:
        return "—"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=MINSK)
    else:
        moment = moment.astimezone(MINSK)
    return moment.strftime("%H-%M")


def within_work_hours(moment: datetime | None = None) -> bool:
    moment = moment or now_minsk()
    if moment.weekday() not in config.WORK_DAYS:
        return False
    start = moment.replace(
        hour=config.WORK_FROM[0], minute=config.WORK_FROM[1], second=0, microsecond=0
    )
    end = moment.replace(
        hour=config.WORK_TO[0], minute=config.WORK_TO[1], second=0, microsecond=0
    )
    return start <= moment <= end


def hours_label() -> str:
    return (
        f"{config.WORK_FROM[0]:02d}:{config.WORK_FROM[1]:02d}"
        f"–{config.WORK_TO[0]:02d}:{config.WORK_TO[1]:02d}"
    )


class PhotoCache:
    def __init__(self) -> None:
        self._keep: list[object] = []

    def add(self, photo: object) -> object:
        self._keep.append(photo)
        return photo

    def load(self, path, size=None):
        if not HAS_PIL or not path.exists():
            return None
        image = Image.open(path).convert("RGBA")
        if size:
            image = image.copy()
            image.thumbnail(size, RESAMPLE)
        return self.add(ImageTk.PhotoImage(image))


class OrangeButton(tk.Button):
    def __init__(self, master, text: str, command: Callable | None = None, **kwargs):
        kwargs.setdefault("text", text)
        kwargs.setdefault("command", command)
        kwargs.setdefault("bg", config.ORANGE)
        kwargs.setdefault("fg", config.WHITE)
        kwargs.setdefault("activebackground", config.ORANGE_HOVER)
        kwargs.setdefault("activeforeground", config.WHITE)
        kwargs.setdefault("relief", "flat")
        kwargs.setdefault("bd", 0)
        kwargs.setdefault("padx", 14)
        kwargs.setdefault("pady", 6)
        kwargs.setdefault("cursor", "hand2")
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("font", ("Segoe UI", 10, "bold"))
        super().__init__(master, **kwargs)
        self.bind("<Enter>", lambda _e: self.configure(bg=config.ORANGE_HOVER))
        self.bind("<Leave>", lambda _e: self.configure(bg=config.ORANGE))


class DoctorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{config.APP_NAME} {config.VERSION}")
        self.configure(bg=config.BG)
        self.ui = self._compute_ui()
        self.minsize(self.ui["min_w"], self.ui["min_h"])
        self.photos = PhotoCache()
        self.client = JiraClient()
        self.current_tab = "computer"
        self._busy = False
        self._tab_buttons: dict[str, tk.Label] = {}
        self._computer_vars: dict[str, tk.BooleanVar] = {}
        self._printer_vars: dict[str, tk.BooleanVar] = {}
        self._user_service_vars: dict[str, tk.BooleanVar] = {}
        self._attach_files: dict[str, list[str]] = {
            "computer": [],
            "printer": [],
            "purchase": [],
            "users": [],
        }
        self._attach_box: dict[str, tk.Frame] = {}
        self._attach_hint: dict[str, tk.StringVar] = {}
        self.user_action_var = tk.StringVar(value="create")
        self.user_last_var = tk.StringVar()
        self.user_first_var = tk.StringVar()
        self.user_middle_var = tk.StringVar()
        self.user_login_var = tk.StringVar()
        self.last_issue_key = ""
        self.last_status = ""
        self.last_draft: dict = {}
        self.watch_key = ""
        self.timer_started_at: datetime | None = None
        self.timer_changed_at: datetime | None = None
        self.timer_stopped_at: datetime | None = None
        self.timer_label: tk.Label | None = None
        self.timer_start_lbl: tk.Label | None = None
        self.timer_change_lbl: tk.Label | None = None
        self.timer_ready_lbl: tk.Label | None = None
        self.timer_var = tk.StringVar(value="")
        self.timer_start_var = tk.StringVar(value="")
        self.timer_change_var = tk.StringVar(value="")
        self.timer_ready_var = tk.StringVar(value="")
        self._hist_shown_key = ""
        self._hist_click_job = None
        self._keep_edit_on_hist_close = False
        self._scene_hold = False
        self.editing = False
        self.edit_changed_at: datetime | None = None
        self._submit_banner = None
        self._submit_banner_job = None
        self.scene: CityScene | None = None
        self.cred_wrap: tk.Frame | None = None
        self.toolbar_wrap: tk.Frame | None = None
        self.login_box = None
        self.password_box = None
        self.phone_box = None
        self.anydesk_box = None
        self.rustdesk_box = None
        self.login_btn = None
        self.header_actions = None
        self._set_icon()
        self._init_style()
        self._build_menu()
        self._build()
        self._load_saved()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._fit_window)
        self.after(200, self._detect_remote_async)
        self.after(3500, self._detect_remote_async)
        self.after(9000, self._detect_remote_async)
        self.after(250, self._prefetch_ip)
        self.after(300, self._refresh_calendar_async)
        self.after(400, self._tick_hours)
        self.after(250, self._tick_timer)
        self.after(500, self._autologin)
        self.after(5000, self._poll_ticket)

    def _set_icon(self) -> None:
        try:
            if sys.platform == "win32" and config.ICON_ICO.exists():
                self.iconbitmap(default=str(config.ICON_ICO))
            elif config.ICON_PNG.exists() and HAS_PIL:
                img = Image.open(config.ICON_PNG)
                self.iconphoto(True, ImageTk.PhotoImage(img))
        except Exception:
            pass

    def _compute_ui(self) -> dict:
        sw = max(800, int(self.winfo_screenwidth() or 1280))
        sh = max(500, int(self.winfo_screenheight() or 720))
        tiny = sh <= 680 or sw <= 1024
        small = (not tiny) and (sh <= 820 or sw <= 1366)
        if tiny:
            mode, frac_w, frac_h = "tiny", 0.98, 0.96
            pad, gap, scene = 8, 3, 118
            f_ui, f_h, f_s, f_sm = 8, 13, 10, 8
            icon, th_c, th_p, th_b, th_u = 32, 2, 2, 4, 2
            hdr_py, cred_py, tab_px, foot = 3, 4, 8, 22
        elif small:
            mode, frac_w, frac_h = "small", 0.94, 0.92
            pad, gap, scene = 10, 4, 176
            f_ui, f_h, f_s, f_sm = 9, 15, 11, 8
            icon, th_c, th_p, th_b, th_u = 40, 3, 3, 5, 3
            hdr_py, cred_py, tab_px, foot = 5, 6, 10, 24
        else:
            mode, frac_w, frac_h = "normal", 0.88, 0.86
            pad, gap, scene = 16, 6, 228
            f_ui, f_h, f_s, f_sm = 10, 18, 12, 9
            icon, th_c, th_p, th_b, th_u = 52, 4, 4, 7, 4
            hdr_py, cred_py, tab_px, foot = 8, 8, 16, 28
        win_w = min(max(720, int(sw * frac_w)), sw - 8)
        win_h = min(max(500, int(sh * frac_h)), sh - 32)
        return {
            "mode": mode,
            "sw": sw,
            "sh": sh,
            "win_w": win_w,
            "win_h": win_h,
            "min_w": min(760 if not tiny else 640, sw - 8),
            "min_h": min(540 if not tiny else 480, sh - 32),
            "pad": pad,
            "gap": gap,
            "scene": scene,
            "icon": icon,
            "f_ui": f_ui,
            "f_h": f_h,
            "f_s": f_s,
            "f_sm": f_sm,
            "th_c": th_c,
            "th_p": th_p,
            "th_b": th_b,
            "th_u": th_u,
            "hdr_py": hdr_py,
            "cred_py": cred_py,
            "tab_px": tab_px,
            "foot": foot,
            "tiny": tiny,
            "small": small or tiny,
        }

    def _init_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except TclError:
            pass
        family = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"
        ui = self.ui
        self.font_ui = (family, ui["f_ui"])
        self.font_ui_b = (family, ui["f_ui"], "bold")
        self.font_h = (family, ui["f_h"], "bold")
        self.font_s = (family, ui["f_s"], "bold")
        self.font_small = (family, ui["f_sm"])
        style.configure("TCheckbutton", background=config.WHITE, font=self.font_ui)
        style.configure("Card.TCheckbutton", background=config.WHITE, font=self.font_ui)
        style.configure("Card.TRadiobutton", background=config.WHITE, font=self.font_ui)
        self.option_add("*Font", self.font_ui)

    def _fit_window(self) -> None:
        self.update_idletasks()
        self.ui = self._compute_ui()
        ui = self.ui
        w, h = ui["win_w"], ui["win_h"]
        x = max(0, (ui["sw"] - w) // 2)
        y = max(2, (ui["sh"] - h) // 8)
        self.minsize(ui["min_w"], ui["min_h"])
        self.geometry(f"{w}x{h}+{x}+{y}")
        scene_h = ui["scene"]
        if self.scene:
            self.scene.refit(scene_h)
        for box, key in (
            (getattr(self, "computer_text", None), "th_c"),
            (getattr(self, "printer_text", None), "th_p"),
            (getattr(self, "purchase_text", None), "th_b"),
            (getattr(self, "user_text", None), "th_u"),
        ):
            if box is not None:
                try:
                    box.configure(height=ui[key])
                except TclError:
                    pass
        self._place_hours_gap()

    def _place_hours_gap(self) -> None:
        if not getattr(self, "hours_banner", None):
            return
        tw = self.scene.tower_width() if self.scene else 70
        try:
            self.hours_banner.pack_configure(padx=(12, max(80, tw * 2)))
        except Exception:
            pass

    def _bind_csl(self, widget) -> None:
        widget.configure(cursor="hand2")
        widget.bind("<Button-1>", lambda _e: webbrowser.open(config.SITE_URL))

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        service = tk.Menu(menubar, tearoff=0)
        service.add_command(label="Отправить заявку", command=self.submit_current)
        service.add_command(label="Редактировать заявку", command=self.edit_ticket)
        service.add_command(label="История запросов", command=self.show_history)
        service.add_separator()
        service.add_command(label="Открыть портал Service Desk", command=lambda: webbrowser.open(config.JIRA_PORTAL))
        service.add_command(label="Сайт CSL.by", command=lambda: webbrowser.open(config.SITE_URL))
        service.add_separator()
        self._autostart_var = tk.BooleanVar(value=install_win.is_autostart())
        service.add_checkbutton(
            label="Запускать вместе с Windows",
            variable=self._autostart_var,
            command=self._toggle_autostart,
        )
        if install_win.is_windows() and not install_win.is_installed():
            service.add_command(label="Установить на этот компьютер…", command=self.install_now)
        if install_win.is_windows() and (install_win.is_installed() or install_win.already_on_disk()):
            service.add_command(label="Удалить с компьютера…", command=self.uninstall_now)
        service.add_separator()
        service.add_command(label="Выход", command=self.service_exit)
        menubar.add_cascade(label="Сервис", menu=service)
        helpmenu = tk.Menu(menubar, tearoff=0)
        helpmenu.add_command(label="Контакты", command=self.show_contacts)
        helpmenu.add_command(label="Предпросмотр: Дед Мороз", command=self.preview_holiday)
        helpmenu.add_command(label="Предпросмотр: поездка", command=self.preview_trip)
        helpmenu.add_command(label="Предпросмотр: ускоренная поездка", command=self.preview_replay)
        helpmenu.add_command(label="Обычная сцена", command=self.preview_normal)
        helpmenu.add_command(label="О программе", command=self.show_about)
        menubar.add_cascade(label="Справка", menu=helpmenu)
        self.config(menu=menubar)

    def _build(self) -> None:
        self._build_header()
        self._build_credentials()
        self._build_tabs()
        self._build_footer()

    def _build_header(self) -> None:
        ui = self.ui
        header = tk.Frame(self, bg=config.DARK)
        header.pack(fill="x")
        row = tk.Frame(header, bg=config.DARK)
        row.pack(fill="x", padx=ui["pad"], pady=ui["hdr_py"])
        icon = self.photos.load(config.ICON_PNG, (ui["icon"], ui["icon"]))
        if icon:
            tk.Label(row, image=icon, bg=config.DARK).pack(side="left", padx=(0, 8))
        titles = tk.Frame(row, bg=config.DARK)
        titles.pack(side="left")
        t1 = tk.Label(titles, text=config.APP_NAME.upper(), fg=config.WHITE, bg=config.DARK, font=self.font_h)
        t1.pack(anchor="w")
        self._bind_csl(t1)
        t2 = tk.Label(titles, text=config.SLOGAN, fg=config.ORANGE, bg=config.DARK, font=self.font_s)
        t2.pack(anchor="w")
        self._bind_csl(t2)

        actions = tk.Frame(row, bg=config.DARK)
        self.header_actions = actions
        actions.pack(side="left", padx=(14, 8))
        btn_padx = 8 if ui["small"] else 12
        btn_pady = 3 if ui["small"] else 5
        btn_font = self.font_ui_b
        labels = (
            ("Отправить", self.submit_current) if ui["tiny"] else ("Отправить заявку", self.submit_current),
            ("Правка", self.edit_ticket) if ui["tiny"] else ("Редактировать", self.edit_ticket),
            ("История", self.show_history),
        )
        for i, (text, cmd) in enumerate(labels):
            OrangeButton(actions, text, command=cmd, padx=btn_padx, pady=btn_pady, font=btn_font).pack(
                side="left", padx=(0 if i == 0 else 6, 0)
            )
        tsize = ui["f_ui"] + 2
        timer_font = ("Consolas", tsize, "bold")
        cap_font = (self.font_small[0], max(8, ui["f_sm"] + 1), "bold")
        self.timer_box = tk.Frame(actions, bg=config.DARK)
        self.timer_box.pack(side="left", padx=(12, 0))
        self.timer_box.configure(cursor="hand2")
        self.timer_box.bind("<Button-1>", lambda _e: self.show_history())

        def _col(parent, caption: str, var: tk.StringVar, color: str) -> tk.Label:
            col = tk.Frame(parent, bg=config.DARK)
            col.pack(side="left", padx=(0, 12))
            cap = tk.Label(col, text=caption, bg=config.DARK, fg="#9CA3AF", font=cap_font)
            cap.pack(anchor="w")
            val = tk.Label(col, textvariable=var, bg=config.DARK, fg=color, font=timer_font)
            val.pack(anchor="w")
            for w in (col, cap, val):
                w.configure(cursor="hand2")
                w.bind("<Button-1>", lambda _e: self.show_history())
            return val

        self.timer_start_lbl = _col(self.timer_box, "Старт", self.timer_start_var, config.ORANGE)
        self.timer_change_lbl = _col(self.timer_box, "Смена", self.timer_change_var, config.CYAN)
        self.timer_ready_lbl = _col(self.timer_box, "Готово", self.timer_ready_var, "#6B7280")
        self.timer_label = self.timer_start_lbl

        meta = tk.Frame(row, bg=config.DARK)
        meta.pack(side="right", padx=(0, 6))
        tk.Label(meta, text=f"☎  {config.CONTACT_PHONE_DISPLAY}", fg=config.WHITE, bg=config.DARK, font=self.font_ui_b).pack(anchor="e")
        tk.Label(meta, text=f"заявки {hours_label()}  ·  пн–пт", fg="#C9CDD3", bg=config.DARK, font=self.font_small).pack(anchor="e")

        self.hours_banner = tk.Label(row, text="", fg=config.WHITE, bg=config.SUCCESS, font=self.font_small, padx=8, pady=4)
        self.hours_banner.pack(side="right", padx=(8, 80))

        tk.Frame(self, bg=config.ORANGE, height=2).pack(fill="x")
        self.scene = CityScene(self, width=1100, height=ui["scene"])
        self.scene.pack(fill="x")
        self.after(80, self._place_hours_gap)

    def _build_credentials(self) -> None:
        ui = self.ui
        wrap = tk.Frame(self, bg=config.BG)
        self.cred_wrap = wrap
        wrap.pack(fill="x", padx=ui["pad"], pady=(ui["gap"], 2))
        card = tk.Frame(wrap, bg=config.WHITE, highlightbackground=config.LINE, highlightthickness=1)
        card.pack(fill="x")
        inner = tk.Frame(card, bg=config.WHITE)
        inner.pack(fill="x", padx=ui["pad"], pady=ui["cred_py"])
        self.cred_title = tk.Label(
            inner, text="Учётные данные портала  h.csl.by", bg=config.WHITE, fg=config.DARK2, font=self.font_ui_b
        )
        self.cred_title.grid(row=0, column=0, columnspan=8, sticky="w", pady=(0, 6))
        self.login_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.phone_var = tk.StringVar(value="+375")
        self.anydesk_var = tk.StringVar()
        self.rustdesk_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Вход не выполнен")
        self.login_box = self._labeled_entry(inner, "Логин", self.login_var, 1, 0, 20)
        self.password_box = self._labeled_entry(inner, "Пароль", self.password_var, 1, 2, 16, show="•")
        self.phone_hint_var = tk.StringVar(value="Пример: +375293761095  ·  ровно 12 цифр после +")
        self.phone_box = self._labeled_entry(
            inner, "Мобильный (+международный)", self.phone_var, 1, 4, 16, phone=True
        )
        self.anydesk_box = self._labeled_entry(inner, "AnyDesk ID (этот ПК)", self.anydesk_var, 2, 0, 18)
        self.rustdesk_box = self._labeled_entry(inner, "RustDesk ID (этот ПК)", self.rustdesk_var, 2, 2, 18)
        actions = tk.Frame(inner, bg=config.WHITE)
        actions.grid(row=3, column=0, columnspan=8, sticky="we", pady=(10, 0))
        self.login_btn = OrangeButton(actions, "Войти в Service Desk", command=self.do_login)
        self.login_btn.pack(side="left")
        self.status_label = tk.Label(actions, textvariable=self.status_var, bg=config.WHITE, fg=config.MUTED, font=self.font_small)
        self.status_label.pack(side="left", padx=14)
        for i in range(8):
            inner.grid_columnconfigure(i, weight=1)

    def _labeled_entry(self, parent, label, variable, row, col, width, show=None, phone=False):
        box = tk.Frame(parent, bg=config.WHITE)
        box.grid(row=row, column=col, columnspan=2, sticky="we", padx=(0, 12))
        tk.Label(box, text=label, bg=config.WHITE, fg=config.MUTED, font=self.font_small).pack(anchor="w")
        entry = tk.Entry(
            box,
            textvariable=variable,
            width=width,
            show=show or "",
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground=config.LINE,
            highlightcolor=config.ORANGE,
        )
        entry.pack(fill="x", ipady=3)
        if phone:
            vcmd = (self.register(self._phone_keyok), "%P")
            entry.configure(validate="key", validatecommand=vcmd)
            self.phone_entry = entry
            self.phone_hint = tk.Label(
                box, textvariable=self.phone_hint_var, bg=config.WHITE, fg=config.MUTED, font=self.font_small
            )
            self.phone_hint.pack(anchor="w", pady=(2, 0))
            variable.trace_add("write", self._refresh_phone_hint)
            self.after(50, self._refresh_phone_hint)
        return box

    def _phone_keyok(self, proposed: str) -> bool:
        if proposed == "":
            return True
        if not proposed.startswith("+"):
            return False
        if any(ch not in "+0123456789" for ch in proposed):
            return False
        if proposed.count("+") != 1:
            return False
        return len(proposed) <= phone_limit(proposed)

    def _refresh_phone_hint(self, *_args) -> None:
        if not getattr(self, "phone_hint", None):
            return
        msg = phone_message(self.phone_var.get())
        if not msg and is_valid_phone(self.phone_var.get()):
            self.phone_hint_var.set("Номер в международном формате, длина верная")
            self.phone_hint.configure(fg=config.SUCCESS)
        else:
            self.phone_hint_var.set(msg or "Пример: +375293761095")
            self.phone_hint.configure(fg=config.DANGER if msg else config.MUTED)

    def _set_cred_visible(self, visible: bool) -> None:
        if not self.cred_wrap or not self.login_box or not self.password_box:
            return
        if visible:
            self.login_box.grid()
            self.password_box.grid()
            if self.phone_box:
                self.phone_box.grid(row=1, column=4, columnspan=2, sticky="we", padx=(0, 12))
            if self.anydesk_box:
                self.anydesk_box.grid()
            if self.rustdesk_box:
                self.rustdesk_box.grid()
            if self.login_btn and not str(self.login_btn.winfo_manager()):
                self.login_btn.pack(side="left", before=self.status_label)
            if getattr(self, "cred_title", None):
                self.cred_title.configure(text="Учётные данные портала  h.csl.by")
        else:
            self.login_box.grid_remove()
            self.password_box.grid_remove()
            if self.anydesk_box:
                self.anydesk_box.grid_remove()
            if self.rustdesk_box:
                self.rustdesk_box.grid_remove()
            if self.phone_box:
                self.phone_box.grid(row=1, column=0, columnspan=2, sticky="we", padx=(0, 12))
            if self.login_btn:
                self.login_btn.pack_forget()
            if getattr(self, "cred_title", None):
                self.cred_title.configure(text="Мобильный")

    def _build_tabs(self) -> None:
        ui = self.ui
        wrap = tk.Frame(self, bg=config.BG)
        wrap.pack(fill="both", expand=True, padx=ui["pad"], pady=(2, 4))
        bar = tk.Frame(wrap, bg=config.DARK)
        bar.pack(fill="x")
        if ui["tiny"]:
            titles = (
                ("computer", "1 ПК"),
                ("printer", "2 Принтеры"),
                ("purchase", "3 Закупки"),
                ("users", "4 Пользователи"),
            )
        else:
            titles = (
                ("computer", "1  ·  Компьютер"),
                ("printer", "2  ·  Принтеры"),
                ("purchase", "3  ·  Закупки"),
                ("users", "4  ·  Создание/удаление пользователей"),
            )
        for key, title in titles:
            self._add_tab_btn(bar, key, title)
        body = tk.Frame(wrap, bg=config.WHITE, highlightbackground=config.LINE, highlightthickness=1)
        body.pack(fill="both", expand=True)
        self.pages = {
            "computer": self._page_computer(body),
            "printer": self._page_printer(body),
            "purchase": self._page_purchase(body),
            "users": self._page_users(body),
        }
        self._show_tab("computer")

    def _add_tab_btn(self, parent, key: str, title: str) -> None:
        btn = tk.Label(
            parent,
            text=title,
            bg=config.TAB_IDLE,
            fg=config.WHITE,
            font=self.font_ui_b,
            padx=self.ui["tab_px"],
            pady=4 if self.ui["small"] else 7,
            cursor="hand2",
        )
        btn.pack(side="left")
        btn.bind("<Button-1>", lambda _e, k=key: self._show_tab(k))
        self._tab_buttons[key] = btn

    def _show_tab(self, key: str) -> None:
        self.current_tab = key
        for name, page in self.pages.items():
            page.pack_forget()
        self.pages[key].pack(fill="both", expand=True)
        for name, btn in self._tab_buttons.items():
            btn.configure(bg=config.ORANGE if name == key else config.TAB_IDLE, fg=config.WHITE)

    def _split_row(self, parent) -> tuple[tk.Frame, tk.Frame]:
        row = tk.Frame(parent, bg=config.WHITE)
        row.pack(fill="both", expand=True)
        left = tk.Frame(row, bg=config.WHITE)
        right = tk.Frame(row, bg=config.WHITE)
        left.pack(side="left", fill="both", expand=True, padx=(0, 12))
        right.pack(side="left", fill="both", expand=True)
        return left, right

    def _checkbox_grid(self, parent, catalog, store) -> None:
        grid = tk.Frame(parent, bg=config.WHITE)
        grid.pack(fill="both", expand=True, anchor="n")
        cols = 1 if self.ui.get("tiny") else 2
        for i, (key, title) in enumerate(catalog):
            var = tk.BooleanVar(value=False)
            store[key] = var
            ttk.Checkbutton(grid, text=title, variable=var, style="Card.TCheckbutton").grid(
                row=i // cols, column=i % cols, sticky="nw", padx=(0, 12), pady=0 if self.ui["small"] else 1
            )
        for c in range(cols):
            grid.grid_columnconfigure(c, weight=1)

    def _text_box(self, parent, height: int) -> tk.Text:
        widget = tk.Text(
            parent,
            height=height,
            wrap="word",
            relief="solid",
            bd=1,
            padx=8,
            pady=6,
            highlightthickness=1,
            highlightbackground=config.LINE,
            highlightcolor=config.ORANGE,
        )
        widget.pack(fill="both", expand=True)
        return widget

    def _notes_column(self, parent, title: str, height: int, pady=(0, 3)) -> tk.Text:
        tk.Label(parent, text=title, bg=config.WHITE, fg=config.DARK2, font=self.font_ui_b).pack(anchor="w", pady=pady)
        return self._text_box(parent, height)

    def _build_attachments(self, parent, tab: str) -> None:
        wrap = tk.Frame(parent, bg=config.WHITE)
        wrap.pack(fill="x", pady=(8, 0))
        row = tk.Frame(wrap, bg=config.WHITE)
        row.pack(fill="x")
        OrangeButton(
            row,
            "Прикрепить файлы",
            command=lambda t=tab: self._add_attachments(t),
            padx=10,
            pady=3,
            font=self.font_ui_b,
        ).pack(side="left")
        hint = tk.StringVar(value="Скриншоты, фото, Excel, Word")
        self._attach_hint[tab] = hint
        tk.Label(row, textvariable=hint, bg=config.WHITE, fg=config.MUTED, font=self.font_small).pack(
            side="left", padx=10
        )
        box = tk.Frame(wrap, bg=config.WHITE)
        box.pack(fill="x", pady=(4, 0))
        self._attach_box[tab] = box
        self._refresh_attach_list(tab)

    def _add_attachments(self, tab: str) -> None:
        current = list(self._attach_files.get(tab) or [])
        left = ATTACH_MAX_FILES - len(current)
        if left <= 0:
            messagebox.showwarning(config.APP_NAME, f"Можно прикрепить не больше {ATTACH_MAX_FILES} файлов.")
            return
        paths = filedialog.askopenfilenames(
            parent=self,
            title="Скриншоты, фото, Excel, Word",
            filetypes=[
                ("Скриншоты и документы", "*.png *.jpg *.jpeg *.gif *.bmp *.webp *.xlsx *.xls *.docx *.doc"),
                ("Изображения", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                ("Excel", "*.xlsx *.xls"),
                ("Word", "*.docx *.doc"),
                ("Все файлы", "*.*"),
            ],
        )
        skipped: list[str] = []
        for raw in paths or ():
            path = Path(raw)
            ext = path.suffix.lower()
            if ext not in ATTACH_EXTS:
                skipped.append(f"{path.name}: тип не подходит")
                continue
            try:
                size = path.stat().st_size
            except OSError:
                skipped.append(f"{path.name}: нет файла")
                continue
            if size > ATTACH_MAX_MB * 1024 * 1024:
                skipped.append(f"{path.name}: больше {ATTACH_MAX_MB} МБ")
                continue
            key = str(path)
            if key in current:
                continue
            if len(current) >= ATTACH_MAX_FILES:
                skipped.append("лимит файлов")
                break
            current.append(key)
        self._attach_files[tab] = current
        self._refresh_attach_list(tab)
        if skipped:
            messagebox.showwarning(config.APP_NAME, "Не добавлено:\n" + "\n".join(skipped[:8]))

    def _remove_attachment(self, tab: str, path: str) -> None:
        files = [p for p in (self._attach_files.get(tab) or []) if p != path]
        self._attach_files[tab] = files
        self._refresh_attach_list(tab)

    def _clear_attachments(self, tab: str | None = None) -> None:
        keys = [tab] if tab else list(self._attach_files)
        for key in keys:
            self._attach_files[key] = []
            self._refresh_attach_list(key)

    def _refresh_attach_list(self, tab: str) -> None:
        box = self._attach_box.get(tab)
        hint = self._attach_hint.get(tab)
        files = list(self._attach_files.get(tab) or [])
        if hint:
            if files:
                hint.set(f"{len(files)} из {ATTACH_MAX_FILES}")
            else:
                hint.set("Скриншоты, фото, Excel, Word")
        if box is None:
            return
        for child in box.winfo_children():
            child.destroy()
        for path in files:
            name = Path(path).name
            row = tk.Frame(box, bg=config.WHITE)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=name, bg=config.WHITE, fg=config.DARK2, font=self.font_small, anchor="w").pack(
                side="left", fill="x", expand=True
            )
            tk.Label(
                row,
                text="×",
                bg=config.WHITE,
                fg=config.DANGER,
                font=self.font_ui_b,
                cursor="hand2",
            ).pack(side="right")
            row.winfo_children()[-1].bind("<Button-1>", lambda _e, t=tab, p=path: self._remove_attachment(t, p))

    def _page_computer(self, parent) -> tk.Frame:
        page = tk.Frame(parent, bg=config.WHITE)
        pad = tk.Frame(page, bg=config.WHITE)
        pad.pack(fill="both", expand=True, padx=self.ui["pad"], pady=self.ui["gap"])
        tk.Label(pad, text="Типовые инциденты с компьютером", bg=config.WHITE, fg=config.DARK2, font=self.font_s).pack(anchor="w")
        tk.Label(
            pad,
            text="Отметьте всё, что подходит. Комментарий — справа.",
            bg=config.WHITE,
            fg=config.MUTED,
            font=self.font_small,
        ).pack(anchor="w", pady=(0, 6))
        left, right = self._split_row(pad)
        self._checkbox_grid(left, config.COMPUTER_INCIDENTS, self._computer_vars)
        self.computer_text = self._notes_column(right, "Описание / уточнения", max(8, self.ui["th_c"] + 4))
        self._build_attachments(pad, "computer")
        return page

    def _page_printer(self, parent) -> tk.Frame:
        page = tk.Frame(parent, bg=config.WHITE)
        pad = tk.Frame(page, bg=config.WHITE)
        pad.pack(fill="both", expand=True, padx=self.ui["pad"], pady=self.ui["gap"])
        tk.Label(pad, text="Типовые инциденты с принтерами", bg=config.WHITE, fg=config.DARK2, font=self.font_s).pack(anchor="w")
        tk.Label(
            pad,
            text="Отметьте симптомы. Комментарий — справа.",
            bg=config.WHITE,
            fg=config.MUTED,
            font=self.font_small,
        ).pack(anchor="w", pady=(0, 6))
        left, right = self._split_row(pad)
        self._checkbox_grid(left, config.PRINTER_INCIDENTS, self._printer_vars)
        self.printer_text = self._notes_column(right, "Описание / модель принтера, кабинет", max(8, self.ui["th_p"] + 4))
        self._build_attachments(pad, "printer")
        return page

    def _page_purchase(self, parent) -> tk.Frame:
        page = tk.Frame(parent, bg=config.WHITE)
        pad = tk.Frame(page, bg=config.WHITE)
        pad.pack(fill="both", expand=True, padx=self.ui["pad"], pady=self.ui["gap"])
        tk.Label(pad, text="Закупки", bg=config.WHITE, fg=config.DARK2, font=self.font_s).pack(anchor="w")
        tk.Label(
            pad,
            text="Опишите пожелания: что закупить, количество, кабинет и зачем.",
            bg=config.WHITE,
            fg=config.MUTED,
            font=self.font_small,
        ).pack(anchor="w", pady=(0, 6))
        self.purchase_text = self._text_box(pad, self.ui["th_b"])
        self._build_attachments(pad, "purchase")
        return page

    def _page_users(self, parent) -> tk.Frame:
        page = tk.Frame(parent, bg=config.WHITE)
        pad = tk.Frame(page, bg=config.WHITE)
        pad.pack(fill="both", expand=True, padx=self.ui["pad"], pady=self.ui["gap"])
        tk.Label(pad, text="Создание / удаление пользователей", bg=config.WHITE, fg=config.DARK2, font=self.font_s).pack(anchor="w")
        tk.Label(
            pad,
            text="Логин собирается сам: первая буква имени + точка + фамилия латиницей (и.ivanov).",
            bg=config.WHITE,
            fg=config.MUTED,
            font=self.font_small,
        ).pack(anchor="w", pady=(0, 6))
        action_row = tk.Frame(pad, bg=config.WHITE)
        action_row.pack(anchor="w", pady=(0, 8))
        ttk.Radiobutton(
            action_row, text="Создать пользователя", variable=self.user_action_var, value="create", style="Card.TRadiobutton"
        ).pack(side="left")
        ttk.Radiobutton(
            action_row, text="Удалить пользователя", variable=self.user_action_var, value="delete", style="Card.TRadiobutton"
        ).pack(side="left", padx=(18, 0))
        names = tk.Frame(pad, bg=config.WHITE)
        names.pack(fill="x")
        fields = (
            ("Фамилия", self.user_last_var),
            ("Имя", self.user_first_var),
            ("Отчество", self.user_middle_var),
            ("Логин (авто)", self.user_login_var),
        )
        for i, (label, var) in enumerate(fields):
            box = tk.Frame(names, bg=config.WHITE)
            box.grid(row=0, column=i, sticky="we", padx=(0, 10))
            tk.Label(box, text=label, bg=config.WHITE, fg=config.MUTED, font=self.font_small).pack(anchor="w")
            tk.Entry(
                box,
                textvariable=var,
                relief="solid",
                bd=1,
                highlightthickness=1,
                highlightbackground=config.LINE,
                highlightcolor=config.ORANGE,
            ).pack(fill="x", ipady=3)
            names.grid_columnconfigure(i, weight=1)
        self.user_last_var.trace_add("write", self._sync_user_login)
        self.user_first_var.trace_add("write", self._sync_user_login)
        left, right = self._split_row(pad)
        tk.Label(left, text="Услуги", bg=config.WHITE, fg=config.DARK2, font=self.font_ui_b).pack(anchor="w", pady=(10, 3))
        self._checkbox_grid(left, config.USER_SERVICES, self._user_service_vars)
        self.user_text = self._notes_column(right, "Пояснения", max(6, self.ui["th_u"] + 4), pady=(10, 3))
        self._build_attachments(pad, "users")
        return page

    def _sync_user_login(self, *_args) -> None:
        self.user_login_var.set(make_user_login(self.user_first_var.get(), self.user_last_var.get()))

    def _build_footer(self) -> None:
        foot = tk.Frame(self, bg=config.DARK, height=self.ui["foot"])
        foot.pack(fill="x", side="bottom")
        foot.pack_propagate(False)
        foot_l = tk.Label(
            foot,
            text=f"Разработчик: {config.DEVELOPER}  ·  CSL  ·  {config.SITE_URL}",
            bg=config.DARK,
            fg="#D1D5DB",
            font=self.font_small,
        )
        foot_l.pack(side="left", padx=14)
        self._bind_csl(foot_l)
        tk.Label(foot, text=f"v{config.VERSION}", bg=config.DARK, fg=config.ORANGE, font=self.font_small).pack(side="right", padx=14)

    def _tick_hours(self) -> None:
        now = now_minsk()
        stamp = now.strftime("%H:%M")
        feast = holiday_title(now.date())
        if feast:
            self.hours_banner.configure(
                text=f"Сегодня нерабочий день РБ: {feast}. Срочно: {config.CONTACT_PHONE_DISPLAY}",
                bg=config.DANGER,
            )
        elif within_work_hours(now):
            self.hours_banner.configure(
                text=f"Приём заявок открыт  ·  до {hours_label().split('–')[1]} (Минск {stamp})",
                bg=config.SUCCESS,
            )
        elif now.weekday() >= 5:
            self.hours_banner.configure(
                text=f"Выходной. Заявки {hours_label()}, пн–пт (календарь РБ). Срочно: {config.CONTACT_PHONE_DISPLAY}",
                bg=config.DANGER,
            )
        else:
            self.hours_banner.configure(
                text=f"Вне времени подачи ({hours_label()}). Срочно: {config.CONTACT_PHONE_DISPLAY}",
                bg=config.DANGER,
            )
        self.after(30000, self._tick_hours)

    def _apply_remote_ids(self, ids: dict[str, str], force: bool = False) -> None:
        anydesk = (ids.get("anydesk") or "").strip()
        rustdesk = (ids.get("rustdesk") or "").strip()
        if anydesk and (force or not self.anydesk_var.get().strip()):
            self.anydesk_var.set(anydesk)
        if rustdesk and (force or not self.rustdesk_var.get().strip()):
            self.rustdesk_var.set(rustdesk)

    def _refresh_calendar_async(self) -> None:
        def work() -> None:
            try:
                from calendar_by import calendar

                calendar().refresh_from_web()
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _prefetch_ip(self) -> None:
        threading.Thread(target=workstation_info, daemon=True).start()

    def _detect_remote_async(self) -> None:
        def work() -> None:
            try:
                ids = detect_remote_ids()
            except Exception:
                ids = {"anydesk": "", "rustdesk": ""}
            self.after(0, lambda: self._apply_remote_ids(ids, force=True))

        threading.Thread(target=work, daemon=True).start()

    def _refresh_remote_ids(self) -> None:
        """Только чтение AnyDesk / RustDesk ID, без установки."""
        try:
            ids = detect_remote_ids()
        except Exception:
            ids = {"anydesk": "", "rustdesk": ""}
        self._apply_remote_ids(ids, force=True)

    def _load_saved(self) -> None:
        data = storage.load_profile()
        if not data:
            self._set_cred_visible(True)
            self._refresh_remote_ids()
            return
        self.login_var.set(data.get("login", ""))
        self.password_var.set(data.get("password", ""))
        self.phone_var.set(data.get("phone", "+375"))
        self.anydesk_var.set(data.get("anydesk", "") or "")
        self.rustdesk_var.set(data.get("rustdesk", "") or "")
        self.last_issue_key = data.get("last_issue_key", "") or ""
        self.last_draft = data.get("last_draft") or {}
        self.watch_key = data.get("watch_issue_key", "") or self.last_issue_key
        self.timer_started_at = parse_when(data.get("ticket_started_at") or "")
        self.timer_changed_at = parse_when(data.get("ticket_changed_at") or "")
        self.timer_stopped_at = parse_when(data.get("ticket_finished_at") or "")
        if (
            self.timer_changed_at
            and self.timer_started_at
            and abs((self.timer_changed_at - self.timer_started_at).total_seconds()) < 15
        ):
            self.timer_changed_at = None
        self.last_status = data.get("last_status") or ""
        self.editing = bool(data.get("editing"))
        self.edit_changed_at = parse_when(data.get("edit_changed_at") or "")
        self._paint_timer()
        self._refresh_remote_ids()
        if data.get("login") and data.get("password"):
            self._set_cred_visible(False)
            self.status_var.set("Автовход…")
        else:
            self._set_cred_visible(True)

    def persist(self) -> None:
        storage.save_profile(
            {
                "login": self.login_var.get().strip(),
                "password": self.password_var.get(),
                "phone": normalize_phone(self.phone_var.get()),
                "anydesk": self.anydesk_var.get().strip(),
                "rustdesk": self.rustdesk_var.get().strip(),
                "saved_at": now_minsk().isoformat(timespec="seconds"),
                "app_version": config.VERSION,
                "last_issue_key": self.last_issue_key,
                "last_draft": self.last_draft,
                "watch_issue_key": self.watch_key,
                "ticket_started_at": self.timer_started_at.isoformat(timespec="seconds") if self.timer_started_at else "",
                "ticket_changed_at": self.timer_changed_at.isoformat(timespec="seconds") if self.timer_changed_at else "",
                "ticket_finished_at": self.timer_stopped_at.isoformat(timespec="seconds") if self.timer_stopped_at else "",
                "last_status": self.last_status,
                "editing": self.editing,
                "edit_changed_at": self.edit_changed_at.isoformat(timespec="seconds") if self.edit_changed_at else "",
            }
        )

    def _autologin(self) -> None:
        login = self.login_var.get().strip()
        password = self.password_var.get()
        if not login or not password:
            self._set_cred_visible(True)
            return
        self._set_busy(True, "Автоматический вход…")

        def work():
            try:
                name = self.client.login(login, password)
                self.client.discover()
                self.after(0, lambda: self._login_ok(name, silent=True))
            except Exception as exc:
                self.after(0, lambda e=str(exc): self._login_fail(e))

        threading.Thread(target=work, daemon=True).start()

    def do_login(self) -> None:
        login = self.login_var.get().strip()
        password = self.password_var.get()
        phone = normalize_phone(self.phone_var.get())
        if not login or not password:
            messagebox.showwarning(config.APP_NAME, "Введите логин и пароль портала.")
            return
        if not is_valid_phone(phone):
            messagebox.showwarning(
                config.APP_NAME,
                phone_message(self.phone_var.get()) or "Укажите мобильный в международном формате, например +375293761095.",
            )
            return
        self.phone_var.set(phone)
        self._set_busy(True, "Выполняется вход…")

        def work():
            try:
                name = self.client.login(login, password)
                self.client.discover()
                self.after(0, lambda: self._login_ok(name, silent=False))
            except Exception as exc:
                self.after(0, lambda e=str(exc): self._login_fail(e))

        threading.Thread(target=work, daemon=True).start()

    def _login_ok(self, name: str, silent: bool = False) -> None:
        self.persist()
        self._set_cred_visible(False)
        desks = ", ".join(d.name for d in self.client.desks) or "портал"
        self.status_var.set(f"Вход выполнен: {name}  ·  {desks}")
        self.status_label.configure(fg=config.SUCCESS)
        self._set_busy(False)
        if self.last_issue_key or self.watch_key:
            self.after(400, self._resume_ticket)
        if not silent:
            messagebox.showinfo(config.APP_NAME, f"Добро пожаловать, {name}.\nHelp CSL уже в пути.")

    def _login_fail(self, error: str) -> None:
        self._set_cred_visible(True)
        self.status_var.set("Ошибка входа")
        self.status_label.configure(fg=config.DANGER)
        self._set_busy(False)
        messagebox.showerror(config.APP_NAME, f"Не удалось войти в {config.JIRA_BASE}.\n\n{error}")

    def _set_busy(self, busy: bool, text: str | None = None) -> None:
        self._busy = busy
        if text:
            self.status_var.set(text)
        self.configure(cursor="watch" if busy else "")

    def _selected(self, mapping, catalog) -> list[str]:
        titles = {k: t for k, t in catalog}
        return [titles[k] for k, var in mapping.items() if var.get() and k in titles]

    def _remote_lines(self) -> list[str]:
        self._refresh_remote_ids()
        anydesk = self.anydesk_var.get().strip()
        rustdesk = self.rustdesk_var.get().strip()
        return ticket_remote_lines(anydesk, rustdesk)

    def _snapshot_form(self) -> dict:
        return {
            "tab": self.current_tab,
            "computer": {k: v.get() for k, v in self._computer_vars.items()},
            "printer": {k: v.get() for k, v in self._printer_vars.items()},
            "computer_text": self.computer_text.get("1.0", "end").strip(),
            "printer_text": self.printer_text.get("1.0", "end").strip(),
            "purchase_text": self.purchase_text.get("1.0", "end").strip(),
            "user_action": self.user_action_var.get(),
            "user_last": self.user_last_var.get(),
            "user_first": self.user_first_var.get(),
            "user_middle": self.user_middle_var.get(),
            "user_login": self.user_login_var.get(),
            "user_services": {k: v.get() for k, v in self._user_service_vars.items()},
            "user_text": self.user_text.get("1.0", "end").strip(),
            "attachments": {k: list(v) for k, v in self._attach_files.items()},
        }

    def _restore_form(self, draft: dict) -> None:
        if not draft:
            return
        tab = draft.get("tab") or "computer"
        for k, var in self._computer_vars.items():
            var.set(bool((draft.get("computer") or {}).get(k)))
        for k, var in self._printer_vars.items():
            var.set(bool((draft.get("printer") or {}).get(k)))
        self.computer_text.delete("1.0", "end")
        self.computer_text.insert("1.0", draft.get("computer_text") or "")
        self.printer_text.delete("1.0", "end")
        self.printer_text.insert("1.0", draft.get("printer_text") or "")
        self.purchase_text.delete("1.0", "end")
        self.purchase_text.insert("1.0", draft.get("purchase_text") or "")
        self.user_action_var.set(draft.get("user_action") or "create")
        self.user_last_var.set(draft.get("user_last") or "")
        self.user_first_var.set(draft.get("user_first") or "")
        self.user_middle_var.set(draft.get("user_middle") or "")
        if draft.get("user_login"):
            self.user_login_var.set(draft.get("user_login") or "")
        for k, var in self._user_service_vars.items():
            var.set(bool((draft.get("user_services") or {}).get(k)))
        self.user_text.delete("1.0", "end")
        self.user_text.insert("1.0", draft.get("user_text") or "")
        saved = draft.get("attachments") or {}
        if isinstance(saved, dict):
            for key in self._attach_files:
                paths = [p for p in (saved.get(key) or []) if Path(p).is_file()]
                self._attach_files[key] = paths
                self._refresh_attach_list(key)
        self._show_tab(tab)

    def _clear_form(self) -> None:
        for store in (self._computer_vars, self._printer_vars, self._user_service_vars):
            for var in store.values():
                var.set(False)
        for box in (self.computer_text, self.printer_text, self.purchase_text, self.user_text):
            box.delete("1.0", "end")
        self.user_action_var.set("create")
        self.user_last_var.set("")
        self.user_first_var.set("")
        self.user_middle_var.set("")
        self.user_login_var.set("")
        self._clear_attachments()
        self._show_tab("computer")

    def _reset_ready_ui(self) -> None:
        """Форма пустая, сцена дома, без анимации — готовы к новой заявке."""
        self._keep_edit_on_hist_close = False
        self.editing = False
        self.edit_changed_at = None
        self.last_draft = {}
        self._hist_shown_key = ""
        self._scene_hold = True
        self._clear_form()
        if self.scene:
            self.scene.stop_replay()
            self.scene.reset_home()
        if self.client.logged_in:
            self.status_var.set("Готово к новой заявке")
            self.status_label.configure(fg=config.SUCCESS)
        self._paint_timer()

    def _user_description_from_ticket(self, description: str) -> str:
        text = (description or "").replace("\r\n", "\n").strip()
        if not text:
            return ""
        cut_marks = (
            "Удалённый доступ",
            "Удаленный доступ",
            "Контактные данные:",
            "Служебная информация:",
            "Статус: Изменено",
        )
        low = text
        cut = len(text)
        for mark in cut_marks:
            pos = low.find(mark)
            if pos >= 0:
                cut = min(cut, pos)
        text = text[:cut].strip()
        for prefix in (
            "Описание пользователя:",
            "Пожелания:",
            "Пояснения:",
            "Типовые инциденты:",
        ):
            if prefix in text:
                text = text.split(prefix, 1)[-1].strip()
        lines = []
        for line in text.splitlines():
            raw = line.strip()
            if raw.startswith("Категория:") or raw.startswith("Тип:") or raw.startswith("Действие:"):
                continue
            if raw.startswith("ФИО:") or raw.startswith("Логин:") or raw.startswith("Услуги:"):
                continue
            if raw.startswith("Исходная заявка:") or raw.startswith("Время изменения:"):
                continue
            if raw.startswith("• "):
                continue
            if raw:
                lines.append(raw)
        return "\n".join(lines).strip()

    def _tab_from_ticket(self, row: dict) -> str:
        blob = " ".join(
            str(row.get(k) or "") for k in ("type", "summary", "description")
        ).lower().replace("ё", "е")
        if "закуп" in blob or "[закупки]" in blob:
            return "purchase"
        if "пользовател" in blob:
            return "users"
        if "принтер" in blob:
            return "printer"
        return "computer"

    def _draft_from_history(self, row: dict) -> dict:
        desc = row.get("description") or ""
        summary = row.get("summary") or ""
        hay = f"{summary}\n{desc}"
        hay_l = hay.lower()
        tab = self._tab_from_ticket(row)
        notes = self._user_description_from_ticket(desc)
        computer = {k: (t.lower() in hay_l) for k, t in config.COMPUTER_INCIDENTS}
        printer = {k: (t.lower() in hay_l) for k, t in config.PRINTER_INCIDENTS}
        services = {k: (t.lower() in hay_l) for k, t in config.USER_SERVICES}
        action = "delete" if "удален" in hay_l or "удалён" in hay_l else "create"
        return {
            "tab": tab,
            "computer": computer,
            "printer": printer,
            "computer_text": notes if tab == "computer" else "",
            "printer_text": notes if tab == "printer" else "",
            "purchase_text": notes if tab == "purchase" else (notes or summary),
            "user_action": action,
            "user_last": "",
            "user_first": "",
            "user_middle": "",
            "user_login": "",
            "user_services": services,
            "user_text": notes if tab == "users" else "",
        }

    def _compose(self) -> tuple[str, str, str] | None:
        phone = normalize_phone(self.phone_var.get())
        login = self.login_var.get().strip()
        ws = workstation_info()
        if self.current_tab == "computer":
            chosen = self._selected(self._computer_vars, config.COMPUTER_INCIDENTS)
            extra = self.computer_text.get("1.0", "end").strip()
            if not chosen and not extra:
                messagebox.showwarning(config.APP_NAME, "Отметьте инцидент или опишите проблему.")
                return None
            summary = f"[Компьютер] {', '.join(chosen) if chosen else extra.splitlines()[0]}"[:254]
            body = ["Категория: Компьютер", "Тип: Проблемы с ПК/Ноутбуком", ""]
            if chosen:
                body += ["Типовые инциденты:"] + [f"• {x}" for x in chosen] + [""]
            if extra:
                body += ["Описание пользователя:", extra, ""]
            category = "computer"
        elif self.current_tab == "printer":
            chosen = self._selected(self._printer_vars, config.PRINTER_INCIDENTS)
            extra = self.printer_text.get("1.0", "end").strip()
            if not chosen and not extra:
                messagebox.showwarning(config.APP_NAME, "Отметьте инцидент с принтером или опишите проблему.")
                return None
            summary = f"[Принтеры] {', '.join(chosen) if chosen else extra.splitlines()[0]}"[:254]
            body = ["Категория: Принтеры", "Тип: Проблемы с ПК/Ноутбуком", ""]
            if chosen:
                body += ["Типовые инциденты:"] + [f"• {x}" for x in chosen] + [""]
            if extra:
                body += ["Описание пользователя:", extra, ""]
            category = "printer"
        elif self.current_tab == "users":
            last = self.user_last_var.get().strip()
            first = self.user_first_var.get().strip()
            middle = self.user_middle_var.get().strip()
            ulogin = self.user_login_var.get().strip() or make_user_login(first, last)
            if not last or not first:
                messagebox.showwarning(config.APP_NAME, "Укажите фамилию и имя.")
                return None
            if not ulogin:
                messagebox.showwarning(config.APP_NAME, "Не удалось сформировать логин. Проверьте фамилию и имя.")
                return None
            action = self.user_action_var.get() or "create"
            action_ru = "Создание" if action == "create" else "Удаление"
            services = self._selected(self._user_service_vars, config.USER_SERVICES)
            extra = self.user_text.get("1.0", "end").strip()
            fio = " ".join(part for part in (last, first, middle) if part)
            summary = f"[Пользователи] {action_ru}: {ulogin} ({fio})"[:254]
            body = [
                "Категория: Пользователи",
                "Тип: Проблемы с ПК/Ноутбуком",
                f"Действие: {action_ru}",
                f"ФИО: {fio}",
                f"Логин: {ulogin}",
                "",
            ]
            if services:
                body += ["Услуги:"] + [f"• {x}" for x in services] + [""]
            if extra:
                body += ["Пояснения:", extra, ""]
            category = "users"
        else:
            extra = self.purchase_text.get("1.0", "end").strip()
            if not extra:
                messagebox.showwarning(config.APP_NAME, "Опишите пожелания по закупке.")
                return None
            summary = f"[Закупки] {extra.splitlines()[0]}"[:254]
            body = ["Категория: Закупки", "Тип: Закупки", "", "Пожелания:", extra, ""]
            category = "purchase"
        names = [Path(p).name for p in (self._attach_files.get(category) or [])]
        if names:
            body += ["Вложения:"] + [f"• {n}" for n in names] + [""]
        body += self._remote_lines()
        body += [
            "Контактные данные:",
            f"• Логин портала: {login}",
            f"• Мобильный: {phone}",
            "",
            "Служебная информация:",
            f"• Компьютер: {ws.get('computer')}",
            f"• Пользователь ОС: {ws.get('os_user')}",
            f"• ОС: {ws.get('os')}",
            f"• Локальный IP: {ws.get('ip_local') or ws.get('ip') or 'не определён'}",
            f"• Внешний IP: {ws.get('ip_external') or 'не определён'}",
            f"• Клиент: {config.APP_NAME} {config.VERSION}",
        ]
        if self.editing and self.edit_changed_at:
            stamp = self.edit_changed_at.strftime("%Y-%m-%d %H:%M:%S")
            body = [
                "Статус: Изменено",
                f"Время изменения: {stamp}",
                f"Исходная заявка: {self.last_issue_key or '—'}",
                "",
            ] + body
            if not summary.startswith("[Изменено]"):
                summary = f"[Изменено] {summary}"[:254]
        return category, summary, "\n".join(body)

    def submit_current(self) -> None:
        if self._busy:
            return
        if not self.login_var.get().strip() or not self.password_var.get():
            self._set_cred_visible(True)
            messagebox.showwarning(config.APP_NAME, "Сначала войдите в Service Desk.")
            return
        phone = normalize_phone(self.phone_var.get())
        if not is_valid_phone(phone):
            self._set_cred_visible(True)
            messagebox.showwarning(config.APP_NAME, "Укажите мобильный в международном формате.")
            return
        self.phone_var.set(phone)
        composed = self._compose()
        if not composed:
            return
        category, summary, description = composed
        files = list(self._attach_files.get(category) or [])
        warn = ""
        if files:
            warn += f"\n\nФайлов: {len(files)}"
        if not within_work_hours():
            warn += f"\n\nСейчас вне времени подачи ({hours_label()}). Срочно: {config.CONTACT_PHONE_DISPLAY}."
        if self.editing and self.last_issue_key:
            changed = ""
            if self.edit_changed_at:
                changed = f"\nСтатус: Изменено ({self.edit_changed_at.strftime('%Y-%m-%d %H:%M:%S')})"
            msg = (
                f"Сохранить изменения заявки {self.last_issue_key}?{changed}\n\n"
                f"Старый запрос будет закрыт, новый уйдёт в Service Desk.\n\n{summary}{warn}"
            )
        else:
            msg = f"Отправить сервисный запрос?\n\n{summary}{warn}"
        if not messagebox.askyesno(config.APP_NAME, msg):
            return
        self.last_draft = self._snapshot_form()
        self.persist()
        self._set_busy(True, "Отправка заявки…")
        old_key = self.last_issue_key if self.editing else ""

        def work():
            try:
                if not self.client.logged_in:
                    self.client.login(self.login_var.get().strip(), self.password_var.get())
                    self.client.discover()
                if old_key:
                    try:
                        self.client.mark_changed(old_key)
                    except Exception:
                        pass
                    try:
                        self.client.close_request(old_key)
                    except Exception:
                        pass
                created = self.client.create_request(category, summary, description, phone, files)
                self.after(0, lambda: self._submit_ok(created))
            except Exception as exc:
                self.after(0, lambda e=str(exc): self._submit_fail(e))

        threading.Thread(target=work, daemon=True).start()

    def _submit_ok(self, created) -> None:
        self.editing = False
        self.edit_changed_at = None
        self._keep_edit_on_hist_close = False
        self._scene_hold = False
        self._set_busy(False, f"Заявка {created.issue_key} создана")
        self.status_label.configure(fg=config.SUCCESS)
        self.last_issue_key = created.issue_key
        self.watch_key = created.issue_key
        self.last_status = ""
        self._hist_shown_key = created.issue_key
        self._start_timer(now_minsk(), created.issue_key)
        self.persist()
        login = self.login_var.get().strip() or "Клиент"
        if self.scene:
            self.scene.stop_replay()
            self.scene.arm(created.issue_key, client_name=login, dest_label="Куда едем")
        self.after(700, self._poll_once)
        self._show_submit_banner(created.issue_key)
        err = str(getattr(created, "attach_error", "") or "")
        if err:
            self.after(400, lambda e=err: messagebox.showwarning(config.APP_NAME, e))

    def _close_submit_banner(self, _event=None) -> None:
        job = self._submit_banner_job
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
            self._submit_banner_job = None
        win = self._submit_banner
        self._submit_banner = None
        if win is None:
            return
        try:
            win.destroy()
        except TclError:
            pass

    def _show_submit_banner(self, key: str) -> None:
        """Корпоративная плашка без кнопки, закрывается через 5 секунд."""
        self._close_submit_banner()
        self.update_idletasks()
        tiny = bool(self.ui.get("tiny"))
        win_w = max(200, int(self.winfo_width() or 800))
        win_h = max(160, int(self.winfo_height() or 600))
        # обычный messagebox ~360×180 → в 2 раза
        w = min(760, max(560, int(win_w * 0.62)))
        h = 300 if not tiny else 230
        if h > win_h - 40:
            h = max(200, win_h - 40)
        family = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"
        win = tk.Toplevel(self)
        self._submit_banner = win
        win.withdraw()
        win.overrideredirect(True)
        win.configure(bg=config.ORANGE)
        try:
            win.transient(self)
            win.attributes("-topmost", True)
        except TclError:
            pass
        card = tk.Frame(win, bg=config.DARK, highlightthickness=0)
        card.pack(fill="both", expand=True, padx=4, pady=4)
        top = tk.Frame(card, bg=config.DARK)
        top.pack(fill="x", padx=28, pady=(22, 8))
        icon = self.photos.load(config.ICON_PNG, (72, 72) if not tiny else (56, 56))
        if icon:
            ic = tk.Label(top, image=icon, bg=config.DARK)
            ic.pack(side="left", padx=(0, 16))
        titles = tk.Frame(top, bg=config.DARK)
        titles.pack(side="left", fill="x", expand=True)
        t1 = tk.Label(
            titles,
            text=config.APP_NAME.upper(),
            fg=config.WHITE,
            bg=config.DARK,
            font=(family, 22 if not tiny else 18, "bold"),
        )
        t1.pack(anchor="w")
        self._bind_csl(t1)
        t2 = tk.Label(
            titles,
            text=config.SLOGAN,
            fg=config.ORANGE,
            bg=config.DARK,
            font=(family, 13 if not tiny else 11, "bold"),
        )
        t2.pack(anchor="w", pady=(2, 0))
        self._bind_csl(t2)
        tk.Frame(card, bg=config.ORANGE, height=4).pack(fill="x", padx=28, pady=(6, 10))
        body = tk.Frame(card, bg=config.DARK)
        body.pack(fill="both", expand=True, padx=28)
        tk.Label(
            body,
            text=f"Заявка {key}",
            fg=config.ORANGE,
            bg=config.DARK,
            font=(family, 32 if not tiny else 24, "bold"),
        ).pack(anchor="w")
        tk.Label(
            body,
            text="Спешим оказывать помощь",
            fg=config.WHITE,
            bg=config.DARK,
            font=(family, 18 if not tiny else 14),
        ).pack(anchor="w", pady=(6, 0))
        bar_host = tk.Frame(card, bg="#2A2A2A", height=8)
        bar_host.pack(fill="x", side="bottom")
        bar_host.pack_propagate(False)
        fill = tk.Frame(bar_host, bg=config.ORANGE, height=8)
        fill.place(relx=0, rely=0, relwidth=1, relheight=1)
        root_x = self.winfo_rootx()
        root_y = self.winfo_rooty()
        x = root_x + max(8, (win_w - w) // 2)
        y = root_y + max(8, (win_h - h) // 3)
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.deiconify()
        win.lift()
        for widget in (win, card, top, titles, body, bar_host):
            widget.bind("<Button-1>", self._close_submit_banner)
        total = 5000
        step = 40
        left = [total]

        def tick() -> None:
            if self._submit_banner is not win:
                return
            left[0] -= step
            frac = max(0.0, left[0] / total)
            try:
                fill.place(relx=0, rely=0, relwidth=frac, relheight=1)
            except TclError:
                return
            if left[0] <= 0:
                self._close_submit_banner()
                return
            self._submit_banner_job = self.after(step, tick)

        self._submit_banner_job = self.after(step, tick)

    def _submit_fail(self, error: str) -> None:
        self._set_busy(False, "Ошибка отправки")
        self.status_label.configure(fg=config.DANGER)
        messagebox.showerror(config.APP_NAME, f"Не удалось отправить заявку.\n\n{error}")

    def edit_ticket(self) -> None:
        if not self.last_issue_key:
            messagebox.showinfo(config.APP_NAME, "Сначала отправьте заявку — потом её можно изменить.")
            return
        self._restore_form(self.last_draft)
        self._begin_local_edit(self.last_issue_key)

    def _begin_local_edit(self, key: str, row: dict | None = None) -> None:
        """Правка только локально. В Jira — после «Отправить заявку»."""
        self.editing = True
        self.last_issue_key = key
        self.watch_key = key
        self.edit_changed_at = now_minsk()
        self.last_status = "Изменено"
        self.timer_changed_at = self.edit_changed_at
        self.timer_stopped_at = None
        self._scene_hold = True
        self._keep_edit_on_hist_close = True
        if self.scene:
            self.scene.stop_replay()
            self.scene.reset_home()
            self.scene.arm(key, client_name=self.login_var.get().strip() or "Клиент", dest_label="Куда едем")
        self._paint_timer()
        stamp = self.edit_changed_at.strftime("%Y-%m-%d %H:%M:%S")
        self.status_var.set(f"{key}: Изменено  ·  {stamp}")
        self.status_label.configure(fg=config.ORANGE)
        try:
            self.persist()
        except Exception:
            pass
        extra = ""
        if row:
            extra = f"\nТема: {row.get('summary') or '—'}"
        messagebox.showinfo(
            config.APP_NAME,
            f"Заявка {key} открыта для правки.\n"
            f"Статус: Изменено\nВремя изменения: {stamp}{extra}\n\n"
            "Правки сохранятся только по кнопке «Отправить заявку».",
        )

    def show_history(self) -> None:
        if not self.client.logged_in:
            messagebox.showwarning(config.APP_NAME, "Сначала выполните вход.")
            return
        win = tk.Toplevel(self)
        win.title("История запросов")
        win.configure(bg=config.WHITE)
        self.update_idletasks()
        hw = min(1180, max(860, self.winfo_width() - 16, 720))
        scene_bottom = self.winfo_rooty() + 80
        if self.scene:
            try:
                scene_bottom = self.scene.winfo_rooty() + self.scene.winfo_height()
            except TclError:
                pass
        screen_h = self.winfo_screenheight()
        top = scene_bottom + 8
        hh = min(480, max(260, screen_h - top - 36))
        if hh < 240:
            top = max(24, screen_h - 340)
            hh = min(320, screen_h - top - 20)
        sx = self.winfo_rootx() + 8
        win.geometry(f"{hw}x{hh}+{sx}+{top}")
        try:
            win.transient(self)
        except TclError:
            pass
        stats = tk.Label(win, text="Загрузка…", bg=config.WHITE, fg=config.DARK2, font=self.font_ui_b, pady=6)
        stats.pack(fill="x")
        hint = tk.Label(
            win,
            text="Клик — анимация заявки. Двойной клик — правка (статус «Изменено»). Сохранение — только «Отправить заявку».",
            bg=config.WHITE,
            fg=config.MUTED,
            font=self.font_small,
        )
        hint.pack(fill="x", padx=10)
        cols = ("key", "created", "closed", "status", "type", "summary", "description")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=12)
        heads = {
            "key": "Номер",
            "created": "Создана",
            "closed": "Закрыта",
            "status": "Статус",
            "type": "Тип",
            "summary": "Тема",
            "description": "Описание",
        }
        widths = {"key": 100, "created": 140, "closed": 140, "status": 110, "type": 160, "summary": 220, "description": 280}
        for c in cols:
            tree.heading(c, text=heads[c])
            tree.column(c, width=widths[c], stretch=True)
        tree.pack(fill="both", expand=True, padx=10, pady=6)
        btns = tk.Frame(win, bg=config.WHITE)
        btns.pack(fill="x", padx=10, pady=8)
        rows_holder: list[dict] = []

        def _short(text: str, n: int = 120) -> str:
            blob = " ".join((text or "").split())
            return blob if len(blob) <= n else blob[: n - 1] + "…"

        def fill(rows):
            rows_holder.clear()
            rows_holder.extend(rows)
            for item in tree.get_children():
                tree.delete(item)
            open_n = prog = closed = 0
            for row in rows:
                iid = tree.insert(
                    "",
                    "end",
                    values=(
                        row.get("key") or "",
                        (row.get("created") or "")[:19],
                        (row.get("closed") or "")[:19],
                        row.get("status") or "",
                        row.get("type") or "",
                        _short(row.get("summary") or "", 80),
                        _short(row.get("description") or "", 140),
                    ),
                )
                st = row.get("status") or ""
                if JiraClient.is_closed(st) or JiraClient.is_paused(st):
                    closed += 1
                elif JiraClient.is_in_progress(st):
                    prog += 1
                else:
                    open_n += 1
            stats.configure(text=f"Всего: {len(rows)}   ·   открыто: {open_n}   ·   в работе: {prog}   ·   закрыто: {closed}")

        def current_row() -> dict | None:
            sel = tree.selection()
            if not sel:
                return None
            key = tree.item(sel[0], "values")[0]
            return next((r for r in rows_holder if r.get("key") == key), None)

        def play_selected(_event=None):
            match = current_row()
            if not match:
                return
            key = match.get("key") or ""
            if key == self._hist_shown_key and self.scene and (
                getattr(self.scene, "replay", False) or self.scene.state != HOME
            ):
                return
            self._scene_hold = False
            self._hist_shown_key = key
            self._show_ticket_scene(match)

        def on_click(_event=None):
            if self._hist_click_job:
                try:
                    self.after_cancel(self._hist_click_job)
                except Exception:
                    pass
            self._hist_click_job = self.after(280, play_selected)

        def on_open(_event=None):
            if self._hist_click_job:
                try:
                    self.after_cancel(self._hist_click_job)
                except Exception:
                    pass
                self._hist_click_job = None
            match = current_row()
            if not match:
                return
            key = match.get("key") or ""
            draft = self._draft_from_history(match)
            self.last_draft = draft
            self._restore_form(draft)
            self._begin_local_edit(key, match)
            try:
                win.destroy()
            except TclError:
                pass

        def on_hist_close():
            if self._hist_click_job:
                try:
                    self.after_cancel(self._hist_click_job)
                except Exception:
                    pass
                self._hist_click_job = None
            keep = self._keep_edit_on_hist_close
            try:
                win.destroy()
            except TclError:
                pass
            if not keep:
                self._reset_ready_ui()

        tree.bind("<ButtonRelease-1>", on_click)
        tree.bind("<Double-1>", on_open)
        win.protocol("WM_DELETE_WINDOW", on_hist_close)

        def load():
            try:
                data = self.client.list_requests(80)
                self.after(0, lambda: fill(data))
            except Exception as exc:
                self.after(0, lambda e=str(exc): messagebox.showerror(config.APP_NAME, e))

        def export():
            if not rows_holder:
                messagebox.showinfo(config.APP_NAME, "Нет данных для экспорта.")
                return
            path = filedialog.asksaveasfilename(
                parent=win,
                defaultextension=".xlsx",
                filetypes=[("Excel", "*.xlsx")],
                initialfile="CSL_istoria_zayavok.xlsx",
            )
            if not path:
                return
            try:
                from openpyxl import Workbook

                wb = Workbook()
                ws = wb.active
                ws.title = "Заявки"
                ws.append(["Номер", "Создана", "Закрыта", "Статус", "Тип", "Тема", "Описание"])
                for row in rows_holder:
                    ws.append(
                        [
                            row.get("key") or "",
                            row.get("created") or "",
                            row.get("closed") or "",
                            row.get("status") or "",
                            row.get("type") or "",
                            row.get("summary") or "",
                            row.get("description") or "",
                        ]
                    )
                wb.save(path)
                messagebox.showinfo(config.APP_NAME, f"Сохранено: {path}")
            except Exception as exc:
                messagebox.showerror(config.APP_NAME, f"Не удалось сохранить Excel.\n{exc}")

        OrangeButton(btns, "Экспорт в Excel", command=export).pack(side="left")
        threading.Thread(target=load, daemon=True).start()

    def _tick_timer(self) -> None:
        self._paint_timer()
        self.after(250, self._tick_timer)

    def _aware(self, moment: datetime | None) -> datetime | None:
        if moment is None:
            return None
        if moment.tzinfo is None:
            return moment.replace(tzinfo=MINSK)
        return moment

    def _elapsed_text(self, start: datetime | None, end: datetime | None) -> str:
        if not start:
            return "—"
        start = self._aware(start)
        end = self._aware(end) or now_minsk()
        return format_elapsed((end - start).total_seconds())

    def _times_differ(self, first: datetime | None, second: datetime | None, seconds: float = 15) -> bool:
        a = self._aware(first)
        b = self._aware(second)
        if not a or not b:
            return False
        return abs((a - b).total_seconds()) >= seconds

    def _paint_timer(self) -> None:
        if not self.timer_started_at:
            self.timer_var.set("")
            self.timer_start_var.set("—")
            self.timer_change_var.set("—")
            self.timer_ready_var.set("—")
            if self.timer_start_lbl:
                self.timer_start_lbl.configure(fg="#6B7280")
            if self.timer_change_lbl:
                self.timer_change_lbl.configure(fg="#6B7280")
            if self.timer_ready_lbl:
                self.timer_ready_lbl.configure(fg="#6B7280")
            return
        self.timer_start_var.set(format_clock(self.timer_started_at))
        self.timer_change_var.set(format_clock(self.timer_changed_at))
        self.timer_ready_var.set(format_clock(self.timer_stopped_at))
        self.timer_var.set(self.timer_start_var.get())
        done = bool(self.timer_stopped_at)
        if self.timer_start_lbl:
            self.timer_start_lbl.configure(fg=config.SUCCESS if done else config.ORANGE)
        if self.timer_change_lbl:
            self.timer_change_lbl.configure(fg=config.CYAN if self.timer_changed_at else "#6B7280")
        if self.timer_ready_lbl:
            self.timer_ready_lbl.configure(fg=config.SUCCESS if done else "#6B7280")

    def _start_timer(self, started: datetime | None = None, key: str = "") -> None:
        if key:
            self.watch_key = key
        moment = started or now_minsk()
        self.timer_started_at = moment
        self.timer_changed_at = None
        self.timer_stopped_at = None
        self.last_status = ""
        self._paint_timer()

    def _note_status_change(self, status: str, changed: datetime | None = None) -> None:
        status = (status or "").strip()
        if not status:
            return
        prev = (self.last_status or "").strip()
        if not prev:
            self.last_status = status
            if self._times_differ(changed, self.timer_started_at) and not JiraClient.is_closed(status):
                self.timer_changed_at = changed
            self._paint_timer()
            return
        if prev.lower() == status.lower():
            return
        if JiraClient.is_closed(status):
            self.last_status = status
            self._paint_timer()
            return
        self.timer_changed_at = changed or now_minsk()
        self.last_status = status
        self._paint_timer()

    def _stop_timer(self, stopped: datetime | None = None) -> None:
        if not self.timer_started_at:
            return
        if self.timer_stopped_at:
            return
        moment = stopped or now_minsk()
        if moment < self.timer_started_at:
            moment = self.timer_started_at
        self.timer_stopped_at = moment
        self._paint_timer()
        try:
            self.persist()
        except Exception:
            pass

    def _bind_timer_to_ticket(
        self,
        key: str,
        created: datetime | None,
        closed: datetime | None,
        status: str,
        changed: datetime | None = None,
    ) -> None:
        self.watch_key = key
        self.timer_started_at = created or self.timer_started_at or now_minsk()
        real_change = self._times_differ(changed, created)
        if JiraClient.is_closed(status):
            self.timer_stopped_at = closed or now_minsk()
            if self.timer_stopped_at < self.timer_started_at:
                self.timer_stopped_at = self.timer_started_at
            if real_change and self._times_differ(changed, self.timer_stopped_at):
                self.timer_changed_at = changed
            else:
                self.timer_changed_at = None
        else:
            self.timer_stopped_at = None
            self.timer_changed_at = changed if real_change else None
        self.last_status = status or ""
        self._paint_timer()

    def _show_ticket_scene(self, row: dict) -> None:
        key = (row.get("key") or "").strip()
        status = row.get("status") or ""
        if not key or not self.scene:
            return
        created = parse_when(row.get("created"))
        closed = parse_when(row.get("closed"))
        changed = parse_when(row.get("status_changed"))
        login = self.login_var.get().strip() or self.scene.client_name or "Клиент"
        already = (
            key == self.watch_key
            and key == (self.scene.issue_key or "")
            and not getattr(self.scene, "replay", False)
            and self.scene.state != HOME
        )
        self._bind_timer_to_ticket(key, created, closed, status, changed)
        if JiraClient.is_closed(status):
            self.scene.play_replay(key, client_name=login, dest_label="Куда едем", speed=8)
            return
        if already:
            return
        self.scene.stop_replay()
        self.scene.arm(key, client_name=login, dest_label="Куда едем")
        self._apply_ticket_info(
            {
                "key": key,
                "status": status,
                "created": row.get("created") or "",
                "closed": row.get("closed") or "",
                "status_changed": row.get("status_changed") or "",
            },
            from_poll=False,
        )

    def _resume_ticket(self) -> None:
        key = self.watch_key or self.last_issue_key
        if not key or not self.client.logged_in:
            return

        def work() -> None:
            try:
                info = self.client.get_request_info(key)
            except Exception:
                info = {"key": key, "status": "", "created": "", "closed": ""}
            self.after(0, lambda: self._resume_ticket_info(info))

        threading.Thread(target=work, daemon=True).start()

    def _resume_ticket_info(self, info: dict) -> None:
        key = (info.get("key") or "").strip()
        if not key:
            return
        self.watch_key = key
        created = parse_when(info.get("created"))
        closed = parse_when(info.get("closed"))
        changed = parse_when(info.get("status_changed"))
        status = info.get("status") or ""
        if created and not self.timer_started_at:
            self.timer_started_at = created
        self._note_status_change(status, changed)
        if JiraClient.is_closed(status):
            if not self.timer_stopped_at:
                self._stop_timer(closed)
        else:
            self.timer_stopped_at = None
        self._paint_timer()
        if self.scene:
            self.scene.arm(key, client_name=self.login_var.get().strip() or "Клиент", dest_label="Куда едем")
        self._apply_ticket_info(info, from_poll=True)
        try:
            self.persist()
        except Exception:
            pass

    def _poll_once(self) -> None:
        key = self.watch_key or self.last_issue_key
        if not self.client.logged_in or not key:
            return

        def work():
            try:
                info = self.client.get_request_info(key)
            except Exception:
                info = {"key": key, "status": "", "created": "", "closed": ""}
            self.after(0, lambda: self._apply_ticket_info(info, from_poll=True))

        threading.Thread(target=work, daemon=True).start()

    def _poll_ticket(self) -> None:
        self._poll_once()
        self.after(6000, self._poll_ticket)

    def _apply_ticket_status(self, key: str, status: str) -> None:
        self._apply_ticket_info({"key": key, "status": status, "created": "", "closed": ""}, from_poll=True)

    def _apply_ticket_info(self, info: dict, from_poll: bool = False) -> None:
        key = (info.get("key") or "").strip()
        status = info.get("status") or ""
        if not key or not self.scene:
            return
        if from_poll and key not in {self.watch_key, self.last_issue_key}:
            return
        if from_poll and self._scene_hold:
            created = parse_when(info.get("created"))
            closed = parse_when(info.get("closed"))
            changed = parse_when(info.get("status_changed"))
            if created and not self.timer_started_at:
                self.timer_started_at = created
            if not self.editing:
                self._note_status_change(status, changed)
                if JiraClient.is_closed(status):
                    self._stop_timer(closed)
            self._paint_timer()
            return
        if getattr(self.scene, "replay", False):
            if JiraClient.is_closed(status) and key == self.watch_key:
                created = parse_when(info.get("created"))
                closed = parse_when(info.get("closed"))
                if created and not self.timer_started_at:
                    self.timer_started_at = created
                if not self.timer_stopped_at:
                    self._stop_timer(closed)
            return
        if key == self.watch_key or key == self.last_issue_key:
            created = parse_when(info.get("created"))
            closed = parse_when(info.get("closed"))
            changed = parse_when(info.get("status_changed"))
            if created and not self.timer_started_at:
                self.timer_started_at = created
            self._note_status_change(status, changed)
            if JiraClient.is_closed(status):
                self._stop_timer(closed)
            elif self.timer_started_at and not from_poll:
                self.timer_stopped_at = None
            self._paint_timer()
        if JiraClient.should_return(status):
            if self.scene.state not in {RETURN, WALK_IN, HOME}:
                self.scene.play_return(key)
        elif JiraClient.is_in_progress(status):
            if self.scene.state == HOME:
                login = self.login_var.get().strip() or self.scene.client_name
                self.scene.play_depart(key, client_name=login, dest_label="Куда едем")
            else:
                self.scene.play_onsite(key)

    def _toggle_autostart(self) -> None:
        want = bool(self._autostart_var.get())
        if want and not install_win.is_installed() and not install_win.already_on_disk():
            if not messagebox.askyesno(
                config.APP_NAME,
                "Чтобы добавить программу в автозагрузку, сначала установите её на этот компьютер.",
            ):
                self._autostart_var.set(False)
                return
            self.install_now()
            self._autostart_var.set(install_win.is_autostart())
            return
        try:
            install_win.set_autostart(want)
        except Exception as exc:
            messagebox.showerror(config.APP_NAME, f"Не удалось изменить автозагрузку.\n{exc}")
            self._autostart_var.set(install_win.is_autostart())

    def install_now(self) -> None:
        if not install_win.is_windows():
            messagebox.showinfo(config.APP_NAME, "Установка рассчитана на Windows.")
            return
        try:
            dest = install_win.install(desktop=True, start_menu=True, autostart=True)
        except Exception as exc:
            messagebox.showerror(config.APP_NAME, f"Не удалось установить.\n{exc}")
            return
        self._autostart_var.set(True)
        messagebox.showinfo(
            config.APP_NAME,
            f"Help CSL установлен.\n{dest}\n\nДобавлен в автозагрузку Windows.",
        )

    def uninstall_now(self) -> None:
        if not messagebox.askyesno(
            config.APP_NAME,
            "Удалить Help CSL с этого компьютера?\n"
            "Ярлыки и автозагрузка будут сняты. Сохранённый логин не трогаем.",
        ):
            return
        try:
            install_win.uninstall()
        except Exception as exc:
            messagebox.showerror(config.APP_NAME, f"Не удалось удалить.\n{exc}")
            return
        if install_win.is_installed():
            self.destroy()
            return
        self._autostart_var.set(False)
        messagebox.showinfo(config.APP_NAME, "Программа удалена с компьютера.")

    def service_exit(self) -> None:
        if not messagebox.askyesno(
            config.APP_NAME, "Выйти из учётки? Логин и пароль будут удалены, поля входа появятся снова."
        ):
            return
        storage.wipe_profile()
        self.login_var.set("")
        self.password_var.set("")
        self.phone_var.set("+375")
        self.anydesk_var.set("")
        self.rustdesk_var.set("")
        self.last_issue_key = ""
        self.last_draft = {}
        self.watch_key = ""
        self.last_status = ""
        self.timer_started_at = None
        self.timer_changed_at = None
        self.timer_stopped_at = None
        self._hist_shown_key = ""
        self._paint_timer()
        self.client = JiraClient()
        self._set_cred_visible(True)
        self._refresh_remote_ids()
        self.status_var.set("Выполнен выход")
        if self.scene:
            self.scene.stop_replay()
            self.scene.reset_home()

    def _on_close(self) -> None:
        try:
            if self.login_var.get().strip() or self.password_var.get():
                self.persist()
        except Exception:
            pass
        self.destroy()

    def show_contacts(self) -> None:
        messagebox.showinfo(
            "Контакты CSL",
            f"{config.COMPANY_LEGAL}\n{config.ADDRESS}\n\n"
            f"{config.CONTACT_PHONE_DISPLAY}\n{config.SITE_URL}\n{config.EMAIL}\n{config.JIRA_BASE}\n\n"
            f"Заявки: {hours_label()}, пн–пт.",
        )

    def preview_trip(self) -> None:
        if not self.scene:
            return
        login = (self.login_var.get() or "Клиент").strip()[:18]
        self.scene.play_depart("C1-DEMO", client_name=login, dest_label="Куда едем")

        def maybe_return() -> None:
            if not self.scene:
                return
            st = self.scene.state
            if st in {HOME, RETURN, WALK_IN}:
                return
            if st == "work":
                self.scene.play_return("C1-DEMO")
                return
            self.after(400, maybe_return)

        self.after(400, maybe_return)

    def preview_replay(self) -> None:
        if not self.scene:
            return
        login = (self.login_var.get() or "Клиент").strip()[:18]
        self.scene.play_replay("C1-DEMO", client_name=login, dest_label="Куда едем", speed=8)

    def preview_holiday(self) -> None:
        if self.scene:
            self.scene.set_holiday(True)
        messagebox.showinfo(
            config.APP_NAME,
            "Новогодняя сцена: зимний лес, Дед Мороз и олени.\n"
            "По календарю она сама включается с 25 декабря по 14 января.\n"
            "Вернуть обычный вид: Справка → Обычная сцена.",
        )

    def preview_normal(self) -> None:
        if self.scene:
            self.scene.set_holiday(False)

    def show_about(self) -> None:
        extra = ""
        if install_win.is_installed():
            extra = f"\nУстановлен: {install_win.install_dir()}"
        if install_win.is_autostart():
            extra += "\nАвтозагрузка: включена"
        messagebox.showinfo(
            f"О программе {config.APP_NAME}",
            f"{config.APP_NAME}  v{config.VERSION}\n{config.SLOGAN}\n\n"
            f"Сервисный запрос → {config.JIRA_BASE}\nРазработчик: {config.DEVELOPER}"
            f"{extra}",
        )


def main() -> None:
    if not os_supported():
        open_unsupported_portal()
        return
    if install_win.bootstrap() != "run":
        return
    enable_dpi()
    app = DoctorApp()
    app.lift()
    app.focus_force()
    app.mainloop()


if __name__ == "__main__":
    main()
