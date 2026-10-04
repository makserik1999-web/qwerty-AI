#!/usr/bin/env bash
# Is the site all right? Run by cron every five minutes (deploy/prepare-server.sh
# installs the line); silent while nothing changes.
#
#     bash deploy/monitor.sh           check, and alert on a change
#     bash deploy/monitor.sh --test    send a test message and exit
#
# Looks at:
#   - every service: running, and healthy where it has a healthcheck - which
#     covers the database, the agent's link to the backend and a backup in
#     the last 26 hours;
#   - the site from the outside in: the page, the API, the quiz service;
#   - the certificate: more than 14 days left;
#   - disk space: less than 85% used.
#
# Alerts go to Telegram when TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set in
# .env, and always to stdout (cron's log). Only when the set of problems
# changes, plus a reminder every 6 hours while something stays broken - one
# message per incident, not one every five minutes.
#
# It runs on the server it watches, so it cannot report the server itself
# being down. docs/DEPLOY.md names an outside check for that.

source "$(dirname "$0")/lib.sh"

STATE="${ANYQ_MONITOR_STATE:-/var/tmp/anyq-monitor.state}"
REMIND_SEC=$((6 * 3600))

token="$(env_get TELEGRAM_BOT_TOKEN)"
chat="$(env_get TELEGRAM_CHAT_ID)"
domain="$(env_get TLS_SERVER_NAME)"; domain="${domain%% *}"

notify() {
    printf '%s %s\n' "$(date '+%F %T')" "$1"
    if [ -n "$token" ] && [ -n "$chat" ]; then
        curl -s --max-time 15 -o /dev/null "https://api.telegram.org/bot${token}/sendMessage" \
            --data-urlencode "chat_id=${chat}" --data-urlencode "text=$1" \
            || printf '%s telegram unreachable\n' "$(date '+%F %T')"
    fi
}

if [ "${1:-}" = "--test" ]; then
    notify "Anyq ($domain): проверка связи мониторинга"
    exit 0
fi

problems=()

# Services.
expected="$(services)"
running="$(docker compose ps --all --format '{{.Service}}|{{.State}}|{{.Health}}' 2>/dev/null || true)"
for service in $expected; do
    line="$(printf '%s\n' "$running" | grep "^${service}|" || true)"
    state="$(printf '%s' "$line" | cut -d'|' -f2)"
    health="$(printf '%s' "$line" | cut -d'|' -f3)"
    if [ -z "$line" ]; then
        problems+=("$service: не запущен")
    elif [ "$state" != "running" ]; then
        problems+=("$service: $state")
    elif [ -n "$health" ] && [ "$health" != "healthy" ] && [ "$health" != "starting" ]; then
        problems+=("$service: $health")
    fi
done

# The site, through nginx.
check() {
    local want="$1" url="$2" what="$3" got
    got="$(status_of "$url")"
    [ "$got" = "$want" ] || problems+=("$what: HTTP $got")
}
check 200 "https://$domain/" "сайт"
check 401 "https://$domain/api/auth/me" "API"
check 404 "https://$domain/api/play/code/AAAAAA" "квизы"

# The certificate.
if command -v openssl >/dev/null 2>&1; then
    end="$(echo | openssl s_client -connect 127.0.0.1:443 -servername "$domain" 2>/dev/null \
        | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2 || true)"
    if [ -n "$end" ]; then
        days=$(( ($(date -d "$end" +%s) - $(date +%s)) / 86400 ))
        [ "$days" -ge 14 ] || problems+=("сертификат истекает через $days дн. - docker compose logs certbot")
    else
        problems+=("сертификат не читается на :443")
    fi
fi

# Disk: the root filesystem and wherever docker keeps its data.
for path in / "$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || echo /)"; do
    # The field that ends in %, not the fifth: a filesystem name with a space
    # in it shifts the columns. `|| true` because a path df cannot read must
    # not end the whole check under pipefail.
    used="$(df -P "$path" 2>/dev/null \
        | awk 'NR == 2 {for (i = NF; i > 0; i--) if ($i ~ /%$/) {sub("%", "", $i); print $i; exit}}' || true)"
    [ -z "$used" ] || [ "$used" -lt 85 ] || problems+=("диск $path занят на ${used}%")
done

# Report changes only.
current="$(printf '%s\n' "${problems[@]+"${problems[@]}"}" | sort -u | sed '/^$/d')"
previous=""
last_sent=0
if [ -f "$STATE" ]; then
    last_sent="$(head -1 "$STATE")"
    previous="$(tail -n +2 "$STATE")"
fi
now="$(date +%s)"

if [ -n "$current" ]; then
    if [ "$current" != "$previous" ] || [ $((now - last_sent)) -ge "$REMIND_SEC" ]; then
        notify "Anyq ($domain): проблемы
$(printf '%s\n' "$current" | sed 's/^/- /')"
        last_sent="$now"
    fi
elif [ -n "$previous" ]; then
    notify "Anyq ($domain): всё снова в порядке"
fi
printf '%s\n%s\n' "$last_sent" "$current" > "$STATE"

[ -z "$current" ]
