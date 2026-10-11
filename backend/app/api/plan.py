"""The plan page: what this account is on, what is left, and the summer pause."""

from fastapi import APIRouter, Request

from app.errors import HTTPExceptionJson
from app.security.cookies import _cookie_token
from app.security.sessions import _user_from_token
from app.services import plans

router = APIRouter()

REFUSAL_MESSAGES = {
    "plan_required": "Generating needs the trial or the Ұстаз plan.",
    "plan_exhausted": "This plan's allowance for that is used up.",
    "no_subscription": "There is no running subscription.",
    "pause_month_only": "Only the monthly plan pauses; the school year one already skips the summer.",
    "pause_summer_only": "The pause is for the summer: from 15 May to the end of August.",
}


def refusal(exc: plans.PlanRefusal) -> HTTPExceptionJson:
    """The HTTP shape of a PlanRefusal, with a code the interface translates."""
    return HTTPExceptionJson(403, REFUSAL_MESSAGES.get(exc.code, exc.code), code=exc.code,
                             resource=exc.resource)


async def _signed_in(request: Request):
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")
    return user


def _offer(plan):
    return {k: plan.get(k) for k in ("_id", "kind", "title", "price", "period", "limits", "videos")}


@router.get("/api/plan")
async def my_plan(request: Request):
    user = await _signed_in(request)
    offers = [_offer(p) for p in await plans.list_plans() if p and p.get("kind") != "trial"]
    trial = await plans.get_plan(plans.TRIAL)
    return {"plan": await plans.summary(user), "offers": offers,
            "trial_limits": (trial or {}).get("limits")}


@router.post("/api/plan/pause")
async def pause(request: Request):
    user = await _signed_in(request)
    try:
        user = await plans.pause(user)
    except plans.PlanRefusal as exc:
        raise refusal(exc) from None
    return {"plan": await plans.summary(user)}


@router.post("/api/plan/resume")
async def resume(request: Request):
    user = await _signed_in(request)
    user = await plans.resume(user)
    return {"plan": await plans.summary(user)}
