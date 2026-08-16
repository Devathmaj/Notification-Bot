# Notification Service for VoucherBot

The notification service for [VoucherBot](https://github.com/Devathmaj/VoucherBot). It watches for new voucher alerts and delivers them to you on **Discord** and **Telegram** — in your DMs/private chat or in the channels/groups where a feed has been set up.

## Get started

**Just visit https://voucherbot-preview.pages.dev/#notifications** — it has everything you need: how to get alerts set up, the bot invite links, permissions, and all the details for using the service on Discord and Telegram.

The rest of this document describes how the service works for end users, and below that is the **self-hosting** guide for running the project yourself.

## What it does

- **Pushes new alerts to you** — whenever VoucherBot publishes a new voucher alert, the notification service delivers it to every subscriber automatically.
- **Two platforms, one service** — receives alerts from [VoucherBot](https://github.com/Devathmaj/VoucherBot) and delivers them on **Discord** (DMs and channel feeds) and **Telegram** (private chats and groups).
- **Query the archive on demand** — newest post or the `n` most recent posts via a simple command, no scrolling required.
- **Never double-sends** — each alert is delivered to each recipient exactly once, even if the publisher retries.
- **Privacy first** — you can delete all your stored data at any time; anything extra is purged automatically.

## Commands

### Discord (slash commands)

| Command | Description |
| --- | --- |
| `/latest` | Fetch the newest notification with its full details (vendor, discount, voucher code, certifications, expiry). |
| `/top <n>` | Fetch the `n` most recent notifications (1–100), newest first. |
| `/notify dm` | Send every new alert to your private chat. |
| `/notify channel <channel> [mention]` | Post every new alert to a channel (requires **Manage Channels**; `mention` can be `none`, `here`, or `everyone`). |
| `/notify list` | Show everything you currently have enabled. |
| `/notify off <target> [channel]` | Turn off DMs or remove a channel feed. |
| `/delete` | Erase all your stored data: DM preference, channel feeds you created, and the associated delivery history. |
| `/help` | Show an overview of commands and behaviour. |

### Telegram

| Command | Description |
| --- | --- |
| `/start` | Subscribe to notifications in this private chat. |
| `/latest` | Show the newest notification with its full details. |
| `/top <n>` | Show the `n` most recent notifications, newest first (1–100). |
| `/stop` | Unsubscribe and delete your stored data. |
| `/help` | Show an overview of commands and behaviour. |

Behaviour on both platforms: new alerts are posted automatically to every configured channel feed / group the bot is in, private-chat alerts only arrive after opting in (`/notify dm` or `/start`), and unsubscribing never removes messages you already received.

---

# Self-hosting

Run the notification service yourself (Discord, Telegram, or both) on your own infrastructure.

## How it works

```
VoucherBot ──voucher_alert event──▶ POST /webhook ──▶ webhook/handlers.py
                                                      │
                                    ┌─────────────────┴─────────────────┐
                                    ▼                                   ▼
                        Discord notifier                       Telegram notifier
                        (DMs + channel feeds)                  (private chats + groups)
                                    │                                   │
                                    └───────────▶ Subscribers & sent_messages (Postgres)
```

The service runs as a single process hosting three independent parts on one asyncio loop:

1. **Webhook server** (FastAPI) — receives `voucher_alert` events, validates the `Authorization: Bearer <WEBHOOK_SECRET>` header, honors per-IP rate limits, and hands each event to the connected platform notifiers.
2. **Discord bot** — slash commands, DM delivery, and one feed per channel.
3. **Telegram bot** — registered as a Telegram webhook (`/telegram/webhook`) for `/start`, `/latest`, `/top`, `/stop`, and group feeds.

A schema pass (`ensure_schema`) creates the service's own tables (`preferences`, `channel_targets`, `sent_messages`, ...) on first boot — it never writes to VoucherBot's `posts` table, which is read-only to this service. Retried events are tracked in `sent_messages` and acked with `200`; a background sweep purges sent-message history for users who left more than 7 days ago.

## Environment

Fill in `.env` (copy from `.env.example`):

- `DISCORD_TOKEN` — Discord bot token.
- `TELEGRAM_HTTP_API_TOKEN` — Telegram bot token from BotFather.
- `TELEGRAM_WEBHOOK_URL` — full public HTTPS URL Telegram posts updates to, ending in `/telegram/webhook`.
- `WEBHOOK_SECRET` — the bearer secret the originating endpoint sends.
- `DATABASE_URL` — the Supabase Postgres URL (direct port 5432; asyncpg does not work with pgbouncer transaction mode). **First run** must use the `postgres` owner URL so the tables are created; afterwards switch to a DML-only user and startup skips DDL.
- `DB_APP_USER` — optional DML-only role auto-GRANTed the needed permissions on first boot.

A platform is enabled simply by providing its token; you can run Discord only, Telegram only, or both.

## Run

```sh
# Bare metal
python -m main

# Docker
docker build -t notification-bot:latest .
docker run -d --name notification-bot -p 43217:43217 --env-file .env notification-bot:latest
```

The webhook server binds to the `PORT` environment variable (set automatically by Render; defaults to `43217`).

## Webhook contract

`POST /webhook` with header `Authorization: Bearer <WEBHOOK_SECRET>` and a JSON payload for the `voucher_alert` event. The service uses `title`, `post`, `claim_url`, `vendor`, `promotion_name`, `promotion_type`, `voucher_code`, `discount`, `reason`, `confidence`, `certifications`, and `regions`. `sent_at` is used as the post's timestamp. The webhook is validated, then `200` is returned with the number of deliveries made; retries are deduplicated per recipient.

Health check: `HEAD /health` returns `200` when the database answers a trivial query.

## Layout

```
config.py            shared pydantic-settings (reads .env)
main.py              entrypoint: runs Discord bot + Telegram bot + FastAPI webhook on one asyncio loop
webhook/             FastAPI server, Bearer auth, event handlers, per-IP rate limiting
bot/discord/         Discord client, slash commands, notifier, SQLAlchemy models & repos
bot/telegram/        Telegram client, /start /latest /top /stop handlers, notifier, groups & users repos
bot/retention.py     purge of stale sent_messages for users who unsubscribed
bot/rate_limit.py    per-user command window rate limiting
bot/*/tests/         pytest suites (SQLite in-memory)
Dockerfile           container image (single process hosts webhook + both bots)
```