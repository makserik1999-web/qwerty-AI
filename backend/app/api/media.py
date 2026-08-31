"""Serving rendered videos, including byte ranges."""

import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from app import config
from app.config import _MEDIA_TYPES, _SAFE_MEDIA_RE
from app.errors import HTTPExceptionJson
from app.security.cookies import _cookie_token
from app.security.sessions import _user_from_token

router = APIRouter()

# ============== Byte-range serving ==============
# Videos MUST be seekable in the browser. starlette 0.36's FileResponse ignores
# the Range header and always answers 200 with the whole file, so the player
# cannot jump forward without downloading everything before that point. Range
# support landed in starlette 0.37, but bumping it means bumping FastAPI, so
# the (small, well-specified) handling lives here instead.
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
_MEDIA_CHUNK_SIZE = 64 * 1024


class _RangeNotSatisfiable(Exception):
    """The client asked for bytes that do not exist in the file."""


def _parse_range_header(header: Optional[str], file_size: int) -> Optional[tuple]:
    """Return an inclusive (start, end) pair, or None to serve the whole file.

    Only a single range is honoured. Multi-range requests are answered with the
    full body, which is a valid response and is never what a video player asks
    for anyway.
    """
    if not header:
        return None
    match = _RANGE_RE.match(header.strip())
    if not match:
        return None

    raw_start, raw_end = match.group(1), match.group(2)
    if not raw_start and not raw_end:
        return None

    if not raw_start:
        # "bytes=-500": the final 500 bytes.
        suffix = int(raw_end)
        if suffix <= 0:
            raise _RangeNotSatisfiable
        start = max(0, file_size - suffix)
        end = file_size - 1
    else:
        start = int(raw_start)
        end = int(raw_end) if raw_end else file_size - 1
        end = min(end, file_size - 1)

    if start >= file_size or start > end:
        raise _RangeNotSatisfiable
    return start, end


def _file_etag(stat_result) -> str:
    """Cheap, stable validator: mtime plus size."""
    return f'"{int(stat_result.st_mtime):x}-{stat_result.st_size:x}"'


def _iter_file_range(path: Path, start: int, end: int):
    """Yield the requested slice in chunks.

    A sync generator on purpose: StreamingResponse runs it in a threadpool, so
    the disk reads never block the event loop.
    """
    remaining = end - start + 1
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining > 0:
            chunk = handle.read(min(_MEDIA_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/media/{filename}")
async def get_media(filename: str, request: Request):
    """Served only to authenticated users, only known video types, no traversal."""
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")
    if not _SAFE_MEDIA_RE.fullmatch(filename):
        raise HTTPExceptionJson(404, "Not found")
    path = config.MEDIA_DIR / filename
    if not path.is_file():
        raise HTTPExceptionJson(404, "Not found")

    stat_result = path.stat()
    file_size = stat_result.st_size
    media_type = _MEDIA_TYPES.get(path.suffix.lower(), "video/mp4")
    etag = _file_etag(stat_result)

    # Rendered videos are immutable: the filename carries a per-render uuid, so
    # a given URL always denotes the same bytes. `private` because the file is
    # behind the session cookie and must not land in a shared cache.
    headers = {
        "Accept-Ranges": "bytes",
        "ETag": etag,
        "Cache-Control": "private, max-age=604800, immutable",
    }

    range_header = request.headers.get("range")
    # If-Range: when the validator no longer matches, the client's partial copy
    # is stale and the whole file must be sent instead of a slice.
    if_range = request.headers.get("if-range")
    if if_range and if_range.strip() != etag:
        range_header = None

    try:
        byte_range = _parse_range_header(range_header, file_size)
    except _RangeNotSatisfiable:
        return Response(
            status_code=416,
            headers={**headers, "Content-Range": f"bytes */{file_size}"},
        )

    if byte_range is None:
        return FileResponse(path, media_type=media_type, headers=headers)

    start, end = byte_range
    return StreamingResponse(
        _iter_file_range(path, start, end),
        status_code=206,
        media_type=media_type,
        headers={
            **headers,
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(end - start + 1),
        },
    )
