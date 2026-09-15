# -*- coding: utf-8 -*-
"""Браузерная версия Help CSL: UI + прокси к Jira Service Desk."""

from __future__ import annotations

import io
import platform
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory, session

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from calendar_by import holiday_title, is_belarus_workday  # noqa: E402
from jira_client import (  # noqa: E402
    JiraClient,
    JiraError,
    is_valid_phone,
    normalize_phone,
    workstation_info,
)

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
ASSETS_DIR = ROOT / "assets"
MINSK = timezone(timedelta(hours=3))

app = Flask(
    __name__,
    static_folder=str(STATIC_DIR),
    static_url_path="/static",
)
app.secret_key = "help-csl-web-" + uuid.uuid4().hex
app.config.update(
    SESSION_COOKIE_NAME="helpcsl",
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_HTTPONLY=True,
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)

_LOCK = threading.Lock()
_CLIENTS: dict[str, JiraClient] = {}


def _sid() -> str:
    token = session.get("sid")
    if not token:
        token = uuid.uuid4().hex
        session["sid"] = token
    return token


def _client() -> JiraClient | None:
    with _LOCK:
        return _CLIENTS.get(_sid())


def _put_client(client: JiraClient) -> None:
    with _LOCK:
        _CLIENTS[_sid()] = client


def _drop_client() -> None:
    with _LOCK:
        _CLIENTS.pop(_sid(), None)


def _now() -> datetime:
    return datetime.now(MINSK)


def _hours_label() -> str:
    return (
        f"{config.WORK_FROM[0]:02d}:{config.WORK_FROM[1]:02d}"
        f"–{config.WORK_TO[0]:02d}:{config.WORK_TO[1]:02d}"
    )


def _within_hours(moment: datetime | None = None) -> bool:
    moment = moment or _now()
    if not is_belarus_workday(moment.date()):
        return False
    if moment.weekday() not in config.WORK_DAYS:
        return False
    start = moment.replace(
        hour=config.WORK_FROM[0], minute=config.WORK_FROM[1], second=0, microsecond=0
    )
    end = moment.replace(
        hour=config.WORK_TO[0], minute=config.WORK_TO[1], second=0, microsecond=0
    )
    return start <= moment <= end


def _err(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


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


def _catalog(kind: str) -> list[tuple[str, str]]:
    if kind == "computer":
        return list(config.COMPUTER_INCIDENTS)
    if kind == "printer":
        return list(config.PRINTER_INCIDENTS)
    if kind == "users":
        return list(config.USER_SERVICES)
    return []


def _selected(mapping: dict, catalog: list[tuple[str, str]]) -> list[str]:
    titles = {k: t for k, t in catalog}
    return [titles[k] for k, on in (mapping or {}).items() if on and k in titles]


def _remote_lines(anydesk: str, rustdesk: str) -> list[str]:
    try:
        from rustdesk_setup import ticket_remote_lines

        return ticket_remote_lines(anydesk, rustdesk)
    except Exception:
        return [
            "Удалённый доступ:",
            f"• AnyDesk ID: {anydesk or 'не найден'}",
            f"• RustDesk ID: {rustdesk or 'не найден'}",
            "",
        ]


def _workstation() -> dict[str, str]:
    ua = (request.headers.get("User-Agent") or "")[:180]
    client_ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
    info = workstation_info()
    info["computer"] = info.get("computer") or "браузер"
    info["os"] = info.get("os") or ua or f"{platform.system()} {platform.release()}"
    if client_ip and client_ip not in {"127.0.0.1", "::1"}:
        if not info.get("ip_external") or info.get("ip_external") == "не определён":
            info["ip_external"] = client_ip
    return info


def compose(data: dict) -> tuple[str, str, str]:
    phone = normalize_phone(data.get("phone") or "")
    login = (data.get("login") or "").strip()
    anydesk = (data.get("anydesk") or "").strip()
    rustdesk = (data.get("rustdesk") or "").strip()
    tab = data.get("tab") or "computer"
    ws = _workstation()

    if tab == "computer":
        chosen = _selected(data.get("computer") or {}, config.COMPUTER_INCIDENTS)
        extra = (data.get("computer_text") or "").strip()
        if not chosen and not extra:
            raise JiraError("Отметьте инцидент или опишите проблему.")
        summary = f"[Компьютер] {', '.join(chosen) if chosen else extra.splitlines()[0]}"[:254]
        body = ["Категория: Компьютер", "Тип: Проблемы с ПК/Ноутбуком", ""]
        if chosen:
            body += ["Типовые инциденты:"] + [f"• {x}" for x in chosen] + [""]
        if extra:
            body += ["Описание пользователя:", extra, ""]
    elif tab == "printer":
        chosen = _selected(data.get("printer") or {}, config.PRINTER_INCIDENTS)
        extra = (data.get("printer_text") or "").strip()
        if not chosen and not extra:
            raise JiraError("Отметьте инцидент с принтером или опишите проблему.")
        summary = f"[Принтеры] {', '.join(chosen) if chosen else extra.splitlines()[0]}"[:254]
        body = ["Категория: Принтеры", "Тип: Проблемы с ПК/Ноутбуком", ""]
        if chosen:
            body += ["Типовые инциденты:"] + [f"• {x}" for x in chosen] + [""]
        if extra:
            body += ["Описание пользователя:", extra, ""]
    elif tab == "users":
        last = (data.get("user_last") or "").strip()
        first = (data.get("user_first") or "").strip()
        middle = (data.get("user_middle") or "").strip()
        ulogin = (data.get("user_login") or "").strip() or make_user_login(first, last)
        if not last or not first:
            raise JiraError("Укажите фамилию и имя.")
        if not ulogin:
            raise JiraError("Не удалось сформировать логин. Проверьте фамилию и имя.")
        action = data.get("user_action") or "create"
        action_ru = "Создание" if action == "create" else "Удаление"
        services = _selected(data.get("user_services") or {}, config.USER_SERVICES)
        extra = (data.get("user_text") or "").strip()
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
    else:
        extra = (data.get("purchase_text") or "").strip()
        if not extra:
            raise JiraError("Опишите пожелания по закупке.")
        summary = f"[Закупки] {extra.splitlines()[0]}"[:254]
        body = ["Категория: Закупки", "Тип: Закупки", "", "Пожелания:", extra, ""]

    body += _remote_lines(anydesk, rustdesk)
    body += [
        "Контактные данные:",
        f"• Логин портала: {login}",
        f"• Мобильный: {phone}",
        "",
        "Служебная информация:",
        f"• Компьютер: {ws.get('computer')}",
        f"• Пользователь ОС: {ws.get('os_user')}",
        f"• ОС: {ws.get('os')}",
        f"• IP: {ws.get('ip')}",
        f"• Клиент: {config.APP_NAME} {config.VERSION} (web)",
    ]
    return tab, summary, "\n".join(body)


@app.after_request
def _headers(resp):
    resp.headers.pop("X-Frame-Options", None)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/assets/<path:name>")
def assets(name: str):
    return send_from_directory(ASSETS_DIR, name)


def _web_zip() -> Path | None:
    for path in (
        Path("/home/user/HelpCSL-web.zip"),
        ROOT / "HelpCSL-web.zip",
        WEB_DIR / "HelpCSL-web.zip",
    ):
        if path.is_file():
            return path
    return None


@app.get("/download/HelpCSL-web.zip")
def download_web_zip():
    path = _web_zip()
    if path is None:
        return _err("Архив веб-версии пока недоступен.", 404)
    return send_file(
        path,
        as_attachment=True,
        download_name="HelpCSL-web.zip",
        mimetype="application/zip",
    )


@app.get("/api/meta")
def api_meta():
    now = _now()
    feast = holiday_title(now.date())
    month_day = (now.month, now.day)
    holiday_scene = month_day >= (12, 25) or month_day <= (1, 14)
    return jsonify(
        {
            "ok": True,
            "version": config.VERSION,
            "app": config.APP_NAME,
            "slogan": config.SLOGAN,
            "site": config.SITE_URL,
            "portal": config.JIRA_PORTAL,
            "jira": config.JIRA_BASE,
            "maps": config.MAPS_URL,
            "address": config.ADDRESS,
            "phone": config.CONTACT_PHONE,
            "phone_display": config.CONTACT_PHONE_DISPLAY,
            "email": config.EMAIL,
            "company": config.COMPANY_LEGAL,
            "hours": _hours_label(),
            "open": _within_hours(now),
            "workday": is_belarus_workday(now.date()),
            "holiday_title": feast,
            "holiday_scene": holiday_scene,
            "now": now.strftime("%H:%M"),
            "computer": [{"id": k, "title": t} for k, t in config.COMPUTER_INCIDENTS],
            "printer": [{"id": k, "title": t} for k, t in config.PRINTER_INCIDENTS],
            "users": [{"id": k, "title": t} for k, t in config.USER_SERVICES],
        }
    )


@app.post("/api/login")
def api_login():
    data = request.get_json(silent=True) or {}
    login = (data.get("login") or "").strip()
    password = data.get("password") or ""
    phone = normalize_phone(data.get("phone") or "")
    if not login or not password:
        return _err("Введите логин и пароль портала.")
    if phone and not is_valid_phone(phone):
        return _err("Укажите мобильный в международном формате, например +375293761095.")
    client = JiraClient()
    try:
        name = client.login(login, password)
        client.discover()
    except JiraError as exc:
        return _err(str(exc), 401 if exc.status == 401 else 400)
    except Exception as exc:
        return _err(f"Не удалось войти в {config.JIRA_BASE}. {exc}", 502)
    _put_client(client)
    session["login"] = login
    session["name"] = name
    desks = ", ".join(d.name for d in client.desks) or "портал"
    return jsonify({"ok": True, "name": name, "login": login, "desks": desks})


@app.post("/api/logout")
def api_logout():
    _drop_client()
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/me")
def api_me():
    client = _client()
    if not client or not client.logged_in:
        return jsonify({"ok": True, "logged_in": False})
    desks = ", ".join(d.name for d in client.desks) or "портал"
    return jsonify(
        {
            "ok": True,
            "logged_in": True,
            "name": session.get("name") or client.display_name,
            "login": session.get("login") or client.username,
            "desks": desks,
        }
    )


@app.post("/api/submit")
def api_submit():
    client = _client()
    if not client or not client.logged_in:
        return _err("Сначала войдите в Service Desk.", 401)
    data = request.get_json(silent=True) or {}
    phone = normalize_phone(data.get("phone") or "")
    if not is_valid_phone(phone):
        return _err("Укажите мобильный в международном формате.")
    data["phone"] = phone
    data["login"] = session.get("login") or client.username
    try:
        tab, summary, description = compose(data)
        old_key = (data.get("close_key") or "").strip()
        if old_key:
            try:
                client.close_request(old_key)
            except Exception:
                pass
        created = client.create_request(tab, summary, description, phone)
    except JiraError as exc:
        return _err(str(exc), 401 if exc.status == 401 else 400)
    except Exception as exc:
        return _err(f"Не удалось отправить заявку. {exc}", 502)
    return jsonify(
        {
            "ok": True,
            "issue_key": created.issue_key,
            "web_url": created.web_url,
            "summary": created.summary,
            "off_hours": not _within_hours(),
        }
    )


@app.get("/api/ticket/<path:key>")
def api_ticket(key: str):
    client = _client()
    if not client or not client.logged_in:
        return _err("Нет сессии.", 401)
    info = client.get_request_info(key)
    status = info.get("status") or ""
    return jsonify(
        {
            "ok": True,
            "key": key,
            "status": status,
            "created": info.get("created") or "",
            "closed": info.get("closed") or "",
            "status_changed": info.get("status_changed") or "",
            "in_progress": JiraClient.is_in_progress(status),
            "should_return": JiraClient.should_return(status),
            "is_closed": JiraClient.is_closed(status),
        }
    )


@app.get("/api/history")
def api_history():
    client = _client()
    if not client or not client.logged_in:
        return _err("Сначала выполните вход.", 401)
    try:
        rows = client.list_requests(80)
    except JiraError as exc:
        return _err(str(exc), 400)
    except Exception as exc:
        return _err(str(exc), 502)
    open_n = prog = closed = 0
    for row in rows:
        st = row.get("status") or ""
        if JiraClient.is_closed(st) or JiraClient.is_paused(st):
            closed += 1
        elif JiraClient.is_in_progress(st):
            prog += 1
        else:
            open_n += 1
    return jsonify(
        {
            "ok": True,
            "rows": rows,
            "total": len(rows),
            "open": open_n,
            "progress": prog,
            "closed": closed,
        }
    )


@app.get("/api/history.xlsx")
def api_history_xlsx():
    client = _client()
    if not client or not client.logged_in:
        return _err("Сначала выполните вход.", 401)
    try:
        from openpyxl import Workbook
    except Exception:
        return _err("Экспорт Excel недоступен.", 500)
    rows = client.list_requests(80)
    wb = Workbook()
    ws = wb.active
    ws.title = "Заявки"
    ws.append(["Номер", "Создана", "Закрыта", "Статус", "Тип", "Тема", "Описание"])
    for row in rows:
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
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    from flask import send_file

    return send_file(
        buf,
        as_attachment=True,
        download_name="CSL_istoria_zayavok.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/api/login-suggest")
def api_login_suggest():
    first = request.args.get("first") or ""
    last = request.args.get("last") or ""
    return jsonify({"ok": True, "login": make_user_login(first, last)})


def main() -> None:
    port = 8080
    print(f"Help CSL web  http://0.0.0.0:{port}/", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
