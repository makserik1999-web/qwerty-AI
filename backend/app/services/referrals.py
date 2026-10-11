"""Inviting a colleague.

    the invited teacher   +2 videos on top of the trial
    the one who invited   +1 month of Ұстаз once the invited teacher has paid
                          for their first subscription; at most 6 such months
                          in any 365 days

The reward waits for money on purpose: a sign-up costs nothing to fake, a
payment does. The +2 videos ride on the trial, which already needs a phone
number nobody has used before.

Each teacher has one code. A link carries it to the sign-up page; the account
records who invited it, once, and never itself.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId

from app import config
from app.db import db

INVITEE_BONUS_VIDEOS = 2
REWARD_MONTHS = 1
YEARLY_CAP = 6

_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


async def code_for(user: Dict[str, Any]) -> str:
    """This account's code, made the first time it is asked for."""
    if user.get("referral_code"):
        return user["referral_code"]
    for _ in range(20):
        code = "".join(secrets.choice(_ALPHABET) for _ in range(6))
        if await db.db.users.find_one({"referral_code": code}, {"_id": 1}):
            continue
        result = await db.db.users.update_one(
            {"_id": user["_id"], "referral_code": {"$exists": False}}, {"$set": {"referral_code": code}})
        if result.modified_count:
            return code
        fresh = await db.db.users.find_one({"_id": user["_id"]}, {"referral_code": 1})
        if fresh and fresh.get("referral_code"):
            return fresh["referral_code"]
    raise RuntimeError("could not make a referral code")  # pragma: no cover


async def inviter_for(code: Optional[str]) -> Optional[Dict[str, Any]]:
    code = (code or "").strip().upper()[:12]
    if not code:
        return None
    return await db.db.users.find_one({"referral_code": code, "role": "teacher"})


def link_for(code: str) -> str:
    return f"{config.PUBLIC_BASE_URL}/signup?ref={code}"


async def summary(user: Dict[str, Any]) -> Dict[str, Any]:
    code = await code_for(user)
    user_id = str(user["_id"])
    invited = await db.db.users.count_documents({"referred_by": user_id})
    paid = await db.db.referral_rewards.count_documents({"inviter_id": user_id})
    this_year = await _rewards_since(user_id, _now() - timedelta(days=365))
    return {"code": code, "link": link_for(code), "invited": invited, "paid": paid,
            "months_this_year": this_year, "cap": YEARLY_CAP,
            "invitee_bonus_videos": INVITEE_BONUS_VIDEOS}


async def _rewards_since(inviter_id: str, since: datetime) -> int:
    return await db.db.referral_rewards.count_documents({"inviter_id": inviter_id, "at": {"$gte": since}})


async def on_payment_confirmed(payment: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Reward the inviter if this was the invited teacher's first paid plan."""
    from app.repositories import audit
    from app.services import plans

    if payment.get("kind") != "subscription":
        return None
    invitee = await db.db.users.find_one({"_id": ObjectId(payment["user_id"])})
    inviter_id = (invitee or {}).get("referred_by")
    if not invitee or not inviter_id:
        return None
    if await db.db.referral_rewards.find_one({"invitee_id": str(invitee["_id"])}):
        return None  # only the first payment counts
    inviter = await db.db.users.find_one({"_id": ObjectId(inviter_id)})
    if not inviter or inviter.get("blocked_at"):
        return None
    if await _rewards_since(inviter_id, _now() - timedelta(days=365)) >= YEARLY_CAP:
        reward = {"inviter_id": inviter_id, "invitee_id": str(invitee["_id"]), "payment": payment.get("code"),
                  "at": _now(), "months": 0, "capped": True}
        await db.db.referral_rewards.insert_one(reward)
        return reward

    before = (inviter.get("subscription") or {}).get("expires_at")
    await plans.extend_by_months(inviter, REWARD_MONTHS)
    reward = {"inviter_id": inviter_id, "invitee_id": str(invitee["_id"]), "payment": payment.get("code"),
              "at": _now(), "months": REWARD_MONTHS, "capped": False}
    await db.db.referral_rewards.insert_one(reward)
    await audit.record(actor={"kind": "system", "user_id": "", "email": "", "role": ""},
                       action="referral.reward", target={"user_id": inviter_id, "email": inviter.get("email") or ""},
                       details={"invitee": invitee.get("email") or str(invitee["_id"]),
                                "payment": payment.get("code"), "expires_before": str(before)},
                       reason="Приглашённый оплатил первую подписку")
    return reward


async def pairs_for_staff(limit: int = 200) -> List[Dict[str, Any]]:
    """Who invited whom, with the hints that matter for abuse."""
    out = []
    cursor = db.db.users.find({"referred_by": {"$exists": True}}).sort("created_at", -1).limit(limit)
    async for invitee in cursor:
        inviter = await db.db.users.find_one({"_id": ObjectId(invitee["referred_by"])}) \
            if ObjectId.is_valid(invitee.get("referred_by", "")) else None
        reward = await db.db.referral_rewards.find_one({"invitee_id": str(invitee["_id"])})
        shared_device = bool(set(invitee.get("device_hashes") or []) & set((inviter or {}).get("device_hashes") or []))
        shared_ip = bool(set(invitee.get("ip_hashes") or []) & set((inviter or {}).get("ip_hashes") or []))
        created = invitee.get("created_at")
        out.append({
            "inviter": (inviter or {}).get("email") or invitee.get("referred_by"),
            "inviter_id": invitee.get("referred_by"),
            "invitee": invitee.get("email") or str(invitee["_id"]),
            "invitee_id": str(invitee["_id"]),
            "joined": created.isoformat() if isinstance(created, datetime) else None,
            "paid": bool(reward),
            "rewarded_months": (reward or {}).get("months", 0),
            "capped": bool((reward or {}).get("capped")),
            "same_device": shared_device,
            "same_network": shared_ip,
        })
    return out


async def crowded_fingerprints(minimum: int = 3) -> List[Dict[str, Any]]:
    """Devices and networks shared by `minimum` or more accounts.

    A school's computer room is one network for a whole class, so a shared
    network alone means little; a shared device is the stronger hint.
    """
    groups: Dict[tuple, List[str]] = {}
    async for user in db.db.users.find({}, {"email": 1, "device_hashes": 1, "ip_hashes": 1}):
        label = user.get("email") or str(user["_id"])
        for kind, field in (("device", "device_hashes"), ("network", "ip_hashes")):
            for digest in set(user.get(field) or []):
                groups.setdefault((kind, digest), []).append(label)
    crowded = [
        {"kind": kind, "fingerprint": digest[:8], "accounts": sorted(accounts)}
        for (kind, digest), accounts in groups.items() if len(accounts) >= minimum
    ]
    crowded.sort(key=lambda g: (g["kind"] != "device", -len(g["accounts"])))
    return crowded
