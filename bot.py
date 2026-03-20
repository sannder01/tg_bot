import os
import json
import random
import logging
from groq import Groq
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
    TypeHandler
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

GROQ_KEY = os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY else None

# ─── Настройки автоответа ─────────────────────────────────────────────────────
# Можешь поменять эти фразы под себя
AUTO_REPLY_SYSTEM_PROMPT = os.getenv("BOT_PERSONA", (
    "Ты отвечаешь вместо владельца этого Telegram аккаунта. "
    "Отвечай вежливо, коротко и по делу. "
    "Если не знаешь ответа — скажи что владелец скоро ответит лично. "
    "Отвечай на языке собеседника."
))

# ─── База данных ─────────────────────────────────────────────────────────────
DB_FILE = "data.json"

def load_db() -> dict:
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"shopping": {}, "wishlist": {}, "quotes": {}, "ai_history": {}, "business_history": {}}

def save_db(db: dict):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def get_chat_key(update: Update) -> str:
    return str(update.effective_chat.id)

# ════════════════════════════════════════════════════════════════════════════
#  🤖  BUSINESS — автоответ за тебя
# ════════════════════════════════════════════════════════════════════════════

async def handle_business_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Срабатывает когда кто-то пишет тебе в личку (через Business подключение)"""
    if not groq_client:
        logger.warning("Groq не настроен — автоответ не работает")
        return

    # Получаем business сообщение из raw update
    try:
        message = update.business_message
    except AttributeError:
        return

    if not message or not message.text:
        return

    if message.from_user and message.from_user.is_bot:
    return

    # Не отвечаем на свои собственные сообщения
    if update.business_message.business_connection_id:
        try:
            connection = await context.bot.get_business_connection(
                update.business_message.business_connection_id
            )
            if message.from_user and connection.user.id == message.from_user.id:
                return
        except Exception:
            pass

    sender_name = message.from_user.first_name if message.from_user else "Собеседник"
    chat_id = str(message.chat.id)
    user_text = message.text

    logger.info(f"Business сообщение от {sender_name}: {user_text}")

    db = load_db()
    db.setdefault("business_history", {}).setdefault(chat_id, [])
    history = db["business_history"][chat_id]

    history.append({"role": "user", "content": f"{sender_name}: {user_text}"})

    # Держим последние 10 сообщений на каждого собеседника
    if len(history) > 10:
        history = history[-10:]

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": AUTO_REPLY_SYSTEM_PROMPT},
                *history
            ],
            max_tokens=300,
        )

        reply = response.choices[0].message.content
        history.append({"role": "assistant", "content": reply})
        db["business_history"][chat_id] = history
        save_db(db)

        # Отвечаем в бизнес-чат (от имени владельца аккаунта)
        await context.bot.send_message(
            chat_id=message.chat.id,
            text=reply,
            business_connection_id=update.business_message.business_connection_id
        )
        logger.info(f"Автоответ отправлен: {reply[:50]}...")

    except Exception as e:
        logger.error(f"Ошибка автоответа: {e}")

# ════════════════════════════════════════════════════════════════════════════
#  /start — управление ботом (в личке с самим ботом)
# ════════════════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ai_status = "✅ ИИ подключён (Llama 3)" if groq_client else "⚠️ ИИ не настроен (нет GROQ_API_KEY)"
    text = (
        f"👋 Привет! Я твой Business-бот.\n"
        f"🤖 {ai_status}\n\n"
        "📨 *Автоответ:*\n"
        "  Подключи меня в Настройки → Business → Чат-боты\n"
        "  Я буду отвечать за тебя в личных переписках!\n\n"
        "🛒 *Список покупок:*\n"
        "  /add молоко — добавить\n"
        "  /list — показать список\n"
        "  /bought 2 — вычеркнуть\n\n"
        "🎯 *Вишлист:*\n"
        "  /wish AirPods — добавить\n"
        "  /wishlist — показать\n"
        "  /done 1 — исполнено\n\n"
        "🤥 *Детектор лжи:*\n"
        "  /check я не ел торт\n\n"
        "💬 *Цитаты:*\n"
        "  /save это легенда\n"
        "  /quote — случайная\n\n"
        "🤖 *Спросить ИИ:*\n"
        "  /ai как сварить борщ?\n"
        "  /reset — сброс истории\n\n"
        "⚙️ *Настройки автоответа:*\n"
        "  /persona [текст] — изменить стиль ответов\n"
        "  /status — текущие настройки\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ════════════════════════════════════════════════════════════════════════════
#  ⚙️  НАСТРОЙКИ
# ════════════════════════════════════════════════════════════════════════════

async def set_persona(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Изменить как бот отвечает за тебя"""
    global AUTO_REPLY_SYSTEM_PROMPT
    if not context.args:
        await update.message.reply_text(
            "✏️ Укажи стиль ответов:\n\n"
            "/persona Отвечай кратко и по делу, я занятой человек\n"
            "/persona Отвечай дружелюбно с юмором\n"
            "/persona Скажи что я занят и перезвоню позже"
        )
        return
    AUTO_REPLY_SYSTEM_PROMPT = " ".join(context.args)
    await update.message.reply_text(f"✅ Стиль автоответа обновлён:\n\n_{AUTO_REPLY_SYSTEM_PROMPT}_", parse_mode="Markdown")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ai = "✅ Подключён" if groq_client else "❌ Не настроен"
    await update.message.reply_text(
        f"⚙️ *Статус бота:*\n\n"
        f"🤖 ИИ: {ai}\n"
        f"📝 Стиль ответов:\n_{AUTO_REPLY_SYSTEM_PROMPT}_",
        parse_mode="Markdown"
    )

# ════════════════════════════════════════════════════════════════════════════
#  🛒  СПИСОК ПОКУПОК
# ════════════════════════════════════════════════════════════════════════════

async def add_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    db.setdefault("shopping", {}).setdefault(key, [])
    if not context.args:
        return await update.message.reply_text("✏️ Укажи что добавить: /add молоко")
    item = " ".join(context.args)
    db["shopping"][key].append({"name": item, "done": False, "by": update.effective_user.first_name})
    save_db(db)
    await update.message.reply_text(f"✅ *{item}* добавлен в список!", parse_mode="Markdown")

async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    items = db.get("shopping", {}).get(key, [])
    if not items:
        return await update.message.reply_text("🛒 Список пуст. /add молоко")
    lines = ["🛒 *Список покупок:*\n"]
    for i, item in enumerate(items, 1):
        icon = "✅" if item["done"] else "◻️"
        lines.append(f"{icon} {i}. {item['name']} _({item['by']})_")
    keyboard = [[InlineKeyboardButton("🗑 Очистить", callback_data=f"clear_shop_{key}")]]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def bought_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    items = db.get("shopping", {}).get(key, [])
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text("✏️ Укажи номер: /bought 2")
    idx = int(context.args[0]) - 1
    if 0 <= idx < len(items):
        items[idx]["done"] = True
        save_db(db)
        await update.message.reply_text(f"✅ *{items[idx]['name']}* куплен!", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Нет такого номера.")

# ════════════════════════════════════════════════════════════════════════════
#  🎯  ВИШЛИСТ
# ════════════════════════════════════════════════════════════════════════════

async def add_wish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    db.setdefault("wishlist", {}).setdefault(key, [])
    if not context.args:
        return await update.message.reply_text("✏️ Укажи желание: /wish поехать в Японию")
    wish = " ".join(context.args)
    db["wishlist"][key].append({"name": wish, "done": False, "by": update.effective_user.first_name})
    save_db(db)
    await update.message.reply_text(f"⭐ *{wish}* добавлен в вишлист!", parse_mode="Markdown")

async def show_wishlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    items = db.get("wishlist", {}).get(key, [])
    if not items:
        return await update.message.reply_text("🎯 Вишлист пуст. /wish что-нибудь")
    lines = ["🎯 *Вишлист:*\n"]
    for i, item in enumerate(items, 1):
        icon = "✅" if item["done"] else "⭐"
        lines.append(f"{icon} {i}. {item['name']} _({item['by']})_")
    keyboard = [[InlineKeyboardButton("🗑 Очистить", callback_data=f"clear_wish_{key}")]]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def done_wish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    items = db.get("wishlist", {}).get(key, [])
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text("✏️ Укажи номер: /done 1")
    idx = int(context.args[0]) - 1
    if 0 <= idx < len(items):
        items[idx]["done"] = True
        save_db(db)
        await update.message.reply_text(f"🎉 *{items[idx]['name']}* исполнено!", parse_mode="Markdown")
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
    icon, verdict_raw, fixed_pct = random.choice(LIE_VERDICTS)
    if fixed_pct is not None:
        verdict, pct_show = verdict_raw, fixed_pct
    else:
        verdict, pct_show = verdict_raw.format(pct=pct, anti=anti), pct
    bar = "🟩" * (pct_show // 10) + "⬜" * (10 - pct_show // 10)
    await update.message.reply_text(
        f"{icon} *Детектор лжи*\n\n👤 {user}: _{text}_\n\n📊 {pct_show}%\n{bar}\n\n🔍 {verdict}",
        parse_mode="Markdown"
    )

# ════════════════════════════════════════════════════════════════════════════
#  💬  ЦИТАТЫ
# ════════════════════════════════════════════════════════════════════════════

async def save_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    db.setdefault("quotes", {}).setdefault(key, [])
    if not context.args:
        return await update.message.reply_text("✏️ Напиши фразу: /save это легендарно")
    phrase = " ".join(context.args)
    db["quotes"][key].append({"text": phrase, "by": update.effective_user.first_name})
    save_db(db)
    await update.message.reply_text(f"💾 Запомнил: _«{phrase}»_", parse_mode="Markdown")

async def random_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    quotes = db.get("quotes", {}).get(key, [])
    if not quotes:
        return await update.message.reply_text("💬 Цитат нет. /save ваша фраза")
    q = random.choice(quotes)
    await update.message.reply_text(f"💬 *Цитата:*\n\n_«{q['text']}»_\n\n— {q['by']}", parse_mode="Markdown")

# ════════════════════════════════════════════════════════════════════════════
#  🤖  ИИ — обычный чат
# ════════════════════════════════════════════════════════════════════════════

async def ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not groq_client:
        return await update.message.reply_text("⚠️ Нет GROQ_API_KEY в .env")
    key = get_chat_key(update)
    db = load_db()
    db.setdefault("ai_history", {}).setdefault(key, [])
    if not context.args:
        return await update.message.reply_text("✏️ /ai как сварить борщ?")
    user_msg = " ".join(context.args)
    history = db["ai_history"][key]
    history.append({"role": "user", "content": user_msg})
    if len(history) > 20:
        history = history[-20:]
    try:
        thinking = await update.message.reply_text("🤖 Думаю...")
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Ты дружелюбный ассистент. Отвечай коротко с юмором. Отвечай на языке пользователя."},
                *history
            ],
            max_tokens=800,
        )
        reply = response.choices[0].message.content
        history.append({"role": "assistant", "content": reply})
        db["ai_history"][key] = history
        save_db(db)
        await thinking.delete()
        await update.message.reply_text(f"🤖 {reply}")
    except Exception as e:
        logger.error(f"Groq error: {e}")
        await update.message.reply_text("❌ ИИ недоступен. Попробуй позже.")

async def reset_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    db.setdefault("ai_history", {})[key] = []
    save_db(db)
    await update.message.reply_text("🔄 История ИИ сброшена!")

# ════════════════════════════════════════════════════════════════════════════
#  🔘  CALLBACK кнопки
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

    # 📨 Business автоответ — ловим все апдейты и проверяем внутри
    app.add_handler(TypeHandler(Update, handle_business_message), group=-1)

    # Обычные команды (в личке с ботом)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("persona", set_persona))
    app.add_handler(CommandHandler("status", status))

    app.add_handler(CommandHandler("add", add_item))
    app.add_handler(CommandHandler("list", show_list))
    app.add_handler(CommandHandler("bought", bought_item))

    app.add_handler(CommandHandler("wish", add_wish))
    app.add_handler(CommandHandler("wishlist", show_wishlist))
    app.add_handler(CommandHandler("done", done_wish))

    app.add_handler(CommandHandler("check", lie_detector))
    app.add_handler(CommandHandler("save", save_quote))
    app.add_handler(CommandHandler("quote", random_quote))

    app.add_handler(CommandHandler("ai", ai_chat))
    app.add_handler(CommandHandler("reset", reset_ai))

    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("Business-бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
