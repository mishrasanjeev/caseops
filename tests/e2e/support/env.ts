import path from "node:path";

export const repoRoot = path.resolve(__dirname, "..", "..", "..");
export const runtimeRoot = path.join(repoRoot, ".e2e");
export const uploadsRoot = path.join(runtimeRoot, "uploads");
export const documentStoragePath = path.join(runtimeRoot, "documents");
export const documentCachePath = path.join(runtimeRoot, "document-cache");
export const uvCacheDir = path.join(repoRoot, ".uv-cache");
// API port is overridable via CASEOPS_E2E_API_PORT so a parallel git
// worktree can run the e2e suite without colliding with another local
// API already bound to 8000 (e.g. a second agent's dev server). Default
// is unchanged.
export const apiPort = process.env.CASEOPS_E2E_API_PORT ?? "8000";
export const webBaseUrl =
  process.env.CASEOPS_WEB_BASE_URL ?? "http://127.0.0.1:3000";
export const apiBaseUrl = `http://127.0.0.1:${apiPort}`;

function toPosixPath(targetPath: string): string {
  return targetPath.replace(/\\/g, "/");
}

const databasePath = toPosixPath(path.join(repoRoot, "caseops-e2e.db"));
const databaseUrl =
  process.env.CASEOPS_E2E_DATABASE_URL?.trim() ||
  `sqlite+pysqlite:///${databasePath}`;

export const e2eEnv: Record<string, string> = {
  CASEOPS_ENV: "e2e",
  CASEOPS_API_HOST: "127.0.0.1",
  CASEOPS_API_PORT: apiPort,
  CASEOPS_AUTO_MIGRATE: "false",
  CASEOPS_DATABASE_URL: databaseUrl,
  CASEOPS_AUTH_SECRET: "caseops-e2e-secret-caseops-e2e-secret",
  CASEOPS_PUBLIC_APP_URL: webBaseUrl,
  CASEOPS_CORS_ORIGINS: JSON.stringify([
    webBaseUrl,
    "http://localhost:3000",
    "http://127.0.0.1:3100",
    "http://localhost:3100",
  ]),
  CASEOPS_DOCUMENT_STORAGE_PATH: toPosixPath(documentStoragePath),
  CASEOPS_DOCUMENT_STORAGE_CACHE_PATH: toPosixPath(documentCachePath),
  CASEOPS_AUTH_RATE_LIMIT_ENABLED: "false",
  CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL: "platform-admin@caseops-e2e.test",
  CASEOPS_CASE_TRACKING_ENABLED: "true",
  // Synthetic E2E companies receive an explicit fixture entitlement in the
  // dated IP suite. Keep the independent rollout dimension explicit too;
  // production flags and billing state are never changed by this harness.
  CASEOPS_IP_WORKSPACE_ENABLED: "true",
  CASEOPS_IP_RULE_GOVERNANCE_ENABLED: "true",
  CASEOPS_CASE_TRACKING_PROVIDER: "ecourtsindia",
  CASEOPS_ECOURTSINDIA_API_BASE_URL: "https://provider.example",
  CASEOPS_ECOURTSINDIA_API_TOKEN: "e2e-provider-token",
  UV_CACHE_DIR: toPosixPath(uvCacheDir),
};
