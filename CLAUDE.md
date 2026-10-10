# Бот группы ЮУрГУ (susulesson)

Telegram-бот на aiogram 3: расписание пар группы и напоминания о сроках сдачи ДЗ, для всей группы.
Пользователь — не программист, общаемся по-русски, объясняем по шагам.

## Источники данных (проверено 11.10.2026)
- Расписание: `https://www.susu.ru/ru/lessons/<транслит группы>` (КЭ-101 → ke-101), таблица `table.schedule`,
  строки `tr.weekday` (дата в h2) и `tr.week-N.subgroup-M` (время, подгруппа, аудитория, дисциплина<br><small>вид</small>).
  На странице ~2 недели вперёд. Список институтов — `/ru/raspisanie-zanyatiy` → `/ru/lessons/<число>`.
  schedule.susu.ru (Универис) — для составителей, API требует вход; его public-выход устарел, не использовать.
- edu.susu.ru — Moodle, мобильный сервис включён: `login/token.php` (service=moodle_mobile_app, логин/пароль
  «Универиса») → `webservice/rest/server.php`. Сроки берём из `core_calendar_get_calendar_events` по курсам
  (eventtype due/close), а не из личного списка дел — чтобы не пропадали, когда владелец аккаунта сдал работу.
  ПРОВЕРИТЬ после появления логина: /status, формат событий, нет ли лишних событий.
  Логин/пароль вписывает пользователь в Bothost сам (EDU_LOGIN/EDU_PASSWORD); мы их не вводим.

## Файлы
`bot.py` (кнопки, админка /add /group /status /refresh, фоновые рассылки `tick`), `schedule.py`, `edu.py`,
`texts.py` (оформление), `storage.py` (всё в DATA_DIR/state.json, на Bothost /app/data), `config.py`.

## Где работает (с 11.10.2026)
Бот @SusuLesson_bot («Student Helper»), группа П-377. Bothost: `bot_1791673439_7303_daniilstrekalev`,
тот же аккаунт и тариф «Базовый», что у косметики (до 5 ботов, отдельно платить не нужно).
Переменные: BOT_TOKEN, EDU_LOGIN, EDU_PASSWORD (GROUP и ADMIN_IDS по умолчанию из config.py).
api/bots.php?path=status_get отдаёт значения переменных открытым текстом — не выводить их в чат.

## Выкладка
GitHub: https://github.com/daniilstrekalev0201/susulesson (public, main). Хостинг — Bothost, как у бота
косметики (см. D:\бот косметика\CLAUDE.md про «Обновить из Git» и confirm()). Локально бота не запускать,
если он уже работает на сервере (Conflict getUpdates).
