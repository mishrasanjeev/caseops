import { API_BASE_URL } from "@/lib/api/config";
import { fetchJsonWithTimeout } from "@/lib/api/client";
import { forwardedRateHeaders, READINESS_TARGET } from "@/lib/server/rate-identity";

const unavailable = () => Response.json({ ready: false, provenance: "unavailable",
  release_sha: /^[0-9a-f]{40}$/.test(process.env.CASEOPS_RELEASE_SHA ?? "") ? process.env.CASEOPS_RELEASE_SHA : "unavailable" },
  { status: 503, headers: { "Cache-Control": "no-store" } });

export async function GET(request: Request) {
  try {
    const headers = forwardedRateHeaders(request.headers, "GET", READINESS_TARGET);
    if (!headers["x-caseops-rate-signature"]) return unavailable();
    if (request.headers.get("x-caseops-automated-test") === "no-paid-providers") {
      headers["X-CaseOps-Automated-Test"] = "no-paid-providers";
    }
    const response = await fetchJsonWithTimeout(`${process.env.CASEOPS_API_BASE_URL ?? API_BASE_URL}${READINESS_TARGET}`,
      { method: "GET", headers, cache: "no-store", credentials: "omit", redirect: "error" }, 10_000);
    const data = response.data as Record<string, unknown> | null;
    const sha = process.env.CASEOPS_RELEASE_SHA ?? "";
    if (!response.ok || !data || Object.keys(data).sort().join(",") !== "provenance,ready,release_sha"
        || data.ready !== true || data.provenance !== "web-forward" || !/^[0-9a-f]{40}$/.test(sha)
        || data.release_sha !== sha) return unavailable();
    return Response.json({ ready: true, provenance: "web-forward", release_sha: sha },
      { headers: { "Cache-Control": "no-store" } });
  } catch { return unavailable(); }
}
