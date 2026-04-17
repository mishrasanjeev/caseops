import path from "node:path";

export const repoRoot = path.resolve(__dirname, "..", "..", "..");
export const runtimeRoot = path.join(repoRoot, ".e2e");
export const uploadsRoot = path.join(runtimeRoot, "uploads");
export const documentStoragePath = path.join(runtimeRoot, "documents");
export const documentCachePath = path.join(runtimeRoot, "document-cache");
export const uvCacheDir = path.join(repoRoot, ".uv-cache");
export const webBaseUrl = "http://127.0.0.1:3000";
export const apiBaseUrl = "http://127.0.0.1:8000";

function toPosixPath(targetPath: string): string {
  return targetPath.replace(/\\/g, "/");
}

const databasePath = toPosixPath(path.join(repoRoot, "caseops-e2e.db"));

export const e2eEnv: Record<string, string> = {
  CASEOPS_ENV: "e2e",
  CASEOPS_API_HOST: "127.0.0.1",
  CASEOPS_API_PORT: "8000",
  CASEOPS_AUTO_MIGRATE: "false",
  CASEOPS_DATABASE_URL: `sqlite+pysqlite:///${databasePath}`,
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
  UV_CACHE_DIR: toPosixPath(uvCacheDir),
};
