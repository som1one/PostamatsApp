"""Утилита для получения chat_id из апдейтов Telegram-бота.

Использование:

    1. Отправь боту в личке /start (а также в любую группу/канал, где он
       должен слать уведомления, отправь любое сообщение).
    2. Запусти:

           python -m backend.scripts.telegram_get_chat_ids

       Скрипт прочитает токен из ``backend/.env`` (через стандартный
       ``Settings``) и выведет последние chat_id, которые видел бот.
    3. Скопируй нужные значения в ``TELEGRAM_ADMIN_CHAT_IDS`` (через
       запятую) в ``backend/.env`` и перезапусти backend.

Скрипт ничего не пишет в БД, никаких сторонних запросов не делает —
только ``GET https://api.telegram.org/bot<token>/getUpdates``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.core.settings import settings  # noqa: E402


async def main() -> int:
    token = settings.TELEGRAM_ADMIN_BOT_TOKEN
    if not token:
        print("TELEGRAM_ADMIN_BOT_TOKEN is not configured in backend/.env")
        return 1

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    timeout = max(1.0, settings.TELEGRAM_API_TIMEOUT_SECONDS)

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url)

    if response.status_code != 200:
        print(f"Telegram API error: {response.status_code} {response.text[:200]}")
        return 1

    payload = response.json()
    if not payload.get("ok"):
        print(f"Telegram returned not ok: {payload}")
        return 1

    seen: dict[str, str] = {}
    for update in payload.get("result", []):
        msg = update.get("message") or update.get("channel_post") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            continue
        title = (
            chat.get("title")
            or chat.get("username")
            or " ".join(part for part in (chat.get("first_name"), chat.get("last_name")) if part)
            or "—"
        )
        seen[str(chat_id)] = f"{chat.get('type', 'unknown')} | {title}"

    if not seen:
        print(
            "No chats yet. Send /start to the bot in your private chat or any "
            "message in a group, then re-run."
        )
        return 0

    print("Detected chats (set CSV in TELEGRAM_ADMIN_CHAT_IDS):")
    for chat_id, info in seen.items():
        print(f"  {chat_id}  —  {info}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
