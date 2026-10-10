#!/usr/bin/env bash
# Build and (re)start the stack on the server, then check it - first on the
# box itself, then the way a visitor gets in, through Cloudflare. The same
# command for the first deploy and every one after it.
#
#     bash deploy/deploy.sh           what is checked out now
#     bash deploy/deploy.sh --pull    git pull first (fast-forward only)
#
# Stops before touching anything if .env is not fit for production: a
# placeholder secret, no tunnel token, a cookie without Secure, a CORS list
# still pointing at localhost. Those do not fail loudly at runtime - the site
# comes up and is quietly wrong.

source "$(dirname "$0")/lib.sh"

pull=0
for arg in "$@"; do
    case "$arg" in
        --pull) pull=1 ;;
        *) die "неизвестный флаг $arg (есть --pull)" ;;
    esac
done

need_env
need_cmd docker "Поставьте Docker: https://docs.docker.com/engine/install/debian/"
need_cmd curl "apt install curl"
need_compose 2.24.4

say "Проверяю .env"
problems=()
[ "$(stat -c %a "$ENV_FILE")" = "600" ] || { chmod 600 "$ENV_FILE"; warn ".env был доступен не только владельцу - поставил 600"; }
domain="$(env_get SITE_DOMAIN)"
case "$domain" in
    ""|localhost|*/*|*:*) problems+=("SITE_DOMAIN - не домен ('$domain'): нужно akronustaz.com, без https://") ;;
esac
[ "$(env_get COOKIE_SECURE)" = "1" ] \
    || problems+=("COOKIE_SECURE не 1 - cookie сессии ушла бы без Secure")
cors="$(env_get CORS_ORIGINS)"
case ",$cors," in *",https://$domain,"*) ;; *) problems+=("CORS_ORIGINS без https://$domain - не заработают вебсокеты и доска учителя в квизе") ;; esac
case "$cors" in *localhost*|*127.0.0.1*) problems+=("CORS_ORIGINS всё ещё пускает localhost") ;; esac
token="$(env_get TUNNEL_TOKEN)"
if [ -z "$token" ]; then
    problems+=("TUNNEL_TOKEN пуст - туннель не подключится (Cloudflare: Zero Trust -> Networks -> Tunnels)")
elif [ "${#token}" -lt 50 ] || ! printf '%s' "$token" | grep -Eq '^[A-Za-z0-9+/=_-]+$'; then
    problems+=("TUNNEL_TOKEN не похож на токен - нужна длинная строка после --token, без пробелов и кавычек")
fi
secret="$(env_get AGENT_SECRET)"
{ [ "${#secret}" -ge 32 ] && [ "${secret#change_me}" = "$secret" ]; } || problems+=("AGENT_SECRET короткий или из примера")
for key in MONGO_ROOT_USER MONGO_APP_USER MONGO_ROOT_PASSWORD MONGO_APP_PASSWORD; do
    value="$(env_get "$key")"
    [ -n "$value" ] || { problems+=("$key пуст"); continue; }
    case "$key" in *PASSWORD)
        { [ "${#value}" -ge 24 ] && [ "${value#change-me}" = "$value" ]; } || problems+=("$key короткий или из примера")
        printf '%s' "$value" | grep -Eq '^[A-Za-z0-9]+$' || problems+=("$key не только из букв и цифр - сломает mongodb:// URI")
    esac
done
if [ "${#problems[@]}" -gt 0 ]; then
    printf '  - %s\n' "${problems[@]}" >&2
    die "исправьте .env и запустите снова"
fi
[ -n "$(env_get OPENROUTER_API_KEY)" ] || warn "OPENROUTER_API_KEY пуст - ИИ-функции будут выключены"
[ -n "$(env_get AZURE_SPEECH_KEY)" ] || warn "AZURE_SPEECH_KEY пуст - видео без озвучки"
[ -n "$(env_get TELEGRAM_BOT_TOKEN)" ] || warn "TELEGRAM_BOT_TOKEN пуст - тревоги мониторинга будут только в логе"
grep -qw avx /proc/cpuinfo 2>/dev/null || warn "у процессора нет AVX - mongo 7 на нём не запустится"

free_gb="$(df -Pk . | awk 'NR == 2 {print int($4 / 1048576)}')"
[ "$free_gb" -ge 10 ] || warn "на диске свободно ${free_gb} ГБ - сборка агента может не влезть"

if [ "$pull" = 1 ]; then
    say "git pull"
    git pull --ff-only
fi

say "Сборка ($(git rev-parse --short HEAD 2>/dev/null || echo '?'))"
docker compose build

say "База"
docker compose up -d mongo
wait_service mongo 180 || die "mongo не стал healthy. docker compose logs mongo"
# The app user, made sure of on every deploy. A fresh volume gets it from
# scripts/mongo-init/ on first boot; this covers a first boot that ran with
# the password still empty, or a volume from before that script. Creating it
# needs the root user, which only this step and mongo's healthcheck ever use.
# The passwords travel as environment variables, never as arguments.
export ROOT_USER ROOT_PASSWORD APP_USER APP_PASSWORD DB_NAME
ROOT_USER="$(env_get MONGO_ROOT_USER)"; ROOT_PASSWORD="$(env_get MONGO_ROOT_PASSWORD)"
APP_USER="$(env_get MONGO_APP_USER)"; APP_PASSWORD="$(env_get MONGO_APP_PASSWORD)"
DB_NAME="$(env_get DATABASE_NAME)"; DB_NAME="${DB_NAME:-anyq_db}"
ensured=0
for _ in $(seq 1 30); do
    docker compose exec -T -e ROOT_USER -e ROOT_PASSWORD -e APP_USER -e APP_PASSWORD -e DB_NAME mongo \
        bash -c 'mongosh --quiet -u "$ROOT_USER" -p "$ROOT_PASSWORD" --authenticationDatabase admin --eval "
            const target = db.getSiblingDB(process.env.DB_NAME);
            if (target.getUser(process.env.APP_USER)) { print(\"  \" + process.env.APP_USER + \": есть\"); }
            else {
                target.createUser({user: process.env.APP_USER, pwd: process.env.APP_PASSWORD,
                                   roles: [{role: \"readWrite\", db: process.env.DB_NAME}]});
                print(\"  \" + process.env.APP_USER + \": создан\");
            }"' && { ensured=1; break; }
    sleep 2
done
[ "$ensured" = 1 ] || die "не удалось войти в mongo пользователем root - пароль в .env не тот, с которым создавалась база?"
unset ROOT_PASSWORD APP_PASSWORD

say "Запуск"
docker compose up -d --remove-orphans
wait_healthy 900 || die "не все сервисы поднялись. docker compose ps; docker compose logs <сервис>"

failed=0
report() {
    local got="$1" want="$2" what="$3"
    if [ "$got" = "$want" ]; then
        printf '  ok   %s  %s\n' "$got" "$what"
    else
        printf '  FAIL %s (ждали %s)  %s\n' "$got" "$want" "$what"
        failed=1
    fi
}

say "На самом сервере ($LOCAL_URL, мимо Cloudflare)"
report "$(local_status /)" 200 "сайт"
report "$(local_status /api/auth/me)" 401 "бэкенд и база (вход не выполнен)"
report "$(local_status /api/play/code/AAAAAA)" 404 "квиз-сервис"
report "$(local_status /ws/agent)" 403 "канал агента закрыт снаружи"
report "$(ws_status "$LOCAL_URL/ws/quiz/play")" 101 "вебсокет через nginx"
agent="$(docker compose exec -T backend curl -s --max-time 5 http://localhost:8000/health || true)"
case "$agent" in *'"agent":"connected"'*) echo "  ok   агент подключён к бэкенду" ;; *) echo "  FAIL агент не подключён: $agent"; failed=1 ;; esac
# The client's address as the backend sees it: a request claiming to come from
# a documentation address (TEST-NET-3) through Cloudflare's header must show
# up in the backend's access log under that address, not cloudflared's.
probe="203.0.113.$((RANDOM % 250 + 2))"
local_status /api/auth/me -H "CF-Connecting-IP: $probe" >/dev/null
sleep 1
if docker compose logs --since 2m backend 2>/dev/null | grep -q "$probe"; then
    echo "  ok   IP клиента берётся из CF-Connecting-IP"
else
    echo "  FAIL бэкенд не видит IP из CF-Connecting-IP - лимиты будут общими на всех"
    failed=1
fi

say "Снаружи, через Cloudflare (https://$domain)"
report "$(public_status "https://$domain/")" 200 "сайт"
report "$(public_status "https://$domain/api/auth/me")" 401 "API"
report "$(public_status "https://$domain/ws/agent")" 403 "канал агента закрыт"
report "$(public_status "http://$domain/")" 301 "http -> https (Always Use HTTPS)"
report "$(ws_status "https://$domain/ws/quiz/play")" 101 "вебсокет через Cloudflare"
hsts="$(curl -sI --max-time 20 "https://$domain/" | grep -ci '^strict-transport-security' || true)"
[ "$hsts" -ge 1 ] && echo "  ok   HSTS" || { echo "  FAIL нет заголовка HSTS"; failed=1; }

echo
docker compose ps --format 'table {{.Service}}\t{{.Status}}'
if [ "$failed" != 0 ]; then
    cat >&2 <<'EOF'

Если не прошли только проверки через Cloudflare: туннель ещё не подключился
(docker compose logs cloudflared) или маршрут в панели указывает не на
http://frontend:80.
EOF
    die "стек запущен, но проверки выше не прошли"
fi
printf '\nГотово: https://%s/ (%s)\n' "$domain" "$(git rev-parse --short HEAD 2>/dev/null || echo '?')"
