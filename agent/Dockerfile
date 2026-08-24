FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for Manim + LaTeX
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      pkg-config \
      libcairo2-dev \
      libpango1.0-dev \
      ffmpeg \
      ghostscript \
      dvisvgm \
      texlive-latex-base \
      texlive-latex-recommended \
      texlive-latex-extra \
      texlive-fonts-recommended \
      texlive-fonts-extra \
      texlive-science \
      preview-latex-style \
      fontconfig \
      fonts-dejavu-core \
      git \
    && rm -rf /var/lib/apt/lists/*

# Install python deps
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r /app/requirements.txt

# Copy the agent code (includes manim-mcp-server)
COPY . /app

# Default environment
ENV MANIM_MCP_SERVER_SCRIPT=/app/manim-mcp-server/src/manim_server.py
ENV MANIM_ALLOW_LATEX=1
ENV AGENT_WS_URL=ws://backend:8000/ws/agent

# Create media output directory
RUN mkdir -p /app/manim-mcp-server/src/media/outputs

CMD ["python", "agent_ws_client.py"]

