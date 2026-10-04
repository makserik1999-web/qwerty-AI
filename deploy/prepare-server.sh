#!/usr/bin/env bash
# One-time setup of the server around the stack. As root, from the checkout:
#
#     sudo bash deploy/prepare-server.sh
#
# Docker itself is assumed to be there (docs/DEPLOY.md, step 1). This adds:
#   - a swap file, when there is none: building the agent image and rendering
#     with LaTeX both spike memory, and the OOM killer picks the database;
#   - the backups directory, readable by root only;
#   - the monitoring cron line;
#   - the firewall (ufw): ssh, 80 and 443 - only when asked, with --firewall,
#     because a firewall switched on over ssh is how people lock themselves out.
#
# Safe to run again: each step looks before it acts.

source "$(dirname "$0")/lib.sh"

firewall=0
for arg in "$@"; do
    case "$arg" in
        --firewall) firewall=1 ;;
        *) die "неизвестный флаг $arg (есть --firewall)" ;;
    esac
done

[ "$(id -u)" = 0 ] || die "нужен root: sudo bash deploy/prepare-server.sh"
need_cmd docker "Поставьте Docker: https://docs.docker.com/engine/install/ (раздел для вашего дистрибутива)"
docker compose version >/dev/null 2>&1 || die "нет docker compose v2: apt install docker-compose-plugin"
need_cmd curl "apt install curl"
command -v openssl >/dev/null 2>&1 || warn "нет openssl - мониторинг не сможет проверять срок сертификата (apt install openssl)"

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
# Anyq: deploy/monitor.sh - alerts to Telegram when something breaks.
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

say "Фаервол"
if [ "$firewall" = 1 ]; then
    need_cmd ufw "apt install ufw"
    # The port this very session came in on, so it stays open whatever it is.
    ssh_port="$(printf '%s' "${SSH_CONNECTION:-}" | awk '{print $4}')"
    ssh_port="${ssh_port:-22}"
    ufw allow "$ssh_port/tcp" >/dev/null
    ufw allow 80/tcp >/dev/null
    ufw allow 443/tcp >/dev/null
    ufw --force enable >/dev/null
    echo "  открыты: $ssh_port (ssh), 80, 443"
    # Docker publishes ports past ufw's rules, which is why the stack
    # publishes only 80 and 443 and nothing else - mongo is not on the host.
else
    echo "  не трогаю. Чтобы открыть только ssh, 80 и 443: sudo bash deploy/prepare-server.sh --firewall"
fi

cat <<'EOF'

Сервер готов. Проверить тревоги (когда TELEGRAM_* в .env заполнены):
    bash deploy/monitor.sh --test
EOF
