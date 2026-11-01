import { describe, expect, it } from "vitest";

import type { IpCoreRecords } from "@/lib/api/endpoints";
import {
  flattenRegisterState,
  normalizedRegisterRecord,
  registerFormFromState,
  registrySyncSentence,
  registryTargets,
} from "@/lib/ip/registry-evidence";

const identifier = (overrides: Record<string, unknown>) => ({
  id: `identifier-${Math.random()}`,
  docket_id: "pine",
  application_id: null,
  proceeding_id: null,
  identifier_kind: "application",
  raw_value: "",
  normalized_value: "",
  office: "IP India",
  jurisdiction: "IN",
  source: "import",
  effective_from: "2026-01-01",
  effective_until: null,
  is_primary: false,
  reconciliation_status: "confirmed",
  supersedes_identifier_id: null,
  superseded_by_identifier_id: null,
  correction_reason: null,
  created_at: "2026-01-01T00:00:00Z",
  ...overrides,
});

const proceeding = (id: string, side: string, created = "2026-10-01T00:00:00Z") => ({
  id,
  docket_id: "pine",
  application_id: "app-1",
  proceeding_kind: "opposition",
  side,
  office: "IP India",
  jurisdiction: "IN",
  stage: "draft",
  origin_kind: "linked_application",
  stage_template_version: "v1",
  source_pending_identifier_allocation: false,
  version: 1,
  created_at: created,
  updated_at: created,
});

// The PINE LABS docket Ram reported on (production 2026-10-31), reduced.
const PINE = {
  assets: [],
  applications: [{
    id: "app-1", docket_id: "pine", asset_id: "asset-1", office: "IP India", jurisdiction: "IN",
    filing_phase: "draft", is_active: true, lifecycle_version: 1, source_pending_identifier_allocation: false,
    version: 1, created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z",
  }],
  proceedings: [proceeding("opp-opponent", "opponent"), proceeding("opp-applicant", "applicant")],
  identifiers: [
    identifier({ application_id: "app-1", identifier_kind: "application", raw_value: "4009154", is_primary: true }),
    identifier({ application_id: "app-1", proceeding_id: "opp-applicant", identifier_kind: "opposition", raw_value: "1234567" }),
    identifier({ application_id: "app-1", identifier_kind: "application", raw_value: "OLD-1", effective_until: "2026-02-01" }),
  ],
} as unknown as IpCoreRecords;

describe("registryTargets", () => {
  it("labels every record with its own number and side so no two read alike", () => {
    const targets = registryTargets(PINE);
    expect(targets.map((row) => row.label)).toEqual([
      "Application 4009154 · IP India · IN · Draft",
      "Opposition number pending · opponent side · IP India · Draft",
      "Opposition 1234567 · applicant side · IP India · Draft",
    ]);
    expect(targets[0]).toMatchObject({
      value: "application:app-1", identifier: "4009154", identifierKind: "application",
      identifierKinds: ["application", "registration"], office: "IP India", jurisdiction: "IN",
    });
    expect(targets[2]).toMatchObject({ value: "proceeding:opp-applicant", identifier: "1234567", identifierKinds: ["opposition"] });
    expect(targets[1]).toMatchObject({ identifier: "", identifierKind: "opposition" });
  });

  it("adds the opening date, then an ordinal, when two records still read alike", () => {
    const twins = { ...PINE, applications: [], identifiers: [], proceedings: [
      proceeding("a", "opponent", "2026-10-01T12:00:00Z"),
      proceeding("b", "opponent", "2026-10-02T12:00:00Z"),
      proceeding("c", "opponent", "2026-10-02T12:00:00Z"),
    ] } as unknown as IpCoreRecords;
    const labels = registryTargets(twins).map((row) => row.label);
    expect(new Set(labels).size).toBe(3);
    expect(labels[0]).toMatch(/opened 1 Oct 2026$/);
    expect(labels[2]).toMatch(/opened 2 Oct 2026 \(2\)$/);
  });

  it("offers nothing for a docket without an application or proceeding (a Madrid record)", () => {
    expect(registryTargets({ assets: [], applications: [], proceedings: [], identifiers: [] })).toEqual([]);
  });
});

describe("structured register evidence", () => {
  const accepted = {
    identifiers: { application: "4009154" },
    parties: [{ name: "Pine Labs Limited", role: "applicant" }],
    office: "IP India",
    jurisdiction: "IN",
    status: "draft",
    renewal_date: "2036-08-24",
    goods: { "9": "Software" },
  };

  it("prefills every accepted value and changes nothing when nothing is edited", () => {
    const form = registerFormFromState(accepted);
    expect(form.fields.map((field) => [field.path, field.label, field.value])).toEqual([
      ["/status", "Status on the register", "draft"],
      ["/office", "Office on the register", "IP India"],
      ["/jurisdiction", "Jurisdiction on the register", "IN"],
      ["/identifiers/application", "Application number", "4009154"],
      ["/mark_name", "Mark as shown on the register", ""],
      ["/registration_date", "Registration date", ""],
      ["/renewal_date", "Renewal due date", "2036-08-24"],
      ["/journal_number", "Trade Marks Journal number", ""],
      ["/publication_date", "Journal publication date", ""],
      ["/hearing_date", "Next hearing date", ""],
      ["/goods/9", "Goods › 9", "Software"],
    ]);
    expect(form.fields.find((field) => field.path === "/renewal_date")?.input).toBe("date");
    const unchanged = normalizedRegisterRecord(form, {}, form.parties);
    expect(flattenRegisterState(unchanged)).toEqual(flattenRegisterState(accepted));
  });

  it("records edits, new details and parties in the accepted shape; a blank field is left out", () => {
    const form = registerFormFromState(accepted);
    const record = normalizedRegisterRecord(
      form,
      { "/status": " Registered ", "/registration_date": "2027-01-15", "/office": "" },
      [{ name: "Pine Labs Limited", role: "proprietor" }, { name: " ", role: "" }],
    );
    expect(record).toEqual({
      identifiers: { application: "4009154" },
      parties: [{ name: "Pine Labs Limited", role: "proprietor" }],
      jurisdiction: "IN",
      status: "Registered",
      registration_date: "2027-01-15",
      renewal_date: "2036-08-24",
      goods: { "9": "Software" },
    });
  });

  it("sends untouched values exactly as accepted, including spacing and nulls", () => {
    const state = { status: " Registered ", number: 7, note: null, parties: [{ name: "Acme ", role: "owner" }] };
    const form = registerFormFromState(state);
    expect(normalizedRegisterRecord(form, {}, form.parties)).toEqual(state);
    expect(normalizedRegisterRecord(form, { "/number": "8" }, form.parties)).toEqual({ ...state, number: 8 });
  });

  it("keeps an empty party list unchanged rather than reporting it removed", () => {
    const form = registerFormFromState({ status: "draft", parties: [] });
    expect(form.parties).toEqual([]);
    expect(normalizedRegisterRecord(form, {}, [])).toEqual({ status: "draft", parties: [] });
  });
});

describe("registrySyncSentence", () => {
  it("names the gate instead of one generic sentence", () => {
    expect(registrySyncSentence({ reason: "rollout_disabled" })).toBe("Automated registry sync is paused by CaseOps.");
    expect(registrySyncSentence({ reason: "missing_entitlement" })).toBe("Automated registry sync is not in your plan.");
    expect(registrySyncSentence({ reason: "workspace_not_configured" })).toMatch(/needs setup/);
    expect(registrySyncSentence({ reason: "missing_capability" })).toBe("Your role cannot run automated registry sync.");
    expect(registrySyncSentence(undefined)).toBeNull();
  });
});
