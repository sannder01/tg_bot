"""
handlers/business.py — Telegram Business API автоответ через Groq.

Когда бот подключён как «Business-бот» (Настройки → Business → Чат-боты),
он получает все сообщения в личке владельца.

Логика:
  • Если сообщение от владельца и НЕ команда → пропуск
  • Если команда → обрабатываем (/ai, /check, /deadlines, /help, …)
  • Если обычное сообщение → Groq генерирует автоответ
"""

import logging
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from db import load_db, save_db
from config import GROQ_API_KEY
from handlers.start import get_persona
from handlers.deadlines import fetch_deadlines, build_deadline_message

logger = logging.getLogger(__name__)

_groq_client = None
if GROQ_API_KEY:
    try:
        from groq import Groq
        _groq_client = Groq(api_key=GROQ_API_KEY)
    except ImportError:
        pass


async def handle_business_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """TypeHandler(-1) — ловит business_message раньше остальных обработчиков."""
    try:
        message = update.business_message
    except AttributeError:
        return
    if not message or not message.text:
        return
    if message.from_user and message.from_user.is_bot:
        return

    sender_name = message.from_user.first_name if message.from_user else "Собеседник"
    chat_id     = str(message.chat.id)
    user_text   = message.text

    # Проверяем, является ли отправитель владельцем бизнес-аккаунта
    is_owner = False
    if message.business_connection_id:
        try:
            conn = await context.bot.get_business_connection(message.business_connection_id)
            if message.from_user and conn.user.id == message.from_user.id:
                is_owner = True
        except Exception:
            pass

    # Владелец пишет НЕ команду → ничего не делаем
    if is_owner and not user_text.startswith("/"):
        return

    if not _groq_client:
        return

    # ── Обработка команд из бизнес-чата ──────────────────────────────────
    if user_text.startswith("/"):
        parts = user_text.split()
        cmd   = parts[0].lower().replace("/", "")
        args  = parts[1:]

        reply: str | None = None

        if cmd == "check":
            import random
            claim = " ".join(args) if args else "это"
            pct   = random.randint(0, 100)
            bar   = "🟩" * (pct // 10) + "⬜" * (10 - pct // 10)
            verdicts = ["🤥 Наглая ЛОЖЬ!", "😬 Скорее врёт...", "🤔 Сомнительно", "✅ Чистая правда!"]
            verdict = verdicts[min(pct // 25, 3)]
            reply = f"🕵️ <b>Детектор лжи</b>\n\n<i>{claim}</i>\n\n📊 {pct}%\n{bar}\n\n{verdict}"

        elif cmd == "deadlines":
            try:
                events   = fetch_deadlines()
                reply_md = build_deadline_message(events)
                await context.bot.send_message(
                    chat_id=message.chat.id,
                    text=reply_md,
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=True,
                    business_connection_id=message.business_connection_id,
                )
            except Exception as exc:
                await context.bot.send_message(
                    chat_id=message.chat.id,
                    text=f"❌ Не удалось загрузить дедлайны:\n<code>{exc}</code>",
                    parse_mode=ParseMode.HTML,
                    business_connection_id=message.business_connection_id,
                )
            return

        elif cmd == "ai" and args:
            user_msg = " ".join(args)
            try:
                response = _groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": "Ты дружелюбный ассистент. Отвечай коротко с юмором. Отвечай на языке пользователя."},
                        {"role": "user",   "content": user_msg},
                    ],
                    max_tokens=500,
                )
                reply = "🤖 " + response.choices[0].message.content
            except Exception:
                reply = "❌ ИИ недоступен. Попробуй позже."

        elif cmd == "stop":
            db = load_db()
            db["ai_enabled"][chat_id] = False
            save_db(db)
            reply = "🔇 Автоответ ИИ отключён.\n/resume чтобы включить."

        elif cmd == "resume":
            db = load_db()
            db["ai_enabled"][chat_id] = True
            save_db(db)
            reply = "🔊 Автоответ ИИ включён!"

        elif cmd == "help":
            reply = (
                "📋 <b>Команды для бизнес-чата:</b>\n\n"
                "/check — детектор лжи\n"
                "/deadlines — дедлайны AITU LMS\n"
                "/ai &lt;вопрос&gt; — спросить ИИ\n\n"
                "/stop — отключить автоответ ИИ\n"
                "/resume — включить автоответ ИИ"
            )

        else:
            reply = "❓ Неизвестная команда. Напиши /help"

        if reply:
            try:
                await context.bot.send_message(
                    chat_id=message.chat.id,
                    text=reply,
                    parse_mode=ParseMode.HTML,
                    business_connection_id=message.business_connection_id,
                )
            except Exception as exc:
                logger.error("Ошибка отправки бизнес-команды: %s", exc)
        return

    # ── Обычное сообщение — автоответ ИИ ─────────────────────────────────
    db = load_db()
    if not db["ai_enabled"].get(chat_id, False):
        return

    db["business_history"].setdefault(chat_id, [])
    history = db["business_history"][chat_id]
    history.append({"role": "user", "content": f"{sender_name}: {user_text}"})
    if len(history) > 10:
        history = history[-10:]

    try:
        response = _groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": get_persona()},
                *history,
            ],
            max_tokens=300,
        )
        ai_reply = response.choices[0].message.content
        history.append({"role": "assistant", "content": ai_reply})
        db["business_history"][chat_id] = history
        save_db(db)
        await context.bot.send_message(
            chat_id=message.chat.id,
            text=ai_reply,
            business_connection_id=message.business_connection_id,
        )
        logger.info("Автоответ для %s: %s...", sender_name, ai_reply[:50])
    except Exception as exc:
        logger.error("Ошибка автоответа: %s", exc)
