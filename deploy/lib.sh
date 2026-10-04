# Shared by the deploy/*.sh scripts. Sourced, not run.
#
# Every script works from the repository root and reads .env there - the same
# file compose reads, so a value checked here is the value the stack gets.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

ENV_FILE=.env
PROD_FILES="docker-compose.yml:docker-compose.prod.yml"

# BuildKit attaches a provenance record with the build time to every image, so
# on Docker's containerd image store (the default on new installs) even a
# fully cached rebuild gets a new image ID - and `up -d` then recreates every
# service, dropping a class's quiz sockets on a deploy that changed nothing.
# Measured on Docker 29: five new IDs per rebuild with it, none without.
export BUILDX_NO_DEFAULT_ATTESTATIONS=1

say() { printf '\n==> %s\n' "$*"; }
warn() { printf '  ! %s\n' "$*" >&2; }
die() { printf '\nОШИБКА: %s\n' "$*" >&2; exit 1; }

# The value of KEY in .env: the last occurrence wins, as it does for compose;
# surrounding quotes and a stray CR from a file edited on Windows removed.
env_get() {
    local line
    line="$(grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 || true)"
    line="${line#*=}"
    line="${line%$'\r'}"
    line="${line%\"}"; line="${line#\"}"
    line="${line%\'}"; line="${line#\'}"
    printf '%s' "$line"
}

need_env() {
    [ -f "$ENV_FILE" ] || die "нет .env. Сначала: bash deploy/init-env.sh <домен>"
    case "$(env_get COMPOSE_FILE)" in
        *docker-compose.prod.yml*) ;;
        *) die "в .env нет COMPOSE_FILE=$PROD_FILES - без него compose не видит прод-настройки" ;;
    esac
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "нет команды '$1'. $2"
}

# Every service compose would start, one per line (the restore profile is not
# among them).
services() { docker compose config --services; }

# Waits until every service runs and every healthcheck says healthy.
wait_healthy() {
    local timeout="${1:-600}" started now bad
    started="$(date +%s)"
    while :; do
        bad="$(docker compose ps --all --format '{{.Service}} {{.State}} {{.Health}}' \
            | awk '$2 != "running" || ($3 != "" && $3 != "healthy") {print $1 "(" $2 ($3 == "" ? "" : "," $3) ")"}' \
            | tr '\n' ' ')"
        local missing=""
        for s in $(services); do
            docker compose ps --format '{{.Service}}' | grep -qx "$s" || missing="$missing $s"
        done
        [ -z "$bad" ] && [ -z "$missing" ] && return 0
        now="$(date +%s)"
        if [ $((now - started)) -ge "$timeout" ]; then
            warn "не дождался: ${bad}${missing:+ не запущены:$missing}"
            return 1
        fi
        printf '  ждём: %s%s\n' "$bad" "${missing:+ не запущены:$missing}"
        sleep 10
    done
}

# Waits for one service's healthcheck.
wait_service() {
    local service="$1" timeout="${2:-120}" waited=0
    until [ "$(docker compose ps "$service" --format '{{.Health}}' 2>/dev/null)" = "healthy" ]; do
        [ "$waited" -lt "$timeout" ] || return 1
        sleep 3
        waited=$((waited + 3))
    done
}

# HTTP status of a URL on THIS server, under the site's real name - so it is
# checked before DNS points here, and without a round trip through it.
status_of() {
    local url="$1" host port
    host="$(printf '%s' "$url" | sed -E 's#^[a-z]+://([^/:]+).*#\1#')"
    case "$url" in https://*) port=443 ;; *) port=80 ;; esac
    curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
        --resolve "$host:$port:127.0.0.1" ${INSECURE:+-k} "$url" || true
}
