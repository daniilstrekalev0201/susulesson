"""Сроки сдачи заданий из «Электронного ЮУрГУ» (edu.susu.ru, Moodle).

Бот входит как мобильное приложение Moodle (логин/пароль «Универиса» из переменных
EDU_LOGIN/EDU_PASSWORD), берёт список курсов и события календаря «срок сдачи» по ним.
Берутся события курсов, а не личный список дел, поэтому срок не пропадает у всей группы,
когда владелец аккаунта сам сдал работу.
"""

import asyncio
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


async def _call(session: aiohttp.ClientSession, token: str, function: str, timeout: int = 60, **params):
    data = {"wstoken": token, "wsfunction": function, "moodlewsrestformat": "json",
            **_flatten(params)}
    async with session.post(f"{URL}/webservice/rest/server.php", data=data,
                            timeout=aiohttp.ClientTimeout(total=timeout)) as r:
        answer = await r.json(content_type=None)
    if isinstance(answer, dict) and "exception" in answer:
        if answer.get("errorcode") in ("invalidtoken", "accessexception"):
            raise TokenExpired(answer.get("message", ""))
        raise EduError(answer.get("message") or answer.get("errorcode") or "ошибка Moodle")
    return answer


# ---------- преподаватели курсов ----------
# Moodle отвечает на эти запросы медленно, поэтому они идут в фоне раз в TEACHERS_EVERY_H часов
# и не задерживают сроки сдачи и команду /refresh.

TEACHERS_EVERY_H = 12
TEACHER_ROLES = ("editingteacher", "teacher")
_teachers_task: asyncio.Task | None = None


def _short_name(fullname: str) -> str:
    """«Иванов Иван Иванович» → «Иванов И. И.»."""
    parts = fullname.split()
    if len(parts) < 2:
        return fullname.strip()
    return parts[0] + " " + " ".join(p[0] + "." for p in parts[1:3])


async def _course_teachers(session: aiohttp.ClientSession, token: str, cid: int) -> list[str]:
    """Преподаватели курса, у которого нет «контактов»: кто может править курс, иначе — по ролям участников."""
    try:
        answer = await _call(session, token, "core_enrol_get_enrolled_users_with_capability", timeout=30,
                             coursecapabilities=[{"courseid": cid, "capabilities": ["moodle/course:update"]}],
                             options=[{"name": "userfields", "value": "fullname"}])
        users = answer[0]["users"] if answer else []
        if users:
            return [_short_name(u["fullname"]) for u in users]
    except (EduError, aiohttp.ClientError, TimeoutError, KeyError, IndexError, TypeError) as e:
        log.info("edu.susu.ru: курс %s, преподаватели по правам: %r", cid, e)
    users = await _call(session, token, "core_enrol_get_enrolled_users", timeout=40, courseid=cid,
                        options=[{"name": "userfields", "value": "fullname,roles"}])
    rank = {}
    for u in users:
        roles = [TEACHER_ROLES.index(r["shortname"]) for r in u.get("roles", [])
                 if r.get("shortname") in TEACHER_ROLES]
        if roles:
            rank[_short_name(u["fullname"])] = min(roles)
    return sorted(rank, key=rank.get)  # сначала лектор (editingteacher), потом ассистенты


async def _update_teachers(session: aiohttp.ClientSession, token: str, names: dict) -> None:
    edu = storage.state["edu"]
    started = time.monotonic()
    found = {}
    try:
        answer = await _call(session, token, "core_course_get_courses_by_field", timeout=40,
                             field="ids", value=",".join(map(str, names)))
        found = {c["id"]: [_short_name(p["fullname"]) for p in c.get("contacts") or []]
                 for c in answer.get("courses", [])}
        log.info("edu.susu.ru: контакты есть у %d курсов из %d (%.0f с)",
                 sum(map(bool, found.values())), len(names), time.monotonic() - started)
    except (EduError, aiohttp.ClientError, TimeoutError, KeyError, ValueError) as e:
        log.warning("edu.susu.ru: контакты курсов: %r (%.0f с)", e, time.monotonic() - started)
    for cid in names:
        if found.get(cid):
            continue
        moment = time.monotonic()
        try:
            found[cid] = await _course_teachers(session, token, cid)
        except (EduError, aiohttp.ClientError, TimeoutError, KeyError, ValueError) as e:
            log.warning("edu.susu.ru: курс %s, участники: %r (%.0f с)", cid, e, time.monotonic() - moment)
    teachers = {names[cid]: list(dict.fromkeys(who))[:3] for cid, who in found.items() if who and cid in names}
    if teachers:
        edu["teachers"] = teachers
    edu["teachers_at"] = time.time()
    storage.save()
    log.info("edu.susu.ru: преподаватели известны для %d курсов из %d (%.0f с)",
             len(teachers), len(names), time.monotonic() - started)


async def _teachers_safe(session: aiohttp.ClientSession, token: str, names: dict) -> None:
    try:
        await _update_teachers(session, token, names)
    except Exception:
        log.exception("edu.susu.ru: ошибка при загрузке преподавателей")


async def _fetch(session: aiohttp.ClientSession, token: str) -> tuple[list[dict], dict]:
    info = await _call(session, token, "core_webservice_get_site_info")
    courses = await _call(session, token, "core_enrol_get_users_courses", userid=info["userid"])
    names = {c["id"]: c.get("fullname") or c.get("shortname") or "" for c in courses}
    if not names:
        return [], names
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
    return deadlines, names


async def refresh(session: aiohttp.ClientSession, force: bool = False) -> list[dict]:
    """Обновляет сроки сдачи. Возвращает задания, которых раньше не было (для «🆕 Новое задание»)."""
    edu = storage.state["edu"]
    if not enabled() or (not force and time.time() - edu["at"] < EDU_REFRESH_MIN * 60):
        return []
    try:
        try:
            if not edu["token"]:
                edu["token"] = await _login(session)
            deadlines, names = await _fetch(session, edu["token"])
        except TokenExpired:
            edu["token"] = await _login(session)
            deadlines, names = await _fetch(session, edu["token"])
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

    global _teachers_task
    stale = time.time() - edu.get("teachers_at", 0) > TEACHERS_EVERY_H * 3600
    if names and (force or stale) and not (_teachers_task and not _teachers_task.done()):
        _teachers_task = asyncio.create_task(_teachers_safe(session, edu["token"], names))
    return new
