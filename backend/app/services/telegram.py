"""Messages to the team's Telegram: a payment waiting to be checked.

The same bot deploy/monitor.sh alerts through - TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID in .env. Payments may go to another chat than the server
alerts (PAYMENT_TELEGRAM_CHAT_ID), for whoever checks Kaspi.

Like the mail, a message never fails or slows the request it reports on:
it is sent in the background and a failure is a log line.

    docker compose exec backend python -m app.services.telegram

sends a test message, to check the settings.
"""

import asyncio
import json
import urllib.parse
import urllib.request
from typing import Optional

from app import config

_pending: set = set()


def configured() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and payments_chat())


def payments_chat() -> str:
    return config.PAYMENT_TELEGRAM_CHAT_ID or config.TELEGRAM_CHAT_ID


def _post(chat_id: str, text: str) -> None:
    body = urllib.parse.urlencode({
        "chat_id": chat_id, "text": text, "disable_web_page_preview": "true",
    }).encode()
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=15) as response:
        reply = json.loads(response.read().decode() or "{}")
    if not reply.get("ok"):
        raise RuntimeError(str(reply.get("description") or "not ok")[:200])


async def send(text: str, chat_id: Optional[str] = None) -> bool:
    chat = chat_id or payments_chat()
    if not config.TELEGRAM_BOT_TOKEN or not chat:
        return False
    try:
        await asyncio.to_thread(_post, chat, text[:4000])
        return True
    except Exception as e:  # noqa: BLE001 - reported, never raised
        # The token is in the URL, so the error is described, never printed whole.
        print(f"[telegram] send failed: {type(e).__name__} {getattr(e, 'code', '')}".rstrip(), flush=True)
        return False


def send_later(text: str) -> None:
    """Send without making the request wait for Telegram."""
    if not configured():
        return
    task = asyncio.create_task(send(text))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


if __name__ == "__main__":
    if not configured():
        raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (or PAYMENT_TELEGRAM_CHAT_ID) are not set.")
    ok = asyncio.run(send("Akron: тестовое сообщение. Уведомления о платежах будут приходить сюда."))
    raise SystemExit(0 if ok else "Not sent - check the token, the chat id, and that you wrote to the bot first.")
