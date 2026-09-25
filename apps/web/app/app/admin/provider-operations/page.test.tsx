import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult, screen, waitFor, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchProviderReadinessMock,
  ignoreProviderOperationMock,
  listProviderOperationsMock,
  markProviderOperationResolvedMock,
  previewProviderOperationReplayMock,
  replayProviderOperationMock,
  resolveCaseTrackingProviderIncidentMock,
  toastError,
  toastSuccess,
  useCapabilityMock,
} = vi.hoisted(() => ({
  fetchProviderReadinessMock: vi.fn(),
  ignoreProviderOperationMock: vi.fn(),
  listProviderOperationsMock: vi.fn(),
  markProviderOperationResolvedMock: vi.fn(),
  previewProviderOperationReplayMock: vi.fn(),
  replayProviderOperationMock: vi.fn(),
  resolveCaseTrackingProviderIncidentMock: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchProviderReadiness: fetchProviderReadinessMock,
  ignoreProviderOperation: ignoreProviderOperationMock,
  listProviderOperations: listProviderOperationsMock,
  markProviderOperationResolved: markProviderOperationResolvedMock,
  previewProviderOperationReplay: previewProviderOperationReplayMock,
  replayProviderOperation: replayProviderOperationMock,
  resolveCaseTrackingProviderIncident: resolveCaseTrackingProviderIncidentMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: useCapabilityMock,
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import ProviderOperationsPage from "@/app/app/admin/provider-operations/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

// Mutation tests query only inside their own render container. If a test ever
// overruns its deadline, cleanup() empties that container and the abandoned
// user flow fails on its next query instead of driving the next test's page.
function renderOperationsPage() {
  const view = render(withClient(<ProviderOperationsPage />));
  return { view, page: within(view.container) };
}

// Radix portal content stays queryable after React detaches it, so every query
// on a portal scope first requires this test's page and the portal to be mounted.
function mountedWithin(view: RenderResult, element: HTMLElement) {
  const queries = within(element);
  return new Proxy(queries, {
    get(target, key) {
      const query = Reflect.get(target, key);
      if (typeof query !== "function") return query;
      return (...args: unknown[]) => {
        expect(view.container).toBeInTheDocument();
        expect(element).toBeInTheDocument();
        return query(...args);
      };
    },
  });
}

// Radix portals the action dialog to document.body, outside the container.
// Resolve the single open dialog only while this test's page is still mounted,
// then scope to it. A plain attribute lookup keeps a cold accessible-role query
// out of the polling deadline.
async function ownDialog(view: RenderResult) {
  const element = await waitFor(() => {
    expect(view.container).toBeInTheDocument();
    const dialogs = document.querySelectorAll<HTMLElement>('[role="dialog"]');
    expect(dialogs).toHaveLength(1);
    return dialogs[0];
  });
  return { element, dialog: mountedWithin(view, element) };
}

// One paste per field: the field still receives focus and a real input event,
// but the page re-renders once per field instead of once per character.
// Paste targets whichever element has focus, so require focus first: an
// abandoned flow holding a detached field fails here instead of pasting into
// the next test's focused input.
async function enterText(user: UserEvent, field: HTMLElement, value: string) {
  await user.click(field);
  expect(field).toHaveFocus();
  await user.paste(value);
  expect(field).toHaveDisplayValue(value);
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
  correlation_ref: "id:correlation",
  response_class: "provider_outage",
  last_attempted_at: "2026-06-02T00:00:00Z",
  last_successful_at: null,
  last_good_at: null,
  next_scheduled_at: null,
  freshness_state: "never_succeeded",
  records_affected: null,
  estimated_cost_minor: 0,
  estimated_cost_currency: "INR",
  estimated_cost_basis: "internal_idempotent_delivery",
  retryable: true,
  quarantined: true,
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
    {
      provider: "ecourtsindia",
      display_name: "eCourtsIndia case tracking",
      adp_slice: "IPLF-050",
      state: "ready",
      configured: true,
      enabled: true,
      external_calls_enabled: true,
      durable_workflow_available: true,
      required_config_names: [],
      missing_config_names: [],
      required_approval_keys: [],
      missing_approval_keys: [],
      endpoint_paths: ["/api/case-tracking/search"],
      idempotency_fields: ["tracked_case_id"],
      change_detection_fields: ["normalized_record_hash"],
      review_queue: "TrackedCase provider operations",
      retry_dead_letter: "Shared guarded replay is available.",
      limitations: [],
      adapter_contract: {
        provider: "ecourtsindia",
        display_name: "eCourtsIndia case tracking",
        domain: "court_tracking",
        adapter_status: "implemented",
        commercial_terms_status: "support_matrix_governed",
        required_capabilities: ["search", "record_fetch", "health"],
        implemented_capabilities: ["search", "record_fetch", "health"],
        attribution_label: "eCourtsIndia provider-normalized court record",
        cost_categories: ["case_refresh"],
        health_path: "/api/admin/integrations/health",
        support_matrix_path: "/api/case-tracking/support-matrix",
        operations_path: "/api/admin/provider-operations/jobs",
        endpoint_paths: ["/api/case-tracking/search"],
        legal_coverage: [],
        activation_blockers: [],
        limitations: [],
      },
    },
    {
      provider: "indian-kanoon",
      display_name: "Indian Kanoon licensed API",
      adp_slice: "IPLF-054",
      state: "blocked_missing_config",
      configured: false,
      enabled: false,
      external_calls_enabled: false,
      durable_workflow_available: true,
      required_config_names: ["INDIAN_KANOON_API_TOKEN"],
      missing_config_names: ["INDIAN_KANOON_API_TOKEN"],
      required_approval_keys: [],
      missing_approval_keys: [],
      endpoint_paths: ["/api/authorities/providers/indian-kanoon/search"],
      idempotency_fields: ["company_id", "document_id"],
      change_detection_fields: ["content_hash"],
      review_queue: "Authority legal-source review",
      retry_dead_letter: "Shared guarded replay is available.",
      limitations: ["No public HTML scraping."],
      adapter_contract: {
        provider: "indian-kanoon",
        display_name: "Indian Kanoon licensed API",
        domain: "legal_research",
        adapter_status: "implemented_default_off",
        commercial_terms_status: "runtime_metadata_governed",
        required_capabilities: ["search", "document"],
        implemented_capabilities: ["search", "document"],
        attribution_label: "Powered by Indian Kanoon",
        cost_categories: ["legal_source_search"],
        health_path: "/api/authorities/providers/indian-kanoon/health",
        support_matrix_path: "/api/authorities/providers/indian-kanoon/readiness",
        operations_path: "/api/admin/provider-operations/jobs",
        endpoint_paths: ["/api/authorities/providers/indian-kanoon/search"],
        legal_coverage: [],
        activation_blockers: [
          "provider_terms_metadata_not_configured",
          "provider_credentials_not_configured",
          "permitted_uses_not_configured",
          "verified_actual_cost_profiles_not_configured",
        ],
        limitations: ["No public HTML scraping."],
      },
    },
  ],
};

describe("ProviderOperationsPage", () => {
  beforeEach(() => {
    fetchProviderReadinessMock.mockReset();
    ignoreProviderOperationMock.mockReset();
    listProviderOperationsMock.mockReset();
    markProviderOperationResolvedMock.mockReset();
    previewProviderOperationReplayMock.mockReset();
    replayProviderOperationMock.mockReset();
    resolveCaseTrackingProviderIncidentMock.mockReset();
    useCapabilityMock.mockReset();
    toastError.mockReset();
    toastSuccess.mockReset();
    useCapabilityMock.mockReturnValue(true);
    listProviderOperationsMock.mockResolvedValue({
      operations: [operation],
      open_count: 1,
      ignored_count: 0,
      resolved_count: 0,
      replayable_count: 1,
    });
    fetchProviderReadinessMock.mockResolvedValue(readiness);
    previewProviderOperationReplayMock.mockResolvedValue({
      preview_token: "signed-preview-token-value",
      expires_at: "2026-06-02T00:05:00Z",
      operation_count: 1,
      estimated_total_cost_minor: 0,
      currency: "INR",
      items: [
        {
          operation,
          expected_updated_at: operation.updated_at,
          estimated_cost_minor: 0,
          currency: "INR",
          cost_basis: "internal_idempotent_delivery",
        },
      ],
      warnings: [],
    });
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
    expect(await screen.findByTestId("readiness-ecourtsindia")).toHaveTextContent(
      "3/3 capabilities",
    );
    expect(screen.getByTestId("readiness-ecourtsindia")).toHaveTextContent(
      "/api/case-tracking/support-matrix",
    );
    expect(await screen.findByTestId("readiness-indian-kanoon")).toHaveTextContent(
      "legal research",
    );
    expect(screen.getByTestId("readiness-indian-kanoon")).toHaveTextContent(
      "implemented default off",
    );
    expect(await screen.findByTestId(`provider-operation-${operation.id}`)).toBeInTheDocument();
    expect(screen.getByText("[token-redacted] at [url-redacted]")).toBeInTheDocument();
    expect(screen.queryByText(/secret-token/i)).not.toBeInTheDocument();
  });

  it("renders IP registry, journal, and source-health failures without unsafe actions", async () => {
    const ipOperations = [
      {
        ...operation,
        id: "ip_registry_sync:attempt-1",
        job_kind: "ip_registry_sync" as const,
        provider: "ipindia-registry",
        source_type: "ip_registry_link",
        status: "failed",
        response_class: "authentication" as const,
        freshness_state: "stale" as const,
        estimated_cost_basis: "recorded_registry_attempt",
        retryable: false,
        quarantined: false,
        replay_available: false,
        ignore_available: false,
        mark_resolved_available: false,
        automatic_replay_block_code: "provider_replay_not_activated",
      },
      {
        ...operation,
        id: "ip_journal_ingestion:run-1",
        job_kind: "ip_journal_ingestion" as const,
        provider: "ipindia-journal",
        source_type: "ip_journal_publication",
        status: "paused_cost_quota",
        response_class: "rate_limit" as const,
        freshness_state: "stale" as const,
        estimated_cost_minor: 275,
        estimated_cost_basis: "recorded_journal_ingestion",
        retryable: false,
        quarantined: false,
        replay_available: false,
        ignore_available: false,
        mark_resolved_available: false,
        automatic_replay_block_code: "journal_payload_not_retained_for_replay",
      },
      {
        ...operation,
        id: "source_link_health:report-1",
        job_kind: "source_link_health" as const,
        provider: "source-actions",
        source_type: "authority_document",
        status: "queued",
        response_class: "changed_content" as const,
        freshness_state: "blocked" as const,
        estimated_cost_basis: "internal_source_health_review",
        retryable: false,
        quarantined: true,
        replay_available: false,
        ignore_available: true,
        mark_resolved_available: true,
        automatic_replay_block_code: "source_health_requires_fresh_inspection",
      },
    ];
    listProviderOperationsMock.mockResolvedValue({
      operations: ipOperations,
      open_count: 3,
      ignored_count: 0,
      resolved_count: 0,
      replayable_count: 0,
    });

    render(withClient(<ProviderOperationsPage />));

    expect(
      await screen.findByTestId("provider-operation-ip_registry_sync:attempt-1"),
    ).toHaveTextContent("authentication");
    expect(
      screen.getByTestId("provider-operation-ip_journal_ingestion:run-1"),
    ).toHaveTextContent("INR 2.75");
    expect(
      screen.getByTestId("provider-operation-source_link_health:report-1"),
    ).toHaveTextContent("changed content");
    expect(
      screen.getByTestId("provider-operation-replay-ip_registry_sync:attempt-1"),
    ).toBeDisabled();
    expect(
      screen.getByTestId("provider-operation-resolve-source_link_health:report-1"),
    ).toBeEnabled();
    expect(screen.queryByText(/provider\.example|bearer|lawyer@/i)).not.toBeInTheDocument();
  });

  it("requests replay through the guarded provider operation endpoint", async () => {
    const user = userEvent.setup();
    const { view, page } = renderOperationsPage();
    await user.click(await page.findByTestId(`provider-operation-replay-${operation.id}`));
    expect(replayProviderOperationMock).not.toHaveBeenCalled();
    const { element: dialogElement, dialog } = await ownDialog(view);
    expect(dialog.getByText("Replay provider operation")).toBeInTheDocument();
    expect(await dialog.findByText(/Scope: 1 operation/i)).toBeInTheDocument();
    expect(previewProviderOperationReplayMock).toHaveBeenCalledTimes(1);
    expect(previewProviderOperationReplayMock.mock.calls[0][0]).toEqual({
      operationIds: [operation.id],
    });
    const confirm = dialog.getByTestId("provider-operation-confirm-action");
    expect(confirm).toBeDisabled();
    await enterText(
      user,
      dialog.getByLabelText("Reason"),
      "Reviewed provider failure and approved replay.",
    );
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith("Notification intent was queued."),
    );
    expect(replayProviderOperationMock).toHaveBeenCalledTimes(1);
    expect(replayProviderOperationMock.mock.calls[0][0]).toEqual({
      operationId: operation.id,
      previewToken: "signed-preview-token-value",
      reason: "Reviewed provider failure and approved replay.",
    });
    expect(previewProviderOperationReplayMock).toHaveBeenCalledTimes(1);
    expect(ignoreProviderOperationMock).not.toHaveBeenCalled();
    expect(markProviderOperationResolvedMock).not.toHaveBeenCalled();
    expect(resolveCaseTrackingProviderIncidentMock).not.toHaveBeenCalled();
    expect(toastError).not.toHaveBeenCalled();
    // The settled mutation closes the dialog, refreshes the jobs and frees the row.
    await waitFor(() => expect(dialogElement).not.toBeInTheDocument());
    await waitFor(() => expect(listProviderOperationsMock).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(page.getByTestId(`provider-operation-replay-${operation.id}`)).toBeEnabled(),
    );
  });

  it("requires root cause, prevention, and canary evidence for tracked-case closure", async () => {
    const user = userEvent.setup();
    const trackingOperation = {
      ...operation,
      id: "case_tracking_record:tracking-op-1",
      job_kind: "case_tracking_record" as const,
      provider: "ecourtsindia",
      status: "replay_queued",
      replay_available: false,
      mark_resolved_available: true,
    };
    listProviderOperationsMock.mockResolvedValue({
      operations: [trackingOperation],
      open_count: 1,
      ignored_count: 0,
      resolved_count: 0,
      replayable_count: 0,
    });
    resolveCaseTrackingProviderIncidentMock.mockResolvedValue({
      action: "mark_resolved",
      changed: true,
      message: "Tracked-case provider incident closed with successful canary evidence.",
      operation: { ...trackingOperation, status: "resolved" },
    });

    const { view, page } = renderOperationsPage();
    await user.click(
      await page.findByTestId(`provider-operation-resolve-${trackingOperation.id}`),
    );
    const { element: dialogElement, dialog } = await ownDialog(view);
    const confirm = dialog.getByTestId("provider-operation-confirm-action");
    await enterText(
      user,
      dialog.getByLabelText("Reason"),
      "Provider authentication expired before the polling window.",
    );
    expect(confirm).toBeDisabled();
    await enterText(
      user,
      dialog.getByLabelText("Prevention"),
      "Alert before credentials expire and block affected polling.",
    );
    expect(confirm).toBeDisabled();
    await enterText(
      user,
      dialog.getByLabelText("Canary evidence"),
      "Single-record replay succeeded and remained healthy.",
    );
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith(
        "Tracked-case provider incident closed with successful canary evidence.",
      ),
    );
    expect(resolveCaseTrackingProviderIncidentMock).toHaveBeenCalledTimes(1);
    expect(resolveCaseTrackingProviderIncidentMock.mock.calls[0][0]).toEqual({
      operationId: trackingOperation.id,
      rootCause: "Provider authentication expired before the polling window.",
      prevention: "Alert before credentials expire and block affected polling.",
      canaryEvidence: "Single-record replay succeeded and remained healthy.",
    });
    expect(markProviderOperationResolvedMock).not.toHaveBeenCalled();
    expect(previewProviderOperationReplayMock).not.toHaveBeenCalled();
    expect(replayProviderOperationMock).not.toHaveBeenCalled();
    expect(ignoreProviderOperationMock).not.toHaveBeenCalled();
    expect(toastError).not.toHaveBeenCalled();
    // The settled mutation closes the dialog, refreshes the jobs and frees the row.
    await waitFor(() => expect(dialogElement).not.toBeInTheDocument());
    await waitFor(() => expect(listProviderOperationsMock).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(
        page.getByTestId(`provider-operation-resolve-${trackingOperation.id}`),
      ).toBeEnabled(),
    );
  });
});
