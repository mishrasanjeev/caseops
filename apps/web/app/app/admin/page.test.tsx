import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { capabilityMock } = vi.hoisted(() => ({ capabilityMock: vi.fn() }));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (cap: string) => capabilityMock(cap),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import AdminPage from "@/app/app/admin/page";

// PG-107 (2026-05-01): TenantAIPolicyCard uses React Query, so the
// admin page now needs a QueryClientProvider in tests. Wrap render so
// existing tests don't have to change.
function renderWithQuery(ui: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("AdminPage audit export (P0-001 cookie-auth regression)", () => {
  let originalFetch: typeof globalThis.fetch;
  let originalCreateObjectURL: typeof URL.createObjectURL;
  let originalRevokeObjectURL: typeof URL.revokeObjectURL;
  const fetchMock = vi.fn();
  let auditResponse: () => Promise<Response | {
    ok: boolean;
    status: number;
    headers?: { get: (key: string) => string | null };
    blob?: () => Promise<Blob>;
    json?: () => Promise<unknown>;
  }>;

  function jsonResponse(data: unknown, status = 200): Response {
    return new Response(JSON.stringify(data), {
      status,
      headers: { "content-type": "application/json" },
    });
  }

  beforeEach(() => {
    capabilityMock.mockReset();
    capabilityMock.mockImplementation(() => true);
    fetchMock.mockReset();
    auditResponse = async () => ({
      ok: true,
      status: 200,
      headers: {
        get: (k: string) =>
          k.toLowerCase() === "content-disposition"
            ? 'attachment; filename="audit-export.jsonl"'
            : null,
      },
      blob: async () => new Blob(["row\n"], { type: "application/jsonl" }),
    });
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/admin/tenant-ai-policy")) {
        return jsonResponse({
          company_id: "company-1",
          predictive_bench_strategy_enabled: false,
        });
      }
      if (url.includes("/api/admin/ai-token-governance")) {
        const body = typeof init?.body === "string" ? JSON.parse(init.body) : {};
        return jsonResponse({
          company_id: "company-1",
          period_start: "2026-05-01T00:00:00Z",
          period_end: "2026-06-01T00:00:00Z",
          firm_quota_tokens:
            init?.method === "PATCH" ? body.firm_quota_tokens : 100000,
          user_quota_tokens:
            init?.method === "PATCH" ? body.user_quota_tokens : 25000,
          warning_threshold_percent:
            init?.method === "PATCH" ? body.warning_threshold_percent : 90,
          firm_used_tokens: 75000,
          firm_remaining_tokens: 25000,
          firm_state: "warning",
          top_users: [
            {
              actor_membership_id: "membership-1",
              user_label: "Owner One",
              used_tokens: 60000,
              run_count: 4,
              state: "warning",
              remaining_tokens: 0,
            },
          ],
          usage_by_matter: [
            {
              matter_id: "matter-1",
              matter_code: "EXT-001",
              matter_title: "External access matter",
              used_tokens: 60000,
              run_count: 3,
            },
          ],
          usage_by_purpose_model: [
            {
              purpose: "matter_summary",
              provider: "mock",
              model: "caseops-mock-1",
              used_tokens: 75000,
              run_count: 5,
            },
          ],
        });
      }
      if (url.includes("/api/admin/enterprise-readiness")) {
        return jsonResponse({
          enterprise_identity: {
            provider: "enterprise_identity",
            readiness_classification: "planned",
            oidc_status: "disabled",
            saml_status: "planned",
            scim_status: "planned",
            sso_enforcement_status: "disabled",
            enabled: false,
            not_enabled_reason:
              "SSO, SAML, and SCIM are readiness-only until an IdP UAT pass is recorded.",
            last_test_status: "not_run",
            last_tested_at: null,
            required_evidence: ["IdP metadata validated"],
          },
          agent_trust_plane: {
            provider: "agent_trust_plane",
            readiness_classification: "planned",
            autonomous_execution_enabled: false,
            grant_count: 0,
            active_grant_count: 0,
            execution_count: 0,
            blocked_execution_count: 0,
            not_enabled_reason: "Autonomous scoped-agent execution is not live.",
          },
          ai_governance: {
            provider: "ai_governance",
            readiness_classification: "review-first",
            approved_policy_count: 0,
            pending_policy_count: 0,
            blocked_policy_count: 0,
            legal_disclaimer_required: true,
            regression_gates_required: true,
          },
        });
      }
      if (url.includes("/api/admin/storage-governance")) {
        const body = typeof init?.body === "string" ? JSON.parse(init.body) : {};
        return jsonResponse({
          company_id: "company-1",
          used_bytes: 1073741824,
          quota_bytes:
            init?.method === "PATCH" ? body.quota_bytes : 5368709120,
          remaining_bytes:
            init?.method === "PATCH" && body.quota_bytes !== null
              ? Math.max(body.quota_bytes - 1073741824, 0)
              : 4294967296,
          max_upload_size_bytes: 26214400,
          state: "ok",
          warning_threshold_percent: 90,
          usage_by_matter: [
            {
              matter_id: "matter-1",
              matter_code: "EXT-001",
              matter_title: "External access matter",
              used_bytes: 1073741824,
              attachment_count: 2,
            },
          ],
          largest_files: [
            {
              attachment_id: "file-1",
              matter_id: "matter-1",
              matter_code: "EXT-001",
              matter_title: "External access matter",
              original_filename: "pleading.pdf",
              size_bytes: 1048576,
            },
          ],
          archive_candidates: [],
        });
      }
      if (url.includes("/api/matters/")) {
        return jsonResponse({
          matters: [
            {
              id: "matter-1",
              matter_code: "EXT-001",
              title: "External access matter",
              client_name: "Client",
              opposing_party: "Counterparty",
              status: "active",
              lifecycle_version: 1,
              practice_area: "Commercial",
              forum_level: "high_court",
              court_name: "Delhi High Court",
              judge_name: null,
              description: null,
              next_hearing_on: null,
              created_at: "2026-05-05T00:00:00Z",
              updated_at: "2026-05-05T00:00:00Z",
            },
          ],
          next_cursor: null,
        });
      }
      if (url.includes("/api/admin/portal/invitations")) {
        const body = typeof init?.body === "string" ? JSON.parse(init.body) : {};
        return jsonResponse(
          {
            portal_user: {
              id: "portal-user-1",
              company_id: "company-1",
              email: body.email,
              full_name: body.full_name,
              role: body.role,
              last_signed_in_at: null,
            },
            grants: [
              {
                id: "grant-1",
                matter_id: body.matter_ids?.[0],
                role: body.role,
                scope_json: {
                  can_upload: body.can_upload,
                  can_invoice: body.can_invoice,
                  can_reply: body.can_reply,
                },
                granted_at: "2026-05-05T00:00:00Z",
                revoked_at: null,
              },
            ],
            debug_token: "debug-token",
          },
          201,
        );
      }
      if (url.includes("/api/admin/audit/export")) {
        return auditResponse();
      }
      return jsonResponse({});
    });
    originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
    originalCreateObjectURL = URL.createObjectURL;
    originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => "blob:mock");
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
  });

  it("downloads via credentials:'include' (no Authorization header)", async () => {
    const user = userEvent.setup();
    renderWithQuery(<AdminPage />);
    expect(screen.getByRole("link", { name: /roles/i })).toHaveAttribute(
      "href",
      "/app/admin/roles",
    );
    expect(await screen.findByText("Enterprise readiness")).toBeInTheDocument();
    expect(screen.getByText(/autonomous scoped-agent execution is not live/i)).toBeInTheDocument();
    await user.click(screen.getByTestId("download-audit-export"));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).includes("/api/admin/audit/export"),
        ),
      ).toBe(true),
    );
    const auditCall = fetchMock.mock.calls.find(([input]) =>
      String(input).includes("/api/admin/audit/export"),
    );
    expect(auditCall).toBeDefined();
    const [, init] = auditCall!;
    expect(init.credentials).toBe("include");
    expect(init.headers?.Authorization).toBeUndefined();
  });

  it("surfaces an actionable error on 401 instead of throwing 'session expired'", async () => {
    auditResponse = async () => ({
      ok: false,
      status: 401,
      json: async () => ({ detail: "no" }),
    });
    const { toast } = await import("sonner");
    const user = userEvent.setup();
    renderWithQuery(<AdminPage />);
    await user.click(screen.getByTestId("download-audit-export"));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringMatching(/sign in again/i),
      ),
    );
  });

  it("surfaces an actionable error on 403 with the capability hint", async () => {
    auditResponse = async () => ({
      ok: false,
      status: 403,
      json: async () => ({ detail: "denied" }),
    });
    const { toast } = await import("sonner");
    const user = userEvent.setup();
    renderWithQuery(<AdminPage />);
    await user.click(screen.getByTestId("download-audit-export"));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringMatching(/audit:export/i),
      ),
    );
  });

  it("invites outside counsel with a selected matter grant and OC permissions", async () => {
    const user = userEvent.setup();
    renderWithQuery(<AdminPage />);

    await user.type(screen.getByTestId("portal-invite-name"), "Counsel One");
    await user.type(screen.getByTestId("portal-invite-email"), "oc@example.com");
    await user.selectOptions(screen.getByTestId("portal-invite-role"), "outside_counsel");
    await waitFor(() =>
      expect(screen.getByTestId("portal-invite-matter")).not.toBeDisabled(),
    );
    await user.selectOptions(screen.getByTestId("portal-invite-matter"), "matter-1");
    await user.click(screen.getByTestId("portal-invite-submit"));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).includes("/api/admin/portal/invitations"),
        ),
      ).toBe(true),
    );
    const inviteCall = fetchMock.mock.calls.find(([input]) =>
      String(input).includes("/api/admin/portal/invitations"),
    );
    expect(inviteCall).toBeDefined();
    const [, init] = inviteCall!;
    const body = JSON.parse(String(init.body));
    expect(body).toMatchObject({
      email: "oc@example.com",
      full_name: "Counsel One",
      role: "outside_counsel",
      matter_ids: ["matter-1"],
      can_upload: true,
      can_invoice: true,
      can_reply: false,
    });
  });

  it("shows storage governance and patches the firm quota", async () => {
    const user = userEvent.setup();
    renderWithQuery(<AdminPage />);

    const input = await screen.findByTestId("storage-quota-input");
    await waitFor(() =>
      expect((input as HTMLInputElement).value).toBe("5"),
    );
    await user.clear(input);
    await user.type(input, "6");
    await user.click(screen.getByTestId("storage-quota-save"));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([request, init]) =>
            String(request).includes("/api/admin/storage-governance") &&
            init?.method === "PATCH",
        ),
      ).toBe(true),
    );
    const patchCall = fetchMock.mock.calls.find(
      ([request, init]) =>
        String(request).includes("/api/admin/storage-governance") &&
        init?.method === "PATCH",
    );
    expect(patchCall).toBeDefined();
    const [, init] = patchCall!;
    expect(JSON.parse(String(init.body))).toEqual({
      quota_bytes: 6442450944,
    });
  });

  it("shows AI token governance and patches monthly quotas", async () => {
    const user = userEvent.setup();
    renderWithQuery(<AdminPage />);

    const firmInput = await screen.findByTestId("firm-ai-token-quota-input");
    const userInput = await screen.findByTestId("user-ai-token-quota-input");
    const warningInput = await screen.findByTestId("ai-token-warning-input");
    await waitFor(() =>
      expect((firmInput as HTMLInputElement).value).toBe("100000"),
    );
    expect((userInput as HTMLInputElement).value).toBe("25000");
    expect((warningInput as HTMLInputElement).value).toBe("90");

    await user.clear(firmInput);
    await user.type(firmInput, "150000");
    await user.clear(userInput);
    await user.type(userInput, "30000");
    await user.clear(warningInput);
    await user.type(warningInput, "80");
    await user.click(screen.getByTestId("ai-token-governance-save"));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([request, init]) =>
            String(request).includes("/api/admin/ai-token-governance") &&
            init?.method === "PATCH",
        ),
      ).toBe(true),
    );
    const patchCall = fetchMock.mock.calls.find(
      ([request, init]) =>
        String(request).includes("/api/admin/ai-token-governance") &&
        init?.method === "PATCH",
    );
    expect(patchCall).toBeDefined();
    const [, init] = patchCall!;
    expect(JSON.parse(String(init.body))).toEqual({
      firm_quota_tokens: 150000,
      user_quota_tokens: 30000,
      warning_threshold_percent: 80,
    });
  });
});

// QG-AUTH-004 lint-style guard: the admin page MUST NOT depend on
// getStoredToken() for the audit export path. We assert the absence at
// the source level so a future regression that re-imports it is caught
// by vitest, not by a real user.
describe("AdminPage QG-AUTH-004 — no getStoredToken dependency", () => {
  it("admin page source does not import getStoredToken", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "page.tsx"),
      "utf-8",
    );
    expect(src).not.toMatch(/getStoredToken/);
  });
});
