export const reportedDraftTarget = {
  matterId: "7771c86f-a6d6-442f-a675-4be40622dc05",
  draftId: "3e81e0ec-e193-4be1-9f3f-b5fee1dcb4f5",
} as const;

export function productionDraftSettings(baseURL: string, env: Record<string, string | undefined>) {
  const required = (key: string) => {
    const value = env[key]?.trim();
    if (!value) throw new Error(`BUG001 production requires ${key}.`);
    return value;
  };
  const canonical = (value: string, expected: string) => {
    let url: URL;
    try { url = new URL(value); } catch { throw new Error("BUG001 production origin is invalid."); }
    if (url.origin !== expected || url.pathname !== "/" || url.username || url.password || url.search || url.hash) {
      throw new Error("BUG001 production requires canonical HTTPS origins.");
    }
    return url.origin;
  };
  const web = canonical(baseURL, "https://caseops.ai");
  const api = canonical(required("PROD_API_BASE_URL"), "https://api.caseops.ai");
  const sha = required("CASEOPS_EXPECTED_RELEASE_SHA");
  if (!/^[a-f0-9]{40}$/.test(sha)) throw new Error("BUG001 production requires an exact 40-hex serving SHA.");
  if ((env.CASEOPS_B5_DRAFT_MATTER_ID ?? reportedDraftTarget.matterId) !== reportedDraftTarget.matterId
    || (env.CASEOPS_B5_DRAFT_ID ?? reportedDraftTarget.draftId) !== reportedDraftTarget.draftId) {
    throw new Error("BUG001 production may only read the owner-reported retained draft.");
  }
  const slug = required("CASEOPS_RAM_PROD_SLUG"), email = required("CASEOPS_RAM_PROD_EMAIL");
  if (slug !== "test-legal" || email.toLowerCase() !== "ram@testfirm.com") {
    throw new Error("BUG001 production requires the actual reporting QA account.");
  }
  return { web, api, sha, slug, email, password: required("CASEOPS_RAM_PROD_PASSWORD"), ...reportedDraftTarget };
}

export function allowedProductionDraftRead(pathname: string): boolean {
  const matter = `/api/matters/${reportedDraftTarget.matterId}`;
  const draft = `${matter}/drafts/${reportedDraftTarget.draftId}`;
  return ["/api/auth/me", "/api/build", "/api/drafting/court-profiles", matter, `${matter}/drafts`,
    draft, `${draft}/compare`, `${draft}/filing-checklist`, `${draft}/export.pdf`].includes(pathname);
}

export function productionDraftRequestPolicy(value: string, method: string, marker: string | undefined, settings: { web: string; api: string }) {
  const url = new URL(value);
  if (url.protocol === "blob:") return "read";
  if (![settings.web, settings.api].includes(url.origin)) return "external";
  if (method !== "OPTIONS" && marker !== "no-paid-providers") return "blocked";
  const loginPath = url.origin === settings.api && url.pathname === "/api/auth/login";
  if (loginPath && method === "POST") return "login";
  if (loginPath && method === "OPTIONS") return "read";
  return ["GET", "HEAD", "OPTIONS"].includes(method)
    && (url.origin === settings.web || allowedProductionDraftRead(url.pathname)) ? "read" : "blocked";
}

export function citationReviewExportGuard(status: number, problem: unknown, draftStatus: string, verifiedCount: number) {
  const detail = problem && typeof problem === "object" && "detail" in problem ? problem.detail : null;
  return status === 422 && verifiedCount <= 0 && !["approved", "finalized"].includes(draftStatus)
    && typeof detail === "string" && detail.includes("zero verified citations") && detail.includes("PDF export is refused");
}

// Observe the real application's blob download handoff, but cancel native saving.
// Only a digest/size receipt leaves page memory; no PDF bytes or filename do.
export function capturePdfDownloadsInMemory() {
  const state = window as unknown as { __bug001Download: { count: number; hash: string | null; bytes: number; invalid: boolean } };
  state.__bug001Download = { count: 0, hash: null, bytes: 0, invalid: false };
  const capture = (event: MouseEvent) => {
    const anchor = event.target instanceof Element ? event.target.closest("a[download]") as HTMLAnchorElement | null : null;
    if (!anchor) return;
    event.preventDefault();
    state.__bug001Download.count++;
    state.__bug001Download.hash = null;
    if (!anchor.href.startsWith("blob:") || !anchor.download.endsWith(".pdf")) {
      state.__bug001Download.invalid = true;
      return;
    }
    void fetch(anchor.href).then(response => response.arrayBuffer()).then(async bytes => {
      const digest = await crypto.subtle.digest("SHA-256", bytes);
      state.__bug001Download.bytes = bytes.byteLength;
      state.__bug001Download.hash = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, "0")).join("");
    }).catch(() => { state.__bug001Download.invalid = true; });
  };
  document.addEventListener("click", capture, true);
  return () => document.removeEventListener("click", capture, true);
}
