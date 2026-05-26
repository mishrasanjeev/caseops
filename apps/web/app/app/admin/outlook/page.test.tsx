import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchOutlookTenantConfigurationMock,
  startOutlookCalendarConnectionMock,
  testOutlookTenantConfigurationMock,
  updateOutlookTenantConfigurationMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  fetchOutlookTenantConfigurationMock: vi.fn(),
  startOutlookCalendarConnectionMock: vi.fn(),
  testOutlookTenantConfigurationMock: vi.fn(),
  updateOutlookTenantConfigurationMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchOutlookTenantConfiguration: fetchOutlookTenantConfigurationMock,
  startOutlookCalendarConnection: startOutlookCalendarConnectionMock,
  testOutlookTenantConfiguration: testOutlookTenantConfigurationMock,
  updateOutlookTenantConfiguration: updateOutlookTenantConfigurationMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: useCapabilityMock,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import AdminOutlookConfigurationPage from "@/app/app/admin/outlook/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function readinessStatus(overrides = {}) {
  return {
    provider: "outlook",
    configured: false,
    config_source: "missing",
    enabled: true,
    required_config: [
      { name: "OUTLOOK_CLIENT_ID", configured: false },
      { name: "OUTLOOK_CLIENT_SECRET", configured: false },
      { name: "OUTLOOK_REDIRECT_URI", configured: false },
      {
        name: "OUTLOOK_TENANT_ID_OR_APPROVED_TENANT_MODE",
        configured: true,
      },
    ],
    required_approvals: [
      {
        key: "oauth_consent_model_approved",
        label: "OAuth consent model approved",
        approved: false,
      },
      {
        key: "scopes_approved",
        label: "Microsoft Graph scopes approved",
        approved: false,
      },
      {
        key: "durable_runbook_approved",
        label: "Durable sync retry/dead-letter/replay runbook approved",
        approved: false,
      },
      {
        key: "rollback_approved",
        label: "Rollback and disable procedure approved",
        approved: false,
      },
      {
        key: "redaction_rules_approved",
        label: "Provider error redaction rules approved",
        approved: false,
      },
    ],
    approved_scopes: ["offline_access", "User.Read", "Calendars.ReadWrite"],
    missing_config_names: [
      "OUTLOOK_CLIENT_ID",
      "OUTLOOK_CLIENT_SECRET",
      "OUTLOOK_REDIRECT_URI",
    ],
    missing_approval_keys: [
      "oauth_consent_model_approved",
      "scopes_approved",
      "durable_runbook_approved",
      "rollback_approved",
      "redaction_rules_approved",
    ],
    connection_count: 0,
    connected_account_count: 0,
    last_test_status: "not_run",
    last_tested_at: null,
    last_error_redacted: null,
    adp20_readiness: "blocked_pending_admin_configuration",
    ...overrides,
  };
}

describe("AdminOutlookConfigurationPage", () => {
  beforeEach(() => {
    fetchOutlookTenantConfigurationMock.mockReset();
    startOutlookCalendarConnectionMock.mockReset();
    testOutlookTenantConfigurationMock.mockReset();
    updateOutlookTenantConfigurationMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockReturnValue(true);
    fetchOutlookTenantConfigurationMock.mockResolvedValue(readinessStatus());
    updateOutlookTenantConfigurationMock.mockImplementation(async () =>
      readinessStatus({
        configured: true,
        config_source: "tenant_admin",
        missing_config_names: [],
        missing_approval_keys: [],
      }),
    );
    testOutlookTenantConfigurationMock.mockResolvedValue({
      provider: "outlook",
      status: "passed",
      checks: [{ key: "MICROSOFT_GRAPH_ME", label: "Graph probe", status: "passed" }],
      adp20_readiness: "ready_for_adp20_implementation",
      tested_at: "2026-05-26T00:00:00Z",
    });
  });

  it("renders access refusal when caller is not a workspace admin", () => {
    useCapabilityMock.mockReturnValue(false);
    render(withClient(<AdminOutlookConfigurationPage />));
    expect(screen.getByText(/Workspace admin required/i)).toBeInTheDocument();
    expect(fetchOutlookTenantConfigurationMock).not.toHaveBeenCalled();
  });

  it("saves names-only Outlook configuration and approval state", async () => {
    const user = userEvent.setup();
    render(withClient(<AdminOutlookConfigurationPage />));

    await user.type(await screen.findByTestId("outlook-client-id"), "client-id");
    await user.type(screen.getByTestId("outlook-client-secret"), "fixture-credential");
    await user.type(screen.getByTestId("outlook-redirect-uri"), "https://api.example.test/callback");
    for (const label of [
      "OAuth consent model approved",
      "Graph scopes approved",
      "Durable operation runbook approved",
      "Rollback and disable procedure approved",
      "Provider error redaction rules approved",
    ]) {
      await user.click(screen.getByLabelText(label));
    }
    await user.click(screen.getByTestId("outlook-config-save"));

    await waitFor(() =>
      expect(updateOutlookTenantConfigurationMock).toHaveBeenCalledWith(
        expect.objectContaining({
          clientId: "client-id",
          clientSecret: "fixture-credential",
          redirectUri: "https://api.example.test/callback",
          oauthConsentModelApproved: true,
          scopesApproved: true,
          durableRunbookApproved: true,
          rollbackApproved: true,
          redactionRulesApproved: true,
        }),
      ),
    );
  });

  it("runs the readiness probe and renders check results", async () => {
    const user = userEvent.setup();
    render(withClient(<AdminOutlookConfigurationPage />));

    await user.click(await screen.findByTestId("outlook-config-test"));
    await waitFor(() =>
      expect(testOutlookTenantConfigurationMock).toHaveBeenCalled(),
    );
    expect(await screen.findByTestId("outlook-config-test-results")).toBeInTheDocument();
    expect(screen.getByText("Graph probe")).toBeInTheDocument();
  });
});
