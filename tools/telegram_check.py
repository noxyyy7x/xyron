#!/usr/bin/env python3
"""Checks that your Telegram bot works from this Pi. It never prints the token.

   python3 tools/telegram_check.py            check the bot and the connection
   python3 tools/telegram_check.py --send     also send you a test message (message your bot first)
"""
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.telegram.org"
PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"


def parse_env(text):
    out = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def redact(text, token):
    return str(text).replace(token, "<token>") if token else str(text)


def call(token, method, params=None, timeout=20):
    req = urllib.request.Request(f"{API}/bot{token}/{method}", data=json.dumps(params or {}).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:  # Telegram explains its refusals in the body
        try:
            return json.load(e)
        except Exception:
            return {"ok": False, "error_code": e.code, "description": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "error_code": 0, "description": f"{type(e).__name__}: {redact(e, token)}"}


def run(env_text, api=call, send=False):
    """Returns a list of (level, title, detail). `api(token, method, params)` is how Telegram is reached."""
    out = []
    env = parse_env(env_text)
    token, want = env.get("TELEGRAM_BOT_TOKEN", ""), env.get("TELEGRAM_BOT_USERNAME", "").lstrip("@")
    if not token:
        return [(FAIL, "Bot token", "TELEGRAM_BOT_TOKEN is not in .env. Do the 'store the token' step first")]
    colons = token.count(":")
    if colons != 1 or not re.fullmatch(r"\d{6,12}:[A-Za-z0-9_-]{30,}", token):
        why = f"it has {colons} colons (a real token has exactly one), so it was probably pasted more than once" if colons > 1 else "it does not look like a Telegram token (digits, a colon, then letters and digits)"
        return [(FAIL, "Bot token looks right", why + ". Run the 'store the token' step again, pasting once")]
    out.append((PASS, "Bot token looks right", f"{len(token)} characters, one colon"))
    me = api(token, "getMe")
    if not me.get("ok"):
        code = me.get("error_code")
        hint = {401: "Telegram says the token is wrong or was revoked. Copy it again from BotFather", 0: "this Pi could not reach Telegram. Check its internet connection"}.get(code, "")
        return out + [(FAIL, "Telegram accepts the token", f"{me.get('description', 'no answer')}" + (f". {hint}" if hint else ""))]
    bot = me["result"]
    out.append((PASS, "Telegram accepts the token", f"your bot is '{bot.get('first_name')}' (@{bot.get('username')})"))
    if want:
        same = want.lower() == str(bot.get("username", "")).lower()
        out.append((PASS if same else FAIL, "The username in .env matches the bot", "ok" if same else f".env says @{want} but the token belongs to @{bot.get('username')}"))
    else:
        out.append((WARN, "The username in .env matches the bot", "TELEGRAM_BOT_USERNAME is not set"))
    out.append((PASS if bot.get("can_join_groups") is False else WARN, "The bot cannot be added to groups", "ok" if bot.get("can_join_groups") is False else "it still can: tell BotFather /setjoingroups and choose Disable"))
    hook = api(token, "getWebhookInfo")
    url = (hook.get("result") or {}).get("url") if hook.get("ok") else None
    out.append((PASS if hook.get("ok") and not url else WARN, "No webhook is set (XYRON will ask Telegram for messages instead)", "ok" if hook.get("ok") and not url else (f"a webhook is set: {url}" if url else "could not check")))
    cmds = api(token, "getMyCommands")
    names = [c.get("command") for c in (cmds.get("result") or [])] if cmds.get("ok") else []
    out.append((PASS if {"status", "pause", "resume", "mute", "unlink", "help"} <= set(names) else INFO, "The bot's command menu", ", ".join("/" + n for n in names) if names else "not set yet (optional: BotFather /setcommands)"))
    upd = api(token, "getUpdates", {"timeout": 0, "limit": 20, "allowed_updates": ["message"]})
    chats = {}
    if upd.get("ok"):
        for u in upd.get("result", []):
            m = u.get("message") or {}
            ch = m.get("chat") or {}
            if ch.get("type") == "private" and ch.get("id"):
                chats[ch["id"]] = (m.get("from") or {}).get("first_name") or "someone"
    if send:
        if not chats:
            out.append((WARN, "Test message", "nobody has messaged the bot yet. Open your bot in Telegram, press Start, then run this again with --send"))
        else:
            chat_id, name = list(chats.items())[-1]
            r = api(token, "sendMessage", {"chat_id": chat_id, "text": "XYRON test: this Pi can reach Telegram and your bot works. No alerts are switched on yet."})
            tail = str(chat_id)[-4:]
            out.append((PASS if r.get("ok") else FAIL, "Test message sent", f"to {name} (chat ending {tail})" if r.get("ok") else redact(r.get("description", "failed"), token)))
    else:
        out.append((INFO, "Messages waiting for the bot", f"{len(chats)} private chat(s). Add --send to get a test message"))
    return out


def main(argv, env_text, api=call, printer=print):
    res = run(env_text, api, send="--send" in argv)
    for level, title, detail in res:
        printer(f"[{level}] {title}" + (f": {detail}" if detail else ""))
    bad = [r for r in res if r[0] == FAIL]
    printer("\n" + ("All good: your Telegram bot is ready." if not bad and not any(r[0] == WARN for r in res) else
                    "Looks usable, with a few things to tidy (see WARN above)." if not bad else "Fix the FAIL lines above, then run this again."))
    return 1 if bad else 0


if __name__ == "__main__":
    env_path = Path(__file__).resolve().parent.parent / ".env"
    text = env_path.read_text(errors="ignore") if env_path.exists() else ""
    sys.exit(main(sys.argv[1:], text))
