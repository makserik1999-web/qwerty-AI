#!/bin/sh
# Decide what the site listens on, before nginx renders its templates.
#
# The nginx image runs everything in /docker-entrypoint.d in name order and
# 20-envsubst-on-templates.sh does the rendering, so 15- here lands first and
# whatever it writes is in place by the time the config is read.
#
# Two files come out of this:
#
#   listen.inc   - included by the one server block in nginx.conf.template.
#                  Plain HTTP listens on 3000; TLS listens on 3443 with the
#                  certificate. Kept as an include because the whole site
#                  config below that line has to be identical either way, and
#                  a second copy of it would drift - while an `ssl_certificate`
#                  pointing at a file that is not mounted stops nginx dead, so
#                  it cannot simply always be there.
#
#   redirect.conf - only under TLS: answers plain HTTP with a 301, so that
#                  typing http:// does not quietly serve the whole site in
#                  clear text.
#
# HTTPS_TERMINATED=1 turns it on. Off is the default, because this stack is
# normally run on localhost where there is no certificate to serve.

set -eu

CONF_D=/etc/nginx/conf.d
CERT_DIR="${TLS_CERT_DIR:-/etc/nginx/certs}"
CERT="${CERT_DIR}/fullchain.pem"
KEY="${CERT_DIR}/privkey.pem"

mkdir -p "$CONF_D"

if [ "${HTTPS_TERMINATED:-0}" != "1" ]; then
    printf 'listen 3000;\n' > "$CONF_D/listen.inc"
    rm -f "$CONF_D/redirect.conf"
    echo "anyq: serving plain HTTP on 3000 (HTTPS_TERMINATED is not 1)"
    exit 0
fi

# Fail loudly rather than falling back to HTTP. Starting in clear text because
# a certificate was missing is the one outcome nobody would notice: the site
# would come up, work, and be unencrypted.
if [ ! -r "$CERT" ] || [ ! -r "$KEY" ]; then
    echo "anyq: HTTPS_TERMINATED=1 but no readable certificate at ${CERT_DIR}" >&2
    echo "anyq: mount fullchain.pem and privkey.pem there, or run" >&2
    echo "anyq:   bash scripts/make_dev_cert.sh    (self-signed, local testing)" >&2
    exit 1
fi

cat > "$CONF_D/listen.inc" <<EOF
listen 3443 ssl;
http2 on;

ssl_certificate     ${CERT};
ssl_certificate_key ${KEY};

# TLS 1.2 and 1.3 only. Everything older has a published attack against it,
# and nothing that can reach this site is too old to speak 1.2.
ssl_protocols TLSv1.2 TLSv1.3;
ssl_prefer_server_ciphers off;
ssl_session_cache shared:anyq_tls:10m;
ssl_session_timeout 1d;
ssl_session_tickets off;
EOF

# \$host and \$request_uri are nginx's, not the shell's - this heredoc is
# quoted so they survive, and envsubst leaves them alone because it only
# substitutes names that are actually in the environment.
cat > "$CONF_D/redirect.conf" <<'EOF'
server {
    listen 3000;
    server_name _;

    # Let's Encrypt proves the domain over plain HTTP: it fetches a token that
    # certbot left in this shared directory. A file it asked for, not site
    # content - and the one thing answered here rather than redirected, so a
    # renewal does not depend on the HTTPS side being healthy.
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/acme;
        default_type text/plain;
    }

    # A permanent redirect and nothing else. No content is ever served over
    # plain HTTP once TLS is on.
    location / {
        return 301 https://$host__HTTPS_PORT_SUFFIX__$request_uri;
    }
}
EOF

# The public HTTPS port, if it is not 443. $host carries no port, so without
# this the redirect from a stack published on, say, 3443 would point at a port
# nothing is listening on.
sed -i "s|__HTTPS_PORT_SUFFIX__|${TLS_PUBLIC_PORT_SUFFIX:-}|" "$CONF_D/redirect.conf"

echo "anyq: serving HTTPS on 3443, redirecting 3000 -> https://\$host${TLS_PUBLIC_PORT_SUFFIX:-}"

# Other names for the same site - www.<domain> - answered with a 301 to the
# first name in TLS_SERVER_NAME, over HTTPS too. Without it www would serve
# the whole site under a second origin: a second session cookie, and an Origin
# that the backend's and the quiz board's CORS_ORIGINS do not list.
if [ -n "${TLS_REDIRECT_HOSTS:-}" ]; then
    canonical="${TLS_SERVER_NAME%% *}"
    cat >> "$CONF_D/redirect.conf" <<EOF

server {
    listen 3443 ssl;
    http2 on;
    server_name ${TLS_REDIRECT_HOSTS};

    ssl_certificate     ${CERT};
    ssl_certificate_key ${KEY};

    return 301 https://${canonical}${TLS_PUBLIC_PORT_SUFFIX:-}\$request_uri;
}
EOF
    echo "anyq: redirecting ${TLS_REDIRECT_HOSTS} -> https://${canonical}${TLS_PUBLIC_PORT_SUFFIX:-}"
fi

# certbot renews the certificate in place, but nginx read it once, at start,
# and would go on serving the old one until it expired. So it is looked at
# every hour and nginx reloads when it changed. A reload is graceful: open
# connections - a class's quiz sockets included - finish on the old workers.
(
    stamp() { cksum "$CERT" "$KEY" 2>/dev/null || true; }
    last="$(stamp)"
    while sleep "${TLS_RELOAD_CHECK_SEC:-3600}"; do
        now="$(stamp)"
        if [ -n "$now" ] && [ "$now" != "$last" ]; then
            echo "anyq: certificate changed on disk, reloading nginx"
            nginx -s reload && last="$now"
        fi
    done
) </dev/null &
