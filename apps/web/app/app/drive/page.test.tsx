import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/config";
import { driveCandidateListResponse, googleDriveStatusResponse } from "@/lib/api/schemas";

const mocks = vi.hoisted(() => ({
  status: vi.fn(), candidates: vi.fn(), review: vi.fn(), toast: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchGoogleDriveStatus: mocks.status, fetchDriveCandidates: mocks.candidates,
  reviewDriveCandidate: mocks.review, startGoogleDriveConnection: vi.fn(),
  syncGoogleDriveCandidates: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { error: mocks.toast, success: vi.fn() } }));

import DrivePage from "./page";

describe("DrivePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.candidates.mockResolvedValue(driveCandidateListResponse.parse({ candidates: [{
      id: "candidate", company_id: "company", provider_file_id: "reviewed-file",
      provider_version: "2026-10-08T00:00:00+00:00",
      name: "reviewed.txt", provider: "google_drive", status: "new",
      suggested_matter_id: "matter", size_bytes: 25, mime_type: "text/plain",
      owner_display: null, modified_time: "2026-10-08T00:00:00Z",
      folder_path: "reviewed-evidence", web_url: null, linked_matter_id: null,
      confidence: 1, imported_attachment_id: null, provenance: {}, last_error_redacted: null,
      created_at: "2026-10-08T00:00:00Z", updated_at: "2026-10-08T00:00:00Z",
    }], pending_count: 1 }));
  });

  it("exports the Drive review queue page", () => {
    expect(DrivePage).toBeTypeOf("function");
  });

  it("refreshes connector state after Import rejects revoked Google consent", async () => {
    let status = "connected";
    mocks.status.mockImplementation(async () => googleDriveStatusResponse.parse({
      provider: "google_drive", configured: true, missing_config_names: [],
      connections: [{
        id: "connection", company_id: "company", membership_id: "owner", provider: "google_drive",
        provider_account_id: "offline-owner", display_email: "drive-owner@example.com", status,
        scopes: ["https://www.googleapis.com/auth/drive.readonly"],
        connected_at: "2026-10-08T00:00:00Z", last_list_at: null,
        created_at: "2026-10-08T00:00:00Z", updated_at: "2026-10-08T00:00:00Z",
      }],
    }));
    mocks.review.mockImplementation(async () => {
      status = "error";
      throw new ApiError(409, "Google authorization expired or was revoked. Reconnect this account.", {});
    });
    const client = new QueryClient({ defaultOptions: {
      queries: { retry: false }, mutations: { retry: false },
    } });
    render(<QueryClientProvider client={client}><DrivePage /></QueryClientProvider>);
    const sync = await screen.findByRole("button", { name: "Sync Google Drive" });
    await waitFor(() => expect(sync).toBeEnabled());
    await userEvent.click(await screen.findByRole("button", { name: /^Import$/ }));
    await waitFor(() => expect(mocks.status).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("status")).toHaveTextContent("authorization needs to be reconnected");
    expect(screen.getByRole("button", { name: "Reconnect Google Drive" })).toBeEnabled();
    expect(sync).toBeDisabled();
    expect(mocks.review).toHaveBeenCalledTimes(1);
    expect(mocks.toast).toHaveBeenCalledWith("Google authorization expired or was revoked. Reconnect this account.");
  });
});
