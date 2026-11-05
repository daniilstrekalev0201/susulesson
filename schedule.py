"""Расписание группы с сайта ЮУрГУ: страница www.susu.ru/ru/lessons/<группа>.

На странице — пары на ближайшие ~2 недели с точными датами, сайт обновляет её каждый день.
"""

import hashlib
import html
import logging
import re
import time
from datetime import date, datetime

import aiohttp

import storage
from config import GROUP, LOCAL_TZ, SCHEDULE_REFRESH_MIN

BASE = "https://www.susu.ru"
INDEX = BASE + "/ru/raspisanie-zanyatiy"
HEADERS = {"User-Agent": "Mozilla/5.0 (susulesson Telegram bot)"}

TRANSLIT = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r",
     "s", "t", "u", "f", "h", "c", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"],
))

log = logging.getLogger(__name__)


def current_group() -> str:
    return storage.state.get("group") or GROUP


def _norm(name: str) -> str:
    return re.sub(r"\s+", "", name).upper()


def _clean(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("\xa0", " ").strip()


async def _get(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=40)) as r:
        r.raise_for_status()
        return await r.text()


def _page_group(page: str) -> str:
    m = re.search(r'<h1 class="page-header">(.*?)</h1>', page, re.S)
    return _clean(m.group(1)) if m else ""


async def find_group_url(session: aiohttp.ClientSession, group: str) -> str | None:
    """Ищет страницу группы: сначала по транслиту (КЭ-101 → ke-101), потом по списку институтов."""
    slug = "".join(TRANSLIT.get(ch, ch) for ch in group.lower().strip())
    guess = f"{BASE}/ru/lessons/{slug}"
    try:
        if _norm(_page_group(await _get(session, guess))) == _norm(group):
            return guess
    except aiohttp.ClientError:
        pass

    index = await _get(session, INDEX)
    for inst in dict.fromkeys(re.findall(r'href="(/ru/lessons/\d+)"', index)):
        page = await _get(session, BASE + inst)
        for href, name in re.findall(r'<a href="(/ru/lessons/[^"]+)">([^<]+)</a>', page):
            if _norm(_clean(name)) == _norm(group):
                return BASE + href
    return None


def parse(page: str) -> list[dict]:
    """Разбирает таблицу расписания в список пар."""
    lessons = []
    day = None
    for row in re.split(r"<tr\b", page)[1:]:
        if 'class="weekday"' in row:
            m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", row)
            day = date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat() if m else None
            continue
        if day is None or 'class="week' not in row:
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < 4:
            continue
        times = re.findall(r"(\d{1,2}:\d{2})(?::\d{2})?", cells[0])
        if len(times) < 2:
            continue
        subject, _, kind = cells[3].partition("<br")
        lessons.append({
            "date": day,
            "start": times[0].zfill(5),
            "end": times[1].zfill(5),
            "subgroup": _clean(cells[1]),
            "room": _clean(cells[2]),
            "subject": _clean(subject),
            "kind": _clean("<br" + kind) if kind else "",
        })
    return lessons


# ---------- изменения в расписании ----------
# state["changes"]: {ключ пары: {"orig": пара до первого изменения или None (новая пара),
#                                "cur": пара сейчас или None (отменена), "at": когда заметили}}
# Пометки живут, пока не прошёл день пары; вернулось как было — пометка снимается.

BIG_DROP = 0.5  # пропала больше половины пар — скорее сбой сайта, ждём подтверждения


def key(x: dict) -> str:
    return f"{x['date']}|{x['start']}|{x['subgroup']}"


def same(a: dict | None, b: dict | None) -> bool:
    fields = ("subject", "kind", "room", "end")
    if a is None or b is None:
        return a is b
    return all(a.get(f) == b.get(f) for f in fields)


def _today() -> str:
    return datetime.now(LOCAL_TZ).date().isoformat()


def _diff(old: list[dict], new: list[dict]) -> tuple[list[tuple[str, dict | None, dict | None]], int]:
    """Что поменялось на днях, которые есть в обеих копиях: ([(ключ, было, стало)], сколько пар было)."""
    if not old or not new:
        return [], 0
    first = _today()
    last = min(max(x["date"] for x in old), max(x["date"] for x in new))
    window = lambda xs: {key(x): x for x in xs if first <= x["date"] <= last}
    was, now = window(old), window(new)
    diff = [(k, was.get(k), now.get(k)) for k in sorted(was.keys() | now.keys())
            if not same(was.get(k), now.get(k))]
    return diff, len(was)


def _remember(diff: list) -> list[str]:
    """Обновляет пометки, возвращает ключи новых изменений для уведомления."""
    changes = storage.state["changes"]
    fresh = []
    for k, was, now in diff:
        orig = changes[k]["orig"] if k in changes else was
        if same(orig, now):
            changes.pop(k, None)  # вернули как было
            continue
        changes[k] = {"orig": orig, "cur": now, "at": int(time.time())}
        fresh.append(k)
    return fresh


def prune_changes() -> None:
    first = _today()
    storage.state["changes"] = {k: v for k, v in storage.state["changes"].items() if k[:10] >= first}


async def refresh(session: aiohttp.ClientSession, force: bool = False) -> list[str]:
    """Скачивает расписание, если пора. При ошибке остаётся прошлая копия.

    Возвращает ключи новых изменений в расписании (для уведомления).
    """
    st = storage.state
    group = current_group()
    if not group:
        return []
    if not force and time.time() - st["lessons_at"] < SCHEDULE_REFRESH_MIN * 60:
        return []
    try:
        if not st.get("group_url"):
            st["group_url"] = await find_group_url(session, group)
            if not st["group_url"]:
                log.warning("Группа %s не найдена на susu.ru", group)
                st["lessons_at"] = time.time()
                storage.save()
                return []
        lessons = parse(await _get(session, st["group_url"]))
    except (aiohttp.ClientError, TimeoutError) as e:
        log.warning("Не удалось скачать расписание: %r", e)
        return []
    fresh = []
    # Сайт иногда отдаёт пустую страницу — не затираем хорошую копию пустой.
    if lessons or not st["lessons"]:
        diff, before = _diff(st["lessons"], lessons)
        gone = sum(1 for _, _, now in diff if now is None)
        signature = hashlib.md5(repr(lessons).encode()).hexdigest()
        if gone > 5 and gone > BIG_DROP * before and st.get("suspect") != signature:
            # Такое бывает при сбое сайта: ждём, пока страница повторит то же самое.
            st["suspect"] = signature
            st["lessons_at"] = time.time() - SCHEDULE_REFRESH_MIN * 60 + 20 * 60  # проверить через 20 мин
            storage.save()
            log.warning("Расписание: пропало %d пар — похоже на сбой, проверю ещё раз", gone)
            return []
        st.pop("suspect", None)
        fresh = _remember(diff)
        st["lessons"] = lessons
    prune_changes()
    st["lessons_at"] = time.time()
    storage.save()
    log.info("Расписание %s обновлено: %d пар, изменений %d", group, len(lessons), len(fresh))
    return fresh


def for_day(day: date) -> list[dict]:
    iso = day.isoformat()
    return sorted((x for x in storage.state["lessons"] if x["date"] == iso), key=lambda x: x["start"])


def start_dt(lesson: dict) -> datetime:
    h, m = map(int, lesson["start"].split(":"))
    return datetime.fromisoformat(lesson["date"]).replace(hour=h, minute=m, tzinfo=LOCAL_TZ)


def subjects() -> list[str]:
    return sorted({x["subject"] for x in storage.state["lessons"] if x["subject"]})
