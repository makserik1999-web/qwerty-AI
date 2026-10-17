"""These tests drive an interface that no longer exists.

Ф0 replaced `frontend/src` with the new UI from Hollyz812/anyq. It is a
different interface: different components, different markup, and none of the
`data-testid` hooks these tests reach for. Every file in this directory would
fail on the first selector.

They are skipped rather than deleted because they are the most precise record
we have of what the player is supposed to do, written against a version that
actually did it. Ported one at a time in Ф2, alongside the component each one
covers - the test and its component come back together, or neither does.

What still has to be true when the port is finished, one hook per behaviour:

    video-element, seek-bar          the player plays and seeks
    download-video                   the file can be saved
    annotation-canvas,               drawing over a paused frame
      draw-mode-toggle
    export-toggle, export-panel,     gif / clip / frame export, with its
      export-format-gif,               parameters and the job it queues
      export-format-clip,
      export-length, export-width,
      export-submit, export-close
    deck-button, deck-download       the teacher deck
    from-cache-badge                 an answer served from the library says so
    regenerate-button                ... and can be asked again from scratch
    quota-remaining                  what is left of the budget
    add-screenshot                   a question can carry an image

`tests/e2e/` is untouched: it speaks to nginx over HTTP and WebSocket without
a browser, so replacing the interface did not affect it.
"""

from pathlib import Path

import pytest

_REASON = (
    "UI replaced in Ф0; ported with its components in Ф2 "
    "(see tests/ui/conftest.py and frontend/legacy/README.md)"
)


def pytest_collection_modifyitems(items):
    """Skip everything collected from this directory.

    A module-level `pytestmark` in a conftest does nothing - it only applies
    inside a test module - and `collect_ignore` would make these vanish from
    the run entirely. Marking each item keeps them counted and keeps the
    reason on screen, so the debt stays visible instead of disappearing.
    """
    here = Path(__file__).parent
    skip = pytest.mark.skip(reason=_REASON)
    for item in items:
        try:
            in_here = Path(str(item.fspath)).parent == here
        except Exception:  # pragma: no cover - defensive, fspath is always set
            continue
        if in_here:
            item.add_marker(skip)
