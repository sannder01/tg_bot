"""
handlers/start.py — приветствие, статус и настройка персоны.
"""

import logging
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from config import GROQ_API_KEY, DEADLINE_CHAT_ID, DEADLINE_HOUR

logger = logging.getLogger(__name__)

# Персона хранится в памяти процесса (изменяется через /persona)
# Импортируется из config как дефолт, переопределяется командой
from config import BOT_PERSONA
_persona_state = {"value": BOT_PERSONA}


def get_persona() -> str:
    return _persona_state["value"]


def set_persona(text: str) -> None:
    _persona_state["value"] = text


# ─── Separator ───────────────────────────────────────────────────────────────
_SEP = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — показываем главное меню в стиле Nothing Tech."""
    ai_status  = "✅ <code>Groq / Llama-3</code>" if GROQ_API_KEY else "❌ <code>Нет GROQ_API_KEY</code>"
    dl_status  = f"✅ <code>{DEADLINE_CHAT_ID}</code>" if DEADLINE_CHAT_ID else "⚠️ <code>DEADLINE_CHAT_ID не задан</code>"

    text = (
        f"⚡️ <b>SYSTEM ONLINE</b>\n"
        f"{_SEP}\n\n"
        f"🤖 ИИ:       {ai_status}\n"
        f"📚 Рассылка: {dl_status}\n\n"
        f"{_SEP}\n"
        f"<b>TASK MANAGER</b>\n"
        f"  /tasks     — открыть виджет задач\n"
        f"  /newtask   — добавить задачу (FSM)\n\n"
        f"<b>ДЕДЛАЙНЫ</b>\n"
        f"  /deadlines — дедлайны AITU LMS\n"
        f"  <i>(авторассылка в {DEADLINE_HOUR:02d}:00)</i>\n\n"
        f"<b>ИИ</b>\n"
        f"  /ai &lt;вопрос&gt; — спросить Llama-3\n"
        f"  /reset        — сбросить историю\n\n"
        f"<b>MISC</b>\n"
        f"  /check &lt;текст&gt; — детектор лжи\n"
        f"  /save &lt;фраза&gt;  — сохранить цитату\n"
        f"  /quote         — случайная цитата\n\n"
        f"<b>НАСТРОЙКИ</b>\n"
        f"  /persona &lt;текст&gt; — стиль автоответа\n"
        f"  /status         — статус бота\n"
        f"{_SEP}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/status — текущий статус бота."""
    ai  = "✅ Подключён (Llama-3)" if GROQ_API_KEY else "❌ Не настроен"
    persona = get_persona()
    text = (
        f"⚙️ <b>STATUS</b>\n"
        f"{_SEP}\n\n"
        f"🤖 ИИ: {ai}\n\n"
        f"📝 <b>Персона автоответа:</b>\n"
        f"<i>{persona}</i>\n"
        f"{_SEP}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_persona(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/persona <текст> — изменить системный промпт автоответа."""
    if not context.args:
        await update.message.reply_text(
            "✏️ <b>Укажи стиль автоответа:</b>\n\n"
            "<code>/persona Отвечай кратко, я занятой человек</code>\n"
            "<code>/persona Скажи что я занят и отвечу позже</code>\n"
            "<code>/persona Отвечай дружелюбно с юмором</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    new_persona = " ".join(context.args)
    set_persona(new_persona)
    await update.message.reply_text(
        f"✅ <b>Стиль обновлён:</b>\n\n<i>{new_persona}</i>",
        parse_mode=ParseMode.HTML,
    )
