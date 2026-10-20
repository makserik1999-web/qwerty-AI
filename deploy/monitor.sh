#!/usr/bin/env bash
# Is the site all right? Run by cron every five minutes (deploy/prepare-server.sh
# installs the line); silent while nothing changes.
#
#     bash deploy/monitor.sh           check, and alert on a change
#     bash deploy/monitor.sh --test    send a test message and exit
#
# Looks at:
#   - every service: running, and healthy where it has a healthcheck - which
#     covers the database, the agent's link to the backend, the tunnel's link
#     to Cloudflare and a backup in the last 26 hours;
#   - the site on the box itself (127.0.0.1:8080) and the way visitors get in,
#     through Cloudflare - so a broken tunnel and a broken site tell apart;
#   - disk space: less than 85% used.
#
# No certificate check: the one visitors see is Cloudflare's, and Cloudflare
# renews it.
#
# Alerts go to Telegram when TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set in
# .env, and always to stdout (cron's log). Only when the set of problems
# changes, plus a reminder every 6 hours while something stays broken - one
# message per incident, not one every five minutes. An alert Telegram did not
# take (the server's own internet is often what broke) is tried again on the
# next run, and "back to normal" says what it was and for how long - so it
# makes sense even when the alert itself never arrived.
#
# Silent while deploy.sh runs: replacing containers is not an outage.
#
# It runs on the server it watches, so it cannot report the server itself
# being down. docs/DEPLOY.md names an outside check for that.

source "$(dirname "$0")/lib.sh"

STATE="${ANYQ_MONITOR_STATE:-/var/tmp/anyq-monitor.state}"
SINCE_FILE="${STATE}.since"
REMIND_SEC=$((6 * 3600))
# A deploy marker older than this is a deploy that died without cleaning up;
# it no longer silences anything.
DEPLOY_QUIET_SEC=$((30 * 60))

token="$(env_get TELEGRAM_BOT_TOKEN)"
chat="$(env_get TELEGRAM_CHAT_ID)"
domain="$(env_get SITE_DOMAIN)"

notify() {
    printf '%s %s\n' "$(date '+%F %T')" "$1"
    if [ -n "$token" ] && [ -n "$chat" ]; then
        if ! curl -s --max-time 15 -o /dev/null "https://api.telegram.org/bot${token}/sendMessage" \
            --data-urlencode "chat_id=${chat}" --data-urlencode "text=$1"; then
            printf '%s telegram unreachable\n' "$(date '+%F %T')"
            return 1
        fi
    fi
}

if [ "${1:-}" = "--test" ]; then
    notify "Akron ($domain): проверка связи мониторинга"
    exit 0
fi

if [ -f "$DEPLOY_MARK" ] && [ $(($(date +%s) - $(stat -c %Y "$DEPLOY_MARK"))) -lt "$DEPLOY_QUIET_SEC" ]; then
    printf '%s deploy in progress, not checking\n' "$(date '+%F %T')"
    exit 0
fi

problems=()

# Services.
expected="$(services)"
running="$(docker compose ps --all --format '{{.Service}}|{{.State}}|{{.Health}}' 2>/dev/null || true)"
for service in $expected; do
    # While a container is being replaced compose lists two for the service,
    # the old one running and the new one created, and both lines used to end
    # up in one problem: "frontend: running" and a bare "created". The best of
    # them speaks for the service - "running" sorts after every other state.
    line="$(printf '%s\n' "$running" | grep "^${service}|" | sort -r | head -1 || true)"
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

# The site: on the box, then through Cloudflare.
check() {
    local got="$1" want="$2" what="$3"
    [ "$got" = "$want" ] || problems+=("$what: HTTP $got")
}
check "$(local_status /)" 200 "сайт на сервере"
check "$(local_status /api/auth/me)" 401 "API на сервере"
check "$(local_status /api/play/code/AAAAAA)" 404 "квизы на сервере"
check "$(public_status "https://$domain/")" 200 "сайт через Cloudflare"
check "$(public_status "https://$domain/api/auth/me")" 401 "API через Cloudflare"

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
    [ -n "$previous" ] || printf '%s\n' "$now" > "$SINCE_FILE"
    if [ "$current" != "$previous" ] || [ $((now - last_sent)) -ge "$REMIND_SEC" ]; then
        if notify "Akron ($domain): проблемы
$(printf '%s\n' "$current" | sed 's/^/- /')"; then
            last_sent="$now"
        else
            # Not delivered. Zero makes the next run send it again instead of
            # waiting for the six-hour reminder.
            last_sent=0
        fi
    fi
elif [ -n "$previous" ]; then
    since="$(head -1 "$SINCE_FILE" 2>/dev/null || true)"
    took=""
    if [ -n "$since" ]; then
        took=" - около $(((now - since + 59) / 60)) мин"
    fi
    notify "Akron ($domain): всё снова в порядке. Было$took:
$(printf '%s\n' "$previous" | sed 's/^/- /')" || true
    rm -f "$SINCE_FILE"
fi
printf '%s\n%s\n' "$last_sent" "$current" > "$STATE"

[ -z "$current" ]
