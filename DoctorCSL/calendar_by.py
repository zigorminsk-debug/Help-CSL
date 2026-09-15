# -*- coding: utf-8 -*-
"""Производственный календарь РБ: праздники + переносы. Обновляется 1 января."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

MONTHS_RU = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

# Известные постановления Совмина (год: [(с_какой_даты_off, на_какую_on), ...])
KNOWN_TRANSFERS = {
    2026: [(date(2026, 4, 20), date(2026, 4, 25))],
}


def orthodox_easter(year: int) -> date:
    """Пасха по юлианскому календарю, дата в григорианском."""
    a = year % 4
    b = year % 7
    c = year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = ((d + e + 114) % 31) + 1
    julian = date(year, month, day)
    offset = 13 if year < 2100 else 14
    if year < 1900:
        offset = 12
    return julian + timedelta(days=offset)


def radunitsa(year: int) -> date:
    return orthodox_easter(year) + timedelta(days=9)


def fixed_holidays(year: int) -> list[tuple[date, str]]:
    days = [
        (date(year, 1, 1), "Новый год"),
        (date(year, 1, 2), "Новый год"),
        (date(year, 1, 7), "Рождество (православное)"),
        (date(year, 3, 8), "День женщин"),
        (radunitsa(year), "Радуница"),
        (date(year, 5, 1), "Праздник труда"),
        (date(year, 5, 9), "День Победы"),
        (date(year, 7, 3), "День Независимости"),
        (date(year, 11, 7), "День Октябрьской революции"),
        (date(year, 12, 25), "Рождество (католическое)"),
    ]
    return days


def _cache_path() -> Path:
    try:
        import storage

        return storage.app_data_dir() / "calendar_by.json"
    except Exception:
        return Path.home() / ".config" / "csl-doctor" / "calendar_by.json"


class BelarusCalendar:
    def __init__(self) -> None:
        self.year = 0
        self.holiday_names: dict[date, str] = {}
        self.extra_off: set[date] = set()
        self.extra_on: set[date] = set()
        self._ensure_year()

    def _ensure_year(self, today: date | None = None) -> None:
        today = today or date.today()
        if self.year == today.year and self.holiday_names:
            return
        self.year = today.year
        self.holiday_names = {d: name for d, name in fixed_holidays(self.year)}
        self.extra_off = set()
        self.extra_on = set()
        for src, dst in KNOWN_TRANSFERS.get(self.year, ()):
            self.extra_off.add(src)
            self.extra_on.add(dst)
        cached = self._load_cache()
        if cached and cached.get("year") == self.year:
            self._apply_cache(cached)

    def refresh_from_web(self) -> None:
        self._ensure_year()
        fetched = self._fetch_transfers(self.year)
        if not fetched:
            self._save_cache()
            return
        self.extra_off = set(fetched["off"])
        self.extra_on = set(fetched["on"])
        self._save_cache()

    def _apply_cache(self, data: dict) -> None:
        def parse_list(key: str) -> set[date]:
            out: set[date] = set()
            for item in data.get(key) or []:
                try:
                    out.add(date.fromisoformat(str(item)[:10]))
                except Exception:
                    pass
            return out

        off = parse_list("extra_off")
        on = parse_list("extra_on")
        if off or on:
            self.extra_off = off
            self.extra_on = on

    def _save_cache(self) -> None:
        path = _cache_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "year": self.year,
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "extra_off": [d.isoformat() for d in sorted(self.extra_off)],
                "extra_on": [d.isoformat() for d in sorted(self.extra_on)],
            }
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_cache(self) -> dict:
        path = _cache_path()
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _fetch_transfers(self, year: int) -> dict | None:
        urls = (
            "https://www.mintrud.gov.by/ru/prazdnichnie-i-vihodnie-dni-ru",
            "https://proraboty.by/proizvodstvennyj-kalendar-na-2026-god/",
        )
        text = ""
        try:
            import requests
        except Exception:
            return None
        for url in urls:
            try:
                resp = requests.get(url, timeout=8, headers={"User-Agent": "HelpCSL/calendar"})
                if resp.status_code == 200 and resp.text:
                    text += "\n" + resp.text
            except Exception:
                continue
        if not text:
            return None
        off: set[date] = set()
        on: set[date] = set()
        blob = re.sub(r"<[^>]+>", " ", text)
        blob = re.sub(r"\s+", " ", blob)
        pattern = re.compile(
            r"(?:с\s+)?(\d{1,2})\s+(" + "|".join(MONTHS_RU) + r")[^.]{0,40}перенос\w*[^.]{0,40}?"
            r"(?:на\s+)?(?:субботу\s+)?(\d{1,2})\s+(" + "|".join(MONTHS_RU) + r")",
            re.I,
        )
        for match in pattern.finditer(blob.lower()):
            d1, m1, d2, m2 = match.groups()
            try:
                src = date(year, MONTHS_RU[m1], int(d1))
                dst = date(year, MONTHS_RU[m2], int(d2))
            except Exception:
                continue
            off.add(src)
            on.add(dst)
        if not off and not on:
            return None
        return {"off": off, "on": on}

    def holiday_name(self, day: date) -> str:
        self._ensure_year(day)
        return self.holiday_names.get(day, "")

    def is_holiday(self, day: date) -> bool:
        self._ensure_year(day)
        return day in self.holiday_names

    def is_workday(self, day: date) -> bool:
        self._ensure_year(day)
        if day in self.extra_on:
            return True
        if day in self.extra_off:
            return False
        if day.weekday() >= 5:
            return False
        return day not in self.holiday_names


_CAL: BelarusCalendar | None = None


def calendar() -> BelarusCalendar:
    global _CAL
    if _CAL is None:
        _CAL = BelarusCalendar()
    _CAL._ensure_year()
    return _CAL


def is_belarus_workday(day: date | None = None) -> bool:
    return calendar().is_workday(day or date.today())


def holiday_title(day: date | None = None) -> str:
    return calendar().holiday_name(day or date.today())
