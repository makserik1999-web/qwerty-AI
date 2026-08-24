


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
- **Simple Authentication**: Hardcoded gatekeeper (admin/yesko)
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

# Edit .env and add your GEMINI_API_KEY
```

### 2. Start Services

```bash
docker compose up --build -d
```

### 3. Access the Application

- **Frontend**: http://localhost:3000
- **Login**: Username: `admin`, Password: `yesko`

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
| GEMINI_API_KEY        | Yes      | -              | Google Gemini API key          |
| DEFAULT_LLM_PROVIDER  | No       | gemini         | LLM provider to use            |
| DEFAULT_MODEL         | No       | gemini-2.5-pro | Default model                  |
| DATABASE_NAME         | No       | anyq_db        | MongoDB database name          |
| FRONTEND_PORT         | No       | 3000           | Port to expose frontend        |
| MANIM_ALLOW_LATEX     | No       | 1              | Enable LaTeX in Manim          |

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
- `GET /api/users/{user_id}/chats` - List user's chats
- `GET /api/users/{user_id}/chats/{chat_id}` - Get chat with messages

### WebSocket
- `WS /ws/{user_id}` - UI client connection
  - Send: `{"type": "user_message", "data": {...}}`
  - Send: `{"type": "create_chat", "data": {...}}`
  - Send: `{"type": "delete_chat", "data": {...}}`
  - Receive: `{"type": "ai_response", "data": {...}}`

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
