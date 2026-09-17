FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp

WORKDIR /app

# ffmpeg does the encoding; the DejaVu font is what makes a Kazakh caption
# render as letters instead of boxes.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
      fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /app/requirements.txt

COPY app /app/app

# Non-root, like the other services. The media volume is mounted with write
# access only because exports are written into a subdirectory of it.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin exporter \
    && mkdir -p /app/media/exports \
    && chown -R exporter:exporter /app

USER exporter

CMD ["python", "-m", "app.worker"]
