export function requireFixtureDatabaseUrl(databaseUrl: string, allowedSqliteUrl: string): void {
  if (allowedSqliteUrl && databaseUrl === allowedSqliteUrl) return;
  let database: URL;
  try {
    database = new URL(databaseUrl);
  } catch {
    throw new Error("Fixture database URL is invalid.");
  }
  if (database.protocol !== "postgresql+psycopg:"
    || !["127.0.0.1", "localhost", "[::1]"].includes(database.hostname)
    || database.search !== "" || database.hash !== ""
    || !/^\/[a-zA-Z0-9_]+$/.test(database.pathname)) {
    throw new Error("Fixtures require loopback PostgreSQL without connection overrides, or the owned SQLite database.");
  }
}
