# -*- coding: utf-8 -*-
"""Клиент Jira Service Management (h.csl.by)."""

from __future__ import annotations

import platform
import re
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests

import config


class JiraError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class RequestType:
    id: str
    name: str
    description: str = ""
    service_desk_id: str = ""


@dataclass
class ServiceDesk:
    id: str
    name: str
    project_key: str = ""
    types: list[RequestType] = field(default_factory=list)


@dataclass
class CreatedRequest:
    issue_key: str
    issue_id: str
    web_url: str
    summary: str
    attached: int = 0
    attach_error: str = ""


class JiraClient:
    def __init__(self, base_url: str = config.JIRA_BASE):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": config.USER_AGENT,
                "Accept": "application/json",
                "X-Atlassian-Token": "no-check",
                "X-ExperimentalApi": "opt-in",
            }
        )
        self.session.verify = True
        self.username = ""
        self.display_name = ""
        self.desks: list[ServiceDesk] = []
        self.logged_in = False

    def _url(self, path: str) -> str:
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def login(self, username: str, password: str) -> str:
        username = (username or "").strip()
        if not username or not password:
            raise JiraError("Укажите логин и пароль.")

        last_error = "Не удалось войти."
        if self._login_session(username, password):
            self.username = username
            self.logged_in = True
            self._load_myself()
            return self.display_name or username

        if self._login_portal(username, password):
            self.username = username
            self.logged_in = True
            self._load_myself()
            return self.display_name or username

        raise JiraError(last_error)

    def _login_session(self, username: str, password: str) -> bool:
        try:
            resp = self.session.post(
                self._url("/rest/auth/1/session"),
                json={"username": username, "password": password},
                timeout=25,
            )
        except requests.RequestException:
            return False
        if resp.status_code in (200, 201):
            return True
        return False

    def _login_portal(self, username: str, password: str) -> bool:
        try:
            self.session.get(
                self._url("/servicedesk/customer/user/login?destination=portals"),
                timeout=25,
            )
            token = self.session.cookies.get("atlassian.xsrf.token", "")
            resp = self.session.post(
                self._url("/servicedesk/customer/user/login"),
                data={
                    "os_username": username,
                    "os_password": password,
                    "os_destination": "portals",
                    "os_cookie": "true",
                    "atl_token": token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=25,
                allow_redirects=True,
            )
        except requests.RequestException:
            return False
        if resp.status_code >= 400:
            return False
        # успешный вход: уже не страница логина или есть сессия пользователя
        if "user/login" in (resp.url or "") and "os_username" in (resp.text or "")[:2000]:
            return False
        probe = self.session.get(
            self._url("/rest/servicedeskapi/servicedesk"),
            timeout=20,
        )
        return probe.status_code == 200

    def _load_myself(self) -> None:
        try:
            resp = self.session.get(self._url("/rest/api/2/myself"), timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                self.display_name = (
                    data.get("displayName")
                    or data.get("name")
                    or data.get("emailAddress")
                    or self.username
                )
                return
        except Exception:
            pass
        self.display_name = self.username

    def discover(self) -> list[ServiceDesk]:
        desks: list[ServiceDesk] = []
        resp = self.session.get(
            self._url("/rest/servicedeskapi/servicedesk"),
            params={"start": 0, "limit": 50},
            timeout=25,
        )
        if resp.status_code == 401:
            raise JiraError("Сессия истекла. Войдите снова.", 401)
        if resp.status_code != 200:
            raise JiraError(
                f"Не удалось получить список порталов Service Desk (код {resp.status_code}).",
                resp.status_code,
            )
        payload = resp.json()
        values = payload.get("values") or payload.get("projects") or []
        for item in values:
            desk = ServiceDesk(
                id=str(item.get("id") or item.get("projectId") or ""),
                name=str(item.get("projectName") or item.get("name") or "Service Desk"),
                project_key=str(item.get("projectKey") or ""),
            )
            desk.types = self._load_types(desk.id)
            if desk.id:
                desks.append(desk)
        if not desks:
            raise JiraError("Для этой учётной записи нет доступных порталов Service Desk.")
        self.desks = desks
        return desks

    def _load_types(self, desk_id: str) -> list[RequestType]:
        types: list[RequestType] = []
        start = 0
        while True:
            resp = self.session.get(
                self._url(f"/rest/servicedeskapi/servicedesk/{desk_id}/requesttype"),
                params={"start": start, "limit": 50},
                timeout=25,
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            values = data.get("values") or []
            for item in values:
                types.append(
                    RequestType(
                        id=str(item.get("id")),
                        name=str(item.get("name") or ""),
                        description=str(item.get("description") or ""),
                        service_desk_id=desk_id,
                    )
                )
            if data.get("isLastPage", True) or not values:
                break
            start += len(values)
        if not types:
            try:
                alt = self.session.get(
                    self._url(f"/rest/servicedesk/1/servicedesk/{desk_id}/request-types"),
                    timeout=25,
                )
                if alt.status_code == 200:
                    payload = alt.json() or {}
                    raw = payload if isinstance(payload, list) else (payload.get("values") or payload.get("requestTypes") or [])
                    for item in raw:
                        if not isinstance(item, dict):
                            continue
                        types.append(
                            RequestType(
                                id=str(item.get("id")),
                                name=str(item.get("name") or ""),
                                description=str(item.get("description") or ""),
                                service_desk_id=desk_id,
                            )
                        )
            except Exception:
                pass
        return types

    def pick_type(self, category: str) -> tuple[ServiceDesk, RequestType]:
        if not self.desks:
            self.discover()
        if category in {"computer", "printer", "users"}:
            forced = self._find_pc_type()
            if forced:
                return forced
            raise JiraError("Не найден тип «Проблемы с ПК/Ноутбуком».")
        if category == "purchase":
            found = self._find_purchase_type()
            if found:
                return found
            raise JiraError("Не найден тип «Закупки» в Service Desk.")
        forced = self._find_pc_type()
        if forced:
            return forced
        for desk in self.desks:
            if desk.types:
                return desk, desk.types[0]
        raise JiraError("В Service Desk нет доступных типов заявок.")

    def _is_pc_type(self, rtype: RequestType) -> bool:
        pc_id = str(getattr(config, "JIRA_PC_REQUEST_TYPE_ID", "8"))
        if str(rtype.id) == pc_id:
            return True
        blob = f"{rtype.name} {rtype.description}".lower().replace("ё", "е")
        return any(n in blob for n in ("проблемы с пк", "пк/ноут", "ноутбук", "компьютер"))

    def _find_purchase_type(self) -> tuple[ServiceDesk, RequestType] | None:
        """Вкладка «Закупки» — в раздел Закупки, не в Проблемы с ПК."""
        desk_id = str(getattr(config, "JIRA_PURCHASE_DESK_ID", "") or getattr(config, "JIRA_DESK_ID", "1"))
        type_id = str(getattr(config, "JIRA_PURCHASE_REQUEST_TYPE_ID", "") or "").strip()
        want = str(getattr(config, "JIRA_PURCHASE_TYPE_NAME", "Закупки") or "Закупки")
        keys = tuple(config.TYPE_KEYWORDS.get("purchase") or ("закуп", "purchase", "сервисн"))

        if type_id:
            for desk in self.desks:
                if desk_id and str(desk.id) != desk_id:
                    continue
                for rtype in desk.types:
                    if str(rtype.id) == type_id:
                        return desk, rtype
            for desk in self.desks:
                if str(desk.id) == desk_id:
                    return desk, RequestType(id=type_id, name=want, service_desk_id=desk.id)
            return (
                ServiceDesk(id=desk_id, name="Service Desk"),
                RequestType(id=type_id, name=want, service_desk_id=desk_id),
            )

        def score(name: str, extra: str = "") -> int:
            blob = f"{name} {extra}".lower().replace("ё", "е")
            if "закуп" in blob:
                return 100
            if want.lower() in blob:
                return 90
            if any(k in blob for k in keys if k not in {"сервисн"}):
                return 70
            if "сервисн" in blob:
                return 40
            return 0

        best: tuple[int, ServiceDesk, RequestType] | None = None
        for desk in self.desks:
            for rtype in desk.types:
                if self._is_pc_type(rtype):
                    continue
                pts = score(rtype.name, f"{rtype.description} {desk.name}")
                if pts <= 0:
                    continue
                if best is None or pts > best[0]:
                    best = (pts, desk, rtype)
        if best:
            return best[1], best[2]

        for desk in self.desks:
            if score(desk.name) <= 0:
                continue
            for rtype in desk.types:
                if not self._is_pc_type(rtype):
                    return desk, rtype
            if desk.types:
                return desk, desk.types[0]

        for desk in self.desks:
            for rtype in desk.types:
                if not self._is_pc_type(rtype):
                    return desk, rtype
        return None

    def _find_pc_type(self) -> tuple[ServiceDesk, RequestType] | None:
        desk_id = str(getattr(config, "JIRA_DESK_ID", "1"))
        type_id = str(getattr(config, "JIRA_PC_REQUEST_TYPE_ID", "8"))
        names = ("проблемы с пк", "ноутбук", "пк/ноут", "компьютер")
        for desk in self.desks:
            if str(desk.id) == desk_id:
                for rtype in desk.types:
                    if str(rtype.id) == type_id:
                        return desk, rtype
        for desk in self.desks:
            for rtype in desk.types:
                blob = f"{rtype.name} {rtype.description}".lower()
                if any(n in blob for n in names):
                    return desk, rtype
        for desk in self.desks:
            if str(desk.id) == desk_id and desk.types:
                for rtype in desk.types:
                    if str(rtype.id) == type_id:
                        return desk, rtype
                # даже если список типов пуст/не совпал — отправим по известным id
                return desk, RequestType(id=type_id, name=config.JIRA_PC_TYPE_NAME, service_desk_id=desk.id)
        # портал известен заранее
        return (
            ServiceDesk(id=desk_id, name="Service Desk"),
            RequestType(id=type_id, name=config.JIRA_PC_TYPE_NAME, service_desk_id=desk_id),
        )

    def _request_fields(self, desk_id: str, type_id: str) -> list[dict[str, Any]]:
        resp = self.session.get(
            self._url(
                f"/rest/servicedeskapi/servicedesk/{desk_id}/requesttype/{type_id}/field"
            ),
            timeout=25,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("requestTypeFields") or data.get("fields") or []

    def _mime(self, path: str) -> str:
        ext = Path(path).suffix.lower()
        return {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xls": "application/vnd.ms-excel",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".doc": "application/msword",
        }.get(ext) or "application/octet-stream"

    def _upload_temp_file(self, desk_id: str, path: Path) -> str:
        url = self._url(f"/rest/servicedeskapi/servicedesk/{desk_id}/attachTemporaryFile")
        try:
            with path.open("rb") as fh:
                resp = self.session.post(
                    url,
                    files={"file": (path.name, fh, self._mime(str(path)))},
                    headers={"X-Atlassian-Token": "no-check", "X-ExperimentalApi": "opt-in"},
                    timeout=120,
                )
        except Exception:
            return ""
        if resp.status_code not in (200, 201):
            return ""
        try:
            data = resp.json() or {}
        except Exception:
            return ""
        items = data.get("temporaryAttachments") or data.get("temporaryAttachmentIds") or []
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict):
                return str(first.get("temporaryAttachmentId") or first.get("id") or "")
            return str(first)
        return str(data.get("temporaryAttachmentId") or "")

    def _link_temp_attachments(self, issue_key: str, temp_ids: list[str]) -> bool:
        if not temp_ids:
            return False
        try:
            resp = self.session.post(
                self._url(f"/rest/servicedeskapi/request/{issue_key}/attachment"),
                json={"temporaryAttachmentIds": temp_ids, "public": True},
                timeout=40,
            )
        except Exception:
            return False
        return resp.status_code in (200, 201, 204)

    def _attach_rest(self, issue_key: str, path: Path) -> bool:
        url = self._url(f"/rest/api/2/issue/{issue_key}/attachments")
        try:
            with path.open("rb") as fh:
                resp = self.session.post(
                    url,
                    files={"file": (path.name, fh, self._mime(str(path)))},
                    headers={"X-Atlassian-Token": "no-check", "X-ExperimentalApi": "opt-in"},
                    timeout=120,
                )
        except Exception:
            return False
        return resp.status_code in (200, 201)

    def attach_files(self, issue_key: str, desk_id: str, paths: list[str]) -> tuple[int, str]:
        """Прикрепить файлы к заявке. Возвращает (успешно, текст ошибки)."""
        key = (issue_key or "").strip()
        files: list[Path] = []
        for raw in paths or []:
            path = Path(raw)
            try:
                if path.is_file() and path.stat().st_size > 0:
                    files.append(path)
            except OSError:
                continue
        if not key or not files:
            return 0, ""
        ok = 0
        failed: list[str] = []
        temp_ids: list[str] = []
        if desk_id:
            for path in files:
                tid = self._upload_temp_file(desk_id, path)
                if tid:
                    temp_ids.append(tid)
                else:
                    failed.append(path.name)
            if temp_ids and self._link_temp_attachments(key, temp_ids):
                ok += len(temp_ids)
            else:
                failed = [p.name for p in files]
                ok = 0
        if ok == 0:
            failed = []
            for path in files:
                if self._attach_rest(key, path):
                    ok += 1
                else:
                    failed.append(path.name)
        err = ""
        if failed:
            err = "Не удалось прикрепить: " + ", ".join(failed[:8])
        return ok, err

    def create_request(
        self,
        category: str,
        summary: str,
        description: str,
        phone: str = "",
        attachments: list[str] | None = None,
    ) -> CreatedRequest:
        desk, rtype = self.pick_type(category)
        phone = normalize_phone(phone)[:32]
        try:
            from rustdesk_setup import with_clickable_links

            description = with_clickable_links(description)
        except Exception:
            pass
        field_values: dict[str, Any] = {
            "summary": summary[:254],
            "description": description,
        }
        for item in self._request_fields(desk.id, rtype.id):
            field_id = str(item.get("fieldId") or item.get("id") or "")
            if not field_id or field_id in field_values:
                continue
            name = str(
                item.get("name") or item.get("label") or item.get("visibleName") or ""
            ).lower()
            is_phone = self._is_phone_field(field_id, name)
            if is_phone:
                field_values[field_id] = phone or ""
                continue
            if not item.get("required"):
                continue
            schema = item.get("jiraSchema") or item.get("schema") or {}
            ftype = str(schema.get("type") or "")
            valid = item.get("validValues") or item.get("allowedValues") or []
            if field_id == "summary":
                field_values[field_id] = summary[:254]
            elif field_id == "description":
                field_values[field_id] = description
            elif valid:
                first = valid[0]
                field_values[field_id] = first.get("value") or first.get("id") or first
            elif ftype in {"string", "textarea"}:
                field_values[field_id] = (summary if "заголов" in name or "summary" in name else "-")[:254]
            else:
                field_values[field_id] = "-"

        resp = self.session.post(
            self._url("/rest/servicedeskapi/request"),
            json={
                "serviceDeskId": desk.id,
                "requestTypeId": rtype.id,
                "requestFieldValues": field_values,
            },
            timeout=40,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            key = data.get("issueKey") or data.get("key") or ""
            links = data.get("_links") or {}
            web = (
                links.get("web")
                or links.get("agent")
                or f"{self.base_url}/browse/{key}"
            )
            created = CreatedRequest(
                issue_key=key,
                issue_id=str(data.get("issueId") or data.get("id") or ""),
                web_url=web,
                summary=summary,
            )
            if key:
                if attachments:
                    try:
                        attached, err = self.attach_files(key, desk.id, attachments)
                        created.attached = attached
                        created.attach_error = err
                    except Exception as exc:
                        created.attach_error = f"Не удалось прикрепить файлы: {exc}"
                try:
                    self.publish_connect_links(key, description)
                except Exception:
                    pass
                try:
                    self.move_to_in_progress(key)
                except Exception:
                    pass
            return created
        if resp.status_code == 401:
            raise JiraError("Сессия истекла. Войдите снова.", 401)
        raise JiraError(self._format_error(resp), resp.status_code)

    def get_request_status(self, issue_key: str) -> str:
        return str(self.get_request_info(issue_key).get("status") or "")

    def get_request_info(self, issue_key: str) -> dict[str, str]:
        """status, created, closed — для счётчика и сцены."""
        key = (issue_key or "").strip()
        info = {"key": key, "status": "", "created": "", "closed": "", "status_changed": ""}
        if not key:
            return info
        try:
            resp = self.session.get(self._url(f"/rest/servicedeskapi/request/{key}"), timeout=20)
            if resp.status_code == 200:
                data = resp.json() or {}
                cur = data.get("currentStatus") or {}
                info["status"] = str(cur.get("status") or "")
                created = data.get("createdDate") or {}
                info["created"] = self._fmt_when(
                    str(created.get("iso8601") or created.get("friendly") or "")
                )
                sd = cur.get("statusDate") or {}
                info["status_changed"] = self._fmt_when(
                    str(sd.get("iso8601") or sd.get("friendly") or "")
                )
                if self.is_closed(info["status"]):
                    info["closed"] = info["status_changed"]
                if info["status"]:
                    return info
            resp = self.session.get(
                self._url(f"/rest/api/2/issue/{key}"),
                params={"fields": "status,created,resolutiondate,updated"},
                timeout=20,
            )
            if resp.status_code == 200:
                fields = (resp.json() or {}).get("fields") or {}
                info["status"] = str(((fields.get("status") or {}).get("name")) or info["status"])
                if not info["created"]:
                    info["created"] = self._fmt_when(str(fields.get("created") or ""))
                if self.is_closed(info["status"]) and not info["closed"]:
                    info["closed"] = self._fmt_when(str(fields.get("resolutiondate") or ""))
                if not info["status_changed"]:
                    info["status_changed"] = info["closed"] or self._fmt_when(str(fields.get("updated") or ""))
        except Exception:
            return info
        return info

    def latest_request(self) -> tuple[str, str]:
        try:
            resp = self.session.get(
                self._url("/rest/servicedeskapi/request"),
                params={"start": 0, "limit": 8},
                timeout=20,
            )
            if resp.status_code != 200:
                return "", ""
            values = (resp.json() or {}).get("values") or []
            if not values:
                return "", ""
            item = values[0]
            key = str(item.get("issueKey") or item.get("key") or "")
            status = str(((item.get("currentStatus") or {}).get("status")) or "")
            return key, status
        except Exception:
            return "", ""

    def list_requests(self, limit: int = 80) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        start = 0
        while len(out) < limit:
            resp = self.session.get(
                self._url("/rest/servicedeskapi/request"),
                params={"start": start, "limit": 50},
                timeout=25,
            )
            if resp.status_code != 200:
                break
            data = resp.json() or {}
            values = data.get("values") or []
            for item in values:
                created = item.get("createdDate") or {}
                cur = item.get("currentStatus") or {}
                status = str(cur.get("status") or "")
                status_date = cur.get("statusDate") or {}
                summary = ""
                description = ""
                for fv in item.get("requestFieldValues") or []:
                    fid = str(fv.get("fieldId") or "").lower()
                    label = str(fv.get("label") or fv.get("name") or "").lower()
                    text = self._field_text(fv.get("value"))
                    if not summary and (fid == "summary" or "заголов" in label or label == "summary"):
                        summary = text
                    elif not description and (
                        fid == "description" or "описан" in label or label in {"description", "подробности"}
                    ):
                        description = text
                closed = ""
                if self.is_closed(status):
                    closed = str(status_date.get("iso8601") or status_date.get("friendly") or "")
                rtype = item.get("requestType") or {}
                out.append(
                    {
                        "key": str(item.get("issueKey") or item.get("key") or ""),
                        "summary": summary,
                        "description": description,
                        "status": status,
                        "created": self._fmt_when(str(created.get("iso8601") or created.get("friendly") or "")),
                        "closed": self._fmt_when(closed),
                        "status_changed": self._fmt_when(
                            str(status_date.get("iso8601") or status_date.get("friendly") or "")
                        ),
                        "type": str(rtype.get("name") or rtype.get("requestTypeName") or ""),
                    }
                )
            if data.get("isLastPage", True) or not values:
                break
            start += len(values)
        self._enrich_requests(out[:limit])
        return out[:limit]

    def _enrich_requests(self, rows: list[dict[str, Any]]) -> None:
        """resolutiondate и описание из Jira REST, если портал их не отдал."""
        need = [r for r in rows if r.get("key") and (not r.get("closed") or not r.get("description") or not r.get("type"))]
        if not need:
            return
        for i in range(0, len(need), 40):
            chunk = need[i : i + 40]
            keys = ",".join(r["key"] for r in chunk)
            try:
                resp = self.session.get(
                    self._url("/rest/api/2/search"),
                    params={
                        "jql": f"key in ({keys})",
                        "fields": "summary,description,status,created,resolutiondate,issuetype",
                        "maxResults": len(chunk),
                    },
                    timeout=25,
                )
            except Exception:
                return
            if resp.status_code != 200:
                return
            by_key = {}
            for issue in (resp.json() or {}).get("issues") or []:
                by_key[str(issue.get("key") or "")] = (issue.get("fields") or {})
            for row in chunk:
                fields = by_key.get(row["key"]) or {}
                if not row.get("summary"):
                    row["summary"] = str(fields.get("summary") or "")
                if not row.get("description"):
                    row["description"] = self._field_text(fields.get("description"))
                if not row.get("type"):
                    itype = fields.get("issuetype") or {}
                    row["type"] = str(itype.get("name") or "")
                if not row.get("closed") and self.is_closed(row.get("status") or ""):
                    row["closed"] = self._fmt_when(str(fields.get("resolutiondate") or ""))
                elif not row.get("closed") and self.is_closed(str((fields.get("status") or {}).get("name") or "")):
                    row["closed"] = self._fmt_when(str(fields.get("resolutiondate") or ""))

    @staticmethod
    def _field_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            parts = [JiraClient._field_text(item) for item in value]
            return "\n".join(p for p in parts if p)
        if isinstance(value, dict):
            if "content" in value:
                return JiraClient._field_text(value.get("content"))
            return str(value.get("text") or value.get("value") or "").strip()
        return str(value).strip()

    @staticmethod
    def _fmt_when(raw: str) -> str:
        text = (raw or "").strip()
        if not text:
            return ""
        text = text.replace("Z", "+00:00")
        if "T" in text:
            text = text.replace("T", " ", 1)
        return text[:19]

    def publish_connect_links(self, issue_key: str, description: str = "") -> None:
        """Кликабельные ссылки в заявке: Web Link + комментарий с https."""
        key = (issue_key or "").strip()
        if not key:
            return
        anydesk = rustdesk = ""
        for line in (description or "").splitlines():
            low = line.lower()
            if "anydesk id:" in low:
                raw = line.split(":", 1)[-1].strip().split()[0]
                if raw and raw.lower() not in {"не", "не найден"}:
                    anydesk = raw
            if "rustdesk id:" in low:
                raw = line.split(":", 1)[-1].strip().split()[0]
                if raw and raw.lower() not in {"не", "не найден"}:
                    rustdesk = raw
        try:
            from rustdesk_setup import anydesk_url, connect_url, https_launch_url
        except Exception:
            return
        items: list[tuple[str, str, str]] = []
        if anydesk:
            proto = anydesk_url(anydesk)
            url = https_launch_url(proto) or proto
            items.append(("anydesk", url, f"AnyDesk {anydesk} — подключиться"))
        if rustdesk:
            proto = connect_url(rustdesk)
            url = https_launch_url(proto) or proto
            items.append(("rustdesk", url, f"RustDesk {rustdesk} — подключиться"))
        for kind, url, title in items:
            if not url:
                continue
            try:
                self.session.post(
                    self._url(f"/rest/api/2/issue/{key}/remotelink"),
                    json={
                        "globalId": f"helpcsl-{kind}-{key}",
                        "relationship": "connects",
                        "object": {"url": url, "title": title},
                    },
                    timeout=15,
                )
            except Exception:
                pass
        if not items:
            return
        body_lines = ["Help CSL — нажмите ссылку, откроется программа:", ""]
        for _kind, url, title in items:
            body_lines.append(title)
            body_lines.append(url)
            body_lines.append("")
        body = "\n".join(body_lines)
        try:
            self.session.post(
                self._url(f"/rest/api/2/issue/{key}/comment"),
                json={"body": body},
                timeout=15,
            )
        except Exception:
            pass

    def move_to_in_progress(self, issue_key: str) -> None:
        """Перевести заявку в очередь «В работе»."""
        key = (issue_key or "").strip()
        if not key:
            return
        if self.is_in_progress(self.get_request_status(key)):
            return
        hints = (
            "в работе",
            "in progress",
            "start progress",
            "начать",
            "работу",
            "взять в работу",
            "working",
        )
        self._apply_transition(key, hints)

    def mark_changed(self, issue_key: str) -> bool:
        """Попытаться перевести в «Изменено». Нет такого перехода — тихо False."""
        key = (issue_key or "").strip()
        if not key:
            return False
        hints = ("измен", "changed", "amend", "update", "правк")
        try:
            self._apply_transition(key, hints)
            return True
        except Exception:
            return False

    def close_request(self, issue_key: str) -> None:
        key = (issue_key or "").strip()
        if not key:
            raise JiraError("Нет номера заявки для закрытия.")
        hints = ("закры", "close", "resolv", "done", "complete", "cancel", "отмен", "решен", "готов")
        self._apply_transition(key, hints)

    def _apply_transition(self, key: str, hints: tuple[str, ...]) -> None:
        try:
            resp = self.session.get(
                self._url(f"/rest/servicedeskapi/request/{key}/transition"),
                timeout=20,
            )
            if resp.status_code == 200:
                values = (resp.json() or {}).get("values") or resp.json() or []
                if isinstance(values, dict):
                    values = values.get("values") or []
                tid = self._pick_transition_id(values, hints)
                if tid:
                    done = self.session.post(
                        self._url(f"/rest/servicedeskapi/request/{key}/transition"),
                        json={"id": tid},
                        timeout=25,
                    )
                    if done.status_code in (200, 204):
                        return
        except Exception:
            pass
        resp = self.session.get(self._url(f"/rest/api/2/issue/{key}/transitions"), timeout=20)
        if resp.status_code != 200:
            raise JiraError("Не удалось получить переходы статуса заявки.")
        trans = (resp.json() or {}).get("transitions") or []
        tid = self._pick_transition_id(trans, hints)
        if not tid:
            raise JiraError("Нет подходящего перехода статуса.")
        done = self.session.post(
            self._url(f"/rest/api/2/issue/{key}/transitions"),
            json={"transition": {"id": str(tid)}},
            timeout=25,
        )
        if done.status_code not in (200, 204):
            raise JiraError(self._format_error(done), done.status_code)

    @staticmethod
    def _pick_transition_id(items: list, hints: tuple[str, ...]) -> str:
        for item in items or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("to") or "").lower()
            if isinstance(item.get("to"), dict):
                name = str(item["to"].get("name") or name).lower()
            blob = name.replace("ё", "е")
            if any(h in blob for h in hints):
                return str(item.get("id") or "")
        return ""

    @staticmethod
    def is_closed(status: str) -> bool:
        blob = (status or "").lower().replace("ё", "е")
        return any(
            m in blob
            for m in (
                "готов",
                "закрыт",
                "решен",
                "выполнен",
                "resolved",
                "done",
                "closed",
                "complete",
                "отменен",
                "отклон",
                "rejected",
                "declined",
                "cancel",
            )
        )

    @staticmethod
    def is_paused(status: str) -> bool:
        blob = (status or "").lower().replace("ё", "е")
        return any(
            mark in blob
            for mark in (
                "приостанов",
                "on hold",
                "on-hold",
                "paused",
                "suspended",
                "отложен",
            )
        )

    @staticmethod
    def should_return(status: str) -> bool:
        return JiraClient.is_closed(status) or JiraClient.is_paused(status)

    @staticmethod
    def is_in_progress(status: str) -> bool:
        blob = (status or "").lower().replace("ё", "е")
        return any(
            mark in blob
            for mark in ("в работе", "in progress", "in-progress", "выполня", "working")
        )

    @staticmethod
    def _is_phone_field(field_id: str, name: str) -> bool:
        blob = f"{field_id} {name}".lower()
        hints = (
            "телефон",
            "телеф",
            "phone",
            "mobile",
            "мобиль",
            "номер телефона",
            "контактный номер",
        )
        return any(h in blob for h in hints)

    @staticmethod
    def _format_error(resp: requests.Response) -> str:
        try:
            data = resp.json()
        except Exception:
            text = (resp.text or "").strip()
            return text[:400] or f"Ошибка сервера (код {resp.status_code})."
        if isinstance(data, dict):
            msgs = data.get("errorMessages") or []
            errors = data.get("errors") or {}
            message = data.get("message") or data.get("errorMessage")
            parts = [str(x) for x in msgs]
            if message:
                parts.append(str(message))
            parts.extend(f"{k}: {v}" for k, v in errors.items())
            if parts:
                return " ".join(parts)
        return f"Не удалось создать заявку (код {resp.status_code})."


_IPV4_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")
_IP_CACHE: dict[str, Any] = {"local": "", "local_all": "", "external": "", "ts": 0.0}


def _is_loopback(ip: str) -> bool:
    return ip.startswith("127.") or ip in {"0.0.0.0", "::1"}


def local_ipv4_list() -> list[str]:
    found: list[str] = []

    def add(ip: str) -> None:
        ip = (ip or "").strip()
        if not _IPV4_RE.fullmatch(ip) or _is_loopback(ip) or ip in found:
            return
        found.append(ip)

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)
        sock.connect(("8.8.8.8", 80))
        add(sock.getsockname()[0])
        sock.close()
    except Exception:
        pass
    try:
        host = socket.gethostname()
        add(socket.gethostbyname(host))
        for item in socket.getaddrinfo(host, None, socket.AF_INET):
            add(item[4][0])
    except Exception:
        pass
    return found


def external_ipv4() -> str:
    urls = (
        "https://api.ipify.org",
        "https://ipv4.icanhazip.com",
        "https://ifconfig.me/ip",
        "https://api.seeip.org",
    )
    headers = {"User-Agent": getattr(config, "USER_AGENT", "HelpCSL")}
    for url in urls:
        try:
            resp = requests.get(url, timeout=4, headers=headers)
            if resp.status_code != 200:
                continue
            ip = (resp.text or "").strip().split()[0]
            if _IPV4_RE.fullmatch(ip) and not _is_loopback(ip):
                return ip
        except Exception:
            continue
    return ""


def workstation_info() -> dict[str, str]:
    import time

    now = time.time()
    if now - float(_IP_CACHE.get("ts") or 0) > 300 or not _IP_CACHE.get("local"):
        locals_ = local_ipv4_list()
        _IP_CACHE["local"] = locals_[0] if locals_ else ""
        _IP_CACHE["local_all"] = ", ".join(locals_)
        _IP_CACHE["external"] = external_ipv4()
        _IP_CACHE["ts"] = now
    local = str(_IP_CACHE.get("local") or "")
    local_all = str(_IP_CACHE.get("local_all") or local)
    external = str(_IP_CACHE.get("external") or "")
    return {
        "computer": os_env("COMPUTERNAME") or socket.gethostname(),
        "os_user": os_env("USERNAME") or os_env("USER") or "",
        "os": f"{platform.system()} {platform.release()} {platform.version()}".strip(),
        "host": socket.gethostname(),
        "ip": local,
        "ip_local": local_all or local or "не определён",
        "ip_external": external or "не определён",
    }


def os_env(name: str) -> str:
    import os

    return os.environ.get(name) or ""


# Точное число цифр после «+» для знакомых стран (E.164).
PHONE_DIGITS: dict[str, int] = {
    "375": 12,
    "7": 11,
    "380": 12,
    "48": 11,
    "370": 11,
    "371": 11,
    "372": 11,
    "1": 11,
}
PHONE_EXAMPLE = "+375293761095"
PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def phone_country(digits: str) -> tuple[str, int | None]:
    for code in sorted(PHONE_DIGITS, key=len, reverse=True):
        if digits.startswith(code):
            return code, PHONE_DIGITS[code]
    return "", None


def phone_limit(value: str) -> int:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    _code, expected = phone_country(digits)
    if expected:
        return 1 + expected
    return 16


def normalize_phone(value: str) -> str:
    raw = (value or "").strip()
    for ch in (" ", "-", "(", ")", ".", "\u00a0"):
        raw = raw.replace(ch, "")
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    if raw.startswith("80") and len(raw) >= 4:
        raw = "+375" + raw[2:]
    elif raw.startswith("375") and not raw.startswith("+"):
        raw = "+" + raw
    elif raw.startswith("8") and len(raw) >= 10 and not raw.startswith("80"):
        raw = "+375" + raw[1:]
    if raw and not raw.startswith("+") and raw[0].isdigit():
        raw = "+" + raw
    return raw


def is_valid_phone(value: str) -> bool:
    n = normalize_phone(value)
    if not n.startswith("+") or len(n) < 2 or not n[1:].isdigit() or n[1] == "0":
        return False
    digits = n[1:]
    _code, expected = phone_country(digits)
    if expected is not None:
        return len(digits) == expected
    return 8 <= len(digits) <= 15


def phone_message(value: str) -> str:
    n = normalize_phone(value)
    if not n.startswith("+"):
        return f"Номер с + и кодом страны. Пример: {PHONE_EXAMPLE}"
    digits = n[1:]
    if not digits.isdigit():
        return "Только «+» и цифры, без пробелов и скобок."
    _code, expected = phone_country(digits)
    if expected is not None:
        if len(digits) < expected:
            left = expected - len(digits)
            word = "цифру" if left == 1 else ("цифры" if left < 5 else "цифр")
            return f"Ещё {left} {word}. Нужно ровно {expected} после +."
        if len(digits) > expected:
            return f"Лишние цифры: для этого кода ровно {expected} после +."
        return ""
    if len(digits) < 8:
        return f"Слишком короткий номер. Пример: {PHONE_EXAMPLE}"
    if len(digits) > 15:
        return "Слишком длинный номер (максимум 15 цифр)."
    return ""
