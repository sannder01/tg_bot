"""
db.py — простой JSON-персистент.

Структура data.json:
{
    "tasks":            { "<chat_id>": [ {id, text, done, created_at}, ... ] },
    "quotes":           { "<chat_id>": [ {text, by}, ... ] },
    "ai_history":       { "<chat_id>": [ {role, content}, ... ] },
    "business_history": { "<chat_id>": [ {role, content}, ... ] },
    "ai_enabled":       { "<chat_id>": true | false }
}
"""

import json
import os

DB_FILE = "data.json"

_DEFAULTS: dict = {
    "tasks":            {},
    "quotes":           {},
    "ai_history":       {},
    "business_history": {},
    "ai_enabled":       {},
}


def load_db() -> dict:
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # гарантируем наличие всех ключей при миграции старых данных
        for key, default in _DEFAULTS.items():
            data.setdefault(key, default)
        return data
    return dict(_DEFAULTS)


def save_db(db: dict) -> None:
    with open(DB_FILE, "w", encoding="utf-8") as fh:
        json.dump(db, fh, ensure_ascii=False, indent=2)
