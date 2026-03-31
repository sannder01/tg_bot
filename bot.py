import os
import re
import json
import random
import logging
import pytz
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen, Request
from groq import Groq
from dotenv import load_dotenv
from icalendar import Calendar
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

# ─── Настройки дедлайнов ──────────────────────────────────────────────────
ICAL_URL = os.getenv(
    "ICAL_URL",
    "https://lms.astanait.edu.kz/calendar/export_execute.php"
    "?userid=17634&authtoken=3f6f62339ece52c531c9dbffe568d0eacd33444f"
    "&preset_what=all&preset_time=recentupcoming"
)
DEADLINE_CHAT_ID = os.getenv("DEADLINE_CHAT_ID", "")
DEADLINE_HOUR    = int(os.getenv("DEADLINE_HOUR",   "8"))
DEADLINE_MINUTE  = int(os.getenv("DEADLINE_MINUTE", "0"))
DEADLINE_TZ      = os.getenv("DEADLINE_TZ", "Asia/Almaty")
DAYS_AHEAD       = int(os.getenv("DAYS_AHEAD", "7"))

# ─── База данных ──────────────────────────────────────────────────────────
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
#  📚  ДЕДЛАЙНЫ
# ════════════════════════════════════════════════════════════════════════════

def escape_md(text: str) -> str:
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, "\\" + ch)
    return text


def parse_course(component) -> str:
    categories = str(component.get("CATEGORIES", ""))
    if categories and categories not in ("None", ""):
        return categories.strip()
    description = str(component.get("DESCRIPTION", ""))
    match = re.search(r"Course[:\s]+(.+)", description, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    summary = str(component.get("SUMMARY", ""))
    match = re.search(r"\((.+?)\)\s*$", summary)
    if match:
        return match.group(1).strip()
    return "Неизвестный предмет"


def fetch_deadlines() -> list:
    logger.info("Загружаю календарь...")
    req = Request(ICAL_URL, headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    })
    with urlopen(req, timeout=15) as resp:
        raw = resp.read()

    tz_obj = pytz.timezone(DEADLINE_TZ)
    cal    = Calendar.from_ical(raw)
    now    = datetime.now(tz_obj)
    limit  = now + timedelta(days=DAYS_AHEAD)
    events = []

    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        dtstart = component.get("DTSTART")
        if dtstart is None:
            continue
        dt = dtstart.dt
        if not isinstance(dt, datetime):
            dt = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = tz_obj.localize(dt)
        else:
            dt = dt.astimezone(tz_obj)
        if now <= dt <= limit:
            events.append({
                "title":  str(component.get("SUMMARY", "(без названия)")),
                "course": parse_course(component),
                "dt":     dt,
                "url":    str(component.get("URL", "")),
            })

    events.sort(key=lambda e: e["dt"])
    return events


def build_deadline_message(events: list) -> str:
    tz_obj  = pytz.timezone(DEADLINE_TZ)
    now     = datetime.now(tz_obj)
    now_str = escape_md(now.strftime("%d.%m.%Y %H:%M"))

    if not events:
        return (
            "✅ *Дедлайнов нет\\!*\n"
            "На ближайшие " + str(DAYS_AHEAD) + " дней ничего нет\\.\n"
            "_Обновлено: " + now_str + "_"
        )

    lines = [
        "📚 *Дедлайны на ближайшие " + str(DAYS_AHEAD) + " дней*",
        "_Обновлено: " + now_str + "_\n",
    ]

    for e in events:
        delta = e["dt"] - now
        days  = delta.days
        hours = delta.seconds // 3600

        if days == 0:
            left = "⚠️ сегодня, через " + str(hours) + "ч"
        elif days == 1:
            left = "🔶 завтра"
        elif days <= 3:
            left = "🟡 через " + str(days) + " д\\."
        else:
            left = "🟢 через " + str(days) + " д\\."

        date_str = escape_md(e["dt"].strftime("%d.%m %H:%M"))
        title    = escape_md(e["title"])
        course   = escape_md(e["course"])

        line = (
            left + " — *" + title + "*\n"
            "    📖 " + course + "\n"
            "    📅 " + date_str
        )
        if e["url"] and e["url"] != "None":
            line += "\n    🔗 [Открыть](" + e["url"] + ")"
        lines.append(line)

    return "\n\n".join(lines)


async def cmd_deadlines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /deadlines — показать дедлайны прямо сейчас."""
    msg = await update.message.reply_text("⏳ Загружаю дедлайны...")
    try:
        events  = fetch_deadlines()
        message = build_deadline_message(events)
        await msg.edit_text(message, parse_mode="MarkdownV2", disable_web_page_preview=True)
    except Exception as e:
        logger.error("Ошибка дедлайнов: %s", e)
        await msg.edit_text("❌ Не удалось загрузить дедлайны:\n<code>" + str(e) + "</code>", parse_mode="HTML")


async def daily_deadlines_job(context):
    """Ежедневная задача — отправить дедлайны."""
    if not DEADLINE_CHAT_ID:
        return
    try:
        events  = fetch_deadlines()
        message = build_deadline_message(events)
        await context.bot.send_message(
            chat_id=DEADLINE_CHAT_ID,
            text=message,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )
        logger.info("Дедлайны отправлены (%d событий)", len(events))
    except Exception as e:
        logger.error("Ошибка daily_deadlines_job: %s", e)
        await context.bot.send_message(
            chat_id=DEADLINE_CHAT_ID,
            text="❌ Не удалось загрузить дедлайны:\n<code>" + str(e) + "</code>",
            parse_mode="HTML",
        )

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

    if is_owner and not user_text.startswith("/"):
        return

    if not groq_client:
        return

    # ── Обработка команд из бизнес-чата ─────────────────────────────────────
    if user_text.startswith("/"):
        cmd = user_text.split()[0].lower().replace("/", "")
        args = user_text.split()[1:]
        db = load_db()

        if cmd == "add" and args:
            item = " ".join(args)
            db.setdefault("shopping", {}).setdefault(chat_id, [])
            db["shopping"][chat_id].append({"name": item, "done": False, "by": sender_name})
            save_db(db)
            reply = "✅ *" + item + "* добавлен в список покупок!"

        elif cmd == "list":
            items = db.get("shopping", {}).get(chat_id, [])
            if not items:
                reply = "🛒 Список пуст. Напиши /add"
            else:
                lines = ["🛒 *Список покупок:*\n"]
                for i, it in enumerate(items, 1):
                    icon = "✅" if it["done"] else "◻️"
                    lines.append(icon + " " + str(i) + ". " + it["name"] + " _(" + it["by"] + ")_")
                reply = "\n".join(lines)

        elif cmd == "bought" and args and args[0].isdigit():
            items = db.get("shopping", {}).get(chat_id, [])
            idx = int(args[0]) - 1
            if 0 <= idx < len(items):
                items[idx]["done"] = True
                save_db(db)
                reply = "✅ *" + items[idx]["name"] + "* куплен!"
            else:
                reply = "❌ Нет такого номера."

        elif cmd == "wish" and args:
            wish = " ".join(args)
            db.setdefault("wishlist", {}).setdefault(chat_id, [])
            db["wishlist"][chat_id].append({"name": wish, "done": False, "by": sender_name})
            save_db(db)
            reply = "⭐ *" + wish + "* добавлен в вишлист!"

        elif cmd == "wishlist":
            items = db.get("wishlist", {}).get(chat_id, [])
            if not items:
                reply = "🎯 Вишлист пуст. Напиши /wish что-нибудь"
            else:
                lines = ["🎯 *Вишлист:*\n"]
                for i, it in enumerate(items, 1):
                    icon = "✅" if it["done"] else "⭐"
                    lines.append(icon + " " + str(i) + ". " + it["name"] + " _(" + it["by"] + ")_")
                reply = "\n".join(lines)

        elif cmd == "done" and args and args[0].isdigit():
            items = db.get("wishlist", {}).get(chat_id, [])
            idx = int(args[0]) - 1
            if 0 <= idx < len(items):
                items[idx]["done"] = True
                save_db(db)
                reply = "🎉 *" + items[idx]["name"] + "* исполнено!"
            else:
                reply = "❌ Нет такого номера."

        elif cmd == "check":
            claim = " ".join(args) if args else "это"
            pct = random.randint(0, 100)
            bar = "🟩" * (pct // 10) + "⬜" * (10 - pct // 10)
            verdicts = ["🤥 Наглая ЛОЖЬ!", "😬 Скорее врёт...", "🤔 Сомнительно", "✅ Чистая правда!"]
            verdict = verdicts[min(pct // 25, 3)]
            reply = "🕵️ *Детектор лжи*\n\n_" + claim + "_\n\n📊 " + str(pct) + "%\n" + bar + "\n\n" + verdict

        elif cmd == "quote":
            quotes = db.get("quotes", {}).get(chat_id, [])
            if quotes:
                q = random.choice(quotes)
                reply = "💬 _«" + q["text"] + "»_\n\n— " + q["by"]
            else:
                reply = "💬 Цитат пока нет."

        elif cmd == "deadlines":
            try:
                events  = fetch_deadlines()
                reply_md = build_deadline_message(events)
                await context.bot.send_message(
                    chat_id=message.chat.id,
                    text=reply_md,
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=True,
                    business_connection_id=message.business_connection_id
                )
            except Exception as e:
                await context.bot.send_message(
                    chat_id=message.chat.id,
                    text="❌ Не удалось загрузить дедлайны:\n<code>" + str(e) + "</code>",
                    parse_mode="HTML",
                    business_connection_id=message.business_connection_id
                )
            return

        elif cmd == "ai" and args:
            if not groq_client:
                reply = "⚠️ ИИ не настроен"
            else:
                user_msg = " ".join(args)
                try:
                    response = groq_client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=[
                            {"role": "system", "content": "Ты дружелюбный ассистент. Отвечай коротко с юмором. Отвечай на языке пользователя."},
                            {"role": "user", "content": user_msg}
                        ],
                        max_tokens=500,
                    )
                    reply = "🤖 " + response.choices[0].message.content
                except Exception:
                    reply = "❌ ИИ недоступен. Попробуй позже."

        elif cmd == "stop":
            db.setdefault("ai_enabled", {})[chat_id] = False
            save_db(db)
            reply = "🔇 Автоответ ИИ отключён. Команды работают.\nНапиши /resume чтобы включить."

        elif cmd == "resume":
            db.setdefault("ai_enabled", {})[chat_id] = True
            save_db(db)
            reply = "🔊 Автоответ ИИ включён!"

        elif cmd == "help":
            reply = (
                "📋 *Команды для чата:*\n\n"
                "/add — добавить покупку\n"
                "/list — список покупок\n"
                "/bought 1 — вычеркнуть\n\n"
                "/wish — добавить в вишлист\n"
                "/wishlist — показать вишлист\n"
                "/done 1 — исполнено\n\n"
                "/check — детектор лжи\n"
                "/quote — случайная цитата\n\n"
                "/deadlines — дедлайны AITU LMS\n\n"
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
            logger.error("Ошибка отправки команды: %s", e)
        return

    # ── Обычное сообщение — отвечает ИИ ─────────────────────────────────────
    db = load_db()

    if not db.get("ai_enabled", {}).get(chat_id):
        return

    db.setdefault("business_history", {}).setdefault(chat_id, [])
    history = db["business_history"][chat_id]
    history.append({"role": "user", "content": sender_name + ": " + user_text})
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
        logger.info("Автоответ для %s: %s...", sender_name, reply[:50])
    except Exception as e:
        logger.error("Ошибка автоответа: %s", e)

# ════════════════════════════════════════════════════════════════════════════
#  /start
# ════════════════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ai = "✅ Подключён (Llama 3)" if groq_client else "❌ Нет GROQ_API_KEY"
    dl = ("✅ " + DEADLINE_CHAT_ID) if DEADLINE_CHAT_ID else "⚠️ не задан DEADLINE_CHAT_ID"
    await update.message.reply_text(
        "👋 Привет! Я твой Business-бот.\n"
        "🤖 ИИ: " + ai + "\n\n"
        "📨 *Автоответ:*\n"
        "  Подключи в Настройки → Business → Чат-боты\n\n"
        "📚 *Дедлайны AITU LMS:*\n"
        "  /deadlines — показать прямо сейчас\n"
        "  _(авторассылка в " + str(DEADLINE_HOUR) + ":00 → " + dl + ")_\n\n"
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
    await update.message.reply_text("✅ Стиль обновлён:\n\n_" + AUTO_REPLY_SYSTEM_PROMPT + "_", parse_mode="Markdown")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ai = "✅ Подключён" if groq_client else "❌ Не настроен"
    await update.message.reply_text(
        "⚙️ *Статус:*\n\n"
        "🤖 ИИ: " + ai + "\n"
        "📝 Стиль:\n_" + AUTO_REPLY_SYSTEM_PROMPT + "_",
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
        return await update.message.reply_text("✏️ /add молоко")
    item = " ".join(context.args)
    db["shopping"][key].append({"name": item, "done": False, "by": update.effective_user.first_name})
    save_db(db)
    await update.message.reply_text("✅ *" + item + "* добавлен!", parse_mode="Markdown")

async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    items = db.get("shopping", {}).get(key, [])
    if not items:
        return await update.message.reply_text("🛒 Список пуст. /add молоко")
    lines = ["🛒 *Список покупок:*\n"]
    for i, it in enumerate(items, 1):
        icon = "✅" if it["done"] else "◻️"
        lines.append(icon + " " + str(i) + ". " + it["name"] + " _(" + it["by"] + ")_")
    keyboard = [[InlineKeyboardButton("🗑 Очистить", callback_data="clear_shop_" + key)]]
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
        await update.message.reply_text("✅ *" + items[idx]["name"] + "* куплен!", parse_mode="Markdown")
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
    await update.message.reply_text("⭐ *" + wish + "* добавлен!", parse_mode="Markdown")

async def show_wishlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    items = db.get("wishlist", {}).get(key, [])
    if not items:
        return await update.message.reply_text("🎯 Вишлист пуст. /wish что-нибудь")
    lines = ["🎯 *Вишлист:*\n"]
    for i, it in enumerate(items, 1):
        icon = "✅" if it["done"] else "⭐"
        lines.append(icon + " " + str(i) + ". " + it["name"] + " _(" + it["by"] + ")_")
    keyboard = [[InlineKeyboardButton("🗑 Очистить", callback_data="clear_wish_" + key)]]
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
        await update.message.reply_text("🎉 *" + items[idx]["name"] + "* исполнено!", parse_mode="Markdown")
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
        icon + " *Детектор лжи*\n\n👤 " + user + ": _" + text + "_\n\n📊 " + str(pct_show) + "%\n" + bar + "\n\n🔍 " + verdict,
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
    await update.message.reply_text("💾 _«" + phrase + "»_", parse_mode="Markdown")

async def random_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = get_chat_key(update)
    db = load_db()
    quotes = db.get("quotes", {}).get(key, [])
    if not quotes:
        return await update.message.reply_text("💬 Цитат нет. /save ваша фраза")
    q = random.choice(quotes)
    await update.message.reply_text("💬 _«" + q["text"] + "»_\n\n— " + q["by"], parse_mode="Markdown")

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
        await update.message.reply_text("🤖 " + reply)
    except Exception as e:
        logger.error("Groq error: %s", e)
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
    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("help",      start))
    app.add_handler(CommandHandler("persona",   set_persona))
    app.add_handler(CommandHandler("status",    status))

    app.add_handler(CommandHandler("deadlines", cmd_deadlines))  # 📚

    app.add_handler(CommandHandler("add",       add_item))
    app.add_handler(CommandHandler("list",      show_list))
    app.add_handler(CommandHandler("bought",    bought_item))

    app.add_handler(CommandHandler("wish",      add_wish))
    app.add_handler(CommandHandler("wishlist",  show_wishlist))
    app.add_handler(CommandHandler("done",      done_wish))

    app.add_handler(CommandHandler("check",     lie_detector))
    app.add_handler(CommandHandler("save",      save_quote))
    app.add_handler(CommandHandler("quote",     random_quote))

    app.add_handler(CommandHandler("ai",        ai_chat))
    app.add_handler(CommandHandler("reset",     reset_ai))

    app.add_handler(CallbackQueryHandler(callback_handler))

    # 📅 Ежедневная рассылка дедлайнов
    if DEADLINE_CHAT_ID:
        tz_obj = pytz.timezone(DEADLINE_TZ)
        send_time = datetime.now(tz_obj).replace(
            hour=DEADLINE_HOUR, minute=DEADLINE_MINUTE, second=0, microsecond=0
        ).timetz()
        app.job_queue.run_daily(daily_deadlines_job, time=send_time)
        logger.info("Рассылка дедлайнов: %02d:%02d %s → %s",
                    DEADLINE_HOUR, DEADLINE_MINUTE, DEADLINE_TZ, DEADLINE_CHAT_ID)
    else:
        logger.warning("DEADLINE_CHAT_ID не задан — ежедневная рассылка отключена")

    logger.info("Business-бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
