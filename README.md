# Utility Meter Bot

MVP Telegram-бота для учёта коммунальных показаний. Текущий этап содержит
полный Telegram-сценарий без OCR: объекты, счётчики, простые тарифы, ручные
показания, расчёт начислений и историю. OCR намеренно отложен до следующего этапа.

## Возможности

- главное меню и команды `/start`, `/help`, `/cancel`;
- создание и просмотр квартир/домов;
- добавление счётчиков холодной воды, горячей воды и электричества;
- настройка простого тарифа для объекта и типа ресурса;
- ручная передача показаний с `Decimal`-расчётом расхода и стоимости;
- предупреждение и отдельное подтверждение аномально большого прироста;
- последние подтверждённые показания по каждому счётчику;
- атомарное сохранение показания, расчётного периода и начисления в PostgreSQL.

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
.venv/bin/ruff check src tests
.venv/bin/mypy src
.venv/bin/python -m pytest -q
.venv/bin/python -m src.main
```

## Первый пользовательский сценарий

1. Отправьте боту `/start`.
2. Откройте «Объекты» и добавьте квартиру или дом.
3. Добавьте объекту один или несколько счётчиков.
4. В разделе «Тарифы» задайте цену соответствующего ресурса.
5. Передайте начальное ручное показание — оно станет базовым.
6. Следующее показание создаст расход и начисление за текущий месяц.

Если прирост превышает настроенный месячный лимит, бот не сохраняет значение до
явного нажатия «Всё равно сохранить».

## Docker Compose

```bash
docker compose up --build -d
docker compose logs -f app
```

Compose запускает только application container. Volume `paddle_models` уже
предусмотрен для будущего локального OCR на Raspberry Pi; PostgreSQL локально не
поднимается.
