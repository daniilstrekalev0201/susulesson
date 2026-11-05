"""Кто может добавлять ДЗ: владельцы (ADMIN_IDS) и помощники, которых они пригласили.

Владелец нажимает «👥 Доступ» → «➕ Пригласить» и пересылает одноразовую ссылку
t.me/<бот>?start=adm_<код>. Кто откроет её первым, тот и становится помощником.
Помощники хранятся в state["admins"], ссылки — в state["invites"].
"""

import secrets
import time
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           Message, User)

import storage
from config import ADMIN_IDS

BTN = "👥 Доступ"
INVITE_PREFIX = "adm_"
INVITE_HOURS = 24

router = Router()


def is_owner(user_id: int | None) -> bool:
    return user_id in ADMIN_IDS


def is_admin(user_id: int | None) -> bool:
    return is_owner(user_id) or str(user_id) in storage.state["admins"]


def _name(user: User) -> str:
    return user.full_name + (f" (@{user.username})" if user.username else "")


def _prune_invites() -> None:
    border = time.time() - INVITE_HOURS * 3600
    storage.state["invites"] = {k: v for k, v in storage.state["invites"].items() if v["at"] > border}


def accept(code: str, user: User) -> int | None:
    """Принимает приглашение. Возвращает ID владельца, который его выдал, или None."""
    _prune_invites()
    invite = storage.state["invites"].pop(code, None)
    if not invite:
        storage.save()
        return None
    storage.state["admins"][str(user.id)] = {"name": _name(user), "by": invite["by"], "at": int(time.time())}
    storage.save()
    return invite["by"]


def access_text() -> str:
    admins = storage.state["admins"]
    lines = ["👥 <b>Доступ к ДЗ</b>",
             "Помощники могут добавлять и удалять ДЗ (кнопка «➕ Добавить ДЗ»), "
             "смотреть /status и обновлять данные /refresh. Выдавать доступ можете только вы.", ""]
    if admins:
        lines.append("Помощники:")
        lines += [f"• {escape(a['name'])}" for a in admins.values()]
        lines.append("\nЧтобы забрать доступ, нажмите 🗑 рядом с именем.")
    else:
        lines.append("Помощников пока нет.")
    return "\n".join(lines)


def access_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"🗑 {a['name'][:40]}", callback_data=f"acc_del:{uid}")]
            for uid, a in storage.state["admins"].items()]
    rows.append([InlineKeyboardButton(text="➕ Пригласить помощника", callback_data="acc_inv")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("access"))
@router.message(F.text == BTN)
async def show_access(message: Message) -> None:
    if not is_owner(message.from_user.id):
        await message.answer("Выдавать доступ может только владелец бота.")
        return
    await message.answer(access_text(), reply_markup=access_kb())


@router.callback_query(F.data == "acc_inv")
async def invite(call: CallbackQuery, bot: Bot) -> None:
    if not is_owner(call.from_user.id):
        await call.answer("Только для владельца", show_alert=True)
        return
    _prune_invites()
    code = secrets.token_urlsafe(12)
    storage.state["invites"][code] = {"by": call.from_user.id, "at": int(time.time())}
    storage.save()
    me = await bot.me()
    await call.answer()
    await call.message.answer(
        "Перешлите эту ссылку человеку, которому даёте доступ. Она одноразовая и действует "
        f"{INVITE_HOURS} часа — кто откроет первым, тот и получит доступ:\n\n"
        f"https://t.me/{me.username}?start={INVITE_PREFIX}{code}",
        disable_web_page_preview=True)


@router.callback_query(F.data.startswith("acc_del:"))
async def revoke(call: CallbackQuery, bot: Bot) -> None:
    if not is_owner(call.from_user.id):
        await call.answer("Только для владельца", show_alert=True)
        return
    uid = call.data.split(":", 1)[1]
    removed = storage.state["admins"].pop(uid, None)
    storage.save()
    await call.answer("Доступ забран" if removed else "Уже без доступа")
    try:
        await call.message.edit_text(access_text(), reply_markup=access_kb())
    except TelegramBadRequest:
        pass
    if removed:
        try:
            await bot.send_message(int(uid), "Доступ к добавлению ДЗ отключён. Обновить кнопки — /start")
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
