import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchProviderReadinessMock,
  ignoreProviderOperationMock,
  listProviderOperationsMock,
  markProviderOperationResolvedMock,
  replayProviderOperationMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  fetchProviderReadinessMock: vi.fn(),
  ignoreProviderOperationMock: vi.fn(),
  listProviderOperationsMock: vi.fn(),
  markProviderOperationResolvedMock: vi.fn(),
  replayProviderOperationMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchProviderReadiness: fetchProviderReadinessMock,
  ignoreProviderOperation: ignoreProviderOperationMock,
  listProviderOperations: listProviderOperationsMock,
  markProviderOperationResolved: markProviderOperationResolvedMock,
  replayProviderOperation: replayProviderOperationMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: useCapabilityMock,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import ProviderOperationsPage from "@/app/app/admin/provider-operations/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const operation = {
  id: "notification_delivery:intent-1",
  job_kind: "notification_delivery",
  provider: "in_app",
  company_id: "company-1",
  matter_id: "matter-1",
  source_type: "legal_update_alert",
  source_ref: "id:abc123",
  provider_item_ref: null,
  status: "dead_letter",
  operator_state: "open",
  error_redacted: "[token-redacted] at [url-redacted]",
  dead_letter_reason: "retry_limit_exhausted",
  attempts: 3,
  max_attempts: 3,
  next_attempt_at: null,
  created_at: "2026-06-02T00:00:00Z",
  updated_at: "2026-06-02T00:00:00Z",
  replay_available: true,
  ignore_available: true,
  mark_resolved_available: true,
  notes: ["Replay uses the existing idempotency key."],
};

const readiness = {
  providers: [
    {
      provider: "google_drive",
      display_name: "Google Drive sync",
      adp_slice: "ADP-21",
      state: "blocked_missing_config",
      configured: false,
      enabled: false,
      external_calls_enabled: false,
      durable_workflow_available: false,
      required_config_names: ["GOOGLE_DRIVE_CLIENT_SECRET"],
      missing_config_names: ["GOOGLE_DRIVE_CLIENT_SECRET"],
      required_approval_keys: ["tenant_drive_sync_approved"],
      missing_approval_keys: ["tenant_drive_sync_approved"],
      endpoint_paths: ["/api/matters/imports/drive/provider-config"],
      idempotency_fields: ["provider_file_id"],
      change_detection_fields: ["modified_time"],
      review_queue: "planned",
      retry_dead_letter: "ADP-24 provider operations replay is available.",
      limitations: ["No external calls."],
    },
  ],
};

describe("ProviderOperationsPage", () => {
  beforeEach(() => {
    fetchProviderReadinessMock.mockReset();
    ignoreProviderOperationMock.mockReset();
    listProviderOperationsMock.mockReset();
    markProviderOperationResolvedMock.mockReset();
    replayProviderOperationMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockReturnValue(true);
    listProviderOperationsMock.mockResolvedValue({
      operations: [operation],
      open_count: 1,
      ignored_count: 0,
      resolved_count: 0,
      replayable_count: 1,
    });
    fetchProviderReadinessMock.mockResolvedValue(readiness);
    replayProviderOperationMock.mockResolvedValue({
      action: "replay",
      changed: true,
      message: "Notification intent was queued.",
      operation: { ...operation, status: "queued", replay_available: false },
    });
  });

  it("renders access refusal when caller is not a workspace admin", () => {
    useCapabilityMock.mockReturnValue(false);
    render(withClient(<ProviderOperationsPage />));
    expect(screen.getByText(/Workspace admin required/i)).toBeInTheDocument();
    expect(listProviderOperationsMock).not.toHaveBeenCalled();
  });

  it("shows provider readiness and redacted operations", async () => {
    render(withClient(<ProviderOperationsPage />));
    expect(await screen.findByText("Provider operations")).toBeInTheDocument();
    expect(await screen.findByTestId("readiness-google_drive")).toBeInTheDocument();
    expect(await screen.findByTestId(`provider-operation-${operation.id}`)).toBeInTheDocument();
    expect(screen.getByText("[token-redacted] at [url-redacted]")).toBeInTheDocument();
    expect(screen.queryByText(/secret-token/i)).not.toBeInTheDocument();
  });

  it("requests replay through the guarded provider operation endpoint", async () => {
    const user = userEvent.setup();
    render(withClient(<ProviderOperationsPage />));
    await user.click(await screen.findByTestId(`provider-operation-replay-${operation.id}`));
    expect(replayProviderOperationMock).not.toHaveBeenCalled();
    expect(screen.getByText("Replay provider operation")).toBeInTheDocument();
    const confirm = screen.getByTestId("provider-operation-confirm-action");
    expect(confirm).toBeDisabled();
    await user.type(
      screen.getByLabelText("Reason"),
      "Reviewed provider failure and approved replay.",
    );
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    await waitFor(() =>
      expect(replayProviderOperationMock).toHaveBeenCalled(),
    );
    expect(replayProviderOperationMock.mock.calls[0][0]).toEqual({
      operationId: operation.id,
      reason: "Reviewed provider failure and approved replay.",
    });
  });
});
