"""
handlers/deadlines.py — дедлайны из iCal (AITU LMS).
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

import pytz
from icalendar import Calendar

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import DEADLINE_TZ, DAYS_AHEAD, ICAL_URL, DEADLINE_CHAT_ID

logger = logging.getLogger(__name__)


# ─── Утилиты ─────────────────────────────────────────────────────────────────

def _escape_md(text: str) -> str:
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, "\\" + ch)
    return text


def _parse_course(component) -> str:
    categories = str(component.get("CATEGORIES", ""))
    if categories and categories not in ("None", ""):
        return categories.strip()
    description = str(component.get("DESCRIPTION", ""))
    m = re.search(r"Course[:\s]+(.+)", description, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    summary = str(component.get("SUMMARY", ""))
    m = re.search(r"\((.+?)\)\s*$", summary)
    if m:
        return m.group(1).strip()
    return "Неизвестный предмет"


# ─── Получение и парсинг дедлайнов ───────────────────────────────────────────

def fetch_deadlines() -> list[dict]:
    logger.info("Загружаю календарь...")
    req = Request(
        ICAL_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
    )
    with urlopen(req, timeout=15) as resp:
        raw = resp.read()

    tz_obj = pytz.timezone(DEADLINE_TZ)
    cal    = Calendar.from_ical(raw)
    now    = datetime.now(tz_obj)
    limit  = now + timedelta(days=DAYS_AHEAD)
    events: list[dict] = []

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
                "course": _parse_course(component),
                "dt":     dt,
                "url":    str(component.get("URL", "")),
            })

    events.sort(key=lambda e: e["dt"])
    return events


def build_deadline_message(events: list[dict]) -> str:
    tz_obj  = pytz.timezone(DEADLINE_TZ)
    now     = datetime.now(tz_obj)
    now_str = _escape_md(now.strftime("%d.%m.%Y %H:%M"))

    if not events:
        return (
            "✅ *Дедлайнов нет\\!*\n"
            f"На ближайшие {DAYS_AHEAD} дней ничего нет\\.\n"
            f"_Обновлено: {now_str}_"
        )

    lines = [
        f"📚 *Дедлайны на ближайшие {DAYS_AHEAD} дней*",
        f"_Обновлено: {now_str}_\n",
    ]

    for e in events:
        delta = e["dt"] - now
        days  = delta.days
        hours = delta.seconds // 3600

        if days == 0:
            left = f"⚠️ сегодня, через {hours}ч"
        elif days == 1:
            left = "🔶 завтра"
        elif days <= 3:
            left = f"🟡 через {days} д\\."
        else:
            left = f"🟢 через {days} д\\."

        date_str = _escape_md(e["dt"].strftime("%d.%m %H:%M"))
        title    = _escape_md(e["title"])
        course   = _escape_md(e["course"])

        line = (
            f"{left} — *{title}*\n"
            f"    📖 {course}\n"
            f"    📅 {date_str}"
        )
        if e["url"] and e["url"] != "None":
            line += f"\n    🔗 [Открыть]({e['url']})"
        lines.append(line)

    return "\n\n".join(lines)


# ─── Handlers ────────────────────────────────────────────────────────────────

async def cmd_deadlines(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/deadlines — показать дедлайны прямо сейчас."""
    msg = await update.message.reply_text("⏳ Загружаю дедлайны...")
    try:
        events  = fetch_deadlines()
        message = build_deadline_message(events)
        await msg.edit_text(message, parse_mode="MarkdownV2", disable_web_page_preview=True)
    except Exception as exc:
        logger.error("Ошибка дедлайнов: %s", exc)
        await msg.edit_text(
            f"❌ Не удалось загрузить дедлайны:\n<code>{exc}</code>",
            parse_mode=ParseMode.HTML,
        )


async def daily_deadlines_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ежедневная задача — рассылка дедлайнов."""
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
    except Exception as exc:
        logger.error("Ошибка daily_deadlines_job: %s", exc)
        await context.bot.send_message(
            chat_id=DEADLINE_CHAT_ID,
            text=f"❌ Не удалось загрузить дедлайны:\n<code>{exc}</code>",
            parse_mode=ParseMode.HTML,
        )
