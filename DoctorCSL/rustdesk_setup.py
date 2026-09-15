# -*- coding: utf-8 -*-
"""Ссылки AnyDesk / RustDesk для заявки. Установка клиента не выполняется."""

from __future__ import annotations

from urllib.parse import quote

import config


def _server() -> str:
    return str(getattr(config, "RUSTDESK_SERVER", "") or "").strip()


def _key() -> str:
    return str(getattr(config, "RUSTDESK_KEY", "") or "").strip()


def _password() -> str:
    return str(getattr(config, "RUSTDESK_PASSWORD", "") or "")


def connect_url(rid: str) -> str:
    """Ссылка с сервером и ключом CSL."""
    rid = "".join(ch for ch in (rid or "") if ch.isdigit())
    if not rid:
        return ""
    server = _server()
    key = quote(_key(), safe="")
    pwd = quote(_password(), safe="")
    if server:
        return f"rustdesk://{rid}@{server}?key={key}&password={pwd}"
    return f"rustdesk://connection/new/{rid}?password={pwd}"


def anydesk_url(aid: str) -> str:
    aid = "".join(ch for ch in (aid or "") if ch.isalnum() or ch in "._@-")
    if not aid:
        return ""
    return f"anydesk:{aid}"


def launcher_page_url(kind: str, ident: str) -> str:
    """Короткая https в одну строку. Jira подсветит. Без TinyURL/da.gd/httpbin."""
    ident = (ident or "").strip()
    if not ident:
        return ""
    if kind == "anydesk":
        ident = "".join(ch for ch in ident if ch.isalnum() or ch in "._@-")
        proto = anydesk_url(ident)
    elif kind == "rustdesk":
        ident = "".join(ch for ch in ident if ch.isdigit())
        proto = connect_url(ident)
    else:
        proto = ""
    if not proto:
        return ""
    custom = str(getattr(config, "CONNECT_LAUNCHER_URL", "") or "").strip()
    if custom:
        sep = "&" if "?" in custom else "?"
        key = "anydesk" if kind == "anydesk" else "rustdesk"
        return f"{custom}{sep}{key}={quote(ident, safe='')}"
    return "https://itty.bitty.site/#/" + proto


def html_connect_anchor(href: str, title: str) -> str:
    return ""


def wiki_connect_link(href: str, title: str) -> str:
    return ""


def https_launch_url(protocol_url: str) -> str:
    proto = (protocol_url or "").strip()
    if proto.startswith("anydesk:"):
        return launcher_page_url("anydesk", proto.split(":", 1)[-1])
    if proto.startswith("rustdesk:"):
        rest = proto.split("://", 1)[-1]
        rid = rest.split("?", 1)[0].split("@", 1)[0].rsplit("/", 1)[-1]
        rid = "".join(ch for ch in rid if ch.isdigit())
        return launcher_page_url("rustdesk", rid)
    return proto


def with_clickable_links(text: str) -> str:
    return text or ""


def ticket_remote_lines(anydesk: str, rustdesk: str) -> list[str]:
    anydesk = (anydesk or "").strip()
    rustdesk = "".join(ch for ch in (rustdesk or "") if ch.isdigit())
    server = _server()
    lines = ["Удалённый доступ — нажмите ссылку, откроется программа:", ""]
    if anydesk:
        href = launcher_page_url("anydesk", anydesk)
        lines.append(f"AnyDesk ID: {anydesk}" + (f"  {href}" if href else ""))
    else:
        lines.append("AnyDesk ID: не найден")
    if rustdesk:
        href = launcher_page_url("rustdesk", rustdesk)
        lines.append(f"RustDesk ID: {rustdesk}" + (f"  {href}" if href else ""))
    else:
        lines.append("RustDesk ID: не найден")
    if server:
        lines.append(f"Сервер RustDesk CSL: {server}")
    lines.append("")
    return lines
