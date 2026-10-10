"""Все данные бота в одном файле DATA_DIR/state.json."""

import json
import os
import time

from config import DATA_DIR

PATH = os.path.join(DATA_DIR, "state.json")

state: dict = {}


def _defaults() -> dict:
    return {
        "group": None,          # группа, выбранная командой /group (иначе из переменной GROUP)
        "group_url": None,      # адрес страницы группы на susu.ru
        "lessons": [],          # последнее скачанное расписание
        "lessons_at": 0,
        "subscribers": {},      # chat_id -> настройки уведомлений
        "homework": [],         # ДЗ, добавленные админами вручную
        "edu": {"token": None, "deadlines": [], "at": 0, "seen": None, "error": None},
        "sent": {},             # уже отправленные напоминания, чтобы не повторяться
        "next_id": 1,
    }


def load() -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    data = _defaults()
    if os.path.exists(PATH):
        with open(PATH, encoding="utf-8") as f:
            saved = json.load(f)
        data.update(saved)
        for key, value in _defaults()["edu"].items():
            data["edu"].setdefault(key, value)
    state.clear()
    state.update(data)
    return state


def save() -> None:
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PATH)


def was_sent(key: str) -> bool:
    return key in state["sent"]


def mark_sent(key: str) -> None:
    state["sent"][key] = int(time.time())


def prune_sent(days: int = 30) -> None:
    border = time.time() - days * 86400
    state["sent"] = {k: v for k, v in state["sent"].items() if v >= border}


def subscriber(chat_id: int, title: str = "") -> dict:
    """Настройки чата; новый чат подписывается со значениями по умолчанию."""
    subs = state["subscribers"]
    key = str(chat_id)
    if key not in subs:
        subs[key] = {"morning": True, "evening": True, "before": False, "deadlines": True}
    if title:
        subs[key]["title"] = title
    return subs[key]
