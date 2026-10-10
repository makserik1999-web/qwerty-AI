"""Assembly: routers, the error handler, and what runs in the background."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from quiz_service import db as database
from quiz_service.api import play, quizzes, sessions, ws
from quiz_service.errors import ApiError, api_error_handler
from quiz_service.events import consume_loop
from quiz_service.lifecycle import sweep_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.connect()
    await database.create_indexes()
    tasks = [asyncio.create_task(sweep_loop()), asyncio.create_task(consume_loop())]
    print("Quiz service ready", flush=True)
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        database.db.client.close()


app = FastAPI(title="Akron Quiz", version="1.0.0", lifespan=lifespan)
app.add_exception_handler(ApiError, api_error_handler)

app.include_router(quizzes.router)
app.include_router(sessions.router)
app.include_router(play.router)
app.include_router(ws.router)


@app.get("/health")
async def health():
    try:
        await database.db.db.command("ping")
        return {"status": "healthy", "database": "connected"}
    except Exception:  # noqa: BLE001
        return {"status": "degraded", "database": "unreachable"}
