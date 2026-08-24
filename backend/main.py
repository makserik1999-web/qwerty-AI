"""
Unified Backend - FastAPI Chat Server with WebSocket support
Handles UI clients and AI Agent communication via WebSocket
HTTP GET endpoint for fetching chat history only
"""

import os
import json
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from bson import ObjectId

# ============== Configuration ==============
MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongo:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "spoon_chat")

# ============== Database ==============
class Database:
    client: AsyncIOMotorClient = None
    db = None

db = Database()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db.client = AsyncIOMotorClient(MONGO_URL)
    db.db = db.client[DATABASE_NAME]
    await db.db.chats.create_index([("user_id", 1)])
    await db.db.messages.create_index([("chat_id", 1), ("timestamp", 1)])
    print(f"Connected to MongoDB at {MONGO_URL}")
    yield
    # Shutdown
    db.client.close()
    print("Disconnected from MongoDB")

app = FastAPI(title="Anyq Backend", version="1.0.0", lifespan=lifespan)

# Mount media directory for serving videos
MEDIA_DIR = os.getenv("MEDIA_DIR", "/app/media")
Path(MEDIA_DIR).mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============== Pydantic Models ==============
class ChatCreate(BaseModel):
    title: Optional[str] = "New Chat"

class ScreenshotData(BaseModel):
    id: str
    image_base64: str

# ============== Connection Managers ==============
class UIConnectionManager:
    """Manages WebSocket connections from UI clients."""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        print(f"UI client connected: user_id={user_id}")
    
    def disconnect(self, user_id: str):
        self.active_connections.pop(user_id, None)
        print(f"UI client disconnected: user_id={user_id}")
    
    async def send_to_user(self, user_id: str, message: dict):
        ws = self.active_connections.get(user_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception as e:
                print(f"Error sending to user {user_id}: {e}")
    
    def get_connection(self, user_id: str) -> Optional[WebSocket]:
        return self.active_connections.get(user_id)


class AgentConnectionManager:
    """Manages WebSocket connection to AI Agent."""
    
    def __init__(self):
        self.agent_connection: Optional[WebSocket] = None
        self.pending_requests: Dict[str, dict] = {}
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.agent_connection = websocket
        print("AI Agent connected")
    
    def disconnect(self):
        self.agent_connection = None
        print("AI Agent disconnected")
    
    async def send_to_agent(self, request_id: str, user_id: str, chat_id: str,
                            text: Optional[str], screenshots: List[Dict[str, Any]]):
        if not self.agent_connection:
            raise Exception("AI Agent not connected")
        
        self.pending_requests[request_id] = {
            "user_id": user_id,
            "chat_id": chat_id
        }
        
        image_data = None
        if screenshots and len(screenshots) > 0:
            image_data = screenshots[0].get("image_base64")
        
        await self.agent_connection.send_json({
            "request_id": request_id,
            "text": text,
            "image_data": image_data
        })
    
    def get_request_info(self, request_id: str, pop: bool = True) -> Optional[dict]:
        if pop:
            return self.pending_requests.pop(request_id, None)
        return self.pending_requests.get(request_id)


ui_manager = UIConnectionManager()
agent_manager = AgentConnectionManager()

# ============== Database Operations ==============
async def create_chat(user_id: str, title: str = "New Chat") -> dict:
    """Create a new chat for a user."""
    chat = {
        "user_id": user_id,
        "title": title,
        "current_video_url": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    result = await db.db.chats.insert_one(chat)
    return {
        "id": str(result.inserted_id),
        "user_id": user_id,
        "title": title,
        "current_video_url": None,
        "created_at": chat["created_at"].isoformat(),
        "updated_at": chat["updated_at"].isoformat(),
        "message_count": 0
    }

async def save_message(chat_id: str, role: str, content: str, 
                       screenshots: List[Dict[str, Any]] = None, video_url: str = None) -> dict:
    """Save a message to the database."""
    message = {
        "chat_id": chat_id,
        "role": role,
        "content": content,
        "screenshots": screenshots or [],
        "video_url": video_url,
        "timestamp": datetime.utcnow()
    }
    result = await db.db.messages.insert_one(message)
    
    update_fields = {"updated_at": datetime.utcnow()}
    if video_url:
        update_fields["current_video_url"] = video_url
    
    await db.db.chats.update_one(
        {"_id": ObjectId(chat_id)},
        {"$set": update_fields}
    )
    
    return {
        "id": str(result.inserted_id),
        "role": role,
        "content": content,
        "screenshots": screenshots or [],
        "video_url": video_url,
        "timestamp": message["timestamp"].isoformat()
    }

async def get_chat_messages(chat_id: str) -> list:
    """Get all messages for a chat."""
    cursor = db.db.messages.find({"chat_id": chat_id}).sort("timestamp", 1)
    messages = []
    async for msg in cursor:
        messages.append({
            "id": str(msg["_id"]),
            "role": msg["role"],
            "content": msg.get("content", ""),
            "screenshots": msg.get("screenshots", []),
            "video_url": msg.get("video_url"),
            "timestamp": msg["timestamp"].isoformat()
        })
    return messages

async def get_user_chats(user_id: str) -> list:
    """Get all chats for a user."""
    cursor = db.db.chats.find({"user_id": user_id}).sort("updated_at", -1)
    chats = []
    async for chat in cursor:
        chat_id = str(chat["_id"])
        msg_count = await db.db.messages.count_documents({"chat_id": chat_id})
        chats.append({
            "id": chat_id,
            "user_id": chat["user_id"],
            "title": chat["title"],
            "current_video_url": chat.get("current_video_url"),
            "created_at": chat["created_at"].isoformat(),
            "updated_at": chat["updated_at"].isoformat(),
            "message_count": msg_count
        })
    return chats

async def delete_chat_by_id(chat_id: str, user_id: str) -> bool:
    """Delete a chat and its messages."""
    result = await db.db.chats.delete_one({
        "_id": ObjectId(chat_id),
        "user_id": user_id
    })
    if result.deleted_count > 0:
        await db.db.messages.delete_many({"chat_id": chat_id})
        return True
    return False

# ============== HTTP Endpoints ==============
@app.get("/")
async def root():
    return {"message": "Spoon Unified Backend is running"}

@app.get("/health")
async def health_check():
    agent_status = "connected" if agent_manager.agent_connection else "disconnected"
    return {
        "status": "healthy",
        "agent": agent_status,
        "active_ui_connections": len(ui_manager.active_connections)
    }

@app.get("/api/users/{user_id}/chats")
async def list_user_chats(user_id: str):
    """Get all chats for a user."""
    chats = await get_user_chats(user_id)
    return {"items": chats}

@app.get("/api/users/{user_id}/chats/{chat_id}")
async def get_chat_history(user_id: str, chat_id: str):
    """Get messages for a specific chat."""
    chat = await db.db.chats.find_one({
        "_id": ObjectId(chat_id),
        "user_id": user_id
    })
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    messages = await get_chat_messages(chat_id)
    return {
        "id": chat_id,
        "user_id": user_id,
        "title": chat["title"],
        "current_video_url": chat.get("current_video_url"),
        "created_at": chat["created_at"].isoformat(),
        "updated_at": chat["updated_at"].isoformat(),
        "message_count": len(messages),
        "messages": messages
    }

# ============== WebSocket Endpoints ==============
# IMPORTANT: /ws/agent MUST be defined BEFORE /ws/{user_id} to avoid route conflict

@app.websocket("/ws/agent")
async def websocket_agent_endpoint(websocket: WebSocket):
    """WebSocket endpoint for AI Agent."""
    await agent_manager.connect(websocket)
    
    try:
        while True:
            data = await websocket.receive_json()
            
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
                    "data": {"message": error or "Agent processing failed"}
                })
                continue
            
            video_url = None
            if video_path:
                video_url = f"/media/{os.path.basename(video_path)}"
            
            if status == "complete" and response_text:
                msg_data = await save_message(
                    chat_id, "assistant", response_text, 
                    video_url=video_url
                )
                
                await ui_manager.send_to_user(user_id, {
                    "type": "ai_response",
                    "data": {
                        "message_id": msg_data["id"],
                        "chat_id": chat_id,
                        "content": response_text,
                        "video_url": video_url,
                        "timestamp": msg_data["timestamp"]
                    }
                })
    
    except WebSocketDisconnect:
        agent_manager.disconnect()
    except Exception as e:
        print(f"Agent WebSocket error: {e}")
        agent_manager.disconnect()


@app.websocket("/ws/{user_id}")
async def websocket_ui_endpoint(websocket: WebSocket, user_id: str):
    """WebSocket endpoint for UI clients."""
    await ui_manager.connect(websocket, user_id)
    
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            payload = data.get("data", {})
            
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            
            if msg_type == "create_chat":
                title = payload.get("title", "New Chat")
                chat = await create_chat(user_id, title)
                await websocket.send_json({
                    "type": "chat_created",
                    "data": chat
                })
                continue
            
            if msg_type == "delete_chat":
                chat_id = payload.get("chat_id")
                if chat_id:
                    success = await delete_chat_by_id(chat_id, user_id)
                    await websocket.send_json({
                        "type": "chat_deleted",
                        "data": {"chat_id": chat_id, "success": success}
                    })
                continue
            
            if msg_type == "user_message":
                chat_id = payload.get("chat_id")
                prompt = payload.get("prompt", "")
                screenshots = payload.get("screenshots", [])
                
                if not chat_id:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": "chat_id is required"}
                    })
                    continue
                
                if not prompt and not screenshots:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": "Either prompt or screenshots required"}
                    })
                    continue
                
                await save_message(chat_id, "user", prompt, screenshots)
                
                await websocket.send_json({
                    "type": "message_received"
                })
                
                request_id = f"{user_id}_{chat_id}_{datetime.utcnow().timestamp()}"
                
                if not agent_manager.agent_connection:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": "AI Agent is not available. Please try again later."}
                    })
                    continue
                
                try:
                    await agent_manager.send_to_agent(
                        request_id=request_id,
                        user_id=user_id,
                        chat_id=chat_id,
                        text=prompt,
                        screenshots=screenshots
                    )
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": f"Failed to send to agent: {str(e)}"}
                    })
                continue
    
    except WebSocketDisconnect:
        ui_manager.disconnect(user_id)
    except Exception as e:
        print(f"UI WebSocket error for user {user_id}: {e}")
        ui_manager.disconnect(user_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
