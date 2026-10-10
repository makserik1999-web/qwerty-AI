"""One error type, answered as {"detail": ...} like the backend's."""

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, detail: str, code: str = ""):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        # A stable machine word next to the English sentence, for the cases the
        # interface says something specific about - in the reader's language,
        # which this service does not know.
        self.code = code


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    body = {"detail": exc.detail}
    if exc.code:
        body["code"] = exc.code
    return JSONResponse(status_code=exc.status_code, content=body)
