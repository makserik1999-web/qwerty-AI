"""Payments in the admin panel: check Kaspi, then confirm, reject or refund.

Admin only - support handles people, not money. Confirming applies the plan;
each decision goes into the audit log with who made it.
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.payments import http
from app.errors import HTTPExceptionJson
from app.repositories import audit
from app.security.staff import require_admin, require_staff
from app.services import payments

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_staff)])


class Decision(BaseModel):
    reason: Optional[str] = ""


class RefundRequest(BaseModel):
    reason: str
    take_back: bool = True


def _reason(text: Optional[str], *, required: bool, default: str = "") -> str:
    reason = " ".join((text or "").split())[:500]
    if required and not reason:
        raise HTTPExceptionJson(400, "Say why - it goes into the audit log", code="reason_required")
    return reason or default


def _target(payment):
    return {"user_id": payment.get("user_id"), "email": payment.get("email") or "",
            "payment": payment.get("code")}


@router.get("/payments", dependencies=[Depends(require_admin)])
async def list_payments(status: str = "", code: str = ""):
    return {"items": await payments.list_for_staff(status, code=code),
            "revenue": await payments.revenue_by_month()}


@router.post("/payments/{payment_id}/confirm", dependencies=[Depends(require_admin)])
async def confirm(payment_id: str, body: Decision, actor=Depends(require_staff)):
    reason = _reason(body.reason, required=False, default="Оплата сверена в Kaspi")
    try:
        done = await payments.confirm(payment_id, actor)
    except payments.PaymentRefusal as exc:
        raise http(exc) from None
    await audit.record(actor=audit.staff_actor(actor), action="payment.confirm", target=_target(done),
                       details={"amount": done.get("amount"), "plan_id": done.get("plan_id"),
                                **(done.get("applied") or {})},
                       reason=reason)
    return payments.view(done)


@router.post("/payments/{payment_id}/reject", dependencies=[Depends(require_admin)])
async def reject(payment_id: str, body: Decision, actor=Depends(require_staff)):
    reason = _reason(body.reason, required=True)
    try:
        done = await payments.reject(payment_id, actor, reason)
    except payments.PaymentRefusal as exc:
        raise http(exc) from None
    await audit.record(actor=audit.staff_actor(actor), action="payment.reject", target=_target(done),
                       details={"amount": done.get("amount")}, reason=reason)
    return payments.view(done)


@router.post("/payments/{payment_id}/refund", dependencies=[Depends(require_admin)])
async def refund(payment_id: str, body: RefundRequest, actor=Depends(require_staff)):
    reason = _reason(body.reason, required=True)
    try:
        done = await payments.refund(payment_id, actor, reason, take_back=body.take_back)
    except payments.PaymentRefusal as exc:
        raise http(exc) from None
    await audit.record(actor=audit.staff_actor(actor), action="payment.refund", target=_target(done),
                       details={"amount": done.get("amount"), "take_back": body.take_back}, reason=reason)
    return payments.view(done)
