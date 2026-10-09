import { NextResponse } from "next/server";
import { z } from "zod";
import { demoAdmissionSchema } from "@/lib/demo-admission";
import { fetchJsonWithTimeout } from "@/lib/api/client";
import { API_BASE_URL } from "@/lib/api/config";

export async function POST(request: Request) {
  let input: unknown;
  try { input = await request.json(); }
  catch { return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 }); }
  const parsed = demoAdmissionSchema.safeParse(input);
  if (!parsed.success) return NextResponse.json({ error: "Review the request fields and try again." }, { status: 400 });
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) headers["x-forwarded-for"] = forwarded;
  try {
    const response = await fetchJsonWithTimeout(
      `${process.env.CASEOPS_API_BASE_URL ?? API_BASE_URL}/api/billing/enrollments/demo-request`,
      { method: "POST", headers, body: JSON.stringify(parsed.data), cache: "no-store", credentials: "omit", redirect: "error" }, 15_000,
    );
    if (!response.ok) {
      const status = [400, 409, 422, 429].includes(response.status) ? response.status : 503;
      const error = status === 429 ? "Too many requests. Try again later."
        : status === 409 ? "This request key was already used for different details."
        : status === 400 || status === 422 ? "Review the request fields and try again."
        : "Could not confirm the saved request. Retry without changing your details.";
      return NextResponse.json({ error }, { status });
    }
    const saved = z.object({ id: z.string().uuid(), status: z.literal("demo_requested") }).safeParse(response.data);
    if (!saved.success || saved.data.id !== parsed.data.idempotency_key) throw new Error("Invalid admission response");
    return NextResponse.json({ accepted: true, ...saved.data }, { status: 202, headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "Could not confirm the saved request. Retry without changing your details." }, { status: 503 });
  }
}
