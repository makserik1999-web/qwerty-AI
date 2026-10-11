"""Confirming a phone number with a code by SMS.

One number belongs to one account. The trial plan will hang off a confirmed
number - one trial per number, ever - which is why the number has to be
proven rather than typed.

Every message costs money, so sending is rationed in the database (limits
that survive a restart), not in memory:

    per account   one a minute, five a day
    per number    five a day
    per address   ten an hour
    everyone      SMS_DAILY_MAX a day, then sending stops until it eases

A code is six digits, lives ten minutes, and allows five guesses; only its
salted hash is stored.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from pymongo.errors import DuplicateKeyError

from app import config
from app.db import db
from app.errors import HTTPExceptionJson
from app.models import PhoneStartRequest, PhoneVerifyRequest
from app.security.cookies import _cookie_token
from app.security.ratelimit import _client_ip
from app.security.sessions import _user_from_token, _user_payload
from app.services import sms

router = APIRouter()

CODE_TTL = timedelta(minutes=10)
CODE_ATTEMPTS = 5
RESEND_AFTER_SEC = 60
PER_ACCOUNT_DAY = 5
PER_PHONE_DAY = 5
PER_IP_HOUR = 10
LOG_KEEP = timedelta(days=2)


def _code_hash(salt: str, code: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode("utf-8")).hexdigest()


def _aware(value):
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def _signed_in(request: Request):
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")
    return user


def _phone_or_400(raw: str) -> str:
    phone = sms.normalize_phone(raw)
    if not phone:
        raise HTTPExceptionJson(400, "Enter a Kazakhstan mobile number", code="phone_invalid")
    return phone


async def _taken_by_someone_else(phone: str, user_id) -> bool:
    other = await db.db.users.find_one({"phone": phone, "_id": {"$ne": user_id}}, {"_id": 1})
    return other is not None


@router.post("/api/auth/phone/start")
async def start(body: PhoneStartRequest, request: Request):
    user = await _signed_in(request)
    phone = _phone_or_400(body.phone)
    user_id = str(user["_id"])

    if user.get("phone") == phone and user.get("phone_verified_at"):
        return {"ok": True, "already": True}
    if await _taken_by_someone_else(phone, user["_id"]):
        raise HTTPExceptionJson(409, "This number belongs to another account", code="phone_taken")

    now = datetime.now(timezone.utc)
    last = await db.db.sms_log.find_one({"user_id": user_id}, sort=[("at", -1)])
    if last:
        wait = RESEND_AFTER_SEC - int((now - _aware(last["at"])).total_seconds())
        if wait > 0:
            raise HTTPExceptionJson(429, "Wait before asking for another code",
                                    code="sms_wait", retry_after=wait)
    day_ago, hour_ago = now - timedelta(days=1), now - timedelta(hours=1)
    ip = _client_ip(request)
    if (await db.db.sms_log.count_documents({"user_id": user_id, "at": {"$gte": day_ago}}) >= PER_ACCOUNT_DAY
            or await db.db.sms_log.count_documents({"phone": phone, "at": {"$gte": day_ago}}) >= PER_PHONE_DAY
            or await db.db.sms_log.count_documents({"ip": ip, "at": {"$gte": hour_ago}}) >= PER_IP_HOUR):
        raise HTTPExceptionJson(429, "Too many codes. Try again tomorrow.", code="sms_limit")
    if await db.db.sms_log.count_documents({"at": {"$gte": day_ago}}) >= config.SMS_DAILY_MAX:
        print(f"[sms] daily cap SMS_DAILY_MAX={config.SMS_DAILY_MAX} reached - sending paused", flush=True)
        raise HTTPExceptionJson(503, "Codes are paused for today. Try again later.", code="sms_paused")

    code = f"{secrets.randbelow(10 ** 6):06d}"
    salt = secrets.token_hex(8)
    await db.db.phone_codes.replace_one(
        {"user_id": user_id},
        {"user_id": user_id, "phone": phone, "salt": salt, "code_hash": _code_hash(salt, code),
         "attempts": 0, "created_at": now, "expires_at": now + CODE_TTL},
        upsert=True,
    )
    # Counted before sending: a send that fails still may have cost money,
    # and a failing provider must not become a way around the limits.
    await db.db.sms_log.insert_one({"user_id": user_id, "phone": phone, "ip": ip,
                                    "at": now, "expires_at": now + LOG_KEEP})
    if not await sms.send(phone, f"Akron: растау коды {code}. Ешкімге бермеңіз."):
        raise HTTPExceptionJson(502, "Could not send the code. Try again later.", code="sms_failed")
    return {"ok": True, "phone": phone, "retry_after": RESEND_AFTER_SEC}


@router.post("/api/auth/phone/verify")
async def verify(body: PhoneVerifyRequest, request: Request):
    user = await _signed_in(request)
    phone = _phone_or_400(body.phone)
    user_id = str(user["_id"])
    code = "".join(ch for ch in (body.code or "") if ch.isdigit())

    record = await db.db.phone_codes.find_one({"user_id": user_id})
    now = datetime.now(timezone.utc)
    if not record or record.get("phone") != phone or _aware(record["expires_at"]) < now:
        raise HTTPExceptionJson(400, "The code has expired. Ask for a new one.", code="code_expired")
    if record.get("attempts", 0) >= CODE_ATTEMPTS:
        await db.db.phone_codes.delete_one({"_id": record["_id"]})
        raise HTTPExceptionJson(429, "Too many wrong codes. Ask for a new one.", code="code_attempts")
    if len(code) != 6 or not secrets.compare_digest(_code_hash(record["salt"], code), record["code_hash"]):
        await db.db.phone_codes.update_one({"_id": record["_id"]}, {"$inc": {"attempts": 1}})
        left = CODE_ATTEMPTS - record.get("attempts", 0) - 1
        raise HTTPExceptionJson(400, "Wrong code", code="code_wrong", attempts_left=max(0, left))

    if await _taken_by_someone_else(phone, user["_id"]):
        raise HTTPExceptionJson(409, "This number belongs to another account", code="phone_taken")
    try:
        await db.db.users.update_one({"_id": user["_id"]},
                                     {"$set": {"phone": phone, "phone_verified_at": now}})
    except DuplicateKeyError:
        # Someone else confirmed the same number a moment ago.
        raise HTTPExceptionJson(409, "This number belongs to another account", code="phone_taken") from None
    await db.db.phone_codes.delete_one({"_id": record["_id"]})
    return {"user": _user_payload({**user, "phone": phone, "phone_verified_at": now})}
