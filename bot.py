"""Бот группы ЮУрГУ: расписание пар и напоминания о сроках сдачи ДЗ."""

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta
from html import escape

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (BotCommand, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, KeyboardButton, Message,
                           ReplyKeyboardMarkup)

import edu
import schedule
import storage
import texts
from config import (ADMIN_IDS, BEFORE_PAIR_MIN, BOT_TOKEN, DEADLINE_REMIND_HOURS,
                    EVENING_AT, LOCAL_TZ, MORNING_AT)

log = logging.getLogger("bot")
router = Router()

B_TODAY, B_TOMORROW, B_WEEK, B_DZ, B_SETTINGS, B_ADD = (
    "📅 Сегодня", "📆 Завтра", "🗓 Неделя", "📚 Сдачи", "⚙️ Уведомления", "➕ Добавить ДЗ")

SETTINGS = [
    ("morning", f"Утром ({MORNING_AT}): пары и сдачи"),
    ("evening", f"Вечером ({EVENING_AT}): пары на завтра"),
    ("before", f"За {BEFORE_PAIR_MIN} мин до каждой пары"),
    ("deadlines", "Сроки сдачи и новые задания"),
]


def is_admin(user_id: int | None) -> bool:
    return user_id in ADMIN_IDS


def main_kb(user_id: int | None) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=B_TODAY), KeyboardButton(text=B_TOMORROW)],
            [KeyboardButton(text=B_WEEK), KeyboardButton(text=B_DZ)],
            [KeyboardButton(text=B_SETTINGS)]]
    if is_admin(user_id):
        rows[-1].append(KeyboardButton(text=B_ADD))
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def chat_title(message: Message) -> str:
    chat = message.chat
    return chat.title or chat.full_name or ""


async def answer_schedule(message: Message, text: str) -> None:
    problem = texts.no_schedule_text()
    if problem and not storage.state["lessons"]:
        text = problem
    await message.answer(text)


# ---------- студентам ----------

@router.message(CommandStart())
async def start(message: Message) -> None:
    storage.subscriber(message.chat.id, chat_title(message))
    storage.save()
    group = schedule.current_group() or "—"
    text = (f"Привет! Я бот группы <b>{escape(group)}</b>.\n\n"
            f"Каждое утро в {MORNING_AT} пришлю пары на день и ближайшие сдачи, "
            f"вечером в {EVENING_AT} — пары на завтра, а ещё напомню о сроках сдачи "
            f"за 3 дня, за день и за 3 часа.\n\n"
            "Настроить уведомления — «⚙️ Уведомления» или /settings, отписаться — /stop.")
    if message.chat.type == ChatType.PRIVATE:
        await message.answer(text, reply_markup=main_kb(message.from_user.id))
    else:
        await message.answer(text + "\n\nКоманды: /today /tomorrow /week /dz /settings")


@router.message(Command("stop"))
async def stop(message: Message) -> None:
    storage.state["subscribers"].pop(str(message.chat.id), None)
    storage.save()
    await message.answer("Больше не пишу сюда. Вернуться — /start.")


@router.message(Command("today"))
@router.message(F.text == B_TODAY)
async def today(message: Message) -> None:
    await answer_schedule(message, texts.day_text(texts.today()))


@router.message(Command("tomorrow"))
@router.message(F.text == B_TOMORROW)
async def tomorrow(message: Message) -> None:
    await answer_schedule(message, texts.day_text(texts.today() + timedelta(days=1)))


@router.message(Command("week"))
@router.message(F.text == B_WEEK)
async def week(message: Message) -> None:
    await answer_schedule(message, texts.week_text(texts.today()))


def dz_admin_kb() -> InlineKeyboardMarkup | None:
    manual = [d for d in texts.deadlines() if d.get("source") == "manual"]
    if not manual:
        return None
    rows = [[InlineKeyboardButton(text=f"🗑 {d['course'][:20]}: {d['title'][:25]}",
                                  callback_data=f"del:{d['id']}")] for d in manual]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("dz"))
@router.message(F.text == B_DZ)
async def dz(message: Message) -> None:
    text = texts.deadlines_text() or "Ближайших сдач нет 🎉"
    if edu.enabled() and storage.state["edu"]["error"] and is_admin(message.from_user.id):
        text += f"\n\n⚠️ edu.susu.ru: {escape(storage.state['edu']['error'])}"
    markup = dz_admin_kb() if is_admin(message.from_user.id) and message.chat.type == ChatType.PRIVATE else None
    await message.answer(text, reply_markup=markup, disable_web_page_preview=True)


@router.callback_query(F.data.startswith("del:"))
async def delete_hw(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Только для админов", show_alert=True)
        return
    hw_id = call.data.split(":", 1)[1]
    storage.state["homework"] = [d for d in storage.state["homework"] if d["id"] != hw_id]
    storage.save()
    await call.answer("Удалено")
    await call.message.edit_text(texts.deadlines_text() or "Ближайших сдач нет 🎉",
                                 reply_markup=dz_admin_kb(), disable_web_page_preview=True)


def settings_kb(chat_id: int) -> InlineKeyboardMarkup:
    sub = storage.state["subscribers"].get(str(chat_id), {})
    rows = [[InlineKeyboardButton(text=("✅ " if sub.get(key) else "▫️ ") + label,
                                  callback_data=f"set:{key}")] for key, label in SETTINGS]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("settings"))
@router.message(F.text == B_SETTINGS)
async def settings(message: Message) -> None:
    storage.subscriber(message.chat.id, chat_title(message))
    storage.save()
    await message.answer("Что присылать (нажмите, чтобы включить или выключить):",
                         reply_markup=settings_kb(message.chat.id))


@router.callback_query(F.data.startswith("set:"))
async def toggle(call: CallbackQuery) -> None:
    sub = storage.subscriber(call.message.chat.id)
    key = call.data.split(":", 1)[1]
    sub[key] = not sub.get(key)
    storage.save()
    await call.answer("Включено" if sub[key] else "Выключено")
    try:
        await call.message.edit_reply_markup(reply_markup=settings_kb(call.message.chat.id))
    except TelegramBadRequest:
        pass


@router.message(Command("myid"))
async def myid(message: Message) -> None:
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


# ---------- админам ----------

@router.message(Command("group"))
async def set_group(message: Message, command: CommandObject, http: aiohttp.ClientSession) -> None:
    if not is_admin(message.from_user.id):
        return
    if not command.args:
        await message.answer(f"Сейчас группа: <b>{escape(schedule.current_group() or '—')}</b>\n"
                             "Поменять: /group КЭ-101")
        return
    group = command.args.strip()
    await message.answer(f"Ищу {escape(group)} на susu.ru…")
    url = await schedule.find_group_url(http, group)
    if not url:
        await message.answer("Не нашёл такую группу. Проверьте, как она написана на "
                             "www.susu.ru/ru/raspisanie-zanyatiy")
        return
    st = storage.state
    st.update(group=group, group_url=url, lessons=[], lessons_at=0)
    await schedule.refresh(http, force=True)
    await message.answer(f"Готово, группа <b>{escape(group)}</b>: "
                         f"{len(st['lessons'])} пар в расписании.\n{url}")


@router.message(Command("status"))
async def status(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    st = storage.state

    def ago(ts: float) -> str:
        if not ts:
            return "ещё не было"
        return datetime.fromtimestamp(ts, LOCAL_TZ).strftime("%d.%m %H:%M")

    if not edu.enabled():
        edu_line = "не подключён (нет EDU_LOGIN / EDU_PASSWORD)"
    elif st["edu"]["error"]:
        edu_line = f"ошибка: {escape(st['edu']['error'])}"
    else:
        edu_line = f"ок, {len(st['edu']['deadlines'])} сроков, обновлено {ago(st['edu']['at'])}"
    chats = st["subscribers"]
    groups = sum(1 for k in chats if k.startswith("-"))
    await message.answer(
        f"Группа: <b>{escape(schedule.current_group() or '—')}</b>\n"
        f"Страница: {st.get('group_url') or 'не найдена'}\n"
        f"Расписание: {len(st['lessons'])} пар, обновлено {ago(st['lessons_at'])}\n"
        f"edu.susu.ru: {edu_line}\n"
        f"ДЗ вручную: {len(st['homework'])}\n"
        f"Подписчиков: {len(chats) - groups} + чатов {groups}\n\n"
        "Обновить сейчас — /refresh", disable_web_page_preview=True)


@router.message(Command("refresh"))
async def refresh_now(message: Message, http: aiohttp.ClientSession, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return
    await schedule.refresh(http, force=True)
    new = await edu.refresh(http, force=True)
    await announce_new(bot, new)
    await status(message)


class AddHW(StatesGroup):
    subject = State()
    task = State()
    due = State()


def subjects_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=s[:40], callback_data=f"subj:{i}")]
            for i, s in enumerate(schedule.subjects())]
    rows.append([InlineKeyboardButton(text="✖️ Отмена", callback_data="hw_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("add"))
@router.message(F.text == B_ADD)
async def add_hw(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AddHW.subject)
    await message.answer("По какому предмету ДЗ? Выберите или напишите название.",
                         reply_markup=subjects_kb())


@router.callback_query(F.data == "hw_cancel")
async def hw_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.answer()
    await call.message.edit_text("Отменено.")


@router.callback_query(AddHW.subject, F.data.startswith("subj:"))
async def hw_subject_button(call: CallbackQuery, state: FSMContext) -> None:
    names = schedule.subjects()
    i = int(call.data.split(":")[1])
    await call.answer()
    if i >= len(names):
        return
    await state.update_data(subject=names[i])
    await state.set_state(AddHW.task)
    await call.message.edit_text(f"Предмет: <b>{escape(names[i])}</b>\nЧто нужно сделать?")


@router.message(AddHW.subject, F.text)
async def hw_subject_text(message: Message, state: FSMContext) -> None:
    await state.update_data(subject=message.text.strip())
    await state.set_state(AddHW.task)
    await message.answer("Что нужно сделать?")


@router.message(AddHW.task, F.text)
async def hw_task(message: Message, state: FSMContext) -> None:
    await state.update_data(task=message.text.strip())
    await state.set_state(AddHW.due)
    await message.answer("Когда сдавать? Напишите дату, например <code>15.10</code> или "
                         "<code>15.10 18:00</code>, либо «завтра». Без времени — до 23:59.")


def parse_due(text: str) -> datetime | None:
    text = text.strip().lower()
    base = texts.today()
    words = {"сегодня": 0, "завтра": 1, "послезавтра": 2}
    first = text.split()[0] if text else ""
    m_time = re.search(r"(\d{1,2})[:.](\d{2})\s*$", text) if " " in text or first in words else None
    hour, minute = (int(m_time.group(1)), int(m_time.group(2))) if m_time else (23, 59)
    if first in words:
        day = base + timedelta(days=words[first])
    else:
        m = re.match(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?", text)
        if not m:
            return None
        year = int(m.group(3)) if m.group(3) else base.year
        if year < 100:
            year += 2000
        try:
            day = datetime(year, int(m.group(2)), int(m.group(1))).date()
        except ValueError:
            return None
        if not m.group(3) and day < base:
            day = day.replace(year=year + 1)
    if hour > 23 or minute > 59:
        return None
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=LOCAL_TZ)


@router.message(AddHW.due, F.text)
async def hw_due(message: Message, state: FSMContext) -> None:
    due = parse_due(message.text)
    if not due or due.timestamp() < time.time():
        await message.answer("Не понял дату (или она уже прошла). Пример: <code>15.10 18:00</code>")
        return
    data = await state.get_data()
    await state.clear()
    st = storage.state
    item = {"id": f"m{st['next_id']}", "title": data["task"], "course": data["subject"],
            "due": int(due.timestamp()), "source": "manual"}
    st["next_id"] += 1
    st["homework"].append(item)
    storage.save()
    await message.answer("Добавлено:\n" + texts.deadline_line(item),
                         reply_markup=main_kb(message.from_user.id))
    await announce_new(message.bot, [item], skip_chat=message.chat.id)


# ---------- рассылки ----------

async def send(bot: Bot, chat_id: str, text: str) -> None:
    try:
        await bot.send_message(int(chat_id), text, disable_web_page_preview=True)
    except TelegramForbiddenError:
        storage.state["subscribers"].pop(chat_id, None)  # бота заблокировали или выгнали
    except TelegramBadRequest as e:
        log.warning("Не отправилось в %s: %s", chat_id, e)
        if "chat not found" in str(e):
            storage.state["subscribers"].pop(chat_id, None)
    await asyncio.sleep(0.05)


async def broadcast(bot: Bot, setting: str, text: str, skip_chat: int | None = None) -> None:
    for chat_id, sub in list(storage.state["subscribers"].items()):
        if sub.get(setting) and chat_id != str(skip_chat):
            await send(bot, chat_id, text)
    storage.save()


async def announce_new(bot: Bot, items: list[dict], skip_chat: int | None = None) -> None:
    for d in items:
        if d["due"] > time.time():
            storage.mark_sent(f"new:{d['id']}")
            await broadcast(bot, "deadlines", "🆕 <b>Новое задание</b>\n" + texts.deadline_line(d),
                            skip_chat)


def _at(hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return texts.now().replace(hour=h, minute=m, second=0, microsecond=0)


async def tick(bot: Bot) -> None:
    now = texts.now()
    day = now.date()
    # Если бот перезапускался, сводку всё равно шлём, но не позже чем через 2 часа.
    window = timedelta(hours=2)

    key = f"morning:{day}"
    if _at(MORNING_AT) <= now < _at(MORNING_AT) + window and not storage.was_sent(key):
        storage.mark_sent(key)
        lessons = schedule.for_day(day)
        soon = texts.deadlines_text(3, "📚 <b>Сдать в ближайшие 3 дня</b>")
        if lessons or soon:
            parts = ["☀️ Доброе утро!", texts.day_text(day, "Сегодня пар нет 🎉")]
            if soon:
                parts.append(soon)
            await broadcast(bot, "morning", "\n\n".join(parts))

    key = f"evening:{day}"
    if _at(EVENING_AT) <= now < _at(EVENING_AT) + window and not storage.was_sent(key):
        storage.mark_sent(key)
        next_day = day + timedelta(days=1)
        if schedule.for_day(next_day):
            await broadcast(bot, "evening", "🌙 Пары на завтра\n\n" + texts.day_text(next_day))

    for lesson in schedule.for_day(day):
        start = schedule.start_dt(lesson)
        key = f"pair:{lesson['date']}:{lesson['start']}:{lesson['subject']}:{lesson['subgroup']}"
        if start - timedelta(minutes=BEFORE_PAIR_MIN) <= now < start and not storage.was_sent(key):
            storage.mark_sent(key)
            minutes = max(1, round((start - now).total_seconds() / 60))
            await broadcast(bot, "before", f"🔔 Через {minutes} мин\n"
                            + texts.lesson_line(lesson))

    for d in texts.deadlines():
        left_h = (d["due"] - time.time()) / 3600
        stages = [h for h in DEADLINE_REMIND_HOURS if left_h <= h]
        keys = [f"dl:{d['id']}:{d['due']}:{h}" for h in stages]
        if not stages or all(storage.was_sent(k) for k in keys):
            continue
        for k in keys:
            storage.mark_sent(k)  # сразу все пройденные ступени — без пачки напоминаний подряд
        await broadcast(bot, "deadlines", f"⏰ <b>Срок сдачи {texts.left_text(d)}</b>\n"
                        + texts.deadline_line(d))


async def background(bot: Bot, http: aiohttp.ClientSession) -> None:
    while True:
        try:
            await schedule.refresh(http)
            new = await edu.refresh(http)
            await announce_new(bot, [d for d in new if not storage.was_sent(f"new:{d['id']}")])
            error = storage.state["edu"]["error"]
            if error and not storage.was_sent(f"edu_err:{error}"):
                storage.mark_sent(f"edu_err:{error}")
                for admin in ADMIN_IDS:
                    await send(bot, str(admin), f"⚠️ Не получается зайти в edu.susu.ru: {escape(error)}\n"
                               "Проверьте EDU_LOGIN и EDU_PASSWORD в Bothost. Состояние — /status")
            await tick(bot)
            # Старые ДЗ, добавленные вручную, через неделю после срока убираем.
            week_ago = time.time() - 7 * 86400
            storage.state["homework"] = [d for d in storage.state["homework"] if d["due"] > week_ago]
            storage.prune_sent()
            storage.save()
        except Exception:
            log.exception("Ошибка в фоновой задаче")
        await asyncio.sleep(30)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not BOT_TOKEN:
        raise SystemExit("Нет BOT_TOKEN — впишите токен от @BotFather в переменные окружения.")
    storage.load()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    http = aiohttp.ClientSession()
    dp = Dispatcher(http=http)
    dp.include_router(router)
    await bot.set_my_commands([
        BotCommand(command="today", description="Пары сегодня"),
        BotCommand(command="tomorrow", description="Пары завтра"),
        BotCommand(command="week", description="Пары на неделю"),
        BotCommand(command="dz", description="Ближайшие сдачи"),
        BotCommand(command="settings", description="Уведомления"),
        BotCommand(command="stop", description="Отписаться"),
    ])
    task = asyncio.create_task(background(bot, http))
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()
        await http.close()


if __name__ == "__main__":
    asyncio.run(main())
