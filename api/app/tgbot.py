"""Talking to Telegram: sending messages, and listening for what people send the bot (linking, /status, /pause ...).

Telegram is reached only from here, and only outwards: the app asks Telegram for new messages (long polling),
so no port has to be opened and the site stays private.
"""
import asyncio
import html
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

log = logging.getLogger("xyron.telegram")
API = "https://api.telegram.org"
MAX_TEXT = 4000          # Telegram refuses messages over 4096 characters
MIN_GAP = 1.1            # seconds between messages to one chat (Telegram's own limit is about one a second)


class TelegramError(Exception):
    def __init__(self, code, description, retry_after=0):
        super().__init__(f"{code}: {description}")
        self.code, self.description, self.retry_after = code, description, retry_after


def token():
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def bot_username():
    return os.environ.get("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")


def configured():
    return bool(token())


def esc(text):
    return html.escape(str(text if text is not None else ""), quote=False)


def clip(text, n=MAX_TEXT):
    text = str(text)
    return text if len(text) <= n else text[: n - 1].rstrip() + "\u2026"


def api_call(method, params=None, timeout=35):
    """One call to the Bot API. Returns Telegram's 'result', or raises TelegramError. The token never appears in an error."""
    tok = token()
    if not tok:
        raise TelegramError(0, "no bot token is configured")
    req = urllib.request.Request(f"{API}/bot{tok}/{method}", data=json.dumps(params or {}).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            data = json.load(e)
        except Exception:
            data = {"ok": False, "error_code": e.code, "description": f"HTTP {e.code}"}
    except Exception as e:
        raise TelegramError(0, f"{type(e).__name__}: {str(e).replace(tok, '<token>')[:120]}")
    if not data.get("ok"):
        raise TelegramError(data.get("error_code", 0), str(data.get("description", "failed")).replace(tok, "<token>")[:200], (data.get("parameters") or {}).get("retry_after", 0))
    return data.get("result")


_last_sent = {}
_gap_lock = threading.Lock()


def pace(chat_id, now=time.monotonic, sleep=time.sleep):
    """Wait just long enough that one chat never gets more than one message a second."""
    with _gap_lock:
        wait = _last_sent.get(chat_id, 0) + MIN_GAP - now()
        if wait > 0:
            sleep(wait)
        _last_sent[chat_id] = now()


def send_message(chat_id, text, buttons=None, call=None):
    call = call or api_call
    pace(chat_id)
    params = {"chat_id": chat_id, "text": clip(text), "parse_mode": "HTML", "disable_web_page_preview": True}
    if buttons:
        params["reply_markup"] = {"inline_keyboard": buttons}
    return call("sendMessage", params)


def answer_callback(callback_id, text="", call=None):
    try:
        (call or api_call)("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:180]})
    except TelegramError:
        pass  # the button already did its job; a failed acknowledgement only leaves a spinner


async def poll_loop(handler, load_offset, save_offset, call=None, sleeper=None):
    """Listens for people messaging the bot. `handler(update)` is called for each one."""
    call = call or api_call
    sleeper = sleeper or asyncio.sleep
    if not configured():
        log.warning("telegram: no TELEGRAM_BOT_TOKEN, so the bot stays quiet")
        return
    try:
        await asyncio.to_thread(call, "deleteWebhook", {"drop_pending_updates": False})  # a leftover webhook would block polling
    except TelegramError as e:
        log.warning("telegram: could not clear a webhook: %s", e)
    offset = await asyncio.to_thread(load_offset)
    backoff = 5
    log.info("telegram: bot is listening")
    while True:
        try:
            updates = await asyncio.to_thread(call, "getUpdates", {"offset": offset, "timeout": 25, "allowed_updates": ["message", "callback_query"]}, 40)
            backoff = 5
        except asyncio.CancelledError:
            raise
        except TelegramError as e:
            if e.code == 401:
                log.error("telegram: the token was rejected; the bot is stopping. Check TELEGRAM_BOT_TOKEN")
                return
            wait = e.retry_after or (30 if e.code == 409 else backoff)
            log.warning("telegram: polling problem (%s); trying again in %s s", e, wait)
            await sleeper(wait)
            backoff = min(300, backoff * 2)
            continue
        for u in updates or []:
            offset = max(offset, int(u.get("update_id", 0)) + 1)
            try:
                await asyncio.to_thread(handler, u)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("telegram: a message could not be handled")
        if updates:
            await asyncio.to_thread(save_offset, offset)
