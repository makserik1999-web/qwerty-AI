#!/usr/bin/env bash
# One-time setup of the server around the stack. As root, from the checkout:
#
#     sudo bash deploy/prepare-server.sh
#
# Docker itself is assumed to be there (docs/DEPLOY.md, step 1). This adds:
#   - a swap file, when there is none: building the agent image and rendering
#     with LaTeX both spike memory, and the OOM killer picks the database;
#   - the backups directory, readable by root only;
#   - the monitoring cron line.
#
# It does NOT touch the firewall, ssh or Tailscale. Nothing here needs an open
# port - the Cloudflare tunnel dials out - so ufw stays exactly as it is, and
# the stack publishes nothing but 127.0.0.1:8080.
#
# Safe to run again: each step looks before it acts.

source "$(dirname "$0")/lib.sh"

[ $# -eq 0 ] || die "флагов нет: sudo bash deploy/prepare-server.sh"
[ "$(id -u)" = 0 ] || die "нужен root: sudo bash deploy/prepare-server.sh"
need_cmd docker "Поставьте Docker: https://docs.docker.com/engine/install/debian/"
need_compose 2.24.4
need_cmd curl "apt install curl"

say "Swap"
if [ -n "$(swapon --show --noheadings 2>/dev/null)" ]; then
    echo "  уже есть: $(swapon --show --noheadings | awk '{print $1, $3}' | tr '\n' ' ')"
else
    fallocate -l 4G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=4096 status=none
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "  создан /swapfile, 4 ГБ"
fi

say "Каталог бэкапов"
backup_dir="$(env_get BACKUP_DIR 2>/dev/null || true)"; backup_dir="${backup_dir:-/var/backups/anyq}"
mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
echo "  $backup_dir (700, root)"

say "Мониторинг (cron, каждые 5 минут)"
repo="$(pwd)"
cat > /etc/cron.d/anyq-monitor <<EOF
# Akron: deploy/monitor.sh - alerts to Telegram when something breaks.
*/5 * * * * root cd $repo && bash deploy/monitor.sh >> /var/log/anyq-monitor.log 2>&1
EOF
chmod 644 /etc/cron.d/anyq-monitor
cat > /etc/logrotate.d/anyq-monitor <<'EOF'
/var/log/anyq-monitor.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
}
EOF
echo "  /etc/cron.d/anyq-monitor -> /var/log/anyq-monitor.log"

cat <<'EOF'

Сервер готов. Фаервол, ssh и Tailscale не трогал.
Проверить тревоги (когда TELEGRAM_* в .env заполнены):
    bash deploy/monitor.sh --test
EOF
