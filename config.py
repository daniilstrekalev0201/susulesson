"""Настройки бота. Всё берётся из переменных окружения (в Bothost — раздел «Переменные»)."""

import os
from datetime import timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Номер группы так, как он написан на susu.ru, например КЭ-101.
# Можно поменять прямо в боте командой /group.
GROUP = os.getenv("GROUP", "П-377").strip()

# Telegram ID админов через запятую. Админы добавляют ДЗ вручную и видят /status.
DEFAULT_ADMIN_IDS = "974443828"
ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", DEFAULT_ADMIN_IDS).replace(" ", "").split(",") if x
}

# Логин и пароль от «Универиса» — бот заходит в edu.susu.ru и смотрит сроки сдачи заданий.
# Вписываются только в Bothost, в код и GitHub не попадают. Без них бот работает только
# с расписанием и ДЗ, которые админы добавили вручную.
EDU_LOGIN = os.getenv("EDU_LOGIN", "").strip()
EDU_PASSWORD = os.getenv("EDU_PASSWORD", "")

# Постоянная папка для данных (на Bothost — /app/data).
DATA_DIR = os.getenv("DATA_DIR", "/app/data" if os.path.isdir("/app/data") else "data")

# Челябинск, UTC+5.
LOCAL_TZ = timezone(timedelta(hours=5))

MORNING_AT = os.getenv("MORNING_AT", "07:00")  # утренняя сводка: пары сегодня и ближайшие сдачи
EVENING_AT = os.getenv("EVENING_AT", "20:00")  # вечером: пары на завтра
BEFORE_PAIR_MIN = int(os.getenv("BEFORE_PAIR_MIN", "15"))  # напоминание перед парой
# За сколько часов до срока сдачи напоминать.
DEADLINE_REMIND_HOURS = (72, 24, 3)

SCHEDULE_REFRESH_MIN = 180
EDU_REFRESH_MIN = 60
