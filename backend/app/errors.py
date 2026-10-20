"""The JSON error type the endpoints raise, and its handler."""

from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse


class HTTPExceptionJson(Exception):
    """An error with an English `detail` and, optionally, a machine `code`.

    The detail is for logs and for clients that have nothing better. The code
    is what an interface translates: the server does not know which of three
    languages the reader uses.
    """

    def __init__(self, status_code: int, detail: str, code: Optional[str] = None, **extra):
        self.status_code = status_code
        self.detail = detail
        self.code = code
        self.extra = extra


async def _http_exception_json_handler(request: Request, exc: HTTPExceptionJson):
    content = {"detail": exc.detail}
    if exc.code:
        content["code"] = exc.code
    content.update(exc.extra)
    return JSONResponse(status_code=exc.status_code, content=content)
