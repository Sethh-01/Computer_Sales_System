import json
import logging
import os
import queue
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from apps.api.db import connect


logger = logging.getLogger("computer-sales.alerts")
_alert_queue: queue.Queue[tuple[str, str, str] | None] = queue.Queue(maxsize=200)
_cooldowns: dict[str, float] = {}
_cooldown_lock = threading.Lock()
_worker_started = False
_worker_lock = threading.Lock()


def _send_telegram(category: str, severity: str, message: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        logger.warning(
            "Telegram alert delivery is disabled; configure TELEGRAM_BOT_TOKEN "
            "and TELEGRAM_CHAT_ID."
        )
        return
    text = (
        f"Computer Sales security alert\n"
        f"Severity: {severity.upper()}\n"
        f"Event: {category}\n"
        f"Details: {message}\n"
        f"Time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
    )
    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=urlencode({"chat_id": chat_id, "text": text}).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            result = json.loads(response.read(4096))
        if not result.get("ok"):
            logger.error("Telegram rejected a security alert.")
    except HTTPError as error:
        logger.error("Telegram alert delivery returned HTTP %s.", error.code)
    except (TimeoutError, URLError, OSError, json.JSONDecodeError) as error:
        logger.error(
            "Telegram alert delivery failed (%s).",
            type(error).__name__,
        )


def _worker():
    while True:
        item = _alert_queue.get()
        try:
            if item is None:
                return
            _send_telegram(*item)
        finally:
            _alert_queue.task_done()


def _ensure_worker():
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            threading.Thread(
                target=_worker,
                name="security-alert-delivery",
                daemon=True,
            ).start()
            _worker_started = True


def record_event(
    category: str,
    severity: str,
    message: str,
    *,
    route: str = "",
    notify: bool = True,
):
    category = category[:60]
    severity = severity[:10]
    message = message[:250]
    route = route[:120]
    try:
        with connect() as connection:
            connection.execute(
                "INSERT INTO security_events (category, severity, message, route) "
                "VALUES (?, ?, ?, ?)",
                (category, severity, message, route),
            )
            connection.execute(
                "DELETE FROM security_events WHERE id <= "
                "(SELECT COALESCE(MAX(id), 0) - 2000 FROM security_events)"
            )
    except Exception:
        logger.exception("Could not persist a security event.")

    if not notify:
        return
    try:
        cooldown = max(0, min(3600, int(os.environ.get("SECURITY_ALERT_COOLDOWN_SECONDS", "60"))))
    except ValueError:
        logger.error("SECURITY_ALERT_COOLDOWN_SECONDS must be an integer.")
        cooldown = 60
    now = time.monotonic()
    with _cooldown_lock:
        last_sent = _cooldowns.get(category, 0)
        should_send = last_sent == 0 or now - last_sent >= cooldown
        if should_send:
            _cooldowns[category] = now
    if not should_send:
        return
    _ensure_worker()
    try:
        _alert_queue.put_nowait((category, severity, message))
    except queue.Full:
        logger.error("Security alert queue is full; notification was not delivered.")


def recent_events(limit: int = 20) -> list[dict]:
    limit = min(max(int(limit), 1), 100)
    with connect() as connection:
        rows = connection.execute(
            "SELECT id, category, severity, message, route, created_at "
            "FROM security_events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def clear_cooldowns():
    with _cooldown_lock:
        _cooldowns.clear()
