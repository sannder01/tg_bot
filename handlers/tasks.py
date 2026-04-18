"""
handlers/tasks.py — Task Manager.

Архитектура FSM (Finite State Machine):
────────────────────────────────────────────────────────────────────
  [Любое состояние]
       │
       ▼  /tasks или /newtask или кнопка "➕ Добавить"
  [IDLE] ──/newtask──► [WAITING_TASK_TEXT]
                               │
                               ▼  пользователь вводит текст
                         сохраняем задачу → возвращаем виджет
                               │
                               ▼
                        ConversationHandler.END  (возврат в IDLE)

  Все кнопки виджета (Done / Delete / Undo / Clear)
  обрабатываются через callback_query — они НЕ входят в FSM,
  это просто обычные inline-нажатия.
────────────────────────────────────────────────────────────────────

Callback-data формат (макс. 64 байта):
  "td:{task_id}"  — toggle done (mark as complete)
  "tu:{task_id}"  — toggle undo (restore to active)
  "tx:{task_id}"  — delete task
  "tc"            — clear ALL tasks
  "ta"            — add task (входная точка FSM через кнопку)
  "tr"            — refresh widget (перезагрузить список)
"""

import uuid
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from db import load_db, save_db

logger = logging.getLogger(__name__)

# ── FSM State ─────────────────────────────────────────────────────────────────
WAITING_TASK_TEXT = 1  # единственное состояние — ждём текст задачи


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _new_id() -> str:
    """Генерируем короткий уникальный ID задачи (8 hex-символов)."""
    return uuid.uuid4().hex[:8]


def _get_tasks(chat_key: str) -> list[dict]:
    return load_db()["tasks"].get(chat_key, [])


def _save_tasks(chat_key: str, tasks: list[dict]) -> None:
    db = load_db()
    db["tasks"][chat_key] = tasks
    save_db(db)


def _trunc(text: str, n: int = 22) -> str:
    """Обрезаем строку для кнопки (ограничение Telegram)."""
    return text if len(text) <= n else text[:n - 1] + "…"


# ══════════════════════════════════════════════════════════════════════════════
#  Widget builder  —  сердце UI
# ══════════════════════════════════════════════════════════════════════════════

_SEP = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"


def build_widget(tasks: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    """
    Собираем HTML-текст виджета и InlineKeyboard.

    Возвращает (text, markup).

    Визуальный стиль — Nothing Tech / Retro-futurism:
      • Минимализм, моноширинный шрифт для мета-информации
      • Эмодзи-индикаторы состояния задачи
      • Зачёркнутый текст для выполненных задач
    """
    active = [t for t in tasks if not t["done"]]
    done   = [t for t in tasks if t["done"]]

    # ── Заголовок ─────────────────────────────────────────────────────────
    header = (
        f"⚡️ <b>PROJECT: TASKS</b>\n"
        f"{_SEP}\n"
    )

    # ── Тело списка ───────────────────────────────────────────────────────
    if not tasks:
        body = "\n  <i>Задач нет. Нажми ➕ чтобы начать.</i>\n"
    else:
        rows: list[str] = []

        if active:
            for t in active:
                rows.append(f"  🔘  {t['text']}")

        if done:
            if active:
                rows.append("")           # визуальный разделитель секций
            for t in done:
                # <s> — зачёркнутый текст (HTML)
                rows.append(f"  ✅  <s>{t['text']}</s>")

        body = "\n".join(rows) + "\n"

    # ── Футер ─────────────────────────────────────────────────────────────
    if tasks:
        footer = (
            f"\n{_SEP}\n"
            f"<code>{len(active)} активных  ·  {len(done)} выполнено</code>"
        )
    else:
        footer = f"\n{_SEP}"

    text = header + body + footer

    # ── Inline Keyboard ───────────────────────────────────────────────────
    keyboard: list[list[InlineKeyboardButton]] = []

    for t in tasks:
        tid = t["id"]
        label = _trunc(t["text"])

        if t["done"]:
            # Выполненная задача: кнопки «Восстановить» и «Удалить»
            row = [
                InlineKeyboardButton(f"↩️ {label}", callback_data=f"tu:{tid}"),
                InlineKeyboardButton("🗑",           callback_data=f"tx:{tid}"),
            ]
        else:
            # Активная задача: кнопки «Готово» и «Удалить»
            row = [
                InlineKeyboardButton(f"◻️ {label}", callback_data=f"td:{tid}"),
                InlineKeyboardButton("🗑",           callback_data=f"tx:{tid}"),
            ]
        keyboard.append(row)

    # ── Нижняя панель управления ──────────────────────────────────────────
    nav_row = [InlineKeyboardButton("➕ Добавить", callback_data="ta")]
    if tasks:
        nav_row.append(InlineKeyboardButton("🗑 Очистить всё", callback_data="tc"))
    keyboard.append(nav_row)

    return text, InlineKeyboardMarkup(keyboard)


# ══════════════════════════════════════════════════════════════════════════════
#  Command handlers
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/tasks — показать виджет со всеми задачами."""
    chat_key = str(update.effective_chat.id)
    tasks = _get_tasks(chat_key)
    text, markup = build_widget(tasks)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


# ══════════════════════════════════════════════════════════════════════════════
#  FSM: добавление новой задачи
# ══════════════════════════════════════════════════════════════════════════════

async def task_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Точка входа в FSM — /newtask.
    Переводим пользователя в состояние WAITING_TASK_TEXT.
    Бот запрашивает текст новой задачи.
    """
    await update.message.reply_text(
        "✏️ <b>НОВАЯ ЗАДАЧА</b>\n"
        f"{_SEP}\n"
        "Введи текст задачи.\n\n"
        "<i>Отправь /cancel чтобы отменить.</i>",
        parse_mode=ParseMode.HTML,
    )
    # ── Переход: IDLE → WAITING_TASK_TEXT ─────────────────────────────────
    return WAITING_TASK_TEXT


async def task_add_start_via_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Точка входа в FSM через inline-кнопку «➕ Добавить».
    Отвечаем на callback и показываем приглашение ввести текст.
    """
    query = update.callback_query
    # answerCallbackQuery — пользователь сразу чувствует отклик кнопки
    await query.answer("✏️ Введи текст новой задачи")

    await query.message.reply_text(
        "✏️ <b>НОВАЯ ЗАДАЧА</b>\n"
        f"{_SEP}\n"
        "Введи текст задачи.\n\n"
        "<i>Отправь /cancel чтобы отменить.</i>",
        parse_mode=ParseMode.HTML,
    )
    # ── Переход: IDLE → WAITING_TASK_TEXT ─────────────────────────────────
    return WAITING_TASK_TEXT


async def task_add_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Состояние WAITING_TASK_TEXT.
    Получаем текст задачи, сохраняем в БД, показываем обновлённый виджет.

    Переход: WAITING_TASK_TEXT → ConversationHandler.END (возврат в IDLE)
    """
    chat_key  = str(update.effective_chat.id)
    task_text = update.message.text.strip()

    if not task_text:
        # Пустой ввод — просим повторить, остаёмся в том же состоянии
        await update.message.reply_text("⚠️ Текст задачи не может быть пустым. Попробуй ещё раз.")
        return WAITING_TASK_TEXT

    # ── Создаём задачу ────────────────────────────────────────────────────
    new_task = {
        "id":         _new_id(),
        "text":       task_text,
        "done":       False,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    db = load_db()
    db["tasks"].setdefault(chat_key, [])
    db["tasks"][chat_key].append(new_task)
    save_db(db)

    tasks = db["tasks"][chat_key]

    # ── Подтверждение + свежий виджет ─────────────────────────────────────
    await update.message.reply_text(
        f"🔘 <b>Задача добавлена:</b>\n<code>{task_text}</code>",
        parse_mode=ParseMode.HTML,
    )

    text, markup = build_widget(tasks)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)

    # ── Переход: WAITING_TASK_TEXT → IDLE (конец диалога) ─────────────────
    return ConversationHandler.END


async def task_add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    /cancel во время FSM — отменяем добавление задачи.
    Переход: WAITING_TASK_TEXT → IDLE
    """
    await update.message.reply_text(
        "❌ Добавление отменено.",
        parse_mode=ParseMode.HTML,
    )
    # ── Переход: WAITING_TASK_TEXT → IDLE ─────────────────────────────────
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
#  Callback handlers  —  кнопки виджета
# ══════════════════════════════════════════════════════════════════════════════

async def task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Единая точка обработки всех callback-нажатий виджета задач.
    Паттерн: ^t[duxcr]
    """
    query    = update.callback_query
    data     = query.data              # напр. "td:a1b2c3d4"
    chat_key = str(query.message.chat.id)

    db    = load_db()
    tasks: list[dict] = db["tasks"].get(chat_key, [])

    # ── Разбираем action ──────────────────────────────────────────────────
    if data.startswith("td:"):
        # ── Отметить как выполненную ──────────────────────────────────────
        task_id = data[3:]
        task = next((t for t in tasks if t["id"] == task_id), None)
        if task:
            task["done"] = True
            _save_tasks(chat_key, tasks)
            await query.answer("✅ Выполнено!")   # всплывающее уведомление
        else:
            await query.answer("⚠️ Задача не найдена")
            return

    elif data.startswith("tu:"):
        # ── Восстановить задачу ───────────────────────────────────────────
        task_id = data[3:]
        task = next((t for t in tasks if t["id"] == task_id), None)
        if task:
            task["done"] = False
            _save_tasks(chat_key, tasks)
            await query.answer("↩️ Восстановлено")
        else:
            await query.answer("⚠️ Задача не найдена")
            return

    elif data.startswith("tx:"):
        # ── Удалить задачу ────────────────────────────────────────────────
        task_id = data[3:]
        before  = len(tasks)
        tasks   = [t for t in tasks if t["id"] != task_id]
        if len(tasks) < before:
            _save_tasks(chat_key, tasks)
            await query.answer("🗑 Удалено")
        else:
            await query.answer("⚠️ Задача не найдена")
            return

    elif data == "tc":
        # ── Очистить все задачи ───────────────────────────────────────────
        _save_tasks(chat_key, [])
        tasks = []
        await query.answer("🗑 Список очищен")

    elif data == "tr":
        # ── Просто обновить виджет (refresh) ─────────────────────────────
        await query.answer("🔄 Обновлено")

    else:
        await query.answer()
        return

    # ── Обновляем виджет прямо в том же сообщении ─────────────────────────
    # Все действия кроме "добавить" перерисовывают существующее сообщение.
    text, markup = build_widget(tasks)
    try:
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    except Exception:
        # edit_message_text падает если текст не изменился — игнорируем
        pass

    # ── Стикер при завершении всех задач ─────────────────────────────────
    # Дофаминовое подкрепление: если ВСЕ задачи выполнены — отправляем стикер.
    fresh = load_db()["tasks"].get(chat_key, [])
    if fresh and all(t["done"] for t in fresh):
        await context.bot.send_sticker(
            chat_id=query.message.chat.id,
            # Стикер "огонь" из стандартного набора Telegram
            sticker="CAACAgIAAxkBAAIBgWWlFqhXqFrXlK5xAAFn7FhR1SZMAAJ2BQACX2YhS5q3LVBH5d4KNAQ",
        )


# ══════════════════════════════════════════════════════════════════════════════
#  Сборка ConversationHandler
# ══════════════════════════════════════════════════════════════════════════════

def get_task_conversation_handler() -> ConversationHandler:
    """
    Собираем ConversationHandler для FSM добавления задач.

    Схема переходов:
    ┌──────────────────────────────────────────────────────────────────────┐
    │  entry_points:  /newtask  или  callback "ta"  → WAITING_TASK_TEXT   │
    │  states:                                                             │
    │    WAITING_TASK_TEXT:  любое текстовое сообщение → save → END       │
    │  fallbacks:  /cancel → END                                          │
    └──────────────────────────────────────────────────────────────────────┘
    """
    return ConversationHandler(
        # Точки входа в FSM
        entry_points=[
            CommandHandler("newtask", task_add_start),
            CallbackQueryHandler(task_add_start_via_button, pattern="^ta$"),
        ],
        states={
            # В этом состоянии ловим любой текст (не команду)
            WAITING_TASK_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, task_add_receive),
            ],
        },
        # Команда отмены доступна в любом состоянии FSM
        fallbacks=[
            CommandHandler("cancel", task_add_cancel),
        ],
        # Разговор привязан к (user_id, chat_id)
        per_user=True,
        per_chat=True,
    )


def get_task_callback_handler() -> CallbackQueryHandler:
    """
    Обработчик кнопок виджета (Done / Delete / Undo / Clear / Refresh).
    Паттерн не включает "ta" — он обрабатывается как entry_point FSM.
    """
    return CallbackQueryHandler(
        task_callback,
        pattern=r"^t[duxcr]",  # td: | tu: | tx: | tc | tr
    )
