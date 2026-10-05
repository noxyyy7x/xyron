import getpass
import sys

import pyotp

from . import security as sec
from .db import audit, get_conn, init_schema


def create_owner():
    init_schema()
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM users WHERE role = 'owner'").fetchone():
            print("An owner already exists. Aborting.")
            return 1
    email = input("Owner email: ").strip().lower()
    if "@" not in email:
        print("That doesn't look like an email address.")
        return 1
    pw = getpass.getpass("Password (min 14 characters): ")
    if len(pw) < 14:
        print("Password too short.")
        return 1
    if pw != getpass.getpass("Repeat password: "):
        print("Passwords don't match.")
        return 1
    secret = sec.new_totp_secret()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (email, password_hash, totp_secret_enc, role, status) "
            "VALUES (%s,%s,%s,'owner','active')",
            (email, sec.hash_password(pw), sec.encrypt_secret(secret)),
        )
    audit("owner_created", detail={"email": email})
    print("\nOwner created.")
    print("Add this to your authenticator app (choose 'enter a setup key'):")
    print("  Account: ", email)
    print("  Key:     ", secret)
    print("  URI:     ", pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="XYRON"))
    print("\nThis key is shown only once. Don't share it with anyone.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "create-owner":
        sys.exit(create_owner())
    print("Usage: python -m app.cli create-owner")
    sys.exit(2)
