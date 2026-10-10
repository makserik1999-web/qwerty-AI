"""The JSON error type the endpoints raise, and its handler."""

from fastapi import Request
from fastapi.responses import JSONResponse


class HTTPExceptionJson(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


async def _http_exception_json_handler(request: Request, exc: HTTPExceptionJson):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
