#!/usr/bin/env bash
# The first certificate, from Let's Encrypt. Renewals after that are the
# certbot service's job, and need nothing from here.
#
#     bash deploy/init-tls.sh            the real certificate
#     bash deploy/init-tls.sh --staging  a test one first (not trusted by
#                                        browsers; no rate limit to burn)
#     bash deploy/init-tls.sh --force    replace an existing one - after
#                                        --staging, or when the names change
#
# Running it agrees to the Let's Encrypt Subscriber Agreement on the server
# owner's behalf (https://letsencrypt.org/repository/).
#
# The chicken and egg: with HTTPS_TERMINATED=1 the frontend refuses to start
# without a certificate (on purpose - see docker-entrypoint.d/15-anyq-tls.sh),
# and Let's Encrypt will not issue one without a running site to check. So the
# site is brought up once on plain HTTP, certbot proves the domain through it,
# and then the stack is switched to HTTPS.

source "$(dirname "$0")/lib.sh"

staging=""
force=""
for arg in "$@"; do
    case "$arg" in
        --staging) staging="--staging" ;;
        --force) force="--force-renewal" ;;
        *) die "неизвестный флаг $arg (есть --staging и --force)" ;;
    esac
done

need_env
need_cmd docker "Поставьте Docker: https://docs.docker.com/engine/install/"
need_cmd curl "apt install curl"

domain="$(env_get TLS_SERVER_NAME)"
domain="${domain%% *}"
aliases="$(env_get TLS_REDIRECT_HOSTS)"
email="$(env_get LETSENCRYPT_EMAIL)"
case "$domain" in ""|localhost) die "TLS_SERVER_NAME в .env - не домен ('$domain')" ;; esac

say "DNS"
mine="$(hostname -I 2>/dev/null || true)"
for host in $domain $aliases; do
    ips="$(getent ahostsv4 "$host" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ' || true)"
    [ -n "$ips" ] || die "у $host нет A-записи. Добавьте её у регистратора (на IP этого сервера) и подождите, пока обновится. Если www не нужен - очистите TLS_REDIRECT_HOSTS в .env."
    echo "  $host -> $ips"
    for ip in $ips; do
        case " $mine " in
            *" $ip "*) ;;
            *) warn "$ip нет среди адресов этого сервера ($mine). Если сервер не за NAT - запись указывает не сюда, и проверка не пройдёт." ;;
        esac
    done
done

say "Поднимаю сайт по HTTP - только на время проверки"
HTTPS_TERMINATED=0 docker compose up -d --build frontend
for _ in $(seq 1 60); do
    [ "$(status_of "http://$domain/")" = "200" ] && break
    sleep 3
done
[ "$(status_of "http://$domain/")" = "200" ] || die "сайт не ответил по HTTP на этом сервере. docker compose logs frontend"

say "Проверяю путь, по которому придёт Let's Encrypt"
token="anyq-selftest-$(date +%s)"
docker compose run --rm --no-deps --entrypoint sh certbot -c \
    "mkdir -p /var/www/acme/.well-known/acme-challenge && echo ok > /var/www/acme/.well-known/acme-challenge/$token"
local_answer="$(curl -s --max-time 10 --resolve "$domain:80:127.0.0.1" "http://$domain/.well-known/acme-challenge/$token" || true)"
[ "$local_answer" = "ok" ] || die "nginx не отдаёт /.well-known/acme-challenge/ - образ frontend старый? docker compose build frontend"
public_answer="$(curl -s --max-time 10 "http://$domain/.well-known/acme-challenge/$token" || true)"
[ "$public_answer" = "ok" ] \
    || warn "снаружи по http://$domain/ ответ не пришёл. Открыт ли порт 80 в фаерволе сервера и у хостера?"
docker compose run --rm --no-deps --entrypoint sh certbot -c "rm -f /var/www/acme/.well-known/acme-challenge/$token"

say "Получаю сертификат${staging:+ (staging, тестовый)}"
names=(-d "$domain")
for host in $aliases; do names+=(-d "$host"); done
# No address, no flag: certbot 5 registers without one in --non-interactive
# mode, and the old --register-unsafely-without-email is hidden from its help.
contact=()
[ -z "$email" ] || contact=(--email "$email")
# --cert-name anyq: the files land in live/anyq/ whatever the domain, which is
# the path docker-compose.prod.yml gives nginx.
docker compose run --rm --no-deps --entrypoint certbot certbot certonly \
    --webroot -w /var/www/acme --cert-name anyq "${names[@]}" ${contact[@]+"${contact[@]}"} \
    --agree-tos --no-eff-email --non-interactive --keep-until-expiring \
    ${staging:+"$staging"} ${force:+"$force"} ${staging:+--break-my-certs}

say "Включаю HTTPS"
# The backend too: it was started above with HTTPS_TERMINATED=0, which is what
# gives the session cookie its Secure flag.
docker compose up -d backend frontend
for _ in $(seq 1 40); do
    [ "$(INSECURE=${staging:+1} status_of "https://$domain/")" = "200" ] && break
    sleep 3
done
code="$(INSECURE=${staging:+1} status_of "https://$domain/")"
[ "$code" = "200" ] || die "https://$domain/ ответил $code. docker compose logs frontend"

cat <<EOF

Сертификат на месте, https://$domain/ отвечает.
${staging:+Это ТЕСТОВЫЙ сертификат: браузер ему не поверит. Когда всё работает - bash deploy/init-tls.sh --force
}Продлевать будет сервис certbot, сам. Дальше: bash deploy/deploy.sh
EOF
