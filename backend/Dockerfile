FROM python:3.12-slim

WORKDIR /app

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Non-root user (least privilege)
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/media \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# The websocket keepalive is set here rather than left to uvicorn, whose
# defaults are 20s between pings with 20s to answer. Nobody chose those for
# this channel, and the peer on it is an agent that spends minutes rendering.
#
# 30s between pings with 90s to answer, so that the agent's own keepalive
# (30s / 60s, in anyq/config.py) always fires first. That ordering matters:
# the agent is the side that can do something about a dead connection - it
# reconnects and redelivers - while this side can only drop it.
#
# UI clients are not left undetected by the looser setting: the browser runs
# its own heartbeat over the same socket, pinging every 25s and giving up
# after 35 (frontend/src/lib/useWebSocket.ts).
#
# --proxy-headers with every peer trusted: the only thing that can reach this
# port is the internal docker network, and the one thing on it that talks
# HTTP here is nginx - whose address changes with every recreate, and this
# uvicorn (0.27) takes exact addresses only, no subnets. nginx REPLACES
# X-Forwarded-For with the client it resolved (CF-Connecting-IP behind the
# Cloudflare tunnel) rather than appending to what the client sent, so the
# address and scheme uvicorn reports are nginx's word, not the browser's.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--ws-ping-interval", "30", "--ws-ping-timeout", "90", "--proxy-headers", "--forwarded-allow-ips", "*"]