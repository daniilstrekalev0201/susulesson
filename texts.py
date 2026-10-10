"""Как бот показывает пары и сроки сдачи."""

import time
from datetime import date, datetime, timedelta
from html import escape

import schedule
import storage
from config import LOCAL_TZ

WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
WD_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
PAIR_NUMBERS = {"08:00": 1, "09:45": 2, "11:30": 3, "13:35": 4, "15:20": 5, "17:05": 6, "18:50": 7}
NUM_EMOJI = ["0️⃣", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]
KINDS = {
    "Лекции": "лекция",
    "Практические занятия и семинары": "практика",
    "Лабораторные работы": "лаба",
}


def now() -> datetime:
    return datetime.now(LOCAL_TZ)


def today() -> date:
    return now().date()


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def day_title(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]}, {day:%d.%m}"


def lesson_line(x: dict) -> str:
    number = PAIR_NUMBERS.get(x["start"])
    mark = NUM_EMOJI[number] if number else "▫️"
    kind = KINDS.get(x["kind"], x["kind"].lower())
    parts = [f"{mark} {x['start']}–{x['end']} <b>{escape(x['subject'])}</b>"]
    if kind:
        parts[0] += f" ({escape(kind)})"
    extra = []
    if x["room"]:
        extra.append(f"ауд. {escape(x['room'])}")
    if x["subgroup"]:
        extra.append(f"подгр. {escape(x['subgroup'])}")
    if extra:
        parts.append("      " + " · ".join(extra))
    return "\n".join(parts)


def day_text(day: date, empty: str = "Пар нет 🎉") -> str:
    lessons = schedule.for_day(day)
    head = f"📅 <b>{day_title(day)}</b>"
    if not lessons:
        return f"{head}\n{empty}"
    return head + "\n" + "\n".join(lesson_line(x) for x in lessons)


def week_text(start: date) -> str:
    days = [start + timedelta(days=i) for i in range(7)]
    blocks = [day_text(d) for d in days if schedule.for_day(d)]
    if not blocks:
        return "На ближайшую неделю пар в расписании нет."
    return "\n\n".join(blocks)


def no_schedule_text() -> str:
    if not schedule.current_group():
        return "Группа ещё не выбрана. Админ может задать её командой /group КЭ-101."
    if not storage.state.get("group_url") and storage.state["lessons_at"]:
        return f"Группа {escape(schedule.current_group())} не найдена на сайте susu.ru."
    return ""


# ---------- сроки сдачи ----------

def deadlines(within_days: int | None = None) -> list[dict]:
    """Все будущие сроки: из edu.susu.ru и добавленные вручную, по порядку."""
    st = storage.state
    moment = time.time()
    items = [*st["edu"]["deadlines"], *st["homework"]]
    items = [d for d in items if d["due"] > moment]
    if within_days is not None:
        items = [d for d in items if d["due"] <= moment + within_days * 86400]
    return sorted(items, key=lambda d: d["due"])


def due_dt(d: dict) -> datetime:
    return datetime.fromtimestamp(d["due"], LOCAL_TZ)


def left_text(d: dict) -> str:
    seconds = d["due"] - time.time()
    hours = int(seconds // 3600)
    if hours < 1:
        minutes = max(1, int(seconds // 60))
        return f"через {minutes} мин"
    if hours < 24:
        return f"через {hours} {plural(hours, 'час', 'часа', 'часов')}"
    days = (due_dt(d).date() - today()).days
    if days == 1:
        return "завтра"
    return f"через {days} {plural(days, 'день', 'дня', 'дней')}"


def deadline_line(d: dict) -> str:
    when = due_dt(d)
    line = f"• <b>{WD_SHORT[when.weekday()]} {when:%d.%m, %H:%M}</b> ({left_text(d)}) — {escape(d['title'])}"
    if d.get("course"):
        line += f"\n   <i>{escape(d['course'])}</i>"
    if d.get("text"):
        line += f"\n   {escape(d['text'])}"
    return line


def deadlines_text(within_days: int | None = None, title: str = "📚 <b>Ближайшие сдачи</b>") -> str:
    items = deadlines(within_days)
    if not items:
        return ""
    return title + "\n" + "\n".join(deadline_line(d) for d in items)
