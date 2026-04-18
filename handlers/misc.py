"""
handlers/misc.py — детектор лжи, цитаты.
"""

import random
import logging
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from db import load_db, save_db

logger = logging.getLogger(__name__)

_LIE_VERDICTS = [
    ("🤥", "Это наглая ЛОЖЬ!"),
    ("😬", "Скорее всего врёт..."),
    ("🤔", "Сомнительно, но ладно"),
    ("😶", "Говорит правду на {pct}%"),
    ("✅", "Чистая правда! Верим."),
    ("🎲", "Правда на {pct}%, ложь на {anti}%"),
]


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/check <текст> — детектор лжи."""
    user = update.effective_user.first_name
    text = " ".join(context.args) if context.args else "что-то"
    pct  = random.randint(0, 100)
    anti = 100 - pct
    icon, verdict_raw = random.choice(_LIE_VERDICTS)
    verdict = verdict_raw.format(pct=pct, anti=anti)
    bar = "🟩" * (pct // 10) + "⬜" * (10 - pct // 10)

    await update.message.reply_text(
        f"{icon} <b>Детектор лжи</b>\n\n"
        f"👤 <i>{user}: {text}</i>\n\n"
        f"📊 {pct}%\n{bar}\n\n"
        f"🔍 {verdict}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_save_quote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/save <фраза> — сохранить цитату."""
    chat_key = str(update.effective_chat.id)
    if not context.args:
        await update.message.reply_text("✏️ <code>/save это было легендарно</code>", parse_mode=ParseMode.HTML)
        return
    phrase = " ".join(context.args)
    db = load_db()
    db["quotes"].setdefault(chat_key, [])
    db["quotes"][chat_key].append({"text": phrase, "by": update.effective_user.first_name})
    save_db(db)
    await update.message.reply_text(f"💾 <i>«{phrase}»</i> — сохранено.", parse_mode=ParseMode.HTML)


async def cmd_quote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/quote — случайная цитата."""
    chat_key = str(update.effective_chat.id)
    db     = load_db()
    quotes = db["quotes"].get(chat_key, [])
    if not quotes:
        await update.message.reply_text("💬 Цитат нет. Используй <code>/save фраза</code>", parse_mode=ParseMode.HTML)
        return
    q = random.choice(quotes)
    await update.message.reply_text(
        f"💬 <i>«{q['text']}»</i>\n\n— {q['by']}",
        parse_mode=ParseMode.HTML,
    )
