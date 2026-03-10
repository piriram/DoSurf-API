"""Alert utilities (Telegram)."""

from __future__ import annotations

import datetime
import os
from typing import Dict, Any

import requests
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def _now_kst_text() -> str:
    return datetime.datetime.now(tz=KST).strftime("%Y-%m-%d %H:%M:%S KST")


def send_telegram_alert(message: str, *, level: str = "ERROR", source: str = "do-surf-functions") -> Dict[str, Any]:
    """
    Send alert to Telegram if TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID are configured.

    Returns:
        {"sent": bool, "reason": str | None, "response": dict | None}
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return {"sent": False, "reason": "not_configured", "response": None}

    text = (
        f"🚨 DoSurf Alert ({level})\n"
        f"- source: {source}\n"
        f"- time: {_now_kst_text()}\n"
        f"\n{message}"
    )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return {"sent": True, "reason": None, "response": resp.json()}
    except Exception as e:
        return {"sent": False, "reason": f"send_failed: {e}", "response": None}
