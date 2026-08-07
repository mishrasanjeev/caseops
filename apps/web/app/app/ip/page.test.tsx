import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchIpDocketsMock, fetchIpWorkspaceReadinessMock, useCapabilityMock } = vi.hoisted(() => ({
  fetchIpDocketsMock: vi.fn(),
  fetchIpWorkspaceReadinessMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchIpDockets: fetchIpDocketsMock,
  fetchIpWorkspaceReadiness: fetchIpWorkspaceReadinessMock,
  createIpDocket: vi.fn(),
  addIpTitleInterest: vi.fn(),
  addIpCostItem: vi.fn(),
  discoverIpEvidence: vi.fn(),
  reviewIpEvidenceCandidate: vi.fn(),
  bulkReassignIpCoverage: vi.fn(),
  addIpRelatedRightObligation: vi.fn(),
  completeIpRelatedRightObligation: vi.fn(),
  reconcileIpCosts: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import IpDocketPage from "@/app/app/ip/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("IpDocketPage", () => {
  beforeEach(() => {
    fetchIpDocketsMock.mockReset();
    fetchIpWorkspaceReadinessMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockReturnValue(true);
    fetchIpWorkspaceReadinessMock.mockResolvedValue({
      timezone: "Asia/Calcutta",
      workspace_available: true,
      manual_docketing_available: true,
      features: [],
    });
    fetchIpDocketsMock.mockResolvedValue({ dockets: [], count: 0 });
  });

  it("renders the authorized empty state and working create form", async () => {
    render(withClient(<IpDocketPage />));

    expect(await screen.findByText("No IP records yet")).toBeInTheDocument();
    const create = screen.getByRole("button", { name: "New trademark" });
    expect(create).toBeVisible();
    fireEvent.click(create);
    expect(screen.getByRole("heading", { name: "New trademark particulars" })).toBeVisible();
    expect(screen.getByLabelText("Word mark")).toBeVisible();
    expect(screen.getByRole("button", { name: "Validate and create" })).toBeDisabled();
  });

  it("fails closed when the role cannot view IP records", () => {
    useCapabilityMock.mockReturnValue(false);
    render(withClient(<IpDocketPage />));
    expect(screen.getByText("IP docket access required")).toBeInTheDocument();
    expect(fetchIpDocketsMock).not.toHaveBeenCalled();
  });

  it("hides operational records and explains each failed readiness gate on narrow mobile", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 360 });
    fetchIpWorkspaceReadinessMock.mockResolvedValue({
      timezone: "Asia/Kolkata",
      workspace_available: false,
      manual_docketing_available: false,
      features: [
        {
          feature_id: "workspace_core",
          available: false,
          reason: "missing_entitlement",
          owner: "product-ip",
          required_capabilities: ["ip:read"],
          missing_capabilities: [],
          entitlement_key: "ip_workspace",
          entitled: false,
          rollout_flag: "ip_workspace_enabled",
          rollout_enabled: false,
          rollout_expires_at: null,
          manual_fallback_feature_id: null,
        },
        {
          feature_id: "registry_sync",
          available: false,
          reason: "rollout_disabled",
          owner: "integrations",
          required_capabilities: ["ip:registry_sync"],
          missing_capabilities: [],
          entitlement_key: "ip_registry_sync",
          entitled: true,
          rollout_flag: "ip_registry_sync_enabled",
          rollout_enabled: false,
          rollout_expires_at: null,
          manual_fallback_feature_id: "manual_docketing",
        },
      ],
    });

    render(withClient(<IpDocketPage />));

    expect(await screen.findByRole("heading", { name: "IP workspace setup" })).toBeVisible();
    expect(screen.getByText("The workspace plan does not include this feature · owner product-ip")).toBeVisible();
    expect(screen.getByText("The safety rollout has not been enabled · owner integrations")).toBeVisible();
    expect(screen.getByText("Manual fallback: manual docketing")).toBeVisible();
    expect(fetchIpDocketsMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "New trademark" })).not.toBeInTheDocument();
  });

  it("keeps manual docketing available while a provider automation is disabled", async () => {
    fetchIpWorkspaceReadinessMock.mockResolvedValue({
      timezone: "Asia/Kolkata",
      workspace_available: true,
      manual_docketing_available: true,
      features: [
        {
          feature_id: "workspace_core",
          available: true,
          reason: "available",
          owner: "product-ip",
          required_capabilities: ["ip:read"],
          missing_capabilities: [],
          entitlement_key: "ip_workspace",
          entitled: true,
          rollout_flag: "ip_workspace_enabled",
          rollout_enabled: true,
          rollout_expires_at: null,
          manual_fallback_feature_id: null,
        },
        {
          feature_id: "registry_sync",
          available: false,
          reason: "rollout_disabled",
          owner: "integrations",
          required_capabilities: ["ip:registry_sync"],
          missing_capabilities: [],
          entitlement_key: "ip_registry_sync",
          entitled: true,
          rollout_flag: "ip_registry_sync_enabled",
          rollout_enabled: false,
          rollout_expires_at: null,
          manual_fallback_feature_id: "manual_docketing",
        },
      ],
    });

    render(withClient(<IpDocketPage />));

    expect(await screen.findByText("No IP records yet")).toBeVisible();
    expect(screen.getByRole("button", { name: "New trademark" })).toBeVisible();
    expect(screen.getByText("registry sync")).toBeVisible();
    expect(screen.getByText("Manual fallback remains manual docketing.")).toBeVisible();
  });

  it("renders every grouped operational action at a narrow viewport", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 360 });
    fetchIpDocketsMock.mockResolvedValue({
      dockets: [{
        id: "ip-1", company_id: "company-1", matter_id: "matter-1", record_type: "trademark",
        title: "CASEOPS", primary_identifier: "TM-1", status: "active", restricted: false,
        current_version: 1, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
        current_particulars: { form_key: "TM-A", form_version: "2026.1", readiness_status: "ready", classes_json: [{ class_number: 9, specification: "Software" }] },
        notice_links: [], deadline_incidents: [], title_interests: [], cost_items: [], related_right_obligations: [],
        evidence_candidates: [{ id: "candidate-1", source_type: "communication", source_id: "mail-1", source_fingerprint: "abc", evidence_kind: "correspondence", suggested_link_kind: "instruction", status: "needs_review", accepted_effect: null, duplicate_of_candidate_id: null, metadata_json: { label: "Client instruction" }, reviewed_at: null, created_at: "2026-08-01T00:00:00Z" }],
        deadline_coverages: [{ id: "coverage-1", matter_deadline_id: "deadline-1", responsible_membership_id: "member-1", backup_membership_id: null, coverage_status: "accepted", calendar_projection_status: "queued", reassignment_version: 1, updated_at: "2026-08-01T00:00:00Z" }],
      }],
      count: 1,
    });

    render(withClient(<IpDocketPage />));

    expect(await screen.findByRole("button", { name: "Discover Matter evidence" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Accept and link" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Reject" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Transfer covered deadlines" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Add recordal obligation" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Reconcile with Matter billing" })).toBeVisible();
  });
});
