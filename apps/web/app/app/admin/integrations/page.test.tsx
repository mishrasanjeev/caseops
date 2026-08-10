import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { capabilityMock } = vi.hoisted(() => ({ capabilityMock: vi.fn() }));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => capabilityMock(capability),
}));

import TenantIntegrationsPage from "@/app/app/admin/integrations/page";
import { mockBillingFetch } from "@/test/billing-fixtures";

function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("TenantIntegrationsPage", () => {
  const fetchMock = vi.fn();
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    capabilityMock.mockReturnValue(true);
    fetchMock.mockReset();
    mockBillingFetch(fetchMock);
    originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("blocks non-admin callers before fetching integrations", () => {
    capabilityMock.mockReturnValue(false);
    renderWithQuery(<TenantIntegrationsPage />);

    expect(screen.getByText("Workspace admin required")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sequences initial connector reads instead of cold-starting a request burst", async () => {
    renderWithQuery(<TenantIntegrationsPage />);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toEqual(
      expect.stringContaining("/api/admin/integrations"),
    );
    await screen.findByTestId("google-workspace-configuration");
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(4));
    const firstFourPaths = fetchMock.mock.calls.slice(0, 4).map(([url]) =>
      new URL(String(url)).pathname,
    );
    expect(firstFourPaths).toEqual([
      "/api/admin/integrations",
      "/api/admin/integrations/health",
      "/api/admin/google-workspace-configuration",
      "/api/drive/google/status",
    ]);
  });

  it("renders tenant-safe connector readiness without internal labels", async () => {
    renderWithQuery(<TenantIntegrationsPage />);

    expect(
      await screen.findByTestId("google-workspace-configuration"),
    ).toBeInTheDocument();
    expect(screen.getByText("Google Workspace configuration")).toBeInTheDocument();
    expect(
      screen.getByText("Tenant-owned OAuth setup for Calendar, Gmail, and Drive."),
    ).toBeInTheDocument();
    expect(await screen.findByTestId("google-workspace-setup")).toBeInTheDocument();
    expect(screen.getByText("Google Workspace")).toBeInTheDocument();
    expect(screen.getByTestId("google-workspace-google_calendar")).toHaveTextContent(
      "Calendar",
    );
    expect(screen.getByTestId("google-workspace-gmail")).toHaveTextContent("Gmail");
    expect(screen.getByTestId("google-workspace-google_drive")).toHaveTextContent(
      "Drive",
    );
    fireEvent.click(screen.getByTestId("google-drive-list-files"));
    expect(await screen.findByText("Signed vakalatnama.pdf")).toBeInTheDocument();
    expect(await screen.findByText("Pine Labs Plural")).toBeInTheDocument();
    expect(screen.getByText("SendGrid")).toBeInTheDocument();
    expect(screen.queryByText(/gross profit/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/gross margin/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/internal cost/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/payment MDR/i)).not.toBeInTheDocument();
  });

  it("saves and tests tenant Google Workspace configuration from the UI", async () => {
    renderWithQuery(<TenantIntegrationsPage />);

    const clientId = await screen.findByTestId("google-workspace-client-id");
    fireEvent.change(clientId, { target: { value: "new-google-client" } });
    fireEvent.change(screen.getByTestId("google-workspace-client-secret"), {
      target: { value: "new-google-secret" },
    });
    fireEvent.change(screen.getByTestId("google-calendar-redirect-uri"), {
      target: { value: "https://tenant.example/calendar/callback" },
    });
    fireEvent.change(screen.getByTestId("gmail-redirect-uri"), {
      target: { value: "https://tenant.example/gmail/callback" },
    });
    fireEvent.change(screen.getByTestId("google-drive-redirect-uri"), {
      target: { value: "https://tenant.example/drive/callback" },
    });
    fireEvent.click(screen.getByTestId("google-workspace-save"));

    await screen.findByText("Google Workspace");
    await waitFor(() => {
      const saveCall = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).includes("/api/admin/google-workspace-configuration") &&
          init?.method === "PATCH",
      );
      expect(saveCall).toBeTruthy();
      const body = JSON.parse(String(saveCall?.[1]?.body));
      expect(body).toEqual(
        expect.objectContaining({
          client_id: "new-google-client",
          client_secret: "new-google-secret",
          calendar_redirect_uri: "https://tenant.example/calendar/callback",
          gmail_redirect_uri: "https://tenant.example/gmail/callback",
          drive_redirect_uri: "https://tenant.example/drive/callback",
        }),
      );
    });

    fireEvent.click(screen.getByTestId("google-workspace-test"));
    expect(await screen.findByTestId("google-workspace-test-results")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/admin/google-workspace-configuration/test"),
        expect.objectContaining({ method: "POST" }),
      );
    });
  });
});
