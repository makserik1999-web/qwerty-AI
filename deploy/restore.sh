#!/usr/bin/env bash
# Put a backup back.
#
#     bash deploy/restore.sh                         the dumps there are
#     bash deploy/restore.sh anyq-20261004-210000.archive.gz
#
# REPLACES the database with the dump - every collection in it, as it was at
# that moment; whatever happened since is gone. Videos are copied back from
# the mirror and from the set-aside ones, never over a video still there.
#
# The services that write to the database are stopped for the duration, so
# nothing lands in it halfway through and gets wiped by the next collection.
#
# To move a database here from another machine: put its .archive.gz into
# $BACKUP_DIR/mongo/ (and its videos into $BACKUP_DIR/media/outputs/), then
# run this.

source "$(dirname "$0")/lib.sh"

need_env
backup_dir="$(env_get BACKUP_DIR)"; backup_dir="${backup_dir:-/var/backups/anyq}"

if [ $# -eq 0 ]; then
    echo "Бэкапы базы в $backup_dir/mongo (новые внизу):"
    ls -1tr "$backup_dir/mongo" 2>/dev/null | grep -E '^anyq-.*\.archive\.gz$' | sed 's/^/  /' || echo "  (нет)"
    echo
    echo "Восстановить: bash deploy/restore.sh <имя файла>"
    exit 0
fi

name="${1##*/}"
[ -f "$backup_dir/mongo/$name" ] || die "нет файла $backup_dir/mongo/$name"
domain="$(env_get TLS_SERVER_NAME)"; domain="${domain%% *}"

cat <<EOF

База будет ЗАМЕНЕНА содержимым $name.
Всё, что появилось на сайте после этого бэкапа, пропадёт.
На время восстановления сайт перестанет отвечать.

EOF
read -r -p "Для подтверждения введите домен ($domain): " answer
[ "$answer" = "$domain" ] || die "отменено"

say "Сначала бэкап того, что есть сейчас - на случай, если восстановили не то"
docker compose exec -T backup bash /opt/anyq/backup.sh once \
    || die "свежий бэкап не получился - восстанавливать поверх без него не стану"

say "Останавливаю сервисы, которые пишут в базу"
docker compose stop agent backend quiz exporter

say "Восстанавливаю"
restore_ok=1
docker compose run --rm restore restore "$name" || restore_ok=0

say "Запускаю обратно"
docker compose up -d
wait_healthy 600 || warn "не все сервисы поднялись - docker compose ps"
[ "$restore_ok" = 1 ] || die "mongorestore не прошёл (сервисы запущены снова). Смотрите вывод выше."
echo
echo "Восстановлено из $name."
