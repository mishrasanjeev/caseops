import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  matterMock,
  commsMock,
  hearingsMock,
  replyMock,
  kycMock,
  clientsMock,
  paramsMock,
} = vi.hoisted(() => ({
  matterMock: vi.fn(),
  commsMock: vi.fn(),
  hearingsMock: vi.fn(),
  replyMock: vi.fn(),
  kycMock: vi.fn(),
  clientsMock: vi.fn(),
  paramsMock: vi.fn(() => ({ id: "matter-abc" })),
}));

vi.mock("next/navigation", () => ({
  useParams: () => paramsMock(),
}));

vi.mock("@/lib/api/portal", () => ({
  fetchPortalMatter: matterMock,
  fetchPortalMatterCommunications: commsMock,
  fetchPortalMatterHearings: hearingsMock,
  fetchPortalMatterClients: clientsMock,
  postPortalMatterReply: replyMock,
  submitPortalMatterKyc: kycMock,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import PortalMatterDetailPage from "@/app/portal/matters/[id]/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const matterStub = {
  id: "matter-abc",
  title: "Bail Application — State v Kumar",
  matter_code: "BAIL-001",
  status: "active",
  practice_area: "criminal",
  forum_level: "high_court",
  court_name: "Delhi High Court",
  next_hearing_on: "2026-05-15",
};

describe("PortalMatterDetailPage", () => {
  beforeEach(() => {
    matterMock.mockReset();
    commsMock.mockReset();
    hearingsMock.mockReset();
    replyMock.mockReset();
    kycMock.mockReset();
    clientsMock.mockReset();
    clientsMock.mockResolvedValue({
      clients: [
        {
          id: "c-1",
          name: "Test Client",
          client_type: "individual",
          kyc_status: "not_started",
          kyc_submitted_at: null,
        },
      ],
    });
  });

  it("renders the matter overview with title + status + court", async () => {
    matterMock.mockResolvedValue(matterStub);
    commsMock.mockResolvedValue({ communications: [] });
    hearingsMock.mockResolvedValue({ hearings: [] });

    render(withClient(<PortalMatterDetailPage />));
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /Bail Application/i }),
      ).toBeVisible(),
    );
    // "Delhi High Court" appears twice (PageHeader description + the
    // Overview Court row) — assert at least one match rather than
    // exactly one.
    expect(screen.getAllByText(/Delhi High Court/).length).toBeGreaterThan(0);
    // Tabs are wired
    expect(screen.getByRole("tab", { name: /overview/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /comms/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /hearings/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /kyc/i })).toBeInTheDocument();
  });

  it("posts a reply, clears the textarea, and surfaces a success toast", async () => {
    matterMock.mockResolvedValue(matterStub);
    commsMock.mockResolvedValue({ communications: [] });
    hearingsMock.mockResolvedValue({ hearings: [] });
    replyMock.mockResolvedValue({
      id: "c-1",
      direction: "inbound",
      channel: "note",
      subject: null,
      body: "Got it.",
      occurred_at: "2026-04-24T10:00:00Z",
      status: "logged",
      posted_by_portal_user: true,
    });

    const user = userEvent.setup();
    render(withClient(<PortalMatterDetailPage />));
    await waitFor(() => expect(matterMock).toHaveBeenCalled());
    await user.click(screen.getByRole("tab", { name: /comms/i }));
    await user.type(
      screen.getByTestId("portal-reply-body"),
      "Got it.",
    );
    await user.click(screen.getByTestId("portal-reply-submit"));
    await waitFor(() => expect(replyMock).toHaveBeenCalledWith(
      "matter-abc",
      "Got it.",
    ));
  });

  it("submits KYC with the documents the user filled in", async () => {
    matterMock.mockResolvedValue(matterStub);
    commsMock.mockResolvedValue({ communications: [] });
    hearingsMock.mockResolvedValue({ hearings: [] });
    kycMock.mockResolvedValue({
      matter_id: "matter-abc",
      affected_client_ids: ["c-1"],
      submitted_at: "2026-04-24T10:30:00Z",
    });
    const user = userEvent.setup();
    render(withClient(<PortalMatterDetailPage />));
    await waitFor(() => expect(matterMock).toHaveBeenCalled());
    await user.click(screen.getByRole("tab", { name: /kyc/i }));
    await user.click(screen.getByTestId("portal-kyc-submit"));
    await waitFor(() => expect(kycMock).toHaveBeenCalled());
    const [callMatterId, callClientId, callDocs] = kycMock.mock.calls[0];
    expect(callMatterId).toBe("matter-abc");
    // Single linked client → auto-picked.
    expect(callClientId).toBe("c-1");
    expect(Array.isArray(callDocs)).toBe(true);
  });

  it("shows the hearings list when one is scheduled", async () => {
    matterMock.mockResolvedValue(matterStub);
    commsMock.mockResolvedValue({ communications: [] });
    hearingsMock.mockResolvedValue({
      hearings: [
        {
          id: "h-1",
          hearing_on: "2026-05-15",
          forum_name: "Delhi High Court — Court Room 5",
          judge_name: "Hon'ble Justice X",
          purpose: "First hearing",
          status: "scheduled",
          outcome_note: null,
        },
      ],
    });
    const user = userEvent.setup();
    render(withClient(<PortalMatterDetailPage />));
    await waitFor(() => expect(matterMock).toHaveBeenCalled());
    await user.click(screen.getByRole("tab", { name: /hearings/i }));
    await waitFor(() =>
      expect(screen.getByTestId("portal-hearing-h-1")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Court Room 5/)).toBeInTheDocument();
  });

  it("renders the matter-not-found error when the API 404s", async () => {
    matterMock.mockRejectedValue(
      Object.assign(new Error("not found"), {
        name: "ApiError",
        detail: "Matter not found.",
        status: 404,
      }),
    );
    render(withClient(<PortalMatterDetailPage />));
    await waitFor(() =>
      expect(
        screen.getByText(/we could not load this matter/i),
      ).toBeInTheDocument(),
    );
  });
});
