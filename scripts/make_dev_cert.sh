#!/usr/bin/env bash
# A self-signed certificate, for testing that the HTTPS path works at all.
#
# NOT for anything anyone else connects to. A browser will warn about it, and
# it should - nothing vouches for it. Its whole purpose is to let the TLS
# configuration be exercised on a machine with no domain name: that the site
# comes up on 3443, that plain HTTP redirects, that the cookie gets its Secure
# flag and the websocket still connects over wss.
#
# For a real deployment, put the real files at the same two names:
#
#     frontend/certs/fullchain.pem     certificate + intermediate chain
#     frontend/certs/privkey.pem       private key
#
# certbot writes exactly those two names under
# /etc/letsencrypt/live/<domain>/, so a real certificate is a bind mount and
# no configuration change.

set -euo pipefail

cd "$(dirname "$0")/.."

DIR="frontend/certs"
DOMAIN="${1:-localhost}"

mkdir -p "$DIR"

if [ -f "$DIR/privkey.pem" ] && [ -f "$DIR/fullchain.pem" ]; then
    echo "Certificate already present in ${DIR}/ - leaving it alone." >&2
    echo "Delete the two .pem files first if you want a new one." >&2
    exit 0
fi

if ! command -v openssl >/dev/null 2>&1; then
    echo "openssl is not on PATH. Git for Windows ships one at" >&2
    echo "  C:/Program Files/Git/usr/bin/openssl.exe" >&2
    exit 1
fi

# subjectAltName, not just CN: every current browser ignores the Common Name
# and will refuse a certificate that does not name the host in a SAN.
#
# MSYS_NO_PATHCONV: on Git Bash, an argument that starts with a slash is taken
# for a unix path and rewritten to a Windows one, so `-subj /CN=localhost`
# reaches openssl as `C:/Program Files/Git/CN=localhost` and the command
# fails. It is an unused variable everywhere else.
MSYS_NO_PATHCONV=1 openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
    -keyout "$DIR/privkey.pem" \
    -out "$DIR/fullchain.pem" \
    -subj "/CN=${DOMAIN}" \
    -addext "subjectAltName=DNS:${DOMAIN},DNS:localhost,IP:127.0.0.1"

chmod 600 "$DIR/privkey.pem"

cat >&2 <<NEXT

Self-signed certificate for '${DOMAIN}' written to ${DIR}/.
It is gitignored - a private key must never reach the repository.

To serve over it, put these in .env:

    HTTPS_TERMINATED=1
    TLS_SERVER_NAME=${DOMAIN}
    HTTPS_PORT=3443
    TLS_PUBLIC_PORT_SUFFIX=:3443
    CORS_ORIGINS=https://${DOMAIN}:3443

then:

    docker compose up -d --force-recreate frontend backend

and open https://${DOMAIN}:3443/ - the browser will warn, which is correct
for a certificate nobody vouched for. COOKIE_SECURE follows HTTPS_TERMINATED
automatically, so the session cookie gets its Secure flag with no second
switch to remember.
NEXT
