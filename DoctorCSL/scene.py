# -*- coding: utf-8 -*-
"""Сцена: офис CSL, поездка, вход в здание клиента. 25.12–14.01 — зимний лес и Дед Мороз."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import tkinter as tk
import webbrowser

import config

try:
    from PIL import Image, ImageFilter, ImageOps, ImageTk

    HAS_PIL = True
    try:
        RESAMPLE = Image.Resampling.LANCZOS
    except AttributeError:
        RESAMPLE = Image.LANCZOS
except Exception:
    HAS_PIL = False
    RESAMPLE = None

MINSK = timezone(timedelta(hours=3))

HOME = "home"
WALK_OUT = "walk_out"
DRIVE = "drive"
ARRIVE = "arrive"
WORK = "work"
LEAVE = "leave"
RETURN = "return"
WALK_IN = "walk_in"

_PHASE_TINT = {
    "dawn": ((255, 150, 90), 0.28),
    "day": ((255, 230, 180), 0.08),
    "dusk": ((230, 90, 40), 0.32),
    "night": ((10, 18, 50), 0.42),
}
_HOLIDAY_TINT = {
    "dawn": ((180, 200, 230), 0.08),
    "day": ((210, 226, 240), 0.04),
    "dusk": ((70, 90, 150), 0.08),
    "night": ((8, 16, 42), 0.10),
}


def day_phase(moment=None):
    hour = (moment or datetime.now(MINSK)).hour
    if 5 <= hour < 8:
        return "dawn"
    if 8 <= hour < 17:
        return "day"
    if 17 <= hour < 21:
        return "dusk"
    return "night"


def is_holiday_season(moment=None):
    """С 25 декабря по 14 января включительно."""
    now = moment or datetime.now(MINSK)
    month_day = (now.month, now.day)
    return month_day >= (12, 25) or month_day <= (1, 14)


def _tint(rgb, color, alpha):
    overlay = Image.new("RGB", rgb.size, color)
    return Image.blend(rgb.convert("RGB"), overlay, alpha)


def _is_csl_orange(r, g, b, a):
    return a > 180 and r > 190 and 30 <= g <= 150 and b < 90 and (r - g) > 90


def _is_csl_letter(r, g, b, a):
    return a > 160 and r > 220 and g > 200 and b > 180


def _mirror_keep_csl(image):
    """Разворот влево: кузов зеркальный, CSL читаемый, без шва на борту."""
    try:
        return _mirror_keep_csl_impl(image)
    except Exception:
        return ImageOps.mirror(image)


def _mirror_keep_csl_impl(image):
    flipped = ImageOps.mirror(image)
    w, h = image.size
    if w < 40 or h < 24:
        return flipped
    src = image.load()
    panel_rows = []
    for y in range(int(h * 0.12), min(h, int(h * 0.50))):
        orange_x = [x for x in range(w) if _is_csl_orange(*src[x, y])]
        if len(orange_x) < 12:
            continue
        left, right = min(orange_x), max(orange_x)
        span = right - left
        if span < w * 0.20 or span > w * 0.70:
            continue
        panel_rows.append((y, left, right))
    if not panel_rows:
        return flipped
    letters = []
    for y, left, right in panel_rows:
        inset = max(2, (right - left) // 8)
        for x in range(left + inset, right - inset + 1):
            if _is_csl_letter(*src[x, y]):
                letters.append((x, y))
    if len(letters) < 8:
        return flipped
    xs = [p[0] for p in letters]
    ys = [p[1] for p in letters]
    lx0 = max(0, min(xs) - 2)
    ly0 = max(0, min(ys) - 2)
    lx1 = min(w, max(xs) + 3)
    ly1 = min(h, max(ys) + 3)
    mask = Image.new("L", (w, h), 0)
    mp = mask.load()
    for x, y in letters:
        mp[x, y] = 255
    try:
        mask = mask.filter(ImageFilter.MaxFilter(3))
        mask = mask.filter(ImageFilter.GaussianBlur(0.6))
    except Exception:
        pass
    fp = flipped.load()
    for y, left, right in panel_rows:
        mleft, mright = w - 1 - right, w - 1 - left
        fill = (239, 91, 21, 255)
        for x in range(max(0, mleft), min(w, mright + 1)):
            pix = fp[x, y]
            if _is_csl_orange(*pix):
                fill = pix
                break
        inset = max(2, (right - left) // 8)
        for x in range(mleft + inset, mright - inset + 1):
            if 0 <= x < w:
                r, g, b, a = fp[x, y]
                if _is_csl_letter(r, g, b, a) or (r > 200 and g > 150 and b > 100 and a > 160):
                    fp[x, y] = fill
    dest_x = w - lx1
    if dest_x < 0:
        return flipped
    flipped.paste(image.crop((lx0, ly0, lx1, ly1)), (dest_x, ly0), mask.crop((lx0, ly0, lx1, ly1)))
    return flipped


class CityScene(tk.Canvas):
    def __init__(self, master, width=1040, height=200):
        super().__init__(
            master, width=width, height=height, highlightthickness=0, bd=0, bg="#0B1220"
        )
        self.w = width
        self.h = height
        self.state = HOME
        self.issue_key = ""
        self.client_name = "Клиент"
        self.dest_label = "Куда едем"
        self.city_x = 0.0
        self.car_x = 90.0
        self.agent_x = 28.0
        self.facing = 1
        self.tickn = 0
        self.pending_enter = False
        self.speed = 1.0
        self.replay = False
        self.work_ticks = 0
        self._holiday_force = None
        self.holiday = is_holiday_season()
        self._keep = []
        self._city_base = None
        self._city_phase = ""
        self.city_photo = None
        self.city_w = 800
        self.car_r = self.car_l = None
        self.agent_r = self.agent_l = None
        self.tower = None
        self.car_w = 160
        self.car_h = 58
        self.tower_w = 70
        self.tower_h = 180
        self.agent_w = 28
        self.agent_h = 58
        self._loaded_h = 0
        self._dirty = True
        self._load()
        self.bind("<Configure>", self._on_resize)
        self.bind("<Button-1>", self._on_click)
        self.configure(cursor="hand2")
        self.after(40, self._tick)

    def _photo(self, image):
        photo = ImageTk.PhotoImage(image)
        self._keep.append(photo)
        return photo

    def _bg_path(self):
        if self.holiday:
            winter = getattr(config, "WINTER_JPG", None)
            if winter is not None and winter.exists():
                return winter
        path = config.CITY_PNG
        return path if path.exists() else None

    def _vehicle_path(self):
        if self.holiday:
            sleigh = getattr(config, "SLEIGH_PNG", None)
            if sleigh is not None and sleigh.exists():
                return sleigh
        parked = getattr(config, "AMBULANCE_OFF_PNG", None)
        if parked is not None and parked.exists():
            return parked
        return config.AMBULANCE_PNG if config.AMBULANCE_PNG.exists() else None

    def _agent_path(self):
        if self.holiday:
            santa = getattr(config, "SANTA_PNG", None)
            if santa is not None and santa.exists():
                return santa
        return config.AGENT_PNG if config.AGENT_PNG.exists() else None

    def _load(self):
        if not HAS_PIL:
            return
        if getattr(self, "_holiday_force", None) is None:
            self.holiday = is_holiday_season()
        else:
            self.holiday = bool(self._holiday_force)
        self._keep = []
        self.city_photo = None
        self._city_phase = ""
        fit = max(64, int(self.h) - 2)
        self._loaded_h = self.h
        bg = self._bg_path()
        if bg is not None:
            base = Image.open(bg).convert("RGB")
            base = base.resize(
                (max(720, int(base.width * fit / max(base.height, 1))), fit),
                RESAMPLE,
            )
            self._city_base = base
            self.city_w = base.width
            self._ensure_city(day_phase())
        veh = self._vehicle_path()
        if veh is not None:
            car = Image.open(veh).convert("RGBA")
            # прозрачный конус фар не должен расширять спрайт — иначе свет «оторван»
            box = car.getbbox()
            if box:
                car = car.crop(box)
            if self.holiday:
                car.thumbnail((int(fit * 1.65), int(fit * 0.50)), RESAMPLE)
            else:
                car.thumbnail((int(fit * 1.15), int(fit * 0.42)), RESAMPLE)
            self.car_r = self._photo(car)
            if self.holiday:
                left = ImageOps.mirror(car)
            else:
                left = _mirror_keep_csl(car)
            self.car_l = self._photo(left)
            self.car_w, self.car_h = car.size
        if config.TOWER_PNG.exists():
            tower = Image.open(config.TOWER_PNG).convert("RGBA")
            # до верха сцены (меню «Сервис»): высота = почти вся полоса
            tower.thumbnail((int(fit * 0.72), fit), RESAMPLE)
            self.tower = self._photo(tower)
            self.tower_w, self.tower_h = tower.size
        ag = self._agent_path()
        if ag is not None:
            person = Image.open(ag).convert("RGBA")
            person.thumbnail((int(fit * 0.28), int(fit * 0.48)), RESAMPLE)
            self.agent_r = self._photo(person)
            self.agent_l = self._photo(ImageOps.mirror(person))
            self.agent_w, self.agent_h = person.size
        if self.state == HOME:
            self.car_x = self.tower_w + 8
            self.agent_x = 16.0

    def refit(self, height):
        height = int(height)
        if height < 50:
            return
        if abs(height - self._loaded_h) < 6 and abs(height - self.h) < 2:
            self.h = height
            return
        self.h = height
        self.configure(height=height)
        self._load()
        self._dirty = True

    def _ensure_city(self, phase):
        if not HAS_PIL or self._city_base is None:
            return
        if phase == self._city_phase and self.city_photo is not None:
            return
        table = _HOLIDAY_TINT if self.holiday else _PHASE_TINT
        color, alpha = table.get(phase, table["day"])
        self.city_photo = self._photo(_tint(self._city_base, color, alpha))
        self._city_phase = phase

    def _on_resize(self, event):
        if event.width > 80:
            self.w = event.width
        if event.height > 50:
            if abs(event.height - self._loaded_h) >= 8:
                self.h = event.height
                self._load()
            else:
                self.h = event.height
        self._dirty = True

    def _on_click(self, event):
        ground = self.h - 4
        if 0 <= event.x <= self.tower_w + 10 and ground - self.tower_h - 4 <= event.y <= ground:
            url = getattr(config, "MAPS_URL", "") or (
                "https://www.google.com/maps/search/?api=1&query="
                + quote(getattr(config, "ADDRESS", "Минск, ул. Фабрициуса, 9"))
            )
            webbrowser.open(url)
            return
        webbrowser.open(config.SITE_URL)

    def set_holiday(self, enabled):
        """None — по календарю, True/False — принудительно (предпросмотр)."""
        self._holiday_force = enabled
        self.holiday = is_holiday_season() if enabled is None else bool(enabled)
        self._load()
        self._dirty = True

    def tower_width(self):
        return max(48, int(self.tower_w))

    def _client_x(self):
        return max(self.w - 8 - self._client_w(), self.w * 0.68)

    def _client_w(self):
        return max(120, min(190, int(self._client_h() * 0.78)))

    def _client_h(self):
        target = int(self.tower_h) if self.tower_h else self.h - 8
        return max(70, min(self.h - 6, target))

    def _park_x(self):
        return max(self.tower_w + 24.0, self._client_x() - self.car_w - 8)

    def _door_x(self):
        return self._client_x() + self._client_w() * 0.42

    def _moving(self) -> bool:
        return self.state in {DRIVE, RETURN}

    def arm(self, issue_key="", client_name="", dest_label=""):
        self.issue_key = issue_key
        self.client_name = (client_name or "Клиент").strip()[:18]
        self.dest_label = dest_label or "Куда едем"
        self.pending_enter = False
        self._dirty = True

    def stop_replay(self):
        self.replay = False
        self.speed = 1.0
        self.work_ticks = 0

    def play_replay(self, issue_key="", client_name="", dest_label="", speed=8.0):
        """Ускоренная поездка туда-обратно для закрытой заявки."""
        self.replay = True
        self.speed = max(2.0, min(16.0, float(speed or 8)))
        self.work_ticks = 0
        self.play_depart(issue_key, client_name, dest_label)

    def play_depart(self, issue_key="", client_name="", dest_label=""):
        if not self.replay:
            self.speed = 1.0
            self.work_ticks = 0
        self.issue_key = issue_key or self.issue_key
        if client_name:
            self.client_name = client_name.strip()[:18]
        if dest_label:
            self.dest_label = dest_label
        self.state = WALK_OUT
        self.facing = 1
        self.pending_enter = True
        self.agent_x = 16.0
        self.car_x = self.tower_w + 8
        self._dirty = True

    def play_onsite(self, issue_key=""):
        self.issue_key = issue_key or self.issue_key
        if self.state in {ARRIVE, WORK, LEAVE}:
            return
        if self.state in {WALK_OUT, DRIVE}:
            self.pending_enter = True
            return
        if self.state == HOME:
            self.play_depart(self.issue_key, self.client_name, self.dest_label)
            return
        self.pending_enter = True
        self.state = ARRIVE
        self.facing = 1
        self._dirty = True

    def play_return(self, issue_key=""):
        if self.state in {RETURN, WALK_IN, HOME, LEAVE}:
            return
        self.issue_key = issue_key or self.issue_key
        self.pending_enter = False
        if self.state in {ARRIVE, WORK}:
            inside = self.state == WORK or self.agent_x >= self._door_x() - 1
            self.state = LEAVE
            self.facing = -1
            if inside:
                self.agent_x = self._door_x()
        elif self.state == WALK_OUT:
            self.state = WALK_IN
            self.facing = -1
        else:
            self.state = RETURN
            self.facing = -1
        self._dirty = True

    def reset_home(self):
        self.state = HOME
        self.facing = 1
        self.pending_enter = False
        self.car_x = self.tower_w + 8
        self.agent_x = 16.0
        self._dirty = True

    def _tick(self):
        self.tickn = (self.tickn + 1) % 40
        moved = self.state != HOME
        door = self.tower_w + 8
        park = self._park_x()
        if self.state == WALK_OUT:
            self.facing = 1
            target = door + 6
            self.agent_x = min(target, self.agent_x + 2.4)
            if self.agent_x >= target - 0.5:
                self.state = DRIVE
                self.agent_x = self.car_x + 24
        elif self.state == DRIVE:
            self.facing = 1
            if self.car_x < park - 0.5:
                self.city_x = (self.city_x + 4.0) % max(self.city_w, 1)
                self.car_x = min(park, self.car_x + 3.4)
            else:
                self.car_x = park
                if self.pending_enter:
                    self.state = ARRIVE
                    self.facing = 1
                    self.agent_x = self.car_x + 22
        elif self.state == ARRIVE:
            self.facing = 1
            self.car_x = park
            target = self._door_x()
            if self.agent_x < target:
                self.agent_x = min(target, self.agent_x + 2.8)
            else:
                self.state = WORK
        elif self.state == WORK:
            self.car_x = park
            self.agent_x = self._door_x()
        elif self.state == LEAVE:
            self.facing = -1
            self.car_x = park
            door_car = self.car_x + 18
            if self.agent_x > door_car:
                self.agent_x = max(door_car, self.agent_x - 2.8)
            else:
                self.state = RETURN
                self.facing = -1
        elif self.state == RETURN:
            self.facing = -1
            self.city_x = (self.city_x - 4.0) % max(self.city_w, 1)
            self.car_x = max(door, self.car_x - 3.4)
            self.agent_x = self.car_x + 24
            if self.car_x <= door + 1:
                self.state = WALK_IN
                self.facing = -1
                self.agent_x = door + 6
        elif self.state == WALK_IN:
            self.facing = -1
            self.agent_x = max(14.0, self.agent_x - 2.4)
            if self.agent_x <= 16:
                self.reset_home()
        if moved or self._dirty or self.tickn == 0 or self.holiday:
            self._draw()
            self._dirty = False
        self.after(50 if self.state == HOME else 33, self._tick)

    def _draw_client_building(self, ground):
        x = int(self._client_x())
        bw = int(self._client_w())
        bh = int(self._client_h())
        y0 = ground - bh
        body = "#1E3348" if self.holiday else "#2A3344"
        self.create_rectangle(x, y0, x + bw, ground, fill=body, outline="#F7631B", width=2)
        if self.holiday:
            self.create_polygon(
                x - 4, y0 + 8, x + bw // 2, y0 - 10, x + bw + 4, y0 + 8,
                fill="#E8EEF6", outline="#C5D0DE",
            )
        self.create_rectangle(x + 6, y0 + 8, x + bw - 6, y0 + 44, fill="#F7631B", outline="")
        self.create_text(x + bw // 2, y0 + 18, text="Куда едем", fill="#FFFFFF", font=("Segoe UI", 8, "bold"))
        self.create_text(
            x + bw // 2,
            y0 + 34,
            text=self.client_name or "Клиент",
            fill="#FFF4EA",
            font=("Segoe UI", 8, "bold"),
        )
        rows = max(3, min(6, (bh - 70) // 26))
        cols = 3
        cell_w = max(16, (bw - 28) // cols)
        for r in range(rows):
            for c in range(cols):
                wx = x + 12 + c * cell_w
                wy = y0 + 54 + r * 26
                glow = "#F4C56A" if not self.holiday or (r + c + self.tickn // 8) % 3 else "#7EC8FF"
                self.create_rectangle(wx, wy, wx + cell_w - 8, wy + 14, fill=glow, outline="")
        door_x = x + bw // 2 - 14
        self.create_rectangle(door_x, ground - 32, door_x + 28, ground, fill="#1A1A1A", outline="")

    def _draw_moon(self):
        """Одна луна, не едет вместе с фоном."""
        r = max(10, min(18, self.h // 10))
        cx = max(80, self.w - 70)
        cy = 8 + r
        self.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#E8EEF6", outline="#D5DCE6")

    def _draw_headlights(self, x: int, y: int) -> None:
        """Конус от капота. В новогодней теме не рисуем."""
        if self.holiday:
            return
        beam = max(28, int(self.car_w * 0.34))
        mid = y + int(self.car_h * 0.60)
        spread = max(8, int(self.car_h * 0.16))
        core, halo = "#F6E39A", "#FFF6C8"
        inset = max(4, int(self.car_w * 0.03))
        if self.facing >= 0:
            nose = x + self.car_w - inset
            self.create_polygon(
                nose, mid - 3,
                nose + beam, mid - spread,
                nose + beam + 6, mid + spread + 4,
                nose, mid + 7,
                fill=halo, outline="",
            )
            self.create_polygon(
                nose, mid - 1,
                nose + int(beam * 0.62), mid - spread // 2,
                nose + int(beam * 0.62), mid + spread // 2 + 2,
                nose, mid + 5,
                fill=core, outline="",
            )
        else:
            nose = x + inset
            self.create_polygon(
                nose, mid - 3,
                nose - beam, mid - spread,
                nose - beam - 6, mid + spread + 4,
                nose, mid + 7,
                fill=halo, outline="",
            )
            self.create_polygon(
                nose, mid - 1,
                nose - int(beam * 0.62), mid - spread // 2,
                nose - int(beam * 0.62), mid + spread // 2 + 2,
                nose, mid + 5,
                fill=core, outline="",
            )

    def _draw_snow(self):
        width = max(self.w, 1)
        height = max(self.h, 1)
        for i in range(28):
            sx = (i * 71 + int(self.city_x) * 2 + self.tickn * 3) % width
            sy = (i * 37 + self.tickn * 4) % height
            size = 1 + (i % 3)
            self.create_oval(sx, sy, sx + size, sy + size, fill="#F4F8FC", outline="")

    def _draw(self):
        self.delete("all")
        phase = day_phase()
        self._ensure_city(phase)
        if self.city_photo:
            ox = -int(self.city_x)
            self.create_image(ox, 0, image=self.city_photo, anchor="nw")
            self.create_image(ox + self.city_w, 0, image=self.city_photo, anchor="nw")
        else:
            self.create_rectangle(0, 0, self.w, self.h, fill="#0B1220", outline="")

        ground = self.h - 4
        if self.tower:
            self.create_image(2, ground, image=self.tower, anchor="sw")

        if self.state in {DRIVE, ARRIVE, WORK, LEAVE, RETURN}:
            self._draw_client_building(ground)

        bounce = 1 if self._moving() and (int(self.city_x) // 5) % 2 == 0 else 0
        car_y = ground - self.car_h - bounce
        car_x = int(self.car_x)
        car_img = self.car_r if self.facing >= 0 else self.car_l
        if car_img:
            self.create_image(car_x, car_y, image=car_img, anchor="nw")
        if self._moving():
            self._draw_headlights(car_x, car_y)

        show_agent = self.state in {HOME, WALK_OUT, ARRIVE, LEAVE, WALK_IN}
        img = self.agent_r if self.facing >= 0 else self.agent_l
        if show_agent and img:
            self.create_image(int(self.agent_x), ground - self.agent_h, image=img, anchor="nw")

        if self.holiday:
            self._draw_moon()
            self._draw_snow()
