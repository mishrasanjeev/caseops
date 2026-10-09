import { describe, expect, it } from "vitest";
import { demoAdmissionSchema, demoSources } from "./demo-admission";

const payload = {
  contact_name: "Offline Demo Advocate",
  contact_email: "demo@example.com",
  segment: "solo",
  role: "solo_advocate",
  intent: "demo",
  source: "homepage",
  idempotency_key: "00000000-0000-4000-8000-000000000001",
  privacy_notice_version: "2026-10-09",
};

describe("seo_demo_20261009 explicit admission allowlists", () => {
  it("requires a UUID admission nonce, not an arbitrary credential string", () => {
    expect(demoAdmissionSchema.safeParse(payload).success).toBe(true);
    expect(demoAdmissionSchema.safeParse({ ...payload, idempotency_key: "not-a-uuid" }).success).toBe(false);
  });

  it.each(demoSources)("admits canonical source %s without changing attribution", (source) => {
    expect(demoAdmissionSchema.parse({ ...payload, source })).toEqual({ ...payload, source });
  });

  it.each(["source", "segment", "role", "intent"] as const)(
    "rejects prototype keys in %s rather than interpreting inherited properties as enum members",
    (field) => {
      for (const value of ["constructor", "__proto__"]) {
        const parsed = demoAdmissionSchema.safeParse({ ...payload, [field]: value });
        expect(parsed.success, `${field}=${value}`).toBe(false);
        if (!parsed.success) expect(parsed.error.issues.map((issue) => issue.path)).toContainEqual([field]);
      }
    },
  );

  it.each(["url", "query", "referrer", "utm_json"])("rejects unreviewed attribution field %s", (field) => {
    expect(demoAdmissionSchema.safeParse({ ...payload, [field]: "private-do-not-retain" }).success).toBe(false);
  });
});
