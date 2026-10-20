FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY quiz_service /app/quiz_service

# Non-root, like every other service here.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin quiz \
    && chown -R quiz:quiz /app
USER quiz

EXPOSE 8100

# Pings every 25s, given 60s to answer: a phone in a pocket on a school
# network goes quiet for a while without being gone, and dropping it would
# cost the student nothing but would cost the board a reconnect storm.
#
# --proxy-headers with every peer trusted: the only thing that can reach this
# port is the internal docker network, and the one thing on it that talks
# HTTP here is nginx - whose address changes with every recreate, and this
# uvicorn (0.27) takes exact addresses only, no subnets. nginx REPLACES
# X-Forwarded-For with the client it resolved (CF-Connecting-IP behind the
# Cloudflare tunnel) rather than appending to what the client sent, so the
# address and scheme uvicorn reports are nginx's word, not the browser's.
CMD ["uvicorn", "quiz_service.main:app", "--host", "0.0.0.0", "--port", "8100", "--ws-ping-interval", "25", "--ws-ping-timeout", "60", "--proxy-headers", "--forwarded-allow-ips", "*"]
