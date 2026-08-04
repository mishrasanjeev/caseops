import { NextResponse } from "next/server";

const EXACT_SHA = /^[0-9a-f]{40}$/;

export const dynamic = "force-dynamic";

export function releaseIdentity(
  environment: Record<string, string | undefined> = process.env,
): { service: "web"; release_sha: string; revision: string } {
  const candidate = (environment.CASEOPS_RELEASE_SHA ?? "").trim().toLowerCase();
  return {
    service: "web",
    release_sha: EXACT_SHA.test(candidate) ? candidate : "unavailable",
    revision: environment.K_REVISION?.trim() || "local",
  };
}

export async function GET(): Promise<NextResponse> {
  return NextResponse.json(releaseIdentity(), {
    headers: { "Cache-Control": "no-store" },
  });
}
