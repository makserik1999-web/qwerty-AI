"""Saying which stage a request is on, while it is still on it.

A generation takes between thirty and ninety seconds, and for all of that the
person who asked sees one indicator. The interface is built to show three
steps - reading the question, writing the explanation, rendering the animation
- and without this it sits on the first of them for the whole wait, which is
worse than showing nothing: it looks stuck rather than busy.

The stages are reported from the graph, where the transitions actually happen,
rather than guessed from a timer on the client. A timer would be wrong exactly
when it matters - a repair attempt, a slow model, a queue - and would keep
claiming progress after everything had stopped.

One request at a time. `agent_ws_client` reads frames and runs generations in
separate tasks now, but the generation worker still takes them from its queue
one at a time, so the graph never runs twice concurrently and a module-level
current request is not a race. Embedding requests do run alongside, but they
do not touch the graph and never call in here.
"""

from typing import Awaitable, Callable, Optional

# Named for what the reader is told, not for the node that reports it.
STAGES = ("understand", "write", "render")

Sink = Callable[[str, str], Awaitable[None]]

_sink: Optional[Sink] = None
_request_id: str = ""


def bind(sink: Optional[Sink]) -> None:
    """Point reports at the socket. Unbound, reporting is a no-op."""
    global _sink
    _sink = sink


def begin(request_id: str) -> None:
    global _request_id
    _request_id = request_id or ""


def done() -> None:
    global _request_id
    _request_id = ""


def current() -> str:
    """Which request is being worked on, "" if none.

    The receive loop asks before it drops an idle connection: a reconnect
    while a render is running would send that render's progress reports
    nowhere and hold up its answer for no reason.
    """
    return _request_id


async def report(stage: str) -> None:
    """Say which stage this request has reached.

    Deliberately swallows everything. A progress frame is a courtesy; a
    request must never fail because the courtesy could not be delivered, and
    the socket dropping here would be reported by the answer anyway.
    """
    if not _sink or not _request_id or stage not in STAGES:
        return
    try:
        await _sink(_request_id, stage)
    except Exception:
        pass
