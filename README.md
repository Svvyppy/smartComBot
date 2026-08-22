# Utility Meter Bot

MVP Telegram-бота для учёта коммунальных показаний. Текущий этап содержит
Supabase persistence adapters, ручной сценарий показаний и начислений, а также
минимальную команду `/start`. OCR намеренно отложен до следующего этапа.

## Архитектура

Зависимости направлены от Telegram transport к application services и далее к
абстракциям репозиториев. Supabase SDK используется только в
`src/infrastructure/supabase`.

```text
Telegram / aiogram
        ↓
Application services
        ↓
Repository and storage protocols
        ↓
Supabase Data API / Storage
```

Идентификаторы сущностей — UUID, показания и деньги — `Decimal`/PostgreSQL
`NUMERIC`. Каждый пользовательский запрос к дочерней сущности проходит ownership
проверку по цепочке `users → properties → meters → readings`.

## Настройка Supabase

1. Создайте проект Supabase.
2. Выполните SQL-файлы из `supabase/migrations` по порядку через SQL Editor или
   Supabase CLI.
3. Скопируйте `.env.example` в `.env` и заполните `BOT_TOKEN`, `SUPABASE_URL` и
   `SUPABASE_SERVICE_ROLE_KEY`.

Service Role Key предназначен только для backend-контейнера. Не отправляйте его
в Telegram и не добавляйте `.env` в систему контроля версий. Таблицы создаются с
включённым RLS без публичных политик; private bucket `meter-photos` доступен
backend через service role.

## Локальный запуск

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/python -m src.main
```

## Docker Compose

```bash
docker compose up --build -d
docker compose logs -f app
```

Compose запускает только application container. Volume `paddle_models` уже
предусмотрен для будущего локального OCR на Raspberry Pi; PostgreSQL локально не
поднимается.

