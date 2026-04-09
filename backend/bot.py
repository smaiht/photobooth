"""Telegram bot for admin control.

Commands (admin only):
  /stop     — shutdown server + kiosk
  /status   — current state, session count, printer status
  /restart  — restart the session flow (reset to idle)
"""

import os
import signal
import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command

log = logging.getLogger(__name__)

dp = Dispatcher()
_admin_id: int = 0
_get_status = None  # callback set by main.py


def is_admin(message: Message) -> bool:
    return message.from_user and message.from_user.id == _admin_id


@dp.message(Command("stop"), F.func(is_admin))
async def cmd_stop(message: Message):
    await message.answer("🛑 Выключаю...")
    os.kill(os.getpid(), signal.SIGTERM)


@dp.message(Command("status"), F.func(is_admin))
async def cmd_status(message: Message):
    if _get_status:
        info = _get_status()
        await message.answer(
            f"📊 Состояние: {info['state']}\n"
            f"📸 Сессий: {info['session_count']}\n"
            f"🖨 Печать: {'вкл' if info['print_enabled'] else 'выкл'}\n"
            f"📡 Telegram: {'вкл' if info['tg_enabled'] else 'выкл'}"
        )
    else:
        await message.answer("⚠️ Статус недоступен")


@dp.message(Command("restart"), F.func(is_admin))
async def cmd_restart(message: Message):
    if _get_status:
        info = _get_status()
        if info.get("reset_to_idle"):
            info["reset_to_idle"]()
            await message.answer("🔄 Сброшено в idle")
            return
    await message.answer("⚠️ Не удалось сбросить")


@dp.message(F.func(is_admin))
async def cmd_unknown(message: Message):
    await message.answer("Команды: /stop /status /restart")


async def start_bot(token: str, admin_id: int, get_status_cb=None):
    """Start bot polling. Call as asyncio task."""
    global _admin_id, _get_status
    _admin_id = admin_id
    _get_status = get_status_cb

    if not token:
        log.info("Telegram bot disabled (no token)")
        return

    bot = Bot(token=token)
    log.info(f"Telegram bot starting (admin: {admin_id})")
    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        log.error(f"Bot error: {e}")
