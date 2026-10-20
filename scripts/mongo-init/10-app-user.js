// The application's database user, on a FRESH install.
//
// The mongo image creates MONGO_INITDB_ROOT_USERNAME when the data directory
// is empty, and then runs whatever is in /docker-entrypoint-initdb.d - this
// file - as that root user. It creates the root and nothing else, so before
// this existed a fresh server came up with no anyq_app: the backend, the quiz
// service and the exporter all log in as that user, all of them were refused,
// and the site never started. scripts/mongo_enable_auth.sh covers the other
// case - a volume that already has data in it, where this never runs.
//
// Runs once per data directory, like everything in initdb.d. The passwords
// come from the environment, never from this file.

const dbName = process.env.MONGO_INITDB_DATABASE || "anyq_db";
const user = process.env.MONGO_APP_USER;
const password = process.env.MONGO_APP_PASSWORD;

if (!user || !password) {
  // Loud rather than skipped: a database no service can log in to looks like
  // it worked. deploy/deploy.sh checks for this user on every deploy as well,
  // so once .env is fixed the next deploy creates it.
  print("anyq: MONGO_APP_USER / MONGO_APP_PASSWORD are empty - set them in .env");
  quit(1);
}

const target = db.getSiblingDB(dbName);
if (target.getUser(user)) {
  print("anyq: " + user + " already exists, left alone");
} else {
  target.createUser({ user: user, pwd: password, roles: [{ role: "readWrite", db: dbName }] });
  print("anyq: created " + user + " with readWrite on " + dbName);
}
