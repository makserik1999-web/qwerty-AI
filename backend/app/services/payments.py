"""Payments through Kaspi, confirmed by a person.

There is no payment provider yet, so the flow is the one Kazakh teachers
already know: transfer the amount in Kaspi with a code in the comment, press
"I have paid", and someone on the team checks Kaspi and confirms. Confirming
applies the plan; nothing is applied on the teacher's word alone.

    awaiting   order made, nothing reported yet (closed after a few days)
    submitted  the teacher says it is paid - waiting for the team
    confirmed  money seen in Kaspi; the plan was applied
    rejected   no such money; the reason is shown to the teacher
    refunded   money returned; recorded with who, when and why
    expired    never reported as paid
    cancelled  withdrawn by the teacher before reporting it

The order keeps the price it was made at: changing a price in the admin
panel does not change what someone was told to pay.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId

from app import config
from app.db import db
from app.services import plans

AWAITING, SUBMITTED, CONFIRMED = "awaiting", "submitted", "confirmed"
REJECTED, REFUNDED, EXPIRED, CANCELLED = "rejected", "refunded", "expired", "cancelled"
OPEN = (AWAITING, SUBMITTED)

# No 0/O or 1/I: the code is read off one screen and typed into another.
_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
MAX_OPEN_PER_USER = 3


class PaymentRefusal(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def enabled() -> bool:
    return bool(config.KASPI_PAY_PHONE or config.KASPI_PAY_LINK)


def details() -> Dict[str, str]:
    return {
        "phone": config.KASPI_PAY_PHONE,
        "name": config.KASPI_PAY_NAME,
        "link": config.KASPI_PAY_LINK,
        "note": config.KASPI_PAY_NOTE,
    }


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: Any) -> Optional[str]:
    if not isinstance(value, datetime):
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()


def _new_code() -> str:
    return "AK-" + "".join(secrets.choice(_ALPHABET) for _ in range(5))


def view(payment: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(payment["_id"]),
        "code": payment.get("code"),
        "plan_id": payment.get("plan_id"),
        "title": payment.get("title"),
        "amount": payment.get("amount"),
        "status": payment.get("status"),
        "created_at": _iso(payment.get("created_at")),
        "submitted_at": _iso(payment.get("submitted_at")),
        "decided_at": _iso(payment.get("decided_at")),
        # What the teacher is told when it is rejected; staff notes stay internal.
        "reason": payment.get("reason") if payment.get("status") in (REJECTED, REFUNDED) else "",
    }


async def expire_stale(now: Optional[datetime] = None) -> int:
    now = now or _now()
    result = await db.db.payments.update_many(
        {"status": AWAITING, "created_at": {"$lt": now - timedelta(days=config.PAYMENT_REQUEST_TTL_DAYS)}},
        {"$set": {"status": EXPIRED, "decided_at": now}},
    )
    return result.modified_count


async def create(user: Dict[str, Any], plan_id: str) -> Dict[str, Any]:
    """An order for one plan, at today's price - or the open one already there."""
    if not enabled():
        raise PaymentRefusal("payments_off", 503)
    if user.get("role") != "teacher":
        raise PaymentRefusal("teacher_only", 403)
    plan = await plans.get_plan(plan_id)
    if not plan or plan.get("kind") not in ("subscription", "addon"):
        raise PaymentRefusal("unknown_plan")
    if plan.get("kind") == "addon":
        ent = await plans.resolve(user, activate=False)
        if ent.kind != plans.ON_USTAZ:
            # Bought videos are spent only on top of a running Ұстаз.
            raise PaymentRefusal("addon_needs_ustaz")

    user_id = str(user["_id"])
    await expire_stale()
    existing = await db.db.payments.find_one({"user_id": user_id, "plan_id": plan_id, "status": AWAITING})
    if existing:
        return existing
    if await db.db.payments.count_documents({"user_id": user_id, "status": {"$in": list(OPEN)}}) >= MAX_OPEN_PER_USER:
        raise PaymentRefusal("too_many_open", 429)

    for _ in range(10):
        doc = {
            "code": _new_code(),
            "user_id": user_id,
            "email": user.get("email") or "",
            "plan_id": plan_id,
            "kind": plan.get("kind"),
            "title": plan.get("title"),
            "amount": int(plan.get("price") or 0),
            "status": AWAITING,
            "created_at": _now(),
        }
        if not await db.db.payments.find_one({"code": doc["code"]}, {"_id": 1}):
            result = await db.db.payments.insert_one(doc)
            return {**doc, "_id": result.inserted_id}
    raise PaymentRefusal("try_again", 503)  # pragma: no cover - 32^5 codes


async def _own(user: Dict[str, Any], payment_id: str) -> Dict[str, Any]:
    if not ObjectId.is_valid(payment_id):
        raise PaymentRefusal("not_found", 404)
    found = await db.db.payments.find_one({"_id": ObjectId(payment_id), "user_id": str(user["_id"])})
    if not found:
        raise PaymentRefusal("not_found", 404)
    return found


async def mark_submitted(user: Dict[str, Any], payment_id: str) -> Dict[str, Any]:
    """The teacher says the money went. Nothing is applied until it is checked."""
    payment = await _own(user, payment_id)
    if payment["status"] == SUBMITTED:
        return payment
    updated = await db.db.payments.find_one_and_update(
        {"_id": payment["_id"], "status": AWAITING},
        {"$set": {"status": SUBMITTED, "submitted_at": _now()}},
        return_document=True,
    )
    if not updated:
        raise PaymentRefusal("not_open", 409)
    await _notify_staff(updated)
    return updated


async def cancel(user: Dict[str, Any], payment_id: str) -> Dict[str, Any]:
    payment = await _own(user, payment_id)
    updated = await db.db.payments.find_one_and_update(
        {"_id": payment["_id"], "status": AWAITING},
        {"$set": {"status": CANCELLED, "decided_at": _now()}},
        return_document=True,
    )
    if not updated:
        raise PaymentRefusal("not_open", 409)
    return updated


async def mine(user: Dict[str, Any], limit: int = 20) -> List[Dict[str, Any]]:
    await expire_stale()
    cursor = db.db.payments.find({"user_id": str(user["_id"])}).sort("created_at", -1).limit(limit)
    return [view(p) async for p in cursor]


async def _notify_staff(payment: Dict[str, Any]) -> None:
    from app.services import mailer, telegram

    # Telegram first: it is what someone actually sees on a phone.
    amount = f"{int(payment['amount']):,}".replace(",", " ")
    telegram.send_later(
        "💳 Akron: учитель сообщил об оплате\n\n"
        f"Сумма: {amount} ₸\n"
        f"Тариф: {payment.get('title')}\n"
        f"Код: {payment['code']}\n"
        f"Аккаунт: {payment.get('email') or payment['user_id']}\n\n"
        "Найдите перевод в Kaspi с этим кодом и подтвердите:\n"
        f"{config.PUBLIC_BASE_URL}/admin?tab=payments"
    )
    if not config.PAYMENT_NOTIFY_EMAILS:
        return

    text = (
        f"Учитель сообщил об оплате.\n\n"
        f"Код: {payment['code']}\nСумма: {payment['amount']} ₸\nТариф: {payment.get('title')}\n"
        f"Аккаунт: {payment.get('email') or payment['user_id']}\n\n"
        f"Проверьте Kaspi и подтвердите: {config.PUBLIC_BASE_URL}/admin"
    )
    for to in config.PAYMENT_NOTIFY_EMAILS:
        mailer.send_later(to, f"Akron: оплата {payment['code']} ждёт проверки", text)


# ------------------------------------------------------------------ staff --


async def apply(payment: Dict[str, Any]) -> Dict[str, Any]:
    """Give the account what was paid for. Returns what changed, for the log."""
    user = await db.db.users.find_one({"_id": ObjectId(payment["user_id"])})
    if not user:
        raise PaymentRefusal("account_gone", 409)
    plan = await plans.get_plan(payment["plan_id"]) or {}
    if payment.get("kind") == "addon":
        count = int(plan.get("videos") or 10)
        await plans.add_extra_videos(user, count)
        return {"extra_videos": count}
    before = (user.get("subscription") or {}).get("expires_at")
    updated = await plans.grant(user, payment["plan_id"], months=1)
    return {"expires_before": _iso(before), "expires_after": _iso(updated["subscription"]["expires_at"])}


async def confirm(payment_id: str, actor: Dict[str, Any]) -> Dict[str, Any]:
    """Money seen in Kaspi: apply the plan. Only from an open order, once."""
    if not ObjectId.is_valid(payment_id):
        raise PaymentRefusal("not_found", 404)
    now = _now()
    claimed = await db.db.payments.find_one_and_update(
        {"_id": ObjectId(payment_id), "status": {"$in": [AWAITING, SUBMITTED]}},
        {"$set": {"status": "confirming", "decided_at": now,
                  "decided_by": {"user_id": str(actor["_id"]), "email": actor.get("email") or ""}}},
        return_document=True,
    )
    if not claimed:
        raise PaymentRefusal("not_open", 409)
    try:
        applied = await apply(claimed)
    except Exception:
        await db.db.payments.update_one({"_id": claimed["_id"]}, {"$set": {"status": claimed["status"]}})
        raise
    await db.db.payments.update_one({"_id": claimed["_id"]},
                                    {"$set": {"status": CONFIRMED, "applied": applied}})
    # The invited teacher's first paid plan earns the inviter a month. Never
    # allowed to undo a confirmation that already happened.
    from app.services import referrals

    try:
        await referrals.on_payment_confirmed(claimed)
    except Exception as e:  # noqa: BLE001
        print(f"referral reward failed for {claimed.get('code')}: {type(e).__name__}: {e}")
    return {**claimed, "status": CONFIRMED, "applied": applied}


async def reject(payment_id: str, actor: Dict[str, Any], reason: str) -> Dict[str, Any]:
    if not ObjectId.is_valid(payment_id):
        raise PaymentRefusal("not_found", 404)
    updated = await db.db.payments.find_one_and_update(
        {"_id": ObjectId(payment_id), "status": {"$in": [AWAITING, SUBMITTED]}},
        {"$set": {"status": REJECTED, "decided_at": _now(), "reason": reason,
                  "decided_by": {"user_id": str(actor["_id"]), "email": actor.get("email") or ""}}},
        return_document=True,
    )
    if not updated:
        raise PaymentRefusal("not_open", 409)
    return updated


async def refund(payment_id: str, actor: Dict[str, Any], reason: str, *, take_back: bool) -> Dict[str, Any]:
    """Money returned. `take_back` also ends the subscription or removes the
    bought videos that are still unspent."""
    if not ObjectId.is_valid(payment_id):
        raise PaymentRefusal("not_found", 404)
    updated = await db.db.payments.find_one_and_update(
        {"_id": ObjectId(payment_id), "status": CONFIRMED},
        {"$set": {"status": REFUNDED, "reason": reason,
                  "refund": {"at": _now(), "by": {"user_id": str(actor["_id"]), "email": actor.get("email") or ""},
                             "take_back": take_back}}},
        return_document=True,
    )
    if not updated:
        raise PaymentRefusal("not_confirmed", 409)
    if take_back:
        user = await db.db.users.find_one({"_id": ObjectId(updated["user_id"])})
        if user and updated.get("kind") == "addon":
            remove = min(int(user.get("extra_videos", 0) or 0), int((updated.get("applied") or {}).get("extra_videos", 0)))
            if remove:
                await plans.add_extra_videos(user, -remove)
        elif user:
            await plans.end_subscription(user)
    return updated


async def list_for_staff(status: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    await expire_stale()
    query: Dict[str, Any] = {"status": status} if status else {}
    cursor = db.db.payments.find(query).sort("created_at", -1).limit(limit)
    out = []
    async for p in cursor:
        row = view(p)
        row.update({
            "email": p.get("email") or "",
            "user_id": p.get("user_id"),
            "reason": p.get("reason") or "",
            "decided_by": (p.get("decided_by") or {}).get("email", ""),
            "refund": {"at": _iso((p.get("refund") or {}).get("at")),
                       "by": ((p.get("refund") or {}).get("by") or {}).get("email", "")} if p.get("refund") else None,
        })
        out.append(row)
    return out


async def revenue_by_month(months: int = 6) -> List[Dict[str, Any]]:
    """Confirmed money per calendar month (Kazakhstan time), refunds taken off."""
    offset = timedelta(hours=config.STATS_UTC_OFFSET_HOURS)
    totals: Dict[str, int] = {}
    async for p in db.db.payments.find({"status": {"$in": [CONFIRMED, REFUNDED]}}):
        at = p.get("decided_at")
        if not isinstance(at, datetime):
            continue
        at = at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at
        key = (at + offset).strftime("%Y-%m")
        totals[key] = totals.get(key, 0) + (int(p.get("amount", 0)) if p["status"] == CONFIRMED else 0)
    return [{"month": k, "amount": totals[k]} for k in sorted(totals)[-months:]]
