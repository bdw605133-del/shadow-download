#!/usr/bin/env python3
"""Create or reset the SHADOW DOWNLOAD administrator account.

Usage:
    python tools/init_admin.py --username admin --password 'StrongPassword123!'
    python tools/init_admin.py --username admin            # generates a one-time password
    python tools/init_admin.py --username admin --reset    # resets an existing account
"""

from __future__ import annotations

import argparse
import os
import secrets
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from db import connect_db, init_db, utc_now
from security import hash_password


def strong_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
    return "".join(secrets.choice(alphabet) for _ in range(24))


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialise a SHADOW DOWNLOAD administrator.")
    parser.add_argument("--username", default=os.getenv("SHADOW_ADMIN_USERNAME", "admin"))
    parser.add_argument("--password", default=os.getenv("SHADOW_ADMIN_PASSWORD"))
    parser.add_argument("--display-name", default="Administrator")
    parser.add_argument("--reset", action="store_true", help="Reset the password of an existing admin.")
    args = parser.parse_args()

    settings = config.config_for()
    init_db(settings.DB_PATH)
    connection = connect_db(settings.DB_PATH)
    try:
        existing = connection.execute(
            "SELECT id FROM admins WHERE username = ?", (args.username,)
        ).fetchone()
        if existing and not args.reset:
            print(f"Administrator '{args.username}' already exists. Use --reset to change the password.")
            return 1

        generated = not args.password
        password = args.password or strong_password()
        password_hash = hash_password(password)
        if existing:
            connection.execute(
                "UPDATE admins SET password_hash = ?, display_name = ?, must_change_password = 1 WHERE id = ?",
                (password_hash, args.display_name, existing["id"]),
            )
        else:
            connection.execute(
                "INSERT INTO admins (username, password_hash, display_name, must_change_password, created_at) "
                "VALUES (?, ?, ?, 1, ?)",
                (args.username, password_hash, args.display_name, utc_now()),
            )
        connection.commit()
    finally:
        connection.close()

    print(f"Administrator: {args.username}")
    if generated:
        print("ONE-TIME PASSWORD (copy it now; it will not be shown again):")
        print(password)
    else:
        print("Password set from the supplied value.")
    print("You will be asked to change it after the first login.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
