"""Как бот показывает пары и сроки сдачи."""

import re
import time
from datetime import date, datetime, timedelta
from html import escape

import notes
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
    "Лабораторные занятия": "лаба",
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


def kind_name(kind: str) -> str:
    return KINDS.get(kind, kind.lower())


def lesson_line(x: dict) -> str:
    number = PAIR_NUMBERS.get(x["start"])
    mark = NUM_EMOJI[number] if number else "▫️"
    kind = kind_name(x["kind"])
    parts = [f"{mark} {x['start']}–{x['end']} <b>{escape(x['subject'])}</b>"]
    if kind:
        parts[0] += f" ({escape(kind)})"
    extra = []
    if x["room"].upper().startswith("ДОТ"):
        extra.append("дистанционно")
    elif x["room"]:
        extra.append(f"ауд. {escape(x['room'])}")
    if x["subgroup"]:
        extra.append(f"подгр. {escape(x['subgroup'])}")
    who = teachers(x["subject"])
    if who:
        extra.append(f"👤 {escape(', '.join(who))}")
    if extra:
        parts.append("      " + " · ".join(extra))
    note = change_note(x)
    if note:
        parts.append("      " + note)
    return "\n".join(parts)


# ---------- изменения в расписании ----------

def _when(x: dict) -> str:
    day = date.fromisoformat(x["date"])
    return f"{WD_SHORT[day.weekday()]} {day:%d.%m} {x['start']}"


def _moves(changes: dict) -> dict[str, str]:
    """Переносы: отменённая пара + новая пара того же предмета → {ключ новой: ключ отменённой}
    и обратно. Сначала ищем в тот же день, потом среди замеченных одновременно."""
    added = {k: c["cur"] for k, c in changes.items() if c["orig"] is None and c["cur"]}
    gone = {k: c["orig"] for k, c in changes.items() if c["cur"] is None and c["orig"]}
    pairs = {}
    for same_day in (True, False):
        for ka, a in added.items():
            if ka in pairs:
                continue
            for kg, g in gone.items():
                if kg in pairs or (a["subject"], a["kind"], a["subgroup"]) != (g["subject"], g["kind"], g["subgroup"]):
                    continue
                if (a["date"] == g["date"]) if same_day else (changes[ka]["at"] == changes[kg]["at"]):
                    pairs[ka], pairs[kg] = kg, ka
                    break
    return pairs


def _what_changed(o: dict, x: dict) -> str:
    notes = []
    if o["subject"] != x["subject"]:
        notes.append(f"вместо «{escape(o['subject'])}»")
    if o["kind"] != x["kind"]:
        notes.append(f"была {escape(kind_name(o['kind']))}")
    if o["room"] != x["room"]:
        notes.append(f"ауд. {escape(o['room'] or '—')} → {escape(x['room'] or '—')}")
    if o["end"] != x["end"]:
        notes.append(f"была до {o['end']}")
    return ", ".join(notes)


def change_note(x: dict) -> str:
    """Пометка у пары, которая поменялась: «🆕 новая пара», «🔄 изменено: ауд. …» и т. п."""
    changes = storage.state["changes"]
    k = schedule.key(x)
    c = changes.get(k)
    if not c:
        return ""
    o = c["orig"]
    if o is None:
        moved = _moves(changes).get(k)
        if moved:
            old = changes[moved]["orig"]
            since = old["start"] if old["date"] == x["date"] else _when(old)
            return f"🔄 <b>перенесена</b> (была {since})"
        return "🆕 <b>новая пара</b>"
    return "🔄 <b>изменено:</b> " + _what_changed(o, x)


def cancelled_lines(day: date) -> list[tuple[str, str]]:
    """Отменённые пары дня: [(время, строка)]. Перенесённые в тот же день не показываем."""
    changes = storage.state["changes"]
    moves = _moves(changes)
    lines = []
    for k, c in changes.items():
        o = c["orig"]
        if c["cur"] is not None or not o or o["date"] != day.isoformat():
            continue
        text = f"❌ <s>{o['start']}–{o['end']} {escape(o['subject'])}</s> ({escape(kind_name(o['kind']))})"
        if k in moves:
            new = changes[moves[k]]["cur"]
            if new["date"] == o["date"]:
                continue
            text += f" — <b>перенесена на {_when(new)}</b>"
        else:
            text += " — <b>отменена</b>"
        lines.append((o["start"], text))
    return lines


def changes_text(keys: list[str]) -> str:
    """Уведомление об изменениях по ключам пар из state["changes"]."""
    changes = storage.state["changes"]
    moves = _moves(changes)
    lines, done = [], set()
    for k in sorted({k for k in keys if k in changes}):
        if k in done:
            continue
        c = changes[k]
        o, x = c["orig"], c["cur"]
        if k in moves:
            other = moves[k]
            done |= {k, other}
            old, new = (o, changes[other]["cur"]) if x is None else (changes[other]["orig"], x)
            lines.append(f"🔄 <b>{escape(old['subject'])}</b> ({escape(kind_name(old['kind']))}): "
                         f"перенесена с {_when(old)} на {_when(new)}")
        elif o is None:
            lines.append(f"🆕 {_when(x)} <b>{escape(x['subject'])}</b> ({escape(kind_name(x['kind']))})"
                         " — новая пара")
        elif x is None:
            lines.append(f"❌ {_when(o)} <b>{escape(o['subject'])}</b> ({escape(kind_name(o['kind']))})"
                         " — отменена")
        else:
            lines.append(f"🔄 {_when(x)} <b>{escape(x['subject'])}</b>: {_what_changed(o, x)}")
    if not lines:
        return ""
    return "⚠️ <b>Изменения в расписании</b>\n\n" + "\n".join(lines)


def day_text(day: date, empty: str = "Пар нет 🎉") -> str:
    rows = [(x["start"], lesson_line(x)) for x in schedule.for_day(day)] + cancelled_lines(day)
    head = f"📅 <b>{day_title(day)}</b>"
    if not rows:
        return f"{head}\n{empty}"
    rows.sort(key=lambda r: r[0])
    return head + "\n" + "\n".join(text for _, text in rows)


def week_text(start: date) -> str:
    days = [start + timedelta(days=i) for i in range(7)]
    blocks = [day_text(d) for d in days if schedule.for_day(d) or cancelled_lines(d)]
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


def short_course(name: str) -> str:
    """«2026/2027 Элементы систем автоматики (очная, П-353, …)» → «Элементы систем автоматики»."""
    name = re.sub(r"^\s*\d{4}\s*/\s*\d{4}\s*", "", name)
    name = re.sub(r"\s*\([^()]*\)\s*$", "", name)
    return name.strip()


def teachers(course: str) -> list[str]:
    """Преподаватели предмета (для пар, сдач и ДЗ, добавленных вручную).

    Сначала из конспектов (взяты со страниц курсов и проверены), потом из курсов edu.susu.ru.
    """
    name = short_course(course).lower()
    for s in notes.SUBJECTS.values():
        if s.get("teacher") and s["subject"].lower() == name:
            return [re.sub(r"(\w)\.(?=\w)", r"\1. ", t.strip()) for t in s["teacher"].split(",")]
    known = storage.state["edu"].get("teachers") or {}
    if course in known:
        return known[course]
    for full, who in known.items():
        if short_course(full).lower() == name:
            return who
    return []


def short_title(title: str) -> str:
    return re.sub(r"\s*[-–—]?\s*срок сдачи\s*$", "", title, flags=re.I).strip()


def deadline_line(d: dict) -> str:
    when = due_dt(d)
    line = (f"• <b>{WD_SHORT[when.weekday()]} {when:%d.%m, %H:%M}</b> ({left_text(d)}) — "
            f"{escape(short_title(d['title']))}")
    if d.get("course"):
        line += f"\n   <i>{escape(short_course(d['course']))}</i>"
        who = teachers(d["course"])
        if who:
            line += f" · 👤 {escape(', '.join(who))}"
    if d.get("text"):
        line += f"\n   {escape(d['text'])}"
    return line


def deadlines_text(within_days: int | None = None, title: str = "📚 <b>Ближайшие сдачи</b>") -> str:
    items = deadlines(within_days)
    if not items:
        return ""
    return title + "\n" + "\n".join(deadline_line(d) for d in items)
