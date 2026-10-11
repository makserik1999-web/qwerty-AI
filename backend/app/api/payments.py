"""A teacher paying for a plan: make an order, pay in Kaspi, say so."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.errors import HTTPExceptionJson
from app.security.cookies import _cookie_token
from app.security.sessions import _user_from_token
from app.services import payments

router = APIRouter()

MESSAGES = {
    "payments_off": "Payment is not set up yet.",
    "teacher_only": "Plans are for teacher accounts.",
    "unknown_plan": "No such plan.",
    "addon_needs_ustaz": "Extra videos are added to a running Ұстаз plan.",
    "too_many_open": "Finish or cancel the orders already open first.",
    "not_found": "Not found",
    "not_open": "This order is no longer open.",
}


def http(exc: payments.PaymentRefusal) -> HTTPExceptionJson:
    return HTTPExceptionJson(exc.status, MESSAGES.get(exc.code, exc.code), code=exc.code)


class OrderRequest(BaseModel):
    plan_id: str


async def _signed_in(request: Request):
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")
    return user


@router.get("/api/payments")
async def my_payments(request: Request):
    user = await _signed_in(request)
    return {
        "enabled": payments.enabled(),
        "details": payments.details() if payments.enabled() else None,
        "items": await payments.mine(user),
    }


@router.post("/api/payments", status_code=201)
async def order(body: OrderRequest, request: Request):
    user = await _signed_in(request)
    try:
        found = await payments.create(user, body.plan_id)
    except payments.PaymentRefusal as exc:
        raise http(exc) from None
    return payments.view(found)


@router.post("/api/payments/{payment_id}/submitted")
async def submitted(payment_id: str, request: Request):
    user = await _signed_in(request)
    try:
        return payments.view(await payments.mark_submitted(user, payment_id))
    except payments.PaymentRefusal as exc:
        raise http(exc) from None


@router.post("/api/payments/{payment_id}/cancel")
async def cancel(payment_id: str, request: Request):
    user = await _signed_in(request)
    try:
        return payments.view(await payments.cancel(user, payment_id))
    except payments.PaymentRefusal as exc:
        raise http(exc) from None
