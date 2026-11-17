"""Первый этап интерфейса: клубы и приглашения. Учёт игр — следующий этап."""

import html
import json
import os
import secrets

from aiogram import Dispatcher, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import insert, select, update

from .clubs import Clubs
from .db import sessions
from .money import CURRENCIES, ClubError


class ClubUI:
    def __init__(self, db):
        self.db = db
        self.clubs = Clubs(db)

    def state(self, actor):
        with self.db.tx() as c:
            raw = c.execute(select(sessions.c.data).where(sessions.c.tg_id == actor)).scalar_one_or_none()
            return json.loads(raw) if raw else {}

    def save(self, actor, state):
        raw = json.dumps(state, ensure_ascii=False)
        with self.db.tx() as c:
            changed = c.execute(update(sessions).where(sessions.c.tg_id == actor).values(data=raw))
            if not changed.rowcount:
                c.execute(insert(sessions).values(tg_id=actor, data=raw))

    async def show(self, bot, actor, text, choices, state, edit_id=None):
        generation = secrets.token_hex(6)
        state["buttons"] = {str(i): action for i, (_, action) in enumerate(choices)}
        state["generation"] = generation
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=label, callback_data=f"{generation}:{i}")]
                for i, (label, _) in enumerate(choices)
            ]
        )
        mini_url = os.getenv("MINI_APP_URL", "").strip()
        if mini_url.startswith("https://"):
            markup.inline_keyboard.insert(0, [InlineKeyboardButton(
                text="Открыть покерный клуб", web_app=WebAppInfo(url=mini_url))])
        self.save(actor, state)
        if edit_id:
            try:
                await bot.edit_message_text(
                    chat_id=actor, message_id=edit_id, text=text, parse_mode="HTML", reply_markup=markup
                )
                return
            except TelegramBadRequest as error:
                if "message is not modified" in error.message:
                    return
                if not any(
                    s in error.message for s in ("message to edit not found", "message can't be edited")
                ):
                    raise
        await bot.send_message(actor, text, parse_mode="HTML", reply_markup=markup)

    async def home(self, bot, actor, edit_id=None):
        choices = [(r["name"], {"action": "club", "club_id": r["id"]}) for r in self.clubs.list(actor)]
        # Клубов у друзей немного; пагинация списка клубов добавляется при необходимости.
        choices.append(("Создать клуб", {"action": "create"}))
        await self.show(
            bot, actor, "<b>Покерный клуб</b>\nВыберите клуб или создайте свой.", choices, {}, edit_id
        )

    async def club(self, bot, actor, club_id, edit_id=None):
        club = self.clubs.get(actor, club_id)
        choices = [("Участники", {"action": "roster", "club_id": club_id})]
        if club["role"] in {"owner", "organizer"}:
            choices.append(("Пригласить в клуб", {"action": "invite", "club_id": club_id}))
        choices.append(("Назад", {"action": "home"}))
        await self.show(
            bot,
            actor,
            f"<b>{html.escape(club['name'])}</b>\n{club['currency']} · {club['timezone']}\n"
            "Клуб создан. Учёт игр подключим на следующем этапе.",
            choices,
            {"club_id": club_id},
            edit_id,
        )

    async def message(self, message, bot):
        if message.chat.type != "private":
            return  # Личные диалоги не превращают общий экран группы в персональную панель.
        actor = message.from_user.id
        text = (message.text or "").strip()
        state = self.state(actor)
        try:
            if text.startswith("/start"):
                parts = text.split(maxsplit=1)
                if len(parts) == 2 and parts[1].startswith("join_"):
                    club_id = self.clubs.join(actor, message.from_user.full_name, parts[1][5:])
                    await self.club(bot, actor, club_id)
                else:
                    await self.home(bot, actor)
            elif state.get("step") == "title":
                from .clubs import name_checked

                state["title"] = name_checked(text)
                state["step"] = "currency"
                await self.show(
                    bot,
                    actor,
                    "Выберите валюту клуба:",
                    [(value, {"action": "currency", "value": value}) for value in CURRENCIES]
                    + [("Отмена", {"action": "home"})],
                    state,
                )
            elif state.get("step") == "timezone":
                from .clubs import timezone_checked

                state["timezone"] = timezone_checked(text)
                state["step"] = "confirm"
                await self.show(
                    bot,
                    actor,
                    f"Создать клуб <b>{html.escape(state['title'])}</b>?\n"
                    f"{state['currency']} · {state['timezone']}",
                    [("Создать", {"action": "confirm"}), ("Отмена", {"action": "home"})],
                    state,
                )
            else:
                await self.home(bot, actor)
        except ClubError as error:
            await bot.send_message(actor, str(error))

    async def callback(self, query, bot):
        actor = query.from_user.id
        # Проверка отправителя и личного чата обязательна даже для старых кнопок.
        if not query.message or query.message.chat.id != actor:
            await query.answer("Откройте личный чат с ботом.", show_alert=True)
            return
        state = self.state(actor)
        generation, _, index = (query.data or "").partition(":")
        command = state.get("buttons", {}).get(index)
        if generation != state.get("generation") or command is None:
            await query.answer("Эта кнопка устарела. Откройте последнее меню.", show_alert=True)
            return
        await query.answer()
        edit_id = query.message.message_id
        try:
            action = command["action"]
            if action == "home":
                await self.home(bot, actor, edit_id)
            elif action == "create":
                await self.show(
                    bot,
                    actor,
                    "Как назовём клуб? Отправьте название сообщением.",
                    [("Отмена", {"action": "home"})],
                    {"step": "title", "create_key": secrets.token_hex(12)},
                    edit_id,
                )
            elif action == "currency" and state.get("step") == "currency":
                state.update(currency=command["value"], step="timezone")
                await self.show(
                    bot,
                    actor,
                    "Отправьте часовой пояс, например Asia/Tashkent или Europe/Moscow.",
                    [("Отмена", {"action": "home"})],
                    state,
                    edit_id,
                )
            elif action == "confirm" and state.get("step") == "confirm":
                club_id = self.clubs.create(
                    actor,
                    query.from_user.full_name,
                    state["title"],
                    state["currency"],
                    state["timezone"],
                    state["create_key"],
                )
                await self.club(bot, actor, club_id, edit_id)
            elif action == "club":
                await self.club(bot, actor, command["club_id"], edit_id)
            elif action in {"invite", "roster"}:
                club_id = command["club_id"]
                if action == "invite":
                    token = self.clubs.invite(actor, club_id)
                    username = (await bot.get_me()).username
                    text = f"Приглашение в закрытый клуб:\nhttps://t.me/{username}?start=join_{token}"
                else:
                    rows = self.clubs.roster(actor, club_id)
                    text = "<b>Участники</b>\n" + "\n".join(html.escape(r["name"]) for r in rows[:30])
                    if len(rows) > 30:
                        text += f"\nВсего участников: {len(rows)}"
                await self.show(
                    bot,
                    actor,
                    text,
                    [("Назад", {"action": "club", "club_id": club_id})],
                    {"club_id": club_id},
                    edit_id,
                )
        except ClubError as error:
            await bot.send_message(actor, str(error))


def build_dispatcher(db):
    from .mini_launcher import MiniAppLauncher

    ui = MiniAppLauncher()
    dp = Dispatcher()
    dp.message.register(ui.message, F.text)
    dp.callback_query.register(ui.callback)
    return dp
