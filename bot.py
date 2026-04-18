"""
bot.py — точка входа. Собираем Application и регистрируем все хендлеры.

Порядок регистрации важен:
  group=-1  →  Business-автоответ (самый первый, до всего остального)
  group=0   →  ConversationHandler (FSM задач — перехватывает до обычных команд)
  group=1   →  Обычные CommandHandler и CallbackQueryHandler
"""

import logging
import pytz
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    TypeHandler,
)

from config import (
    TELEGRAM_BOT_TOKEN,
    DEADLINE_CHAT_ID,
    DEADLINE_HOUR,
    DEADLINE_MINUTE,
    DEADLINE_TZ,
)
from handlers.business  import handle_business_message
from handlers.start     import cmd_start, cmd_status, cmd_persona
from handlers.tasks     import (
    cmd_tasks,
    get_task_conversation_handler,
    get_task_callback_handler,
)
from handlers.deadlines import cmd_deadlines, daily_deadlines_job
from handlers.ai_chat   import cmd_ai, cmd_reset_ai
from handlers.misc      import cmd_check, cmd_save_quote, cmd_quote

logging.basicConfig(
    format="%(asctime)s  %(name)-20s  %(levelname)-8s  %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("Нет TELEGRAM_BOT_TOKEN в .env!")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # ── group=-1: Business автоответ ──────────────────────────────────────
    # TypeHandler c group=-1 получает ВСЕ апдейты раньше остальных.
    # handle_business_message сам проверяет, что это business_message.
    app.add_handler(TypeHandler(Update, handle_business_message), group=-1)

    # ── group=0: FSM (ConversationHandler) ───────────────────────────────
    # ConversationHandler должен стоять ДО обычных CommandHandler,
    # иначе /newtask перехватится раньше, чем ConversationHandler успеет
    # зарегистрировать состояние.
    app.add_handler(get_task_conversation_handler(), group=0)

    # ── group=1: Основные команды ─────────────────────────────────────────
    app.add_handler(CommandHandler("start",     cmd_start),     group=1)
    app.add_handler(CommandHandler("help",      cmd_start),     group=1)
    app.add_handler(CommandHandler("status",    cmd_status),    group=1)
    app.add_handler(CommandHandler("persona",   cmd_persona),   group=1)

    app.add_handler(CommandHandler("tasks",     cmd_tasks),     group=1)  # Task Manager

    app.add_handler(CommandHandler("deadlines", cmd_deadlines), group=1)

    app.add_handler(CommandHandler("ai",        cmd_ai),        group=1)
    app.add_handler(CommandHandler("reset",     cmd_reset_ai),  group=1)

    app.add_handler(CommandHandler("check",     cmd_check),     group=1)
    app.add_handler(CommandHandler("save",      cmd_save_quote),group=1)
    app.add_handler(CommandHandler("quote",     cmd_quote),     group=1)

    # Обработчик кнопок виджета задач (Done / Delete / Undo / Clear)
    app.add_handler(get_task_callback_handler(), group=1)

    # ── Ежедневная рассылка дедлайнов ────────────────────────────────────
    if DEADLINE_CHAT_ID:
        tz_obj    = pytz.timezone(DEADLINE_TZ)
        send_time = (
            datetime.now(tz_obj)
            .replace(hour=DEADLINE_HOUR, minute=DEADLINE_MINUTE, second=0, microsecond=0)
            .timetz()
        )
        app.job_queue.run_daily(daily_deadlines_job, time=send_time)
        logger.info(
            "Рассылка дедлайнов: %02d:%02d %s → %s",
            DEADLINE_HOUR, DEADLINE_MINUTE, DEADLINE_TZ, DEADLINE_CHAT_ID,
        )
    else:
        logger.warning("DEADLINE_CHAT_ID не задан — ежедневная рассылка отключена")

    logger.info("Бот запущен 🚀")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
