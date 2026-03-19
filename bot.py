import os
import json
import random
import logging
from groq import Groq
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

load_dotenv()

# ─── Настройка логов ────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Клиент Groq (бесплатный ИИ) ────────────────────────────────────────────
GROQ_KEY = os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY else None

# ─── База данных (простой JSON-файл) ────────────────────────────────────────
DB_FILE = "data.json"

def load_db() -> dict:
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"shopping": {}, "wishlist": {}, "quotes": {}, "ai_history": {}}

def save_db(db: dict):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def get_chat_key(update: Update) -> str:
    return str(update.effective_chat.id)

# ─── /start ──────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ai_status = "✅ ИИ подключён (Llama 3)" if groq_client else "⚠️ ИИ не настроен (нет GROQ_API_KEY)"
    text = (
        f"👋 Привет! Я ваш общий бот для чата.\n"
        f"🤖 {ai_status}\n\n"
        "🛒 *Список покупок:*\n"
        "  /add молоко — добавить в список\n"
        "  /list — показать список покупок\n"
        "  /bought 2 — вычеркнуть товар\n\n"
        "🎯 *Вишлист:*\n"
        "  /wish AirPods — добавить желание\n"
        "  /wishlist — показать вишлист\n"
        "  /done 1 — вычеркнуть желание\n\n"
        "🤥 *Детектор лжи:*\n"
        "  /check я не ел торт\n\n"
        "💬 *Цитаты:*\n"
        "  /save это легенда — сохранить фразу\n"
        "  /quote — случайная цитата\n\n"
        "🤖 *AI ассистент (бесплатно):*\n"
        "  /ai как сварить борщ?\n"
        "  /reset — сбросить историю ИИ\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ════════════════════════════════════════════════════════════════════════════
#  🛒  СПИСОК ПОКУПОК
# ════════════════════════════════════════════════════════════════════════════

async def add_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    db.setdefault("shopping", {}).setdefault(key, [])

    if not context.args:
        await update.message.reply_text("✏️ Укажи что добавить: /add молоко")
        return

    item = " ".join(context.args)
    db["shopping"][key].append({"name": item, "done": False, "by": update.effective_user.first_name})
    save_db(db)
    await update.message.reply_text(f"✅ *{item}* добавлен в список покупок!", parse_mode="Markdown")

async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    items = db.get("shopping", {}).get(key, [])

    if not items:
        await update.message.reply_text("🛒 Список покупок пуст. Добавь что-нибудь: /add молоко")
        return

    lines = ["🛒 *Список покупок:*\n"]
    for i, item in enumerate(items, 1):
        icon = "✅" if item["done"] else "◻️"
        lines.append(f"{icon} {i}. {item['name']} _(добавил {item['by']})_")

    keyboard = [[InlineKeyboardButton("🗑 Очистить список", callback_data=f"clear_shop_{key}")]]
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def bought_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    items = db.get("shopping", {}).get(key, [])

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("✏️ Укажи номер: /bought 2")
        return

    idx = int(context.args[0]) - 1
    if 0 <= idx < len(items):
        items[idx]["done"] = True
        save_db(db)
        await update.message.reply_text(f"✅ *{items[idx]['name']}* куплен!", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Нет такого номера в списке.")

# ════════════════════════════════════════════════════════════════════════════
#  🎯  ВИШЛИСТ
# ════════════════════════════════════════════════════════════════════════════

async def add_wish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    db.setdefault("wishlist", {}).setdefault(key, [])

    if not context.args:
        await update.message.reply_text("✏️ Укажи желание: /wish поехать в Японию")
        return

    wish = " ".join(context.args)
    db["wishlist"][key].append({"name": wish, "done": False, "by": update.effective_user.first_name})
    save_db(db)
    await update.message.reply_text(f"⭐ Желание *{wish}* добавлено в вишлист!", parse_mode="Markdown")

async def show_wishlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    items = db.get("wishlist", {}).get(key, [])

    if not items:
        await update.message.reply_text("🎯 Вишлист пуст. Добавь желание: /wish новый iPhone")
        return

    lines = ["🎯 *Вишлист:*\n"]
    for i, item in enumerate(items, 1):
        icon = "✅" if item["done"] else "⭐"
        lines.append(f"{icon} {i}. {item['name']} _(мечтает {item['by']})_")

    keyboard = [[InlineKeyboardButton("🗑 Очистить вишлист", callback_data=f"clear_wish_{key}")]]
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def done_wish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    items = db.get("wishlist", {}).get(key, [])

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("✏️ Укажи номер: /done 1")
        return

    idx = int(context.args[0]) - 1
    if 0 <= idx < len(items):
        items[idx]["done"] = True
        save_db(db)
        await update.message.reply_text(f"🎉 Желание *{items[idx]['name']}* исполнено!", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Нет такого номера.")

# ════════════════════════════════════════════════════════════════════════════
#  🤥  ДЕТЕКТОР ЛЖИ
# ════════════════════════════════════════════════════════════════════════════

LIE_VERDICTS = [
    ("🤥", "Это наглая ЛОЖЬ!", 0),
    ("😬", "Скорее всего врёт...", 20),
    ("🤔", "Сомнительно, но ладно", 45),
    ("😶", "Говорит правду на {pct}%", None),
    ("✅", "Чистая правда! Верим.", 100),
    ("🕵️", "Детектор сломался от такого вранья!", 0),
    ("🎲", "Правда на {pct}%, ложь на {anti}%", None),
]

async def lie_detector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    text = " ".join(context.args) if context.args else "что-то"
    pct = random.randint(0, 100)
    anti = 100 - pct
    template = random.choice(LIE_VERDICTS)
    icon, verdict_raw, fixed_pct = template

    if fixed_pct is not None:
        verdict = verdict_raw
        pct_show = fixed_pct
    else:
        verdict = verdict_raw.format(pct=pct, anti=anti)
        pct_show = pct

    filled = pct_show // 10
    bar = "🟩" * filled + "⬜" * (10 - filled)

    msg = (
        f"{icon} *Детектор лжи*\n\n"
        f"👤 {user} говорит: _{text}_\n\n"
        f"📊 Правдивость: {pct_show}%\n"
        f"{bar}\n\n"
        f"🔍 Вердикт: *{verdict}*"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# ════════════════════════════════════════════════════════════════════════════
#  💬  ЦИТАТЫ / МЕМЫ
# ════════════════════════════════════════════════════════════════════════════

async def remember_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    db.setdefault("quotes", {}).setdefault(key, [])

    if not context.args:
        await update.message.reply_text("✏️ Напиши фразу: /save это легендарная цитата")
        return

    phrase = " ".join(context.args)
    db["quotes"][key].append({"text": phrase, "by": update.effective_user.first_name})
    save_db(db)
    await update.message.reply_text(f"💾 Запомнил: _«{phrase}»_", parse_mode="Markdown")

async def random_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    quotes = db.get("quotes", {}).get(key, [])

    if not quotes:
        await update.message.reply_text("💬 Цитат нет. Сохрани первую: /save ваша фраза")
        return

    q = random.choice(quotes)
    await update.message.reply_text(
        f"💬 *Цитата из вашего чата:*\n\n_«{q['text']}»_\n\n— {q['by']}",
        parse_mode="Markdown"
    )

# ════════════════════════════════════════════════════════════════════════════
#  🤖  AI АССИСТЕНТ — Groq / Llama 3 (БЕСПЛАТНО)
# ════════════════════════════════════════════════════════════════════════════

async def ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not groq_client:
        await update.message.reply_text(
            "⚠️ ИИ не настроен. Получи бесплатный ключ:\n\n"
            "1. Зайди на console.groq.com\n"
            "2. Зарегистрируйся (можно через Google)\n"
            "3. API Keys → Create Key\n"
            "4. Вставь в .env как GROQ_API_KEY=gsk_..."
        )
        return

    key = get_chat_key(update)
    db = load_db()
    db.setdefault("ai_history", {}).setdefault(key, [])

    if not context.args:
        await update.message.reply_text("✏️ Задай вопрос: /ai что подарить девушке на 8 марта?")
        return

    user_msg = " ".join(context.args)
    history = db["ai_history"][key]
    history.append({"role": "user", "content": user_msg})

    if len(history) > 20:
        history = history[-20:]

    try:
        thinking_msg = await update.message.reply_text("🤖 Думаю...")

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты дружелюбный ИИ-помощник в Telegram-чате. "
                        "Отвечай коротко, по делу, с лёгким юмором. "
                        "Используй эмодзи умеренно. Отвечай на языке пользователя."
                    )
                },
                *history
            ],
            max_tokens=800,
        )

        ai_reply = response.choices[0].message.content
        history.append({"role": "assistant", "content": ai_reply})
        db["ai_history"][key] = history
        save_db(db)

        await thinking_msg.delete()
        await update.message.reply_text(f"🤖 {ai_reply}")

    except Exception as e:
        logger.error(f"Groq error: {e}")
        await update.message.reply_text("❌ ИИ временно недоступен. Попробуй позже.")

async def reset_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    db.setdefault("ai_history", {})[key] = []
    save_db(db)
    await update.message.reply_text("🔄 История диалога с ИИ сброшена!")

# ════════════════════════════════════════════════════════════════════════════
#  🔘  CALLBACK (инлайн кнопки)
# ════════════════════════════════════════════════════════════════════════════

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = load_db()

    if query.data.startswith("clear_shop_"):
        key = query.data.replace("clear_shop_", "")
        db.setdefault("shopping", {})[key] = []
        save_db(db)
        await query.edit_message_text("🛒 Список покупок очищен!")

    elif query.data.startswith("clear_wish_"):
        key = query.data.replace("clear_wish_", "")
        db.setdefault("wishlist", {})[key] = []
        save_db(db)
        await query.edit_message_text("🎯 Вишлист очищен!")

# ════════════════════════════════════════════════════════════════════════════
#  🚀  ЗАПУСК
# ════════════════════════════════════════════════════════════════════════════

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("Нет TELEGRAM_BOT_TOKEN в .env!")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("add", add_item))
    app.add_handler(CommandHandler("list", show_list))
    app.add_handler(CommandHandler("bought", bought_item))

    app.add_handler(CommandHandler("wish", add_wish))
    app.add_handler(CommandHandler("wishlist", show_wishlist))
    app.add_handler(CommandHandler("done", done_wish))

    app.add_handler(CommandHandler("check", lie_detector))

    app.add_handler(CommandHandler("save", remember_quote))
    app.add_handler(CommandHandler("quote", random_quote))

    app.add_handler(CommandHandler("ai", ai_chat))
    app.add_handler(CommandHandler("reset", reset_ai))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))

    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
