"""
Unified Backend - FastAPI Chat Server with WebSocket support and real auth.

Handles UI clients and AI Agent communication via WebSocket.
Identity comes from the HttpOnly session cookie (`anyq_session`), never from
URLs or client headers. The AI Agent channel requires an authenticated
handshake with AGENT_SECRET and is meant to be reachable only over the
internal docker network (nginx blocks /ws/agent from the outside).
"""

import asyncio
import hashlib
import json
import os
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import bcrypt
from bson import ObjectId
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel

# ============== Configuration ==============
MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongo:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "anyq_db")

# Agent channel secret: both backend and agent must share it. When it is empty
# the backend refuses every agent connection (fail closed).
AGENT_SECRET = os.getenv("AGENT_SECRET", "")

# Cookie: HttpOnly + SameSite=Lax; Secure is enabled when the deployment sets
# COOKIE_SECURE=1 (behind TLS). Compose sets it for you when HTTPS_TERMINATED=1.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "720"))
SESSION_TTL = timedelta(hours=SESSION_TTL_HOURS)
COOKIE_NAME = "anyq_session"

# CORS allowlist (comma separated). Credentials are allowed, so origins must be
# explicit - never "*".
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if o.strip()
]

# Media directory: the shared volume where the agent drops rendered videos.
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "/app/media"))
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

# Payload limits
MAX_PROMPT_LEN = int(os.getenv("MAX_PROMPT_LEN", "4000"))
MAX_TITLE_LEN = int(os.getenv("MAX_TITLE_LEN", "100"))
MAX_SCREENSHOTS = int(os.getenv("MAX_SCREENSHOTS", "3"))
MAX_SCREENSHOT_BYTES = int(os.getenv("MAX_SCREENSHOT_BYTES", str(2 * 1024 * 1024)))
MAX_SCREENSHOT_B64_LEN = MAX_SCREENSHOT_BYTES * 4 // 3 + 16

# Login rate limiting (in-memory; single-process uvicorn)
LOGIN_MAX_ATTEMPTS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_WINDOW_SEC = int(os.getenv("LOGIN_WINDOW_SEC", "900"))  # 15 min

# Agent channel
AGENT_HANDSHAKE_TIMEOUT_SEC = float(os.getenv("AGENT_HANDSHAKE_TIMEOUT_SEC", "10"))
PENDING_REQUESTS_TTL_SEC = int(os.getenv("PENDING_REQUESTS_TTL_SEC", "1800"))
PENDING_SWEEP_INTERVAL_SEC = int(os.getenv("PENDING_SWEEP_INTERVAL_SEC", "60"))

_OBJECT_ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")
_SAFE_MEDIA_RE = re.compile(r"^[A-Za-z0-9_\-]+\.(mp4|webm|mov|m4v)$")
_MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".m4v": "video/mp4",
}

# ============== Database ==============
class Database:
    client: AsyncIOMotorClient = None
    db = None


db = Database()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db.client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    db.db = db.client[DATABASE_NAME]

    await db.db.users.create_index("username", unique=True)
    await db.db.users.create_index("email", unique=True, sparse=True)
    # TTL index: expired sessions are removed automatically.
    await db.db.sessions.create_index("expires_at", expireAfterSeconds=0)
    await db.db.sessions.create_index("token_hash", unique=True)
    await db.db.chats.create_index([("user_id", 1), ("updated_at", -1)])
    await db.db.messages.create_index([("chat_id", 1), ("timestamp", 1)])

    print(f"Connected to MongoDB at {MONGO_URL}")
    if not AGENT_SECRET:
        print("WARNING: AGENT_SECRET is not set - agent connections will be refused.")

    sweep_task = asyncio.create_task(_sweep_pending_requests_loop())
    try:
        yield
    finally:
        sweep_task.cancel()
        db.client.close()
        print("Disconnected from MongoDB")


app = FastAPI(title="Anyq Backend", version="1.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)

# ============== Pydantic Models ==============
class ChatCreate(BaseModel):
    title: Optional[str] = None


class SignupRequest(BaseModel):
    username: str
    email: Optional[str] = None
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


# ============== Auth helpers ==============
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,30}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def _new_session_token() -> str:
    return secrets.token_urlsafe(48)


def _user_payload(user: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(user["_id"]),
        "username": user.get("username", ""),
        "email": user.get("email"),
        "created_at": user.get("created_at").isoformat()
        if isinstance(user.get("created_at"), datetime)
        else None,
    }


async def _create_session(user_id: str) -> str:
    token = _new_session_token()
    now = datetime.now(timezone.utc)
    await db.db.sessions.insert_one(
        {
            "token_hash": _hash_token(token),
            "user_id": user_id,
            "created_at": now,
            "expires_at": now + SESSION_TTL,
        }
    )
    return token


async def _user_from_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    session = await db.db.sessions.find_one({"token_hash": _hash_token(token)})
    if not session:
        return None
    # Safety net for the TTL index (which can lag by up to 60s)
    expires_at = session.get("expires_at")
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and expires_at < datetime.now(timezone.utc):
        await db.db.sessions.delete_one({"_id": session["_id"]})
        return None
    return await db.db.users.find_one({"_id": ObjectId(session["user_id"])})


def _session_cookie(token: str, max_age: int) -> str:
    secure = "; Secure" if COOKIE_SECURE else ""
    return (
        f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; "
        f"Max-Age={max_age}{secure}"
    )


def _expired_session_cookie() -> str:
    secure = "; Secure" if COOKIE_SECURE else ""
    return f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0{secure}"


def _cookie_token(request: Request) -> Optional[str]:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    return raw.strip() or None


def _is_allowed_origin(origin: Optional[str]) -> bool:
    """UI WebSocket origin check (CORS does not apply to WS upgrades)."""
    if not origin:
        # Non-browser clients (tests) - allow. Browsers always send Origin.
        return True
    return origin in CORS_ORIGINS


class LoginLimiter:
    """Simple in-memory limiter keyed by ip and ip+username."""

    def __init__(self, max_attempts: int, window_sec: int):
        self.max_attempts = max_attempts
        self.window_sec = window_sec
        self._attempts: Dict[str, List[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_sec
        stamps = [t for t in self._attempts.get(key, []) if t > cutoff]
        if len(stamps) >= self.max_attempts:
            self._attempts[key] = stamps
            return False
        stamps.append(now)
        self._attempts[key] = stamps
        # Bound the dict size
        if len(self._attempts) > 10000:
            for k in list(self._attempts.keys())[:5000]:
                self._attempts.pop(k, None)
        return True

    def reset(self, key: str) -> None:
        self._attempts.pop(key, None)


login_limiter = LoginLimiter(LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SEC)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ============== Connection Managers ==============
class UIConnectionManager:
    """Manages WebSocket connections from UI clients."""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        # Replace any previous socket for the same user (avoid leaks/races)
        old = self.active_connections.get(user_id)
        if old and old is not websocket:
            try:
                await old.close(code=1001, reason="replaced by new connection")
            except Exception:
                pass
        await websocket.accept()
        self.active_connections[user_id] = websocket
        print(f"UI client connected: user_id={user_id}")

    def disconnect(self, user_id: str):
        self.active_connections.pop(user_id, None)
        print(f"UI client disconnected: user_id={user_id}")

    async def send_to_user(self, user_id: str, message: dict):
        ws = self.active_connections.get(user_id)
        if ws is None:
            return False
        try:
            await ws.send_json(message)
            return True
        except Exception as e:
            print(f"Error sending to user {user_id}: {type(e).__name__}")
            return False

    def get_connection(self, user_id: str) -> Optional[WebSocket]:
        return self.active_connections.get(user_id)


class AgentConnectionManager:
    """Manages WebSocket connection to AI Agent."""

    def __init__(self):
        self.agent_connection: Optional[WebSocket] = None
        self.pending_requests: Dict[str, dict] = {}

    async def connect(self, websocket: WebSocket):
        old = self.agent_connection
        if old and old is not websocket:
            try:
                await old.close(code=1001, reason="replaced by new agent")
            except Exception:
                pass
        self.agent_connection = websocket
        print("AI Agent connected")

    def disconnect(self):
        self.agent_connection = None
        print("AI Agent disconnected")

    async def send_to_agent(self, request_id: str, user_id: str, chat_id: str,
                            text: Optional[str], screenshots: List[Dict[str, Any]]):
        if not self.agent_connection:
            raise RuntimeError("AI Agent not connected")

        image_data = None
        if screenshots:
            image_data = screenshots[0].get("image_base64")

        await self.agent_connection.send_json({
            "request_id": request_id,
            "text": text,
            "image_data": image_data,
        })

    def get_request_info(self, request_id: str, pop: bool = True) -> Optional[dict]:
        if pop:
            return self.pending_requests.pop(request_id, None)
        return self.pending_requests.get(request_id)


ui_manager = UIConnectionManager()
agent_manager = AgentConnectionManager()


async def _notify_pending_failures(message: str):
    """Tell every user with an in-flight request that the agent went away."""
    for request_id, info in list(agent_manager.pending_requests.items()):
        user_id = info.get("user_id")
        chat_id = info.get("chat_id")
        agent_manager.pending_requests.pop(request_id, None)
        if user_id:
            await ui_manager.send_to_user(user_id, {
                "type": "error",
                "data": {"message": message, "chat_id": chat_id},
            })


async def _sweep_pending_requests_loop():
    """TTL sweep for pending_requests (agent died mid-request -> no leak)."""
    while True:
        await asyncio.sleep(PENDING_SWEEP_INTERVAL_SEC)
        try:
            now = time.monotonic()
            stale = [
                rid for rid, info in agent_manager.pending_requests.items()
                if now - info.get("created_at", now) > PENDING_REQUESTS_TTL_SEC
            ]
            for rid in stale:
                info = agent_manager.pending_requests.pop(rid, None)
                if info and info.get("user_id"):
                    await ui_manager.send_to_user(info["user_id"], {
                        "type": "error",
                        "data": {
                            "message": "Processing timed out. Please try again.",
                            "chat_id": info.get("chat_id"),
                        },
                    })
        except Exception as e:
            print(f"pending sweep error: {type(e).__name__}: {e}")


# ============== Database Operations ==============
def _validate_chat_id(chat_id: str) -> bool:
    return bool(chat_id) and bool(_OBJECT_ID_RE.fullmatch(chat_id))


async def create_chat(user_id: str, title: str = "New Chat") -> dict:
    """Create a new chat for a user."""
    chat = {
        "user_id": user_id,
        "title": title,
        "current_video_url": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    result = await db.db.chats.insert_one(chat)
    return {
        "id": str(result.inserted_id),
        "user_id": user_id,
        "title": title,
        "current_video_url": None,
        "created_at": chat["created_at"].isoformat(),
        "updated_at": chat["updated_at"].isoformat(),
        "message_count": 0,
    }


async def save_message(chat_id: str, role: str, content: str,
                       screenshots: List[Dict[str, Any]] = None,
                       video_url: str = None) -> dict:
    """Save a message to the database."""
    message = {
        "chat_id": chat_id,
        "role": role,
        "content": content,
        "screenshots": screenshots or [],
        "video_url": video_url,
        "timestamp": datetime.now(timezone.utc),
    }
    result = await db.db.messages.insert_one(message)

    update_fields = {"updated_at": datetime.now(timezone.utc)}
    if video_url:
        update_fields["current_video_url"] = video_url

    await db.db.chats.update_one(
        {"_id": ObjectId(chat_id)},
        {"$set": update_fields},
    )

    return {
        "id": str(result.inserted_id),
        "role": role,
        "content": content,
        "screenshots": screenshots or [],
        "video_url": video_url,
        "timestamp": message["timestamp"].isoformat(),
    }


async def get_chat_messages(chat_id: str) -> list:
    """Get all messages for a chat."""
    cursor = db.db.messages.find({"chat_id": chat_id}).sort("timestamp", 1)
    messages = []
    async for msg in cursor:
        timestamp = msg["timestamp"]
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        messages.append({
            "id": str(msg["_id"]),
            "role": msg["role"],
            "content": msg.get("content", ""),
            "screenshots": msg.get("screenshots", []),
            "video_url": msg.get("video_url"),
            "timestamp": timestamp.isoformat(),
        })
    return messages


async def get_user_chats(user_id: str) -> list:
    """Get all chats for a user with message counts via aggregation (no N+1)."""
    # messages.chat_id is stored as a STRING while chats._id is an ObjectId.
    # Joining them directly compares two different BSON types, which never
    # matches, so message_count came back 0 for every chat. Cast the id to a
    # string first and join on that.
    #
    # This still pulls the matching message documents in order to size the
    # array. That is fine at the current scale; when chats grow long the right
    # fix is a counter denormalised onto the chat document, updated in
    # save_message, rather than a smarter aggregation.
    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$addFields": {"_id_str": {"$toString": "$_id"}}},
        {"$lookup": {
            "from": "messages",
            "localField": "_id_str",
            "foreignField": "chat_id",
            "as": "msgs",
        }},
        {"$addFields": {"message_count": {"$size": "$msgs"}}},
        {"$sort": {"updated_at": -1}},
    ]
    chats = []
    async for chat in db.db.chats.aggregate(pipeline):
        chats.append({
            "id": str(chat["_id"]),
            "user_id": chat["user_id"],
            "title": chat["title"],
            "current_video_url": chat.get("current_video_url"),
            "created_at": _iso_or_none(chat.get("created_at")),
            "updated_at": _iso_or_none(chat.get("updated_at")),
            "message_count": chat.get("message_count", 0),
        })
    return chats


def _iso_or_none(value) -> Optional[str]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return None


async def delete_chat_by_id(chat_id: str, user_id: str) -> bool:
    """Delete a chat and its messages (ownership-checked)."""
    result = await db.db.chats.delete_one({
        "_id": ObjectId(chat_id),
        "user_id": user_id,
    })
    if result.deleted_count > 0:
        await db.db.messages.delete_many({"chat_id": chat_id})
        return True
    return False


def _validate_screenshots(screenshots: Any) -> Optional[str]:
    """Returns an error message, or None when the payload is acceptable."""
    if not isinstance(screenshots, list):
        return "screenshots must be a list"
    if len(screenshots) > MAX_SCREENSHOTS:
        return f"Too many screenshots (max {MAX_SCREENSHOTS})"
    for ss in screenshots:
        b64 = ""
        if isinstance(ss, dict):
            b64 = ss.get("image_base64") or ""
        if not isinstance(b64, str) or not b64:
            return "screenshot is missing image_base64"
        if len(b64) > MAX_SCREENSHOT_B64_LEN:
            return "screenshot is too large"
    return None


def _validate_title(title: Any) -> str:
    t = str(title or "").strip() or "New Chat"
    return t[:MAX_TITLE_LEN]


def _validate_prompt(prompt: Any) -> Optional[str]:
    if not isinstance(prompt, str):
        return "prompt must be a string"
    if len(prompt) > MAX_PROMPT_LEN:
        return f"Message is too long (max {MAX_PROMPT_LEN} characters)"
    return None


# ============== HTTP Endpoints ==============
@app.get("/")
async def root():
    return {"message": "Anyq Backend is running"}


@app.get("/health")
async def health_check():
    try:
        await db.db.command("ping")
        database = "connected"
    except Exception as e:
        database = f"error: {type(e).__name__}"
    agent_status = "connected" if agent_manager.agent_connection else "disconnected"
    payload = {
        "status": "healthy" if database == "connected" else "degraded",
        "database": database,
        "agent": agent_status,
        "active_ui_connections": len(ui_manager.active_connections),
    }
    if database != "connected":
        return JSONResponse(status_code=503, content=payload)
    return payload


# ---------- Auth ----------
@app.post("/api/auth/signup")
async def signup(body: SignupRequest, request: Request):
    username = (body.username or "").strip()
    email = (body.email or "").strip() or None
    password = body.password or ""

    if not _USERNAME_RE.fullmatch(username):
        raise HTTPExceptionJson(400, "Username must be 3-30 chars: letters, digits, underscore")
    if email and not _EMAIL_RE.fullmatch(email):
        raise HTTPExceptionJson(400, "Invalid email address")
    if len(password) < 8:
        raise HTTPExceptionJson(400, "Password must be at least 8 characters")

    # Note: {email: null} in Mongo matches users with NO email field, so the
    # email condition must only be added when an email was actually provided.
    conditions = [{"username": username}]
    if email:
        conditions.append({"email": email})
    existing = await db.db.users.find_one({"$or": conditions})
    if existing:
        if existing.get("username") == username:
            raise HTTPExceptionJson(409, "Username already taken")
        raise HTTPExceptionJson(409, "Email already registered")

    try:
        user = {
            "username": username,
            "password_hash": _hash_password(password),
            "created_at": datetime.now(timezone.utc),
        }
        # Only store email when provided. The sparse unique index on email
        # treats explicit null as a VALUE (not "missing"), so writing
        # email=None here would make every subsequent signup without an email
        # collide with this document (DuplicateKeyError).
        if email:
            user["email"] = email
        result = await db.db.users.insert_one(user)
    except Exception:
        # `from None`: the DuplicateKeyError is deliberately dropped - the
        # client is told "already registered" and never sees Mongo internals.
        raise HTTPExceptionJson(409, "Username or email already registered") from None

    user_id = str(result.inserted_id)
    token = await _create_session(user_id)
    login_limiter.reset(f"user:{username}")

    response = JSONResponse(
        {"user": _user_payload({**user, "_id": result.inserted_id})},
        status_code=201,
    )
    response.headers["Set-Cookie"] = _session_cookie(token, SESSION_TTL_HOURS * 3600)
    return response


@app.post("/api/auth/login")
async def login(body: LoginRequest, request: Request):
    username = (body.username or "").strip()
    password = body.password or ""
    ip = _client_ip(request)

    if not login_limiter.allow(f"ip:{ip}") or not login_limiter.allow(f"user:{username}"):
        raise HTTPExceptionJson(429, "Too many login attempts. Try again later.")

    user = await db.db.users.find_one({"username": username})
    if not user or not _verify_password(password, user.get("password_hash", "")):
        raise HTTPExceptionJson(401, "Invalid username or password")

    token = await _create_session(str(user["_id"]))
    login_limiter.reset(f"user:{username}")
    login_limiter.reset(f"ip:{ip}")

    response = JSONResponse({"user": _user_payload(user)})
    response.headers["Set-Cookie"] = _session_cookie(token, SESSION_TTL_HOURS * 3600)
    return response


@app.post("/api/auth/logout")
async def logout(request: Request):
    token = _cookie_token(request)
    if token:
        await db.db.sessions.delete_many({"token_hash": _hash_token(token)})
    response = JSONResponse({"ok": True})
    response.headers["Set-Cookie"] = _expired_session_cookie()
    return response


@app.get("/api/auth/me")
async def me(request: Request):
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")
    return {"user": _user_payload(user)}


# ---------- Chats (identity from session) ----------
@app.get("/api/chats")
async def list_user_chats(request: Request):
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")
    chats = await get_user_chats(str(user["_id"]))
    return {"items": chats}


@app.get("/api/chats/{chat_id}")
async def get_chat_history(chat_id: str, request: Request):
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")
    if not _validate_chat_id(chat_id):
        raise HTTPExceptionJson(400, "Invalid chat_id")

    chat = await db.db.chats.find_one({"_id": ObjectId(chat_id), "user_id": str(user["_id"])})
    if not chat:
        raise HTTPExceptionJson(404, "Chat not found")

    messages = await get_chat_messages(chat_id)
    return {
        "id": chat_id,
        "user_id": str(user["_id"]),
        "title": chat["title"],
        "current_video_url": chat.get("current_video_url"),
        "created_at": _iso_or_none(chat.get("created_at")),
        "updated_at": _iso_or_none(chat.get("updated_at")),
        "message_count": len(messages),
        "messages": messages,
    }


@app.get("/media/{filename}")
async def get_media(filename: str, request: Request):
    """Served only to authenticated users, only known video types, no traversal."""
    user = await _user_from_token(_cookie_token(request))
    if not user:
        raise HTTPExceptionJson(401, "Not authenticated")
    if not _SAFE_MEDIA_RE.fullmatch(filename):
        raise HTTPExceptionJson(404, "Not found")
    path = MEDIA_DIR / filename
    if not path.is_file():
        raise HTTPExceptionJson(404, "Not found")
    return FileResponse(path, media_type=_MEDIA_TYPES.get(path.suffix.lower(), "video/mp4"))


class HTTPExceptionJson(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


@app.exception_handler(HTTPExceptionJson)
async def _http_exception_json_handler(request: Request, exc: HTTPExceptionJson):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# ============== WebSocket Endpoints ==============
# /ws/agent and /ws are defined as exact paths (no path params)

@app.websocket("/ws/agent")
async def websocket_agent_endpoint(websocket: WebSocket):
    """WebSocket endpoint for AI Agent, protected by AGENT_SECRET handshake."""
    await websocket.accept()
    authed = False
    try:
        raw = await asyncio.wait_for(
            websocket.receive_text(), timeout=AGENT_HANDSHAKE_TIMEOUT_SEC
        )
        data = json.loads(raw)
        if (
            data.get("type") == "auth"
            and AGENT_SECRET
            and secrets.compare_digest(str(data.get("token") or ""), AGENT_SECRET)
        ):
            authed = True
            await websocket.send_json({"type": "auth_ok"})
            print("AI Agent authenticated")
        else:
            print("Agent handshake failed: wrong or missing AGENT_SECRET")
            await websocket.close(code=1008, reason="auth failed")
            return
    except Exception as e:
        print(f"Agent handshake error: {type(e).__name__}: {e}")
        try:
            await websocket.close(code=1008, reason="handshake failed")
        except Exception:
            pass
        return

    try:
        await agent_manager.connect(websocket)
    except Exception as e:
        print(f"Agent manager connect error: {e}")
        return

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except Exception:
                print("Agent sent non-JSON message; ignoring")
                continue
            if not authed:
                continue

            request_id = data.get("request_id")
            response_text = data.get("text", "")
            status = data.get("status", "complete")
            video_path = data.get("video_path", "")
            error = data.get("error", "")

            if not request_id:
                print("Agent sent message without request_id")
                continue

            pop_request = (status == "complete" or status == "error")
            request_info = agent_manager.get_request_info(request_id, pop=pop_request)

            if not request_info:
                print(f"Unknown request_id: {request_id}")
                continue

            user_id = request_info["user_id"]
            chat_id = request_info["chat_id"]

            if status == "error":
                await ui_manager.send_to_user(user_id, {
                    "type": "error",
                    "data": {
                        "message": error or "Agent processing failed",
                        "chat_id": chat_id,
                    },
                })
                continue

            video_url = None
            if video_path and _SAFE_MEDIA_RE.fullmatch(os.path.basename(video_path)):
                video_url = f"/media/{os.path.basename(video_path)}"

            if status == "complete" and response_text:
                try:
                    msg_data = await save_message(
                        chat_id, "assistant", response_text,
                        video_url=video_url,
                    )
                except Exception as e:
                    print(f"Failed to save assistant message: {type(e).__name__}: {e}")
                    continue

                await ui_manager.send_to_user(user_id, {
                    "type": "ai_response",
                    "data": {
                        "message_id": msg_data["id"],
                        "chat_id": chat_id,
                        "content": response_text,
                        "video_url": video_url,
                        "timestamp": msg_data["timestamp"],
                    },
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"Agent WebSocket error: {type(e).__name__}: {e}")
    finally:
        agent_manager.disconnect()
        await _notify_pending_failures(
            "AI Agent is not available. Please try again later."
        )


async def _handle_ui_frame(websocket: WebSocket, user_id: str, data: dict) -> None:
    msg_type = data.get("type")
    payload = data.get("data", {}) if isinstance(data.get("data"), dict) else {}

    if msg_type == "ping":
        await websocket.send_json({"type": "pong"})
        return

    if msg_type == "create_chat":
        title = _validate_title(payload.get("title"))
        chat = await create_chat(user_id, title)
        await websocket.send_json({"type": "chat_created", "data": chat})
        return

    if msg_type == "delete_chat":
        chat_id = payload.get("chat_id")
        if chat_id and _validate_chat_id(chat_id):
            success = await delete_chat_by_id(chat_id, user_id)
            await websocket.send_json({
                "type": "chat_deleted",
                "data": {"chat_id": chat_id, "success": success},
            })
        else:
            await websocket.send_json({
                "type": "chat_deleted",
                "data": {"chat_id": chat_id, "success": False},
            })
        return

    if msg_type == "user_message":
        chat_id = payload.get("chat_id")
        prompt = payload.get("prompt", "")
        screenshots = payload.get("screenshots", [])

        if not chat_id or not _validate_chat_id(chat_id):
            await websocket.send_json({
                "type": "error",
                "data": {"message": "Invalid chat_id", "chat_id": chat_id},
            })
            return

        prompt_err = _validate_prompt(prompt)
        if prompt_err:
            await websocket.send_json({
                "type": "error",
                "data": {"message": prompt_err, "chat_id": chat_id},
            })
            return

        shots_err = _validate_screenshots(screenshots)
        if shots_err:
            await websocket.send_json({
                "type": "error",
                "data": {"message": shots_err, "chat_id": chat_id},
            })
            return

        if not prompt and not screenshots:
            await websocket.send_json({
                "type": "error",
                "data": {"message": "Either prompt or screenshots required", "chat_id": chat_id},
            })
            return

        # Ownership check: the chat must belong to the session user.
        chat = await db.db.chats.find_one({"_id": ObjectId(chat_id), "user_id": user_id})
        if not chat:
            await websocket.send_json({
                "type": "error",
                "data": {"message": "Chat not found", "chat_id": chat_id},
            })
            return

        # Check agent availability BEFORE saving anything (no orphan messages).
        if not agent_manager.agent_connection:
            await websocket.send_json({
                "type": "error",
                "data": {
                    "message": "AI Agent is not available. Please try again later.",
                    "chat_id": chat_id,
                },
            })
            return

        await save_message(chat_id, "user", prompt, screenshots)
        await websocket.send_json({"type": "message_received"})

        request_id = str(uuid.uuid4())
        agent_manager.pending_requests[request_id] = {
            "user_id": user_id,
            "chat_id": chat_id,
            "created_at": time.monotonic(),
        }
        try:
            await agent_manager.send_to_agent(
                request_id=request_id,
                user_id=user_id,
                chat_id=chat_id,
                text=prompt,
                screenshots=screenshots,
            )
        except Exception as e:
            agent_manager.pending_requests.pop(request_id, None)
            await websocket.send_json({
                "type": "error",
                "data": {
                    "message": f"Failed to send to agent: {e}",
                    "chat_id": chat_id,
                },
            })
        return

    # Unknown message type: ignore silently.


@app.websocket("/ws")
async def websocket_ui_endpoint(websocket: WebSocket):
    """WebSocket endpoint for UI clients; identity from the session cookie."""
    token = websocket.cookies.get(COOKIE_NAME)
    user = await _user_from_token(token)
    if not user:
        await websocket.close(code=1008, reason="not authenticated")
        return

    if not _is_allowed_origin(websocket.headers.get("origin")):
        await websocket.close(code=1008, reason="origin not allowed")
        return

    user_id = str(user["_id"])
    try:
        await ui_manager.connect(websocket, user_id)
    except Exception as e:
        print(f"UI connect failed: {e}")
        return

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("frame must be an object")
            except Exception as e:
                # One malformed frame must not kill the connection.
                try:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": f"Invalid message: {type(e).__name__}"},
                    })
                except Exception:
                    pass
                continue

            try:
                await _handle_ui_frame(websocket, user_id, data)
            except WebSocketDisconnect:
                raise
            except Exception as e:
                print(f"UI frame error for user {user_id}: {type(e).__name__}: {e}")
                try:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": "Internal error while processing message"},
                    })
                except Exception:
                    pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"UI WebSocket error for user {user_id}: {type(e).__name__}: {e}")
    finally:
        ui_manager.disconnect(user_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)