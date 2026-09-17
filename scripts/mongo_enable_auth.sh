#!/usr/bin/env bash
# Turn on MongoDB authentication without losing the data already in it.
#
# WHY THIS SCRIPT EXISTS AT ALL
#
# The official mongo image creates MONGO_INITDB_ROOT_USERNAME only when the
# data directory is EMPTY. This deployment's volume is not - it holds the real
# chats, users and library - so adding those variables to compose and
# restarting would start `mongod --auth` against a database with no users in
# it, and every service would be locked out at once.
#
# So the users have to be created while authentication is still off, and only
# then may --auth be switched on. That is the whole of this script: create the
# users now, print what to do next.
#
# Run it from the repository root with the stack up:
#
#     bash scripts/mongo_enable_auth.sh
#
# It is safe to run twice: an existing user is reported and left alone.

set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE=".env"
DB_NAME="$(grep -E '^DATABASE_NAME=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)"
DB_NAME="${DB_NAME:-anyq_db}"

# Alphanumeric on purpose. A password with @ : / or ? in it has to be
# percent-encoded inside a mongodb:// URI, and a half-encoded URI fails in a
# way that reads like a wrong password. Length carries the entropy instead.
gen_password() {
  python -c "import secrets, string; a=string.ascii_letters+string.digits; print(''.join(secrets.choice(a) for _ in range(40)))"
}

# Read a value from .env, or create it with a fresh password and append it.
ensure_var() {
  local key="$1" value
  value="$(grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)"
  if [ -z "$value" ]; then
    value="$2"
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
    echo "  .env: added ${key}" >&2
  else
    echo "  .env: ${key} already set, keeping it" >&2
  fi
  printf '%s' "$value"
}

echo "Reading credentials from ${ENV_FILE} (creating what is missing)..." >&2
ROOT_USER="$(ensure_var MONGO_ROOT_USER anyq_root)"
ROOT_PASSWORD="$(ensure_var MONGO_ROOT_PASSWORD "$(gen_password)")"
APP_USER="$(ensure_var MONGO_APP_USER anyq_app)"
APP_PASSWORD="$(ensure_var MONGO_APP_PASSWORD "$(gen_password)")"

echo "Creating users in the running mongo (authentication still off)..." >&2

# Passed through the environment rather than interpolated into the script
# text, so a password never reaches a process listing or a shell history.
MSYS_NO_PATHCONV=1 docker compose exec -T \
  -e ROOT_USER="$ROOT_USER" -e ROOT_PASSWORD="$ROOT_PASSWORD" \
  -e APP_USER="$APP_USER" -e APP_PASSWORD="$APP_PASSWORD" -e DB_NAME="$DB_NAME" \
  mongo mongosh --quiet --eval '
    const rootUser = process.env.ROOT_USER;
    const appUser  = process.env.APP_USER;
    const dbName   = process.env.DB_NAME;

    function ensure(database, user, password, roles) {
      const existing = database.getUser(user);
      if (existing) {
        print("  " + user + ": already exists, left alone");
        return;
      }
      database.createUser({user: user, pwd: password, roles: roles});
      print("  " + user + ": created");
    }

    // Administration only. No service ever connects as this.
    ensure(db.getSiblingDB("admin"), rootUser, process.env.ROOT_PASSWORD,
           [{role: "root", db: "admin"}]);

    // What the backend and the exporter actually use: read and write one
    // database, and nothing else. Index creation is part of readWrite, so
    // the lifespan that builds indexes on startup still works.
    ensure(db.getSiblingDB(dbName), appUser, process.env.APP_PASSWORD,
           [{role: "readWrite", db: dbName}]);
  '

cat >&2 <<'NEXT'

Users are in place. Now enable authentication:

    docker compose up -d --force-recreate mongo backend exporter

docker-compose.yml already passes --auth and builds MONGO_URL from the
credentials above, so this is the step that starts enforcing it. Check it
took with:

    docker compose exec -T mongo mongosh --quiet --eval "db.adminCommand('ping')"

That must now FAIL with "command ping requires authentication". If it still
succeeds, authentication is not on and nothing was gained.
NEXT
