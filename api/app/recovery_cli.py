"""Break-glass tools for the owner, run on the Pi when nothing else works (for example the owner lost both phone and recovery codes).

  sudo docker compose exec api python -m app.recovery_cli reset-password you@example.com
  sudo docker compose exec api python -m app.recovery_cli reset-2fa you@example.com
  sudo docker compose exec api python -m app.recovery_cli sign-out you@example.com
"""
import getpass
import sys

import pyotp

from . import recovery
from . import security as sec
from .db import audit, get_conn


def _user(conn, email):
    return conn.execute("SELECT id, email FROM users WHERE email = %s", (email.strip().lower(),)).fetchone()


def reset_password(email, ask=getpass.getpass):
    recovery.ensure_schema()
    with get_conn() as conn:
        u = _user(conn, email)
    if not u:
        print("No account with that email.")
        return 1
    pw = ask("New password (min 14 characters): ")
    if len(pw) < 14:
        print("Password too short.")
        return 1
    if pw != ask("Repeat password: "):
        print("Passwords don't match.")
        return 1
    with get_conn() as conn:
        conn.execute("UPDATE users SET password_hash = %s, password_changed_at = now() WHERE id = %s", (sec.hash_password(pw), u["id"]))
    recovery.revoke_sessions(u["id"])
    sec.r.delete(f"rl:login:acct:{u['email']}")
    audit("password_reset_cli", user_id=u["id"], detail={"email": u["email"]})
    print("Password changed, and every device was signed out.")
    return 0


def reset_2fa(email):
    recovery.ensure_schema()
    with get_conn() as conn:
        u = _user(conn, email)
        if not u:
            print("No account with that email.")
            return 1
        secret = sec.new_totp_secret()
        conn.execute("UPDATE users SET totp_secret_enc = %s, totp_shown = true, totp_pending_enc = NULL WHERE id = %s", (sec.encrypt_secret(secret), u["id"]))
        conn.execute("DELETE FROM recovery_codes WHERE user_id = %s", (u["id"],))
    recovery.revoke_sessions(u["id"])
    sec.r.delete(f"rl:login:acct:{u['email']}")
    audit("authenticator_reset_cli", user_id=u["id"], detail={"email": u["email"]})
    print("Authenticator reset. Old recovery codes were removed, and every device was signed out.")
    print("Add this to your authenticator app (choose 'enter a setup key'):")
    print("  Account: ", u["email"])
    print("  Key:     ", secret)
    print("  URI:     ", pyotp.TOTP(secret).provisioning_uri(name=u["email"], issuer_name="XYRON"))
    print("This key is shown only once. After you sign in, create new recovery codes under Security.")
    return 0


def sign_out(email):
    recovery.ensure_schema()
    with get_conn() as conn:
        u = _user(conn, email)
    if not u:
        print("No account with that email.")
        return 1
    recovery.revoke_sessions(u["id"])
    audit("sessions_revoked_cli", user_id=u["id"])
    print("Every device was signed out.")
    return 0


COMMANDS = {"reset-password": reset_password, "reset-2fa": reset_2fa, "sign-out": sign_out}

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] in COMMANDS:
        sys.exit(COMMANDS[sys.argv[1]](sys.argv[2]))
    print("Usage: python -m app.recovery_cli reset-password|reset-2fa|sign-out EMAIL")
    sys.exit(2)
