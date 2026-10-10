#!/bin/sh
# Decide what the site listens on, and whose word to take for the client's
# address - before nginx renders its templates.
#
# The nginx image runs everything in /docker-entrypoint.d in name order and
# 20-envsubst-on-templates.sh does the rendering, so 15- here lands first and
# whatever it writes is in place by the time the config is read.
#
# Two files come out of this, both included by the one server block in
# nginx.conf.template:
#
#   listen.inc   - `listen ${NGINX_PORT};` - 3000 in development, 80 behind
#                  the Cloudflare tunnel (docker-compose.prod.yml).
#
#   real_ip.inc  - empty, unless TRUST_CF_CONNECTING_IP=1. Then nginx takes
#                  the client's address from Cloudflare's CF-Connecting-IP,
#                  but only from a peer on a private network - cloudflared,
#                  next to it in docker. Without this every request arrives
#                  from cloudflared's address, and the per-IP limits (sign-up,
#                  sign-in, quiz joins) would count the whole internet as one
#                  client. Off in development: there anybody could put any
#                  address in that header.
#
# TLS is not here at all. In production Cloudflare terminates it at the edge
# and the tunnel brings plain HTTP to port 80; the session cookie gets its
# Secure flag from COOKIE_SECURE on the backend, not from anything nginx does.

set -eu

CONF_D=/etc/nginx/conf.d
PORT="${NGINX_PORT:-3000}"

mkdir -p "$CONF_D"

case "$PORT" in
    ''|*[!0-9]*)
        echo "anyq: NGINX_PORT must be a port number, got '${PORT}'" >&2
        exit 1
        ;;
esac
printf 'listen %s;\n' "$PORT" > "$CONF_D/listen.inc"

# Left over from the TLS setup this replaced; an old file here would put a
# second server on the port.
rm -f "$CONF_D/redirect.conf"

if [ "${TRUST_CF_CONNECTING_IP:-0}" = "1" ]; then
    cat > "$CONF_D/real_ip.inc" <<'EOF'
real_ip_header CF-Connecting-IP;
set_real_ip_from 10.0.0.0/8;
set_real_ip_from 172.16.0.0/12;
set_real_ip_from 192.168.0.0/16;
set_real_ip_from 127.0.0.1;
EOF
    echo "anyq: HTTP on ${PORT}, client address from CF-Connecting-IP"
else
    : > "$CONF_D/real_ip.inc"
    echo "anyq: HTTP on ${PORT}"
fi
