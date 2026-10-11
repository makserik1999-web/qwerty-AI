"""Grant or take away a staff role. Runs on the server, never over HTTP.

    docker compose exec backend python -m app.staff list
    docker compose exec backend python -m app.staff grant teacher@school.kz --role admin
    docker compose exec backend python -m app.staff revoke teacher@school.kz

This is the only way anyone becomes staff. Signup, the profile and the admin
panel itself have no way to set `staff_role`, so a person who can reach the
site but not the server cannot hand themselves one.

The person signs up on the site first, as anyone would. Before confirming,
check the account printed below is really theirs: signup does not verify
email addresses yet, so someone else could have registered that address.
Every grant and revoke is written to the audit log.

Keep the list short. Staff can read every account, and later the pupils'
work too.
"""

import argparse
import asyncio
import re
import sys
from typing import Any, Callable, Dict, List, Optional

from app.config import DATABASE_NAME, MONGO_URL, STAFF_ROLES
from app.db import db
from app.repositories import audit

# More than this and the command says so. Not a limit - a reminder.
STAFF_COMFORTABLE_MAX = 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.staff", description="Роли сотрудников Akron")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="кто сейчас сотрудник")

    grant = sub.add_parser("grant", help="выдать роль")
    grant.add_argument("email")
    grant.add_argument("--role", required=True, choices=STAFF_ROLES)
    grant.add_argument("--reason", default="")
    grant.add_argument("--yes", action="store_true", help="не спрашивать подтверждение")

    revoke = sub.add_parser("revoke", help="снять роль")
    revoke.add_argument("email")
    revoke.add_argument("--reason", default="")
    revoke.add_argument("--yes", action="store_true", help="не спрашивать подтверждение")
    return parser


async def _find(email: str) -> Optional[Dict[str, Any]]:
    email = (email or "").strip()
    if not email:
        return None
    found = await db.db.users.find_one({"email": email.lower()})
    if found:
        return found
    # Accounts from before emails were stored lowercase.
    return await db.db.users.find_one(
        {"email": re.compile(f"^{re.escape(email)}$", re.IGNORECASE)}
    )


def _describe(user: Dict[str, Any]) -> str:
    created = user.get("created_at")
    return (
        f"  почта:        {user.get('email') or '-'}\n"
        f"  имя:          {user.get('name') or '-'}\n"
        f"  логин:        {user.get('username') or '-'}\n"
        f"  роль:         {user.get('role') or 'student'}\n"
        f"  сотрудник:    {user.get('staff_role') or 'нет'}\n"
        f"  создан:       {created.strftime('%Y-%m-%d %H:%M UTC') if created else '-'}"
    )


async def _staff() -> List[Dict[str, Any]]:
    cursor = db.db.users.find({"staff_role": {"$in": list(STAFF_ROLES)}}).sort("email", 1)
    return [u async for u in cursor]


def _confirmed(question: str, args: argparse.Namespace, confirm: Callable[[str], str],
               interactive: bool, out) -> Optional[bool]:
    """True/False from the person, or None when nobody can be asked."""
    if args.yes:
        return True
    if not interactive:
        print("Нет терминала для подтверждения. Повторите с --yes (или с `exec`, без -T).", file=out)
        return None
    return confirm(f"{question} [y/N] ").strip().lower() in ("y", "yes", "д", "да")


async def run(argv: List[str], *, confirm: Callable[[str], str] = input,
              interactive: Optional[bool] = None, out=None) -> int:
    out = out or sys.stdout
    if interactive is None:
        interactive = sys.stdin.isatty()
    args = _parser().parse_args(argv)

    if args.command == "list":
        staff = await _staff()
        if not staff:
            print("Сотрудников нет.", file=out)
        for user in staff:
            print(f"{user['staff_role']:8} {user.get('email') or '-':40} {user.get('name') or ''}", file=out)
        return 0

    user = await _find(args.email)
    if not user:
        print(f"Аккаунта с почтой {args.email} нет. Сначала человек регистрируется на сайте.", file=out)
        return 1

    print(_describe(user), file=out)

    if args.command == "grant":
        if user.get("staff_role") == args.role:
            print(f"Уже {args.role}. Ничего не меняю.", file=out)
            return 0
        answer = _confirmed(f"Выдать роль {args.role}?", args, confirm, interactive, out)
        if answer is None:
            return 2
        if not answer:
            print("Отменено.", file=out)
            return 1
        previous = user.get("staff_role")
        await db.db.users.update_one({"_id": user["_id"]}, {"$set": {"staff_role": args.role}})
        await audit.record(
            actor=audit.CLI_ACTOR, action="staff.grant", target=audit.user_target(user),
            details={"role": args.role, "previous": previous}, reason=args.reason,
        )
        print(f"Готово: {user.get('email')} теперь {args.role}.", file=out)
        count = len(await _staff())
        if count > STAFF_COMFORTABLE_MAX:
            print(f"Сотрудников сейчас {count}. Держите их минимум: они видят все аккаунты.", file=out)
        return 0

    # revoke
    if not user.get("staff_role"):
        print("Роли нет. Ничего не меняю.", file=out)
        return 0
    answer = _confirmed(f"Снять роль {user['staff_role']}?", args, confirm, interactive, out)
    if answer is None:
        return 2
    if not answer:
        print("Отменено.", file=out)
        return 1
    await db.db.users.update_one({"_id": user["_id"]}, {"$unset": {"staff_role": ""}})
    await audit.record(
        actor=audit.CLI_ACTOR, action="staff.revoke", target=audit.user_target(user),
        details={"previous": user["staff_role"]}, reason=args.reason,
    )
    print(f"Готово: у {user.get('email')} больше нет роли.", file=out)
    return 0


async def _main(argv: List[str]) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient

    db.client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    db.db = db.client[DATABASE_NAME]
    try:
        return await run(argv)
    finally:
        db.client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
