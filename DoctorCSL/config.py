# -*- coding: utf-8 -*-
"""Конфигурация Help CSL. Версия меняется только здесь и в VERSION / CHANGELOG."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote

# --- Нумерация версий (semver) ---
# MAJOR.MINOR.PATCH
#   PATCH — исправления (1.0.1)
#   MINOR — новые функции без ломки (1.1.0)
#   MAJOR — несовместимые изменения (2.0.0)
VERSION = "1.11.17"
VERSION_DATE = "2026-08-28"
APP_NAME = "Help CSL"
APP_NAME_EN = "HelpCSL"
PRODUCT_CODE = "CSL.Help"
SLOGAN = "Help CSL уже в пути"
DEVELOPER = "CSL"
COMPANY_LEGAL = "ООО «Компьютерная безопасность»"
COPYRIGHT = "© 2026 CSL"

SITE_URL = "https://csl.by"
JIRA_BASE = "https://h.csl.by"
JIRA_PORTAL = "https://h.csl.by/servicedesk/customer/portals"
# https://h.csl.by/servicedesk/customer/portal/1/create/8
JIRA_DESK_ID = "1"
JIRA_PC_REQUEST_TYPE_ID = "8"
JIRA_PC_TYPE_NAME = "Проблемы с ПК/Ноутбуком"
JIRA_PURCHASE_DESK_ID = "1"
JIRA_PURCHASE_REQUEST_TYPE_ID = ""  # пусто — найти по имени «Закупки»
JIRA_PURCHASE_TYPE_NAME = "Закупки"
EMAIL = "info@csl.by"
ADDRESS = "г. Минск, ул. Фабрициуса, 9"
MAPS_URL = "https://www.google.com/maps/search/?api=1&query=" + quote(ADDRESS)

# Основной контакт, как задано для программы
CONTACT_PHONE = "+375293761095"
CONTACT_PHONE_DISPLAY = "+375 29 376-10-95"
SITE_PHONES = ("+375293371412", "+375296713822")

# RustDesk CSL (самостоятельный сервер, постоянный пароль для входа специалиста)
RUSTDESK_SERVER = "37.17.55.196"
RUSTDESK_KEY = "bc+xgHwBWvRyd7lzm6+gN7CScXyOlbCpnoJbfMjKRL8="
RUSTDESK_PASSWORD = "Turbo2*(+"
# Jira подсвечивает только http(s). Пусто — встроенная https-страница запуска.
# Можно указать свою, например https://csl.by/connect.html
CONNECT_LAUNCHER_URL = ""

# Время подачи заявок
WORK_FROM = (9, 0)
WORK_TO = (17, 30)
WORK_DAYS = (0, 1, 2, 3, 4)  # пн–пт, плюс календарь праздников РБ
TIMEZONE = "Europe/Minsk"

# Фирменные цвета csl.by
ORANGE = "#F7631B"
ORANGE_HOVER = "#DE5510"
ORANGE_SOFT = "#FFF1E8"
DARK = "#1A1A1A"
DARK2 = "#222222"
NAVY = "#04091E"
BG = "#F3F4F6"
WHITE = "#FFFFFF"
CARD = "#FFFFFF"
TEXT = "#222222"
MUTED = "#6B7280"
LINE = "#E5E7EB"
SUCCESS = "#159756"
DANGER = "#F44A40"
CYAN = "#4CD3E3"
TAB_IDLE = "#2A2A2A"

USER_AGENT = f"HelpCSL/{VERSION} (CSL Service Desk Client)"

def _base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


BASE_DIR = _base_dir()
ASSETS_DIR = BASE_DIR / "assets"
ICON_ICO = ASSETS_DIR / "icon.ico"
ICON_PNG = ASSETS_DIR / "icon.png"
CITY_PNG = ASSETS_DIR / "city.jpg"
WINTER_JPG = ASSETS_DIR / "winter.jpg"
SANTA_PNG = ASSETS_DIR / "santa.png"
SLEIGH_PNG = ASSETS_DIR / "sleigh.png"
AMBULANCE_PNG = ASSETS_DIR / "ambulance_off.png"
AMBULANCE_OFF_PNG = ASSETS_DIR / "ambulance_off.png"
TOWER_PNG = ASSETS_DIR / "tower.png"
AGENT_PNG = ASSETS_DIR / "agent.png"

# Сопоставление вкладок с типами заявок Jira Service Desk (по названию)
TYPE_KEYWORDS = {
    "computer": (
        "компьютер",
        "computer",
        "пк",
        "рабочее место",
        "инцидент",
        "incident",
        "it support",
        "поломк",
        "неисправ",
    ),
    "printer": (
        "принтер",
        "printer",
        "печать",
        "мфу",
        "картридж",
        "сканер",
        "оргтехник",
    ),
    "purchase": (
        "закуп",
        "purchase",
        "procur",
        "снабж",
        "тмц",
        "приобрет",
        "сервисн",
    ),
}

COMPUTER_INCIDENTS = [
    ("pc_power", "Не включается компьютер"),
    ("pc_boot", "Не загружается Windows / чёрный экран"),
    ("pc_bsod", "Синий экран (BSOD) или критическая ошибка"),
    ("pc_slow", "Компьютер зависает или работает очень медленно"),
    ("pc_net", "Нет сети или интернета"),
    ("pc_mail", "Не работает электронная почта"),
    ("pc_app", "Не запускается нужная программа"),
    ("pc_login", "Не могу войти в учётную запись / сброс пароля"),
    ("pc_virus", "Подозрение на вирус или подозрительная активность"),
    ("pc_periph", "Не работает клавиатура, мышь или монитор"),
    ("pc_audio", "Нет звука / не работает гарнитура"),
    ("pc_share", "Нет доступа к сетевой папке или ресурсу"),
    ("pc_install", "Требуется установка программы"),
    ("pc_license", "Нужна легальная активация Windows / Office (лицензия)"),
]

USER_SERVICES = [
    ("mail", "Почта"),
    ("zoom", "Zoom"),
    ("remote", "Удаленный доступ"),
    ("vpn", "VPN"),
]

PRINTER_INCIDENTS = [
    ("pr_noprint", "Принтер не печатает"),
    ("pr_jam", "Замятие бумаги"),
    ("pr_quality", "Полосы, бледная или некачественная печать"),
    ("pr_toner", "Закончился тонер / картридж, нужна заправка"),
    ("pr_missing", "Принтер не виден на компьютере"),
    ("pr_offline", "Принтер офлайн или ошибка подключения"),
    ("pr_blank", "Печатает пустые листы"),
    ("pr_scan", "Не работает сканер / МФУ"),
    ("pr_replace", "Нужна замена картриджа"),
    ("pr_network", "Сетевой принтер недоступен"),
]
