"""Application assembly: middleware, routers and the error handler.

Everything of substance lives in the modules imported below; this file only
wires them together, which is what `uvicorn main:app` ultimately loads.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, chats, health, media
from app.config import CORS_ORIGINS
from app.db import lifespan
from app.errors import HTTPExceptionJson, _http_exception_json_handler
from app.ws import agent as ws_agent
from app.ws import ui as ws_ui

app = FastAPI(title="Anyq Backend", version="1.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)

app.add_exception_handler(HTTPExceptionJson, _http_exception_json_handler)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(chats.router)
app.include_router(media.router)

# /ws/agent and /ws are exact paths (no path params)
app.include_router(ws_agent.router)
app.include_router(ws_ui.router)
