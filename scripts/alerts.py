"""Backward-compatible alert import path."""

from app.clients.alerts import send_telegram_alert

__all__ = ["send_telegram_alert"]
