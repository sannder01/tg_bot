"""
config.py — центральное хранилище всех настроек и переменных окружения.
Импортируй отсюда, не читай os.getenv() где попало.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ── Groq / LLM ────────────────────────────────────────────────────────────────
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
BOT_PERSONA: str  = os.getenv(
    "BOT_PERSONA",
    (
        "Ты отвечаешь вместо владельца этого Telegram аккаунта. "
        "Отвечай вежливо, коротко и по делу. "
        "Если не знаешь ответа — скажи что владелец скоро ответит лично. "
        "Отвечай на языке собеседника."
    ),
)

# ── Дедлайны (AITU LMS iCal) ─────────────────────────────────────────────────
ICAL_URL: str = os.getenv(
    "ICAL_URL",
    (
        "https://lms.astanait.edu.kz/calendar/export_execute.php"
        "?userid=17634&authtoken=3f6f62339ece52c531c9dbffe568d0eacd33444f"
        "&preset_what=courses&preset_time=recentupcoming"
    ),
)
DEADLINE_CHAT_ID: str = os.getenv("DEADLINE_CHAT_ID", "")
DEADLINE_HOUR:    int  = int(os.getenv("DEADLINE_HOUR",   "8"))
DEADLINE_MINUTE:  int  = int(os.getenv("DEADLINE_MINUTE", "0"))
DEADLINE_TZ:      str  = os.getenv("DEADLINE_TZ", "Asia/Almaty")
DAYS_AHEAD:       int  = int(os.getenv("DAYS_AHEAD", "7"))
