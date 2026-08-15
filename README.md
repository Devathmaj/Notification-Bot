# Notification Bot

Shared runtime for Discord (and later Telegram) notification bots.

The bot receives Supabase-style change events via a webhook, reads the row from the
external `public.notification_posts` table, and pushes notifications to users (DM or a
server channel) based on their stored preferences. Users can also query the latest posts
with `/latest` and `/top`.

## Layout

```
config.py            shared pydantic-settings (reads .env)
main.py              entrypoint: runs Discord bot + FastAPI webhook on one asyncio loop
webhook/             FastAPI server, Bearer auth, handlers, per-IP rate limiting
bot/discord/bot/       Discord client, /latest & /top commands, notifier
bot/discord/database/  SQLAlchemy models, connection, preferences repo, posts reader
bot/discord/tests/     pytest suite (SQLite in-memory)
Dockerfile             container image (single process hosts bot + webhook)
```

## Setup

1. Copy `.env.example` to `.env` and fill in:
   - `DISCORD_TOKEN`
   - `WEBHOOK_SECRET`
   - `DATABASE_URL` (Supabase, port 5432 direct)
2. **First run** must use the `postgres` owner URL so the tables are created
   (`CREATE TABLE IF NOT EXISTS`). Optionally set `DB_APP_USER` to auto-GRANT the app role
   `SELECT` on `public.notification_posts` and DML on our tables on that first boot.
3. Switch `DATABASE_URL` to the DML-only app user. Later startups detect the existing tables
   and skip DDL automatically.

## Run

```sh
# Bare metal
python -m main            # or: pip install -e .

# Docker
docker build -t notification-bot:latest .
docker run -d --name notification-bot -p 43217:43217 --env-file .env notification-bot:latest
```

Webhook server on `:43217`. `WEBHOOK_PORT` overrides the default.

## Webhook contract

`POST /webhook` with header `Authorization: Bearer <WEBHOOK_SECRET>` and a Supabase
INSERT event for `public.notification_posts`. The bot uses `id`, `title`,
`promotion_name`, `promotion_type`, `registration_url`, `created_at`, and `ai_result`.
Retried events are deduped per user in `sent_messages` and acked with `200`.

Useful header for your originating endpoint: **`Authorization: Bearer <WEBHOOK_SECRET>`**.

## Commands

- `/latest` — newest post
- `/top <n>` — the `n` most recent posts (1–100); errors otherwise