import os
import json
import random
import logging
from groq import Groq
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler,
    CallbackQueryHandler, ContextTypes,
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

AUTO_REPLY_SYSTEM_PROMPT = os.getenv("BOT_PERSONA", (
    "Ты отвечаешь вместо владельца этого Telegram аккаунта. "
    "Отвечай вежливо, коротко и по делу. "
    "Если не знаешь ответа — скажи что владелец скоро ответит лично. "
    "Отвечай на языке собеседника."
))

DB_FILE = "data.json"

def load_db() -> dict:
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "shopping": {},
        "wishlist": {},
        "quotes": {},
        "ai_history": {},
        "business_history": {},
        "ai_disabled": {}
    }

def save_db(db: dict):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def get_chat_key(update: Update) -> str:
    return str(update.effective_chat.id)

# ════════════════════════════════════════════════════════════════════════════
#  🤖  BUSINESS — автоответ + команды в чате
# ════════════════════════════════════════════════════════════════════════════

async def handle_business_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = update.business_message
    except AttributeError:
        return

    if not message or not message.text:
        return

    if message.from_user and message.from_user.is_bot:
        return

    
    sender_name = message.from_user.first_name if message.from_user else "Собеседник"
    chat_id = str(message.chat.id)
    user_text = message.text

    # Не отвечаем на сообщения владельца аккаунта
    # Если это владелец — только команды, не ИИ
    is_owner = False
    if update.business_message.business_connection_id:
        try:
            connection = await context.bot.get_business_connection(
                update.business_message.business_connection_id
            )
            if message.from_user and connection.user.id == message.from_user.id:
                is_owner = True
        except Exception:
            pass

    # Владелец пишет обычное сообщение — игнорируем
    if is_owner and not user_text.startswith("/"):
        return

    if not groq_client:
        return

    
    # ── Обработка команд из бизнес-чата ──────────────────────────────────────
    if user_text.startswith("/"):
        cmd = user_text.split()[0].lower().replace("/", "")
        args = user_text.split()[1:]
        db = load_db()

        # /add товар
        if cmd == "add" and args:
            item = " ".join(args)
            db.setdefault("shopping", {}).setdefault(chat_id, [])
            db["shopping"][chat_id].append({"name": item, "done": False, "by": sender_name})
            save_db(db)
            reply = f"✅ *{item}* добавлен в список покупок!"

        # /list
        elif cmd == "list":
            items = db.get("shopping", {}).get(chat_id, [])
            if not items:
                reply = "🛒 Список пуст. Напиши /add молоко"
            else:
                lines = ["🛒 *Список покупок:*\n"]
                for i, it in enumerate(items, 1):
                    icon = "✅" if it["done"] else "◻️"
                    lines.append(f"{icon} {i}. {it['name']} _({it['by']})_")
                reply = "\n".join(lines)

        # /bought номер
        elif cmd == "bought" and args and args[0].isdigit():
            items = db.get("shopping", {}).get(chat_id, [])
            idx = int(args[0]) - 1
            if 0 <= idx < len(items):
                items[idx]["done"] = True
                save_db(db)
                reply = f"✅ *{items[idx]['name']}* куплен!"
            else:
                reply = "❌ Нет такого номера."

        # /wish желание
        elif cmd == "wish" and args:
            wish = " ".join(args)
            db.setdefault("wishlist", {}).setdefault(chat_id, [])
            db["wishlist"][chat_id].append({"name": wish, "done": False, "by": sender_name})
            save_db(db)
            reply = f"⭐ *{wish}* добавлен в вишлист!"

        # /wishlist
        elif cmd == "wishlist":
            items = db.get("wishlist", {}).get(chat_id, [])
            if not items:
                reply = "🎯 Вишлист пуст. Напиши /wish что-нибудь"
            else:
                lines = ["🎯 *Вишлист:*\n"]
                for i, it in enumerate(items, 1):
                    icon = "✅" if it["done"] else "⭐"
                    lines.append(f"{icon} {i}. {it['name']} _({it['by']})_")
                reply = "\n".join(lines)

        # /done номер
        elif cmd == "done" and args and args[0].isdigit():
            items = db.get("wishlist", {}).get(chat_id, [])
            idx = int(args[0]) - 1
            if 0 <= idx < len(items):
                items[idx]["done"] = True
                save_db(db)
                reply = f"🎉 *{items[idx]['name']}* исполнено!"
            else:
                reply = "❌ Нет такого номера."

        # /check текст
        elif cmd == "check":
            claim = " ".join(args) if args else "это"
            pct = random.randint(0, 100)
            bar = "🟩" * (pct // 10) + "⬜" * (10 - pct // 10)
            verdicts = ["🤥 Наглая ЛОЖЬ!", "😬 Скорее врёт...", "🤔 Сомнительно", "✅ Чистая правда!"]
            verdict = verdicts[min(pct // 25, 3)]
            reply = f"🕵️ *Детектор лжи*\n\n_{claim}_\n\n📊 {pct}%\n{bar}\n\n{verdict}"

        # /quote
        elif cmd == "quote":
            quotes = db.get("quotes", {}).get(chat_id, [])
            if quotes:
                q = random.choice(quotes)
                reply = f"💬 _«{q['text']}»_\n\n— {q['by']}"
            else:
                reply = "💬 Цитат пока нет."

        # /stop — отключить ИИ
        elif cmd == "stop":
            db.setdefault("ai_enabled", {})[chat_id] = False
            save_db(db)
            reply = "🔇 Автоответ ИИ отключён. Команды работают.\nНапиши /resume чтобы включить."

        elif cmd == "resume":
            db.setdefault("ai_enabled", {})[chat_id] = True
            save_db(db)
            reply = "🔊 Автоответ ИИ включён!"

        # /help
        elif cmd == "help":
            reply = (
                "📋 *Команды для чата:*\n\n"
                "/add молоко — добавить покупку\n"
                "/list — список покупок\n"
                "/bought 1 — вычеркнуть\n\n"
                "/wish AirPods — добавить в вишлист\n"
                "/wishlist — показать вишлист\n"
                "/done 1 — исполнено\n\n"
                "/check текст — детектор лжи\n"
                "/quote — случайная цитата\n\n"
                "/stop — отключить автоответ ИИ\n"
                "/resume — включить автоответ ИИ"
            )

        else:
            reply = "❓ Неизвестная команда. Напиши /help"

        try:
            await context.bot.send_message(
                chat_id=message.chat.id,
                text=reply,
                parse_mode="Markdown",
                business_connection_id=message.business_connection_id
            )
        except Exception as e:
            logger.error(f"Ошибка отправки команды: {e}")
        return

    # ── Обычное сообщение — отвечает ИИ ──────────────────────────────────────
    db = load_db()

    # Проверяем не отключён ли ИИ
    if not db.get("ai_enabled", {}).get(chat_id):
        return

    db.setdefault("business_history", {}).setdefault(chat_id, [])
    history = db["business_history"][chat_id]
    history.append({"role": "user", "content": f"{sender_name}: {user_text}"})
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

        await context.bot.send_message(
            chat_id=message.chat.id,
            text=reply,
            business_connection_id=message.business_connection_id
        )
        logger.info(f"Автоответ для {sender_name}: {reply[:50]}")
    except Exception as e:
        logger.error(f"Ошибка автоответа: {e}")

# ════════════════════════════════════════════════════════════════════════════
#  /start — управление ботом в личке с ботом
# ════════════════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ai = "✅ Подключён (Llama 3)" if groq_client else "❌ Нет GROQ_API_KEY"
    await update.message.reply_text(
        f"👋 Привет! Я твой Business-бот.\n"
        f"🤖 ИИ: {ai}\n\n"
        "📨 *Автоответ:*\n"
        "  Подключи в Настройки → Business → Чат-боты\n\n"
        "🛒 /add молоко — добавить покупку\n"
        "📋 /list — список покупок\n"
        "✅ /bought 1 — вычеркнуть\n\n"
        "⭐ /wish AirPods — добавить в вишлист\n"
        "📋 /wishlist — вишлист\n"
        "✅ /done 1 — исполнено\n\n"
        "🤥 /check текст — детектор лжи\n"
        "💬 /save фраза — сохранить цитату\n"
        "🎲 /quote — случайная цитата\n\n"
        "🤖 /ai вопрос — спросить ИИ\n"
        "🔄 /reset — сброс истории ИИ\n\n"
        "⚙️ /persona текст — изменить стиль автоответа\n"
        "📊 /status — статус бота",
        parse_mode="Markdown"
    )

# ════════════════════════════════════════════════════════════════════════════
#  ⚙️  НАСТРОЙКИ
# ════════════════════════════════════════════════════════════════════════════

async def set_persona(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AUTO_REPLY_SYSTEM_PROMPT
    if not context.args:
        return await update.message.reply_text(
            "✏️ Укажи стиль:\n\n"
            "/persona Отвечай кратко, я занятой человек\n"
            "/persona Скажи что я занят и отвечу позже\n"
            "/persona Отвечай дружелюбно с юмором"
        )
    AUTO_REPLY_SYSTEM_PROMPT = " ".join(context.args)
    await update.message.reply_text(f"✅ Стиль обновлён:\n\n_{AUTO_REPLY_SYSTEM_PROMPT}_", parse_mode="Markdown")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ai = "✅ Подключён" if groq_client else "❌ Не настроен"
    await update.message.reply_text(
        f"⚙️ *Статус:*\n\n"
        f"🤖 ИИ: {ai}\n"
        f"📝 Стиль:\n_{AUTO_REPLY_SYSTEM_PROMPT}_",
        parse_mode="Markdown"
    )

# ════════════════════════════════════════════════════════════════════════════
#  🛒  СПИСОК ПОКУПОК (команды в личке с ботом)
# ════════════════════════════════════════════════════════════════════════════

async def add_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    db.setdefault("shopping", {}).setdefault(key, [])
    if not context.args:
        return await update.message.reply_text("✏️ /add молоко")
    item = " ".join(context.args)
    db["shopping"][key].append({"name": item, "done": False, "by": update.effective_user.first_name})
    save_db(db)
    await update.message.reply_text(f"✅ *{item}* добавлен!", parse_mode="Markdown")

async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    items = db.get("shopping", {}).get(key, [])
    if not items:
        return await update.message.reply_text("🛒 Список пуст. /add молоко")
    lines = ["🛒 *Список покупок:*\n"]
    for i, it in enumerate(items, 1):
        icon = "✅" if it["done"] else "◻️"
        lines.append(f"{icon} {i}. {it['name']} _({it['by']})_")
    keyboard = [[InlineKeyboardButton("🗑 Очистить", callback_data=f"clear_shop_{key}")]]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def bought_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    items = db.get("shopping", {}).get(key, [])
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text("✏️ /bought 2")
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
        return await update.message.reply_text("✏️ /wish поехать в Японию")
    wish = " ".join(context.args)
    db["wishlist"][key].append({"name": wish, "done": False, "by": update.effective_user.first_name})
    save_db(db)
    await update.message.reply_text(f"⭐ *{wish}* добавлен!", parse_mode="Markdown")

async def show_wishlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    items = db.get("wishlist", {}).get(key, [])
    if not items:
        return await update.message.reply_text("🎯 Вишлист пуст. /wish что-нибудь")
    lines = ["🎯 *Вишлист:*\n"]
    for i, it in enumerate(items, 1):
        icon = "✅" if it["done"] else "⭐"
        lines.append(f"{icon} {i}. {it['name']} _({it['by']})_")
    keyboard = [[InlineKeyboardButton("🗑 Очистить", callback_data=f"clear_wish_{key}")]]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def done_wish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    items = db.get("wishlist", {}).get(key, [])
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text("✏️ /done 1")
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
        return await update.message.reply_text("✏️ /save это легендарно")
    phrase = " ".join(context.args)
    db["quotes"][key].append({"text": phrase, "by": update.effective_user.first_name})
    save_db(db)
    await update.message.reply_text(f"💾 _«{phrase}»_", parse_mode="Markdown")

async def random_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    quotes = db.get("quotes", {}).get(key, [])
    if not quotes:
        return await update.message.reply_text("💬 Цитат нет. /save ваша фраза")
    q = random.choice(quotes)
    await update.message.reply_text(f"💬 _«{q['text']}»_\n\n— {q['by']}", parse_mode="Markdown")

# ════════════════════════════════════════════════════════════════════════════
#  🤖  ИИ
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

    # Business автоответ
    app.add_handler(TypeHandler(Update, handle_business_message), group=-1)

    # Команды в личке с ботом
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
