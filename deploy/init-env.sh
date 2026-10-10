#!/usr/bin/env bash
# Writes .env for a production server, once.
#
#     bash deploy/init-env.sh akronustaz.com
#
# Starts from .env.example, so every setting keeps its documentation, and fills
# in what a server behind the Cloudflare tunnel needs: the public domain, the
# cookie's Secure flag, fresh random secrets for the agent channel and both
# database users, and COMPOSE_FILE so every `docker compose` here includes
# docker-compose.prod.yml.
#
# The tunnel token and the API keys are left empty on purpose: they are pasted
# in by hand, and the keys must be NEW ones - see docs/DEPLOY.md.
#
# Refuses to touch an existing .env: regenerating the database passwords
# under a running database locks every service out of it.

source "$(dirname "$0")/lib.sh"

domain="${1:-}"
[ -n "$domain" ] || die "укажите домен: bash deploy/init-env.sh akronustaz.com"
printf '%s' "$domain" | grep -Eq '^[a-z0-9]([a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$' \
    || die "'$domain' не похож на домен (только строчные буквы, без https:// и слэшей)"
[ ! -e "$ENV_FILE" ] || die ".env уже есть - не перезаписываю. Правьте его руками или удалите, если стек ещё ни разу не запускался."

# Alphanumeric only: these go inside a mongodb:// URI, where @ : / ? would
# need percent-encoding (.env.example explains). Length carries the entropy.
random() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom 2>/dev/null | head -c "$1" || true; }

set_var() {
    local tmp
    tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
    awk -v k="$1" -v v="$2" '
        index($0, k "=") == 1 { if (!done) print k "=" v; done = 1; next }
        { print }
        END { if (!done) print k "=" v }
    ' "$ENV_FILE" > "$tmp"
    cat "$tmp" > "$ENV_FILE"
    rm -f "$tmp"
}

umask 077
# The example starts with a UTF-8 BOM and may have CRLF line ends; neither
# belongs in a file compose parses on Linux.
sed -e '1s/^\xEF\xBB\xBF//' -e 's/\r$//' .env.example > "$ENV_FILE"
chmod 600 "$ENV_FILE"

set_var COMPOSE_FILE "$PROD_FILES"
# Pinned, so the volumes keep their names whatever the checkout is called.
set_var COMPOSE_PROJECT_NAME anyq

set_var AGENT_SECRET "$(random 64)"
set_var MONGO_ROOT_PASSWORD "$(random 40)"
set_var MONGO_APP_PASSWORD "$(random 40)"

set_var SITE_DOMAIN "$domain"
set_var CORS_ORIGINS "https://$domain"
# TLS ends at Cloudflare; nginx here is plain HTTP. The cookie still has to
# be Secure, because the browser only ever talks https to this site.
set_var COOKIE_SECURE 1
set_var HTTPS_TERMINATED 0
set_var TUNNEL_TOKEN ""

# 480p to start with: the box is a 2-core i3, and medium (720p) renders
# several times slower. Raise it once render times on the server are known.
set_var EFFORT_DEFAULT low

set_var BACKUP_DIR /var/backups/anyq

cat <<EOF

.env создан (права 600). Секреты агента и базы сгенерированы.

Осталось вписать руками - ключи НОВЫЕ, не те, что уже где-то светились:
    TUNNEL_TOKEN=           токен туннеля из панели Cloudflare (обязательно)
    OPENROUTER_API_KEY=     без него не работает ИИ
    AZURE_SPEECH_KEY=       без него видео без озвучки
    AZURE_SPEECH_REGION=
    GEMINI_API_KEY=         разбор скриншотов (необязательно)
    TELEGRAM_BOT_TOKEN=     куда слать тревоги мониторинга (необязательно)
    TELEGRAM_CHAT_ID=

    nano .env

Дальше: bash deploy/deploy.sh
EOF
