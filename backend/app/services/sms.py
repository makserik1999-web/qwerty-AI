"""Text messages, for confirming a phone number.

Providers, chosen by SMS_PROVIDER:

    log      prints the message to the backend log (development)
    smsc     smsc.kz - HTTP API, login + password
    mobizon  mobizon.kz - HTTP API, one API key

Both real ones are reached with the standard library over HTTPS, so adding a
provider needs no dependency. Their request shapes were written from their
public API descriptions and are covered by tests against those shapes; the
first real message on a new account is the check that the account itself is
set up (sender name, balance).

`send` never raises: it returns whether the provider accepted the message.
"""

import asyncio
import json
import re
import urllib.parse
import urllib.request
from typing import Dict, Optional

from app import config

HTTP_TIMEOUT_SEC = 15
SMSC_URL = "https://smsc.kz/sys/send.php"
MOBIZON_URL = "https://api.mobizon.kz/service/message/sendsmsmessage"

# Kazakhstan mobile numbers only: 7 + 7xx + seven digits. Sending anywhere
# else is how an open "send me a code" form becomes a bill - premium-rate
# numbers abroad are the classic way to pump one.
_KZ_MOBILE = re.compile(r"^77\d{9}$")


def normalize_phone(raw: str) -> Optional[str]:
    """'+7 (707) 123-45-67', '87071234567', '7071234567' -> '77071234567'."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10 and digits.startswith("7"):
        digits = "7" + digits
    elif len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits if _KZ_MOBILE.fullmatch(digits) else None


def display_phone(phone: str) -> str:
    if not phone or len(phone) != 11:
        return phone or ""
    return f"+7 {phone[1:4]} {phone[4:7]} {phone[7:9]} {phone[9:11]}"


def configured() -> bool:
    """Whether phone confirmation is offered at all.

    The log provider counts: it is how development, and a server that has no
    SMS account yet, walk through the flow - the code is read from the log.
    """
    if config.SMS_PROVIDER == "smsc":
        return bool(config.SMSC_LOGIN and config.SMSC_PASSWORD)
    if config.SMS_PROVIDER == "mobizon":
        return bool(config.MOBIZON_API_KEY)
    return config.SMS_PROVIDER == "log"


def _get_json(url: str, params: Dict[str, str]) -> Dict:
    data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SEC) as reply:  # noqa: S310 - fixed https URLs
        return json.loads(reply.read().decode("utf-8"))


def _smsc_params(phone: str, text: str) -> Dict[str, str]:
    params = {
        "login": config.SMSC_LOGIN,
        "psw": config.SMSC_PASSWORD,
        "phones": phone,
        "mes": text,
        "charset": "utf-8",
        "fmt": "3",  # JSON
    }
    if config.SMS_SENDER:
        params["sender"] = config.SMS_SENDER
    return params


def _smsc_ok(reply: Dict) -> bool:
    # Success carries a message id; failure carries "error" and "error_code".
    return "error" not in reply and "id" in reply


def _mobizon_params(phone: str, text: str) -> Dict[str, str]:
    params = {
        "apiKey": config.MOBIZON_API_KEY,
        "output": "json",
        "api": "v1",
        "recipient": phone,
        "text": text,
    }
    if config.SMS_SENDER:
        params["from"] = config.SMS_SENDER
    return params


def _mobizon_ok(reply: Dict) -> bool:
    # Code 0 is success; anything else comes with a message saying why.
    return str(reply.get("code")) == "0"


def _send_sync(phone: str, text: str) -> bool:
    if config.SMS_PROVIDER == "smsc":
        reply = _get_json(SMSC_URL, _smsc_params(phone, text))
        ok = _smsc_ok(reply)
    elif config.SMS_PROVIDER == "mobizon":
        reply = _get_json(MOBIZON_URL, _mobizon_params(phone, text))
        ok = _mobizon_ok(reply)
    else:
        raise RuntimeError(f"unknown SMS_PROVIDER {config.SMS_PROVIDER!r}")
    if not ok:
        # The provider's own words: balance, sender name, number blocked.
        print(f"[sms] {config.SMS_PROVIDER} refused: {str(reply)[:300]}", flush=True)
    return ok


async def send(phone: str, text: str) -> bool:
    if config.SMS_PROVIDER == "log":
        print(f"[sms] provider=log to={phone} text={text}", flush=True)
        return True
    if not configured():
        print(f"[sms] SMS_PROVIDER={config.SMS_PROVIDER} has no credentials - not sent", flush=True)
        return False
    try:
        return await asyncio.to_thread(_send_sync, phone, text)
    except Exception as e:  # noqa: BLE001 - reported, never raised
        print(f"[sms] send failed: {type(e).__name__}: {str(e)[:200]}", flush=True)
        return False
