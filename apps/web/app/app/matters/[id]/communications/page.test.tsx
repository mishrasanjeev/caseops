import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchTimelineMock,
  createCommunicationMock,
  listTemplatesMock,
  renderTemplateMock,
  sendEmailMock,
  useCapabilityMock,
  toastSuccess,
  toastError,
} = vi.hoisted(() => ({
  fetchTimelineMock: vi.fn(),
  createCommunicationMock: vi.fn(),
  listTemplatesMock: vi.fn(),
  renderTemplateMock: vi.fn(),
  sendEmailMock: vi.fn(),
  useCapabilityMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchMatterCommunicationTimeline: fetchTimelineMock,
  createMatterCommunication: createCommunicationMock,
  listEmailTemplates: listTemplatesMock,
  renderEmailTemplate: renderTemplateMock,
  sendMatterEmail: sendEmailMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (cap: string) => useCapabilityMock(cap),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m1" }),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import MatterCommunicationsPage from "@/app/app/matters/[id]/communications/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("MatterCommunicationsPage", () => {
  beforeEach(() => {
    fetchTimelineMock.mockReset();
    createCommunicationMock.mockReset();
    listTemplatesMock.mockReset();
    renderTemplateMock.mockReset();
    sendEmailMock.mockReset();
    useCapabilityMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
    useCapabilityMock.mockImplementation((cap: string) => cap === "communications:write");
    listTemplatesMock.mockResolvedValue({ templates: [] });
    fetchTimelineMock.mockResolvedValue({
      matter_id: "m1",
      filter: "all",
      generated_at: "2026-05-23T00:00:00Z",
      items: [
        {
          id: "communication:c1",
          item_type: "imported_email",
          visibility: "imported_email",
          occurred_at: "2026-05-15T10:30:00Z",
          title: "Filing instructions",
          preview: "Client sent filing instructions and a notice attachment.",
          actor_label: "Client Sender",
          direction: "inbound",
          channel: "email",
          status: "logged",
          thread_key: "manual:thread-777",
          source_type: "communication",
          source_id: "c1",
          communication_id: "c1",
          metadata: {
            thread_message_count: 1,
            has_attachments: true,
            body_is_preview: true,
          },
        },
        {
          id: "note:n1",
          item_type: "internal_note",
          visibility: "internal",
          occurred_at: "2026-05-15T11:00:00Z",
          title: "Internal note",
          preview: "Firm-only follow-up.",
          actor_label: "Firm user",
          source_type: "matter_note",
          source_id: "n1",
          note_id: "n1",
          metadata: { internal_only: true },
        },
        {
          id: "attachment:a1",
          item_type: "attachment",
          visibility: "imported_email",
          occurred_at: "2026-05-15T11:05:00Z",
          title: "Attachment: notice.pdf",
          preview: "Attachment imported from a manually selected email.",
          actor_label: "Attachment reference",
          thread_key: "manual:thread-777",
          source_type: "imported_email_attachment",
          source_id: "a1",
          communication_id: "c1",
          attachment_id: "a1",
          attachment: {
            id: "a1",
            filename: "notice.pdf",
            content_type: "application/pdf",
            size_bytes: 2048,
            document_type: "correspondence",
            uploaded_by_membership_id: "membership-1",
            submitted_by_portal_user_id: null,
            created_at: "2026-05-15T11:05:00Z",
          },
          metadata: {
            size_bytes: 2048,
            is_email_body_attachment: false,
            from_imported_email: true,
          },
        },
      ],
    });
  });

  it("renders imported email, internal note, and attachment timeline rows", async () => {
    render(withClient(<MatterCommunicationsPage />));

    expect(await screen.findByText("Filing instructions")).toBeInTheDocument();
    expect(screen.getAllByText("Internal note").length).toBeGreaterThan(0);
    expect(screen.getByText("notice.pdf")).toBeInTheDocument();
    expect(screen.getAllByText("Imported email").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Internal").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Threaded").length).toBeGreaterThan(0);
  });

  it("requests filtered timeline data when the filter changes", async () => {
    render(withClient(<MatterCommunicationsPage />));

    await waitFor(() =>
      expect(fetchTimelineMock).toHaveBeenCalledWith({
        matterId: "m1",
        filter: "all",
      }),
    );

    fireEvent.click(screen.getByTestId("comm-timeline-filter-attachments"));

    await waitFor(() =>
      expect(fetchTimelineMock).toHaveBeenLastCalledWith({
        matterId: "m1",
        filter: "attachments",
      }),
    );
  });
});
