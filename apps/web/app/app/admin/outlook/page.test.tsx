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
    ],
    machine_control_version: "outlook-connector-controls/2026-08-30.1",
    machine_controls: [
      {
        key: "durable_retry_dead_letter_replay",
        label: "Durable retry, dead-letter, and replay policy",
        version: "calendar-durable-delivery/v1",
        status: "passed",
        detail: "Bounded retry policy loaded.",
      },
      {
        key: "tenant_disable_boundary",
        label: "Tenant disable and rollback boundary",
        version: "outlook-tenant-disable/v1",
        status: "passed",
        detail: "Tenant disable is fail closed.",
      },
      {
        key: "provider_error_redaction",
        label: "Provider error redaction policy",
        version: "provider-error-redaction/v1",
        status: "passed",
        detail: "Provider errors are redacted.",
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
    ],
    missing_machine_control_keys: [],
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
      machine_control_version: "outlook-connector-controls/2026-08-30.1",
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

  it("saves names-only Outlook configuration and provider authority", async () => {
    const user = userEvent.setup();
    render(withClient(<AdminOutlookConfigurationPage />));

    await user.type(await screen.findByTestId("outlook-client-id"), "client-id");
    await user.type(screen.getByTestId("outlook-client-secret"), "fixture-credential");
    await user.type(screen.getByTestId("outlook-redirect-uri"), "https://api.example.test/callback");
    for (const label of [
      "OAuth consent model approved",
      "Graph scopes approved",
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
        }),
      ),
    );
    const submitted = updateOutlookTenantConfigurationMock.mock.calls[0]?.[0];
    expect(submitted).not.toHaveProperty("durableRunbookApproved");
    expect(submitted).not.toHaveProperty("rollbackApproved");
    expect(submitted).not.toHaveProperty("redactionRulesApproved");
  });

  it("shows versioned machine controls without internal approval checkboxes", async () => {
    render(withClient(<AdminOutlookConfigurationPage />));

    expect(await screen.findByTestId("outlook-machine-controls")).toHaveTextContent(
      "calendar-durable-delivery/v1",
    );
    expect(
      screen.queryByRole("checkbox", { name: /runbook|rollback|redaction/i }),
    ).not.toBeInTheDocument();
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
