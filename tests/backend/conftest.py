"""Fixtures for the backend tests only.

Kept out of tests/conftest.py on purpose: an autouse fixture there runs for
the agent tests too, pulls the backend in, and changes the order fixtures are
torn down in.
"""

import pytest


@pytest.fixture(autouse=True)
def _teachers_generate_unless_testing_plans(request, backend, monkeypatch):
    """Most tests are about what happens once a teacher generates, not about
    whether their plan allows it. So a teacher with no trial and no
    subscription is treated as on an unlimited Ұстаз - except in tests marked
    `real_plans`, which check the plan rules themselves.
    """
    if request.node.get_closest_marker("real_plans"):
        yield
        return
    from app.services import plans

    real_resolve = plans.resolve

    async def resolve(user, now=None, activate=True):
        found = await real_resolve(user, now, activate=activate)
        if found.kind == plans.FREE and (found.user.get("role") == "teacher"):
            unlimited = dict.fromkeys(plans.RESOURCES)
            return plans.Entitlement(kind=plans.ON_USTAZ, plan_id="test_unlimited",
                                     plan={"limits": unlimited, "max_effort": "high"},
                                     limits=unlimited, user=found.user)
        return found

    monkeypatch.setattr(plans, "resolve", resolve)
    yield
