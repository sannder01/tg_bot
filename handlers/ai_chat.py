"""
handlers/ai_chat.py — AI-чат через Groq (Llama-3).
"""

import logging
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from db import load_db, save_db
from config import GROQ_API_KEY

logger = logging.getLogger(__name__)

# Инициализируем Groq-клиент один раз
_groq_client = None
if GROQ_API_KEY:
    try:
        from groq import Groq
        _groq_client = Groq(api_key=GROQ_API_KEY)
    except ImportError:
        logger.warning("Пакет groq не установлен")


async def cmd_ai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ai <вопрос> — задать вопрос Llama-3."""
    if not _groq_client:
        await update.message.reply_text("⚠️ Нет <code>GROQ_API_KEY</code> в .env", parse_mode=ParseMode.HTML)
        return

    if not context.args:
        await update.message.reply_text("✏️ <code>/ai как сварить борщ?</code>", parse_mode=ParseMode.HTML)
        return

    chat_key = str(update.effective_chat.id)
    user_msg = " ".join(context.args)

    db = load_db()
    db["ai_history"].setdefault(chat_key, [])
    history = db["ai_history"][chat_key]
    history.append({"role": "user", "content": user_msg})
    if len(history) > 20:
        history = history[-20:]

    thinking = await update.message.reply_text("🤖 <i>Думаю...</i>", parse_mode=ParseMode.HTML)
    try:
        response = _groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Ты дружелюбный ассистент. Отвечай коротко с юмором. Отвечай на языке пользователя."},
                *history,
            ],
            max_tokens=800,
        )
        reply = response.choices[0].message.content
        history.append({"role": "assistant", "content": reply})
        db["ai_history"][chat_key] = history
        save_db(db)
        await thinking.delete()
        await update.message.reply_text(f"🤖 {reply}")
    except Exception as exc:
        logger.error("Groq error: %s", exc)
        await thinking.edit_text("❌ ИИ недоступен. Попробуй позже.")


async def cmd_reset_ai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/reset — сбросить историю AI-чата."""
    chat_key = str(update.effective_chat.id)
    db = load_db()
    db["ai_history"][chat_key] = []
    save_db(db)
    await update.message.reply_text("🔄 История ИИ сброшена.")
