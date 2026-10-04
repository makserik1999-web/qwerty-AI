#!/usr/bin/env bash
# Build and (re)start the stack on the server, then check it from the outside
# in. The same command for the first deploy and every one after it.
#
#     bash deploy/deploy.sh           what is checked out now
#     bash deploy/deploy.sh --pull    git pull first (fast-forward only)
#
# Stops before touching anything if .env is not fit for production: a
# placeholder secret, TLS off, a CORS list still pointing at localhost. Those
# do not fail loudly at runtime - the site comes up and is quietly wrong.

source "$(dirname "$0")/lib.sh"

pull=0
for arg in "$@"; do
    case "$arg" in
        --pull) pull=1 ;;
        *) die "неизвестный флаг $arg (есть --pull)" ;;
    esac
done

need_env
need_cmd docker "Поставьте Docker: https://docs.docker.com/engine/install/"
need_cmd curl "apt install curl"
docker compose version >/dev/null 2>&1 || die "нет docker compose v2 (плагин docker-compose-plugin)"

say "Проверяю .env"
problems=()
[ "$(stat -c %a "$ENV_FILE")" = "600" ] || { chmod 600 "$ENV_FILE"; warn ".env был доступен не только владельцу - поставил 600"; }
domain="$(env_get TLS_SERVER_NAME)"; domain="${domain%% *}"
case "$domain" in ""|localhost) problems+=("TLS_SERVER_NAME - не домен") ;; esac
[ "$(env_get HTTPS_TERMINATED)" = "1" ] || problems+=("HTTPS_TERMINATED не 1 - сайт и cookie пошли бы без шифрования")
[ "$(env_get FRONTEND_PORT)" = "80" ] || problems+=("FRONTEND_PORT не 80")
[ "$(env_get HTTPS_PORT)" = "443" ] || problems+=("HTTPS_PORT не 443")
cors="$(env_get CORS_ORIGINS)"
case ",$cors," in *",https://$domain,"*) ;; *) problems+=("CORS_ORIGINS без https://$domain - не заработает доска учителя в квизе") ;; esac
case "$cors" in *localhost*|*127.0.0.1*) problems+=("CORS_ORIGINS всё ещё пускает localhost") ;; esac
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

docker compose run --rm --no-deps --entrypoint sh certbot -c 'test -r /etc/letsencrypt/live/anyq/fullchain.pem' \
    || die "сертификата ещё нет. Сначала: bash deploy/init-tls.sh"

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
wait_service mongo 120 || die "mongo не стал healthy. docker compose logs mongo"
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
wait_healthy 600 || die "не все сервисы поднялись. docker compose ps; docker compose logs <сервис>"

say "Проверка снаружи (через nginx, под именем $domain)"
failed=0
expect() {
    local want="$1" url="$2" what="$3" got
    got="$(status_of "$url")"
    if [ "$got" = "$want" ]; then
        printf '  ok   %s  %s\n' "$got" "$what"
    else
        printf '  FAIL %s (ждали %s)  %s  %s\n' "$got" "$want" "$what" "$url"
        failed=1
    fi
}
expect 200 "https://$domain/" "сайт"
expect 401 "https://$domain/api/auth/me" "бэкенд и база (вход не выполнен)"
expect 404 "https://$domain/api/play/code/AAAAAA" "квиз-сервис"
expect 403 "https://$domain/ws/agent" "канал агента закрыт снаружи"
expect 301 "http://$domain/" "http -> https"
for host in $(env_get TLS_REDIRECT_HOSTS); do
    expect 301 "https://$host/" "$host -> $domain"
done
hsts="$(curl -sI --max-time 10 --resolve "$domain:443:127.0.0.1" ${INSECURE:+-k} "https://$domain/" | grep -ci '^strict-transport-security' || true)"
[ "$hsts" -ge 1 ] && echo "  ok   HSTS" || { echo "  FAIL нет заголовка HSTS"; failed=1; }
agent="$(docker compose exec -T backend curl -s --max-time 5 http://localhost:8000/health || true)"
case "$agent" in *'"agent":"connected"'*) echo "  ok   агент подключён к бэкенду" ;; *) echo "  FAIL агент не подключён: $agent"; failed=1 ;; esac

echo
docker compose ps --format 'table {{.Service}}\t{{.Status}}'
[ "$failed" = 0 ] || die "стек запущен, но проверки выше не прошли"
printf '\nГотово: https://%s/ (%s)\n' "$domain" "$(git rev-parse --short HEAD 2>/dev/null || echo '?')"
