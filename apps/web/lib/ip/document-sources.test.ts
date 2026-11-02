import { describe, expect, it } from "vitest";

import type { IpDocument } from "@/lib/api/endpoints";
import { isSpecialistSourceDocument } from "@/lib/ip/document-sources";

function document(links: IpDocument["links"], retired = false): IpDocument {
  return {
    id: "document-1",
    links,
    retirement: retired ? { retired_at: "2026-11-01T00:00:00Z", retired_by_name: "Ram", reason: "Wrong file" } : null,
  } as IpDocument;
}

const link = (target_type: IpDocument["links"][number]["target_type"], target_id: string) => ({
  id: `${target_type}-${target_id}`, version_id: null, target_type, target_id,
  created_by_membership_id: "member-1", created_at: "2026-11-01T00:00:00Z",
});

describe("isSpecialistSourceDocument", () => {
  it("matches the specialist validator: exactly one direct link to the record's docket", () => {
    expect(isSpecialistSourceDocument(document([link("docket", "docket-1")]), "docket-1")).toBe(true);
    // The docket list also returns event- and deadline-linked documents; a specialist source refuses them.
    expect(isSpecialistSourceDocument(document([link("event", "event-1")]), "docket-1")).toBe(false);
    expect(isSpecialistSourceDocument(document([link("deadline", "deadline-1")]), "docket-1")).toBe(false);
    expect(isSpecialistSourceDocument(
      document([link("docket", "docket-1"), link("docket", "docket-2")]), "docket-1",
    )).toBe(false);
    expect(isSpecialistSourceDocument(document([link("docket", "docket-2")]), "docket-1")).toBe(false);
    expect(isSpecialistSourceDocument(document([link("docket", "docket-1")], true), "docket-1")).toBe(false);
  });
});
