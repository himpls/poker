"""Telegram opens the Mini App; club actions stay inside the application."""
import os
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, WebAppInfo


def app_url(invite=None):
    url = os.getenv("MINI_APP_URL", "").strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return None
    if invite:
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["invite"] = invite
        return urlunsplit(parts._replace(query=urlencode(query)))
    return url


async def configure_menu(bot):
    url = app_url()
    if url:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
            text="Открыть клуб", web_app=WebAppInfo(url=url)))


class MiniAppLauncher:
    async def message(self, message, bot):
        if message.chat.type != "private":
            return
        invite = None
        parts = (message.text or "").split(maxsplit=1)
        if (len(parts) == 2 and parts[0].split("@")[0] == "/start"
                and re.fullmatch(r"join_[A-Za-z0-9_-]{1,64}", parts[1])):
            invite = parts[1][5:]
        url = app_url(invite)
        if not url:
            await bot.send_message(message.chat.id,
                "Приложение временно недоступно. Попробуйте открыть его позже.")
            return
        await bot.send_message(message.chat.id,
            "Клуб, игры и результаты — в приложении. Нажмите кнопку, чтобы открыть его.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Открыть покерный клуб", web_app=WebAppInfo(url=url))]]))

    async def callback(self, query, bot):
        if not query.message or query.message.chat.type != "private" or query.message.chat.id != query.from_user.id:
            await query.answer()
            return
        await query.answer("Все действия доступны в приложении.")
        await self.message(query.message, bot)
