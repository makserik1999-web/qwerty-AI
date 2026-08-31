"""Liveness and readiness."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.db import db
from app.ws.manager import agent_manager, ui_manager

router = APIRouter()


@router.get("/")
async def root():
    return {"message": "Anyq Backend is running"}


@router.get("/health")
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
