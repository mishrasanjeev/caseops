import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  applyIpAccessChangeMock,
  fetchIpAccessPanelMock,
  listCompanyUsersMock,
  listTeamsMock,
  previewIpAccessChangeMock,
} = vi.hoisted(() => ({
  applyIpAccessChangeMock: vi.fn(),
  fetchIpAccessPanelMock: vi.fn(),
  listCompanyUsersMock: vi.fn(),
  listTeamsMock: vi.fn(),
  previewIpAccessChangeMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/endpoints")>()),
  applyIpAccessChange: applyIpAccessChangeMock,
  fetchIpAccessPanel: fetchIpAccessPanelMock,
  listCompanyUsers: listCompanyUsersMock,
  listTeams: listTeamsMock,
  previewIpAccessChange: previewIpAccessChangeMock,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { IpAccessWorkspace } from "@/components/ip/IpAccessWorkspace";
import type { IpDocket } from "@/lib/api/endpoints";

const docket = {
  id: "ip-1",
  title: "CASEOPS",
  access_policy_version: 3,
} as IpDocket;

const panel = {
  docket_id: "ip-1",
  docket_title: "CASEOPS",
  restricted: true,
  access_policy_version: 3,
  linked_matter_id: "matter-1",
  grants: [],
  walls: [],
  active_internal_membership_count: 1,
  queued_delivery_count: 2,
  excluded_persistence: ["portal_access", "access_reviews", "emergency_access"],
};

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("IpAccessWorkspace", () => {
  beforeEach(() => {
    fetchIpAccessPanelMock.mockReset().mockResolvedValue(panel);
    listCompanyUsersMock.mockReset().mockResolvedValue({
      company_id: "company-1",
      company_slug: "firm",
      users: [
        {
          membership_id: "membership-2",
          full_name: "Priya Reviewer",
          email: "priya@example.test",
          role: "member",
          membership_active: true,
          user_id: "user-2",
          user_active: true,
          created_at: "2026-08-16T00:00:00Z",
        },
      ],
    });
    listTeamsMock.mockReset().mockResolvedValue({ teams: [], team_scoping_enabled: true });
    previewIpAccessChangeMock.mockReset().mockResolvedValue({
      docket_id: "ip-1",
      access_policy_version: 3,
      action: "grant",
      preview_token: "preview-token",
      affected_memberships: [
        {
          membership_id: "membership-2",
          label: "Priya Reviewer",
          before_visible: false,
          after_visible: true,
          linked_matter_visible: false,
        },
      ],
      visibility_gain_count: 1,
      visibility_loss_count: 0,
      queued_delivery_recheck_count: 2,
      document_count: 4,
      linked_matter_id: "matter-1",
      linked_matter_mismatch: true,
      warnings: ["Linked Matter visibility differs; permissions will not be copied."],
      requires_step_up: true,
    });
    applyIpAccessChangeMock.mockReset().mockResolvedValue({
      action: "grant",
      invalidation_operation_id: "operation-1",
      visibility_gain_count: 1,
      visibility_loss_count: 0,
      queued_delivery_recheck_count: 2,
      panel: { ...panel, access_policy_version: 4 },
    });
  });

  it("previews and confirms an independently versioned grant on a narrow viewport", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 360 });
    const onChanged = vi.fn().mockResolvedValue(undefined);
    render(withClient(<IpAccessWorkspace docket={docket} onChanged={onChanged} />));

    const workspace = await screen.findByTestId("ip-access-workspace");
    expect(await within(workspace).findByText("Restricted")).toBeVisible();
    expect(within(workspace).getByText("v3")).toBeVisible();
    expect(within(workspace).getByText(/Linked Matter permissions are never copied/i)).toBeVisible();

    fireEvent.change(within(workspace).getByLabelText("Reason for change"), {
      target: { value: "Conflict clearance completed." },
    });
    fireEvent.change(within(workspace).getByLabelText("Person or team"), {
      target: { value: "membership-2" },
    });
    fireEvent.click(within(workspace).getByRole("button", { name: "Preview grant" }));

    await waitFor(() =>
      expect(previewIpAccessChangeMock).toHaveBeenCalledWith("ip-1", {
        action: "grant",
        expectedAccessPolicyVersion: 3,
        reason: "Conflict clearance completed.",
        subjectType: "membership",
        subjectId: "membership-2",
        effectiveFrom: null,
        expiresAt: null,
      }),
    );
    const preview = await within(workspace).findByTestId("ip-access-preview");
    expect(within(preview).getByText("Gains: 1")).toBeVisible();
    expect(within(preview).getByText("Queued deliveries: 2")).toBeVisible();
    expect(within(preview).getByText(/permissions will not be copied/i)).toBeVisible();

    fireEvent.click(within(preview).getByRole("button", { name: "Apply access change" }));
    await waitFor(() => expect(applyIpAccessChangeMock).toHaveBeenCalledTimes(1));
    expect(applyIpAccessChangeMock).toHaveBeenCalledWith(
      "ip-1",
      expect.objectContaining({ expectedAccessPolicyVersion: 3, subjectId: "membership-2" }),
      "preview-token",
    );
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  });
});
