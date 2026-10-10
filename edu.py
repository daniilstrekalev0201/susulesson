"""Сроки сдачи заданий из «Электронного ЮУрГУ» (edu.susu.ru, Moodle).

Бот входит как мобильное приложение Moodle (логин/пароль «Универиса» из переменных
EDU_LOGIN/EDU_PASSWORD), берёт список курсов и события календаря «срок сдачи» по ним.
Берутся события курсов, а не личный список дел, поэтому срок не пропадает у всей группы,
когда владелец аккаунта сам сдал работу.
"""

import logging
import time

import aiohttp

import storage
from config import EDU_LOGIN, EDU_PASSWORD, EDU_REFRESH_MIN

URL = "https://edu.susu.ru"
DAYS_AHEAD = 60
DEADLINE_TYPES = {"due", "close"}

log = logging.getLogger(__name__)


class EduError(Exception):
    pass


class TokenExpired(EduError):
    pass


def enabled() -> bool:
    return bool(EDU_LOGIN and EDU_PASSWORD)


async def _login(session: aiohttp.ClientSession) -> str:
    data = {"username": EDU_LOGIN, "password": EDU_PASSWORD, "service": "moodle_mobile_app"}
    async with session.post(f"{URL}/login/token.php", data=data,
                            timeout=aiohttp.ClientTimeout(total=40)) as r:
        answer = await r.json(content_type=None)
    if "token" not in answer:
        raise EduError(answer.get("error") or "не удалось войти")
    return answer["token"]


def _flatten(params: dict, prefix: str = "") -> dict:
    """{'events': {'courseids': [1, 2]}} → {'events[courseids][0]': 1, ...} — так хочет Moodle."""
    flat = {}
    for key, value in params.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, dict):
            flat.update(_flatten(value, name))
        elif isinstance(value, (list, tuple)):
            flat.update(_flatten(dict(enumerate(value)), name))
        else:
            flat[name] = int(value) if isinstance(value, bool) else value
    return flat


async def _call(session: aiohttp.ClientSession, token: str, function: str, **params):
    data = {"wstoken": token, "wsfunction": function, "moodlewsrestformat": "json",
            **_flatten(params)}
    async with session.post(f"{URL}/webservice/rest/server.php", data=data,
                            timeout=aiohttp.ClientTimeout(total=60)) as r:
        answer = await r.json(content_type=None)
    if isinstance(answer, dict) and "exception" in answer:
        if answer.get("errorcode") in ("invalidtoken", "accessexception"):
            raise TokenExpired(answer.get("message", ""))
        raise EduError(answer.get("message") or answer.get("errorcode") or "ошибка Moodle")
    return answer


async def _fetch(session: aiohttp.ClientSession, token: str) -> list[dict]:
    info = await _call(session, token, "core_webservice_get_site_info")
    courses = await _call(session, token, "core_enrol_get_users_courses", userid=info["userid"])
    names = {c["id"]: c.get("fullname") or c.get("shortname") or "" for c in courses}
    if not names:
        return []
    now = int(time.time())
    answer = await _call(
        session, token, "core_calendar_get_calendar_events",
        events={"courseids": list(names)},
        options={"userevents": False, "siteevents": False,
                 "timestart": now - 86400, "timeend": now + DAYS_AHEAD * 86400},
    )
    deadlines = []
    for e in answer.get("events", []):
        if e.get("eventtype") not in DEADLINE_TYPES or not e.get("modulename"):
            continue
        deadlines.append({
            "id": f"edu{e['id']}",
            "title": e.get("name", "").strip(),
            "course": names.get(e.get("courseid"), ""),
            "due": int(e["timestart"]),
            "url": f"{URL}/course/view.php?id={e.get('courseid')}",
            "source": "edu",
        })
    return deadlines


async def refresh(session: aiohttp.ClientSession, force: bool = False) -> list[dict]:
    """Обновляет сроки сдачи. Возвращает задания, которых раньше не было (для «🆕 Новое задание»)."""
    edu = storage.state["edu"]
    if not enabled() or (not force and time.time() - edu["at"] < EDU_REFRESH_MIN * 60):
        return []
    try:
        try:
            if not edu["token"]:
                edu["token"] = await _login(session)
            deadlines = await _fetch(session, edu["token"])
        except TokenExpired:
            edu["token"] = await _login(session)
            deadlines = await _fetch(session, edu["token"])
    except (EduError, aiohttp.ClientError, TimeoutError, KeyError, ValueError) as e:
        edu["error"] = str(e) or repr(e)
        edu["at"] = time.time()
        storage.save()
        log.warning("edu.susu.ru: %s", edu["error"])
        return []

    first_time = edu["seen"] is None
    seen = set(edu["seen"] or [])
    new = [] if first_time else [d for d in deadlines if d["id"] not in seen]
    edu["seen"] = sorted(seen | {d["id"] for d in deadlines})[-500:]
    edu["deadlines"] = deadlines
    edu["error"] = None
    edu["at"] = time.time()
    storage.save()
    log.info("edu.susu.ru: %d сроков сдачи, новых %d", len(deadlines), len(new))
    return new
