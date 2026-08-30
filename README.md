


https://github.com/user-attachments/assets/94bb2d73-97fc-424a-856a-d01a279a6879


# Anyq - Interactive Learning Platform

An interactive educational platform that generates AI-powered animated videos to explain scientific concepts.

## Architecture

```
┌─────────────────┐     HTTP/WS      ┌─────────────────┐     WebSocket      ┌──────────────┐
│    Frontend     │◄────────────────►│     Backend     │◄──────────────────►│   AI Agent   │
│   (React/Vite)  │    :3000         │   (FastAPI)     │     :8000          │   (Manim)    │
└─────────────────┘                  └─────────────────┘                    └──────────────┘
                                             │
                                             ▼
                                       ┌───────────┐
                                       │  MongoDB  │
                                       └───────────┘
```

## Features

- **Real-time Communication**: WebSocket-based messaging for instant interactions
- **Educational Video Generation**: AI-powered Manim animations for science topics
- **Real Authentication**: signup/login with bcrypt-hashed passwords and revocable
  HttpOnly session cookies; user identity is derived server-side, never trusted
  from the client
- **Chat History**: Persistent chat storage with MongoDB

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Git

### 1. Clone and Configure

```bash
git clone https://github.com/Yeskendir2502/spoon-unified
cd spoon-unified

# Copy environment template
cp .env.example .env

# Edit .env:
#   1. set AGENT_SECRET to a long random string (backend and agent must share it)
#   2. add your GEMINI_API_KEY (without it the app still runs, but AI features
#      reply with a polite "AI functions unavailable" message)
```

### 2. Start Services

```bash
docker compose up --build -d
```

### 3. Access the Application

- **Frontend**: http://localhost:3000
- First time? Click **Create Account**, then **Sign In**.

## Services

| Service   | Port | Description                           |
|-----------|------|---------------------------------------|
| Frontend  | 3000 | React SPA with Nginx                  |
| Backend   | 8000 | FastAPI server (internal only)        |
| MongoDB   | 27017| Database (internal only)              |
| Agent     | -    | AI agent (connects via WebSocket)     |

## Environment Variables

| Variable              | Required | Default        | Description                    |
|-----------------------|----------|----------------|--------------------------------|
| GEMINI_API_KEY        | No*      | -              | Google Gemini API key          |
| AGENT_SECRET          | Yes      | -              | Shared secret for the agent channel (must match backend & agent) |
| DEFAULT_LLM_PROVIDER  | No       | gemini         | LLM provider to use            |
| DEFAULT_MODEL         | No       | gemini-2.5-pro | Default model                  |
| DATABASE_NAME         | No       | anyq_db        | MongoDB database name          |
| FRONTEND_PORT         | No       | 3000           | Port to expose frontend        |
| MANIM_ALLOW_LATEX     | No       | 1              | Enable LaTeX in Manim          |
| CORS_ORIGINS          | No       | localhost:3000 | Comma-separated allowed origins (credentials are enabled, so no "*") |
| COOKIE_SECURE         | No       | 0              | Set to 1 when serving over HTTPS |

\* Without `GEMINI_API_KEY` the app runs but AI features are unavailable
(polite message instead of an LLM response, no crashes).

## Project Structure

```
anyq/
├── frontend/           # React + TypeScript + Vite
│   ├── src/
│   │   ├── components/ # UI components
│   │   ├── hooks/      # Custom React hooks
│   │   └── types.ts    # TypeScript types
│   └── Dockerfile
├── backend/            # FastAPI server
│   ├── main.py         # Main application
│   └── Dockerfile
├── agent/              # AI agent service
│   ├── agent_ws_client.py
│   ├── science_manim_graph_agent.py
│   └── Dockerfile
├── docker-compose.yml  # Orchestration
├── .env.example        # Environment template
└── .gitignore
```

## API Endpoints

### HTTP (REST)
- `POST /api/auth/signup` - Create an account (sets the `anyq_session` cookie)
- `POST /api/auth/login` - Sign in (sets the `anyq_session` cookie)
- `POST /api/auth/logout` - Sign out (revokes the session)
- `GET /api/auth/me` - Current user from the session cookie
- `GET /api/chats` - List current user's chats
- `GET /api/chats/{chat_id}` - Get chat with messages
- `GET /media/{filename}` - Video file (authenticated)

### WebSocket
- `WS /ws` - UI client connection (authenticated via the session cookie)
  - Send: `{"type": "user_message", "data": {...}}`
  - Send: `{"type": "create_chat", "data": {...}}`
  - Send: `{"type": "delete_chat", "data": {...}}`
  - Receive: `{"type": "ai_response", "data": {...}}`
  - Receive: `{"type": "error", "data": {"message": "...", "chat_id": ...}}`

The agent channel `WS /ws/agent` is **not** exposed through nginx (403); the
agent connects to the backend directly over the internal docker network and
authenticates with `AGENT_SECRET` before processing anything.

## Troubleshooting

### Agent not connecting
- Check `AGENT_WS_URL` environment variable
- Ensure backend is healthy: `docker compose logs backend`

### Videos not generating
- Verify `GEMINI_API_KEY` is set correctly
- Check agent logs: `docker compose logs agent`

### Frontend can't connect
- Ensure all services are running: `docker compose ps`
- Check nginx logs: `docker compose logs frontend`

---

**Anyq v1.0** - Interactive Learning Platform
