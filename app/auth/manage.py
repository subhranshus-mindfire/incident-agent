"""Command-line account management.

    python -m app.auth.manage create-user <username>

The password is read without echo. Run it inside the app container:
    docker compose exec -it app python -m app.auth.manage create-user <username>
"""

import argparse
import asyncio
import getpass
import sys

from app.auth.passwords import hash_password
from app.config.database import async_session_factory
from app.models.user import User


async def create_user(username: str, password: str) -> None:
    async with async_session_factory() as db:
        if await db.get(User, username) is not None:
            raise SystemExit(f"User '{username}' already exists")
        db.add(User(username=username, password_hash=hash_password(password)))
        await db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.auth.manage")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user", help="Create a user who can sign in")
    create.add_argument("username")
    args = parser.parse_args()

    if args.command == "create-user":
        password = getpass.getpass("Password: ")
        if len(password) < 12:
            sys.exit("Password must be at least 12 characters")
        if getpass.getpass("Repeat password: ") != password:
            sys.exit("Passwords do not match")
        asyncio.run(create_user(args.username, password))
        print(f"Created user '{args.username}'")


if __name__ == "__main__":
    main()
