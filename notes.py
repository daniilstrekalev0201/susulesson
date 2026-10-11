"""Конспекты лекций в PDF: «📖 Конспекты» → предмет → лекция → файл.

Список берётся из konspekty/pdf/index.json (его собирает konspekty/build.py).
Файл отправляется в Telegram один раз, дальше бот пересылает его по file_id.
"""

import json
import logging
import os
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (CallbackQuery, FSInputFile, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

import storage

BTN = "📖 Конспекты"
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "konspekty", "pdf")

log = logging.getLogger(__name__)
router = Router()


def _load() -> dict:
    try:
        with open(os.path.join(BASE, "index.json"), encoding="utf-8") as f:
            return {s["slug"]: s for s in json.load(f)}
    except (OSError, ValueError) as e:
        log.warning("Нет списка конспектов: %r", e)
        return {}


SUBJECTS = _load()


def subjects_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"{s['subject']} ({len(s['lectures'])})",
                                  callback_data=f"ks:{slug}")] for slug, s in SUBJECTS.items()]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def lectures_kb(slug: str) -> InlineKeyboardMarkup:
    rows = []
    for lec in SUBJECTS[slug]["lectures"]:
        title = lec["title"] if len(lec["title"]) <= 55 else lec["title"][:54] + "…"
        rows.append([InlineKeyboardButton(text=f"{lec['lecture']}. {title}",
                                          callback_data=f"kl:{slug}:{lec['lecture']}")])
    rows.append([InlineKeyboardButton(text="« Все предметы", callback_data="ks:")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("konspekty"))
@router.message(F.text == BTN)
async def show_subjects(message: Message) -> None:
    if not SUBJECTS:
        await message.answer("Конспектов пока нет.")
        return
    await message.answer("📖 Конспекты лекций в PDF (оформлены по СТО ЮУрГУ).\nВыберите предмет:",
                         reply_markup=subjects_kb())


@router.callback_query(F.data.startswith("ks:"))
async def show_lectures(call: CallbackQuery) -> None:
    slug = call.data[3:]
    await call.answer()
    try:
        if slug in SUBJECTS:
            await call.message.edit_text(f"📖 <b>{escape(SUBJECTS[slug]['subject'])}</b>\nВыберите лекцию:",
                                         reply_markup=lectures_kb(slug))
        else:
            await call.message.edit_text("📖 Выберите предмет:", reply_markup=subjects_kb())
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("kl:"))
async def send_lecture(call: CallbackQuery, bot: Bot) -> None:
    _, slug, num = call.data.split(":")
    subject = SUBJECTS.get(slug)
    lec = next((x for x in subject["lectures"] if str(x["lecture"]) == num), None) if subject else None
    if not lec:
        await call.answer("Конспект не найден", show_alert=True)
        return
    path = os.path.join(BASE, slug, lec["file"])
    await call.answer("Отправляю конспект…")
    # Ключ включает размер файла: после пересборки PDF бот загрузит новую версию.
    key = f"{slug}/{lec['file']}:{os.path.getsize(path)}"
    cache = storage.state.setdefault("file_ids", {})
    caption = f"📖 {escape(subject['subject'])}\nЛекция {lec['lecture']}. {escape(lec['title'])}"
    document = cache.get(key) or FSInputFile(path, filename=f"{subject['subject'][:40]} – лекция {num}.pdf")
    msg = await bot.send_document(call.message.chat.id, document, caption=caption[:1024])
    if key not in cache and msg.document:
        cache[key] = msg.document.file_id
        storage.save()
