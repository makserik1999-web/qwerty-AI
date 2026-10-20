#!/usr/bin/env bash
# Backups, inside the mongo:7 image (docker-compose.prod.yml, services
# "backup" and "restore"). Not meant to be run on the host.
#
#   loop            the service: a dump now if the last one is a day old,
#                   then one every night at BACKUP_HOUR_UTC
#   once            one dump now                  (deploy/backup-now.sh)
#   check           healthcheck: a dump finished within 26 hours
#   restore NAME    put a dump back, and the videos (deploy/restore.sh)
#
# What is kept, under /backups (BACKUP_DIR on the host):
#
#   mongo/anyq-<UTC time>.archive.gz   mongodump of the one database, kept
#                                      BACKUP_KEEP_DAYS days
#   media/outputs/                     the rendered videos, mirrored
#   media-removed/<date>/              videos gone from the site since the
#                                      last run, kept as long as the dumps
#
# The videos are a mirror rather than a dated copy each night: each one is
# written once and never changed, so a nightly copy would store the same
# files again and again. What does change is that a deleted account takes its
# videos with it - and those leave the mirror on the next run, kept aside only
# as long as the dumps that still mention them.

set -euo pipefail

DB="${DATABASE_NAME:-anyq_db}"
URI="${BACKUP_MONGO_URI:?BACKUP_MONGO_URI is not set}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
HOUR="${BACKUP_HOUR_UTC:-21}"
ROOT=/backups
DUMPS="$ROOT/mongo"
MIRROR="$ROOT/media/outputs"
REMOVED="$ROOT/media-removed"
VIDEOS=/media/outputs
MAX_AGE_SEC=$((26 * 3600))

log() { echo "anyq-backup $(date -u +%FT%TZ) $*"; }

newest_dump() {
    find "$DUMPS" -maxdepth 1 -name 'anyq-*.archive.gz' -printf '%T@ %p\n' 2>/dev/null \
        | sort -n | tail -1 | cut -d' ' -f2-
}

dump_age_sec() {
    local newest
    newest="$(newest_dump)"
    [ -n "$newest" ] || { echo 999999999; return; }
    echo $(( $(date +%s) - $(stat -c %Y "$newest") ))
}

backup_db() {
    mkdir -p "$DUMPS"
    local name partial
    name="anyq-$(date -u +%Y%m%d-%H%M%S).archive.gz"
    # Written under another name and renamed when complete, so a dump cut
    # short by a restart is never the newest "backup" anything trusts.
    partial="$DUMPS/.$name.partial"
    # Every step checked by hand: this runs inside `run_once || ...`, where
    # bash switches set -e off for everything the function calls.
    if ! mongodump --uri="$URI" --db="$DB" --archive="$partial" --gzip --quiet; then
        rm -f "$partial"
        log "database: mongodump FAILED"
        return 1
    fi
    mv "$partial" "$DUMPS/$name" || return 1
    # --apparent-size: on some bind mounts du counts blocks and says 0.
    log "database: $name ($(du -h --apparent-size "$DUMPS/$name" | cut -f1))"
}

backup_media() {
    # The agent creates it with the first video, so a new server has none.
    [ -d "$VIDEOS" ] || { log "media: no videos yet"; return 0; }
    mkdir -p "$MIRROR"
    # -n: never rewrite a file that is already there; timestamps kept so the
    # mirror says when a video was made, not when it was copied.
    find "$VIDEOS" -maxdepth 1 -type f -exec cp -n --preserve=timestamps -t "$MIRROR" {} + || return 1
    local today moved=0 file
    today="$(date -u +%Y%m%d)"
    for file in "$MIRROR"/*; do
        [ -f "$file" ] || continue
        if [ ! -e "$VIDEOS/${file##*/}" ]; then
            mkdir -p "$REMOVED/$today"
            mv "$file" "$REMOVED/$today/"
            moved=$((moved + 1))
        fi
    done
    log "media: $(find "$MIRROR" -maxdepth 1 -type f | wc -l) videos mirrored, $moved set aside"
}

prune() {
    # Only after a dump has succeeded, so a run of failures never deletes
    # the last good copies.
    find "$DUMPS" -maxdepth 1 -name 'anyq-*.archive.gz' -mtime +"$KEEP_DAYS" -print -delete \
        | sed 's/^/anyq-backup pruned /'
    find "$DUMPS" -maxdepth 1 -name '.*.partial' -mmin +360 -delete
    [ -d "$REMOVED" ] && find "$REMOVED" -mindepth 1 -maxdepth 1 -type d -mtime +"$KEEP_DAYS" \
        -exec rm -rf {} + || true
}

run_once() {
    backup_db || return 1
    backup_media || log "media: copy FAILED"
    prune
}

seconds_until_next() {
    local now next
    now="$(date -u +%s)"
    next="$(date -u -d "today ${HOUR}:00" +%s)"
    [ "$next" -gt "$now" ] || next="$(date -u -d "tomorrow ${HOUR}:00" +%s)"
    echo $((next - now))
}

case "${1:-loop}" in
    once)
        run_once
        ;;
    check)
        age="$(dump_age_sec)"
        if [ "$age" -le "$MAX_AGE_SEC" ]; then
            echo "last dump $((age / 3600))h ago"
        else
            echo "no dump in the last 26 hours"
            exit 1
        fi
        ;;
    loop)
        trap 'exit 0' TERM INT
        log "keeping ${KEEP_DAYS} days, nightly at ${HOUR}:00 UTC"
        # A fresh server, or one that was down over the backup hour, gets a
        # dump now rather than up to a day later.
        if [ "$(dump_age_sec)" -gt $((23 * 3600)) ]; then
            run_once || log "FAILED - retrying at the next scheduled hour"
        fi
        while :; do
            sleep "$(seconds_until_next)" & wait $!
            run_once || log "FAILED - retrying at the next scheduled hour"
        done
        ;;
    restore)
        name="${2:?which dump? deploy/restore.sh lists them}"
        archive="$DUMPS/${name##*/}"
        [ -f "$archive" ] || { echo "no such dump: $archive" >&2; exit 1; }
        log "restoring the database from ${archive##*/}"
        # --drop: each collection is replaced, not merged into - a merge of
        # a backup into newer data is neither the backup nor the data.
        mongorestore --uri="$URI" --nsInclude="${DB}.*" --archive="$archive" --gzip --drop --quiet
        log "database restored"
        if [ -d "$MIRROR" ] || [ -d "$REMOVED" ]; then
            # The services run as uid 10001 and the agent writes new videos
            # here; a new server's volume may not have the directory yet.
            owner="$(stat -c %u:%g "$VIDEOS" 2>/dev/null || true)"
            [ -n "$owner" ] && [ "$owner" != "0:0" ] || owner="10001:10001"
            mkdir -p "$VIDEOS"
            chown "$owner" "$VIDEOS"
            before="$(find "$VIDEOS" -maxdepth 1 -type f | wc -l)"
            # The set-aside videos as well as the mirror: the backup taken just
            # before a restore moves whatever is missing from the site out of
            # the mirror - and what is missing is often what the restore is for.
            for source in "$MIRROR" "$REMOVED"/*/; do
                [ -d "$source" ] || continue
                find "$source" -maxdepth 1 -type f -exec cp -n --preserve=timestamps -t "$VIDEOS" {} +
            done
            # Handed back to whoever owns the directory - the services run as
            # that user and must be able to read, and the agent to replace.
            find "$VIDEOS" -maxdepth 1 -type f -user 0 -exec chown "$owner" {} +
            after="$(find "$VIDEOS" -maxdepth 1 -type f | wc -l)"
            log "media: $((after - before)) videos put back"
        fi
        ;;
    *)
        echo "usage: backup.sh loop|once|check|restore NAME" >&2
        exit 2
        ;;
esac
