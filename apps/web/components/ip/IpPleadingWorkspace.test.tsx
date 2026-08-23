import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  createMock,
  downloadMock,
  generateMock,
  listDraftsMock,
  listTemplatesMock,
  saveMock,
  transitionMock,
} = vi.hoisted(() => ({
  createMock: vi.fn(),
  downloadMock: vi.fn(),
  generateMock: vi.fn(),
  listDraftsMock: vi.fn(),
  listTemplatesMock: vi.fn(),
  saveMock: vi.fn(),
  transitionMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  createIpPleadingDraft: createMock,
  downloadIpPleadingDraft: downloadMock,
  generateIpPleadingDraft: generateMock,
  listIpPleadingDrafts: listDraftsMock,
  listIpPleadingTemplates: listTemplatesMock,
  saveIpPleadingDraft: saveMock,
  transitionIpPleadingDraft: transitionMock,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { IpPleadingWorkspace } from "@/components/ip/IpPleadingWorkspace";

const draft = {
  id: "draft-1",
  company_id: "company-1",
  matter_id: null,
  ip_docket_id: "docket-1",
  ip_proceeding_id: "proceeding-1",
  created_by_membership_id: "membership-1",
  title: "Notice of opposition",
  draft_type: "notice" as const,
  template_type: "trademark_opposition_notice",
  status: "draft" as const,
  review_required: true,
  current_version_id: "version-1",
  versions: [{
    id: "version-1",
    draft_id: "draft-1",
    revision: 1,
    body: "NOTICE OF OPPOSITION\n\nGrounded pleading body [2026 SCC OnLine Del 450].",
    citations: ["2026 SCC OnLine Del 450"],
    verified_citation_count: 1,
    summary: "Generated with one authority.",
    generated_by_membership_id: "membership-1",
    model_run_id: "run-1",
    template_manifest: { key: "trademark_opposition_notice" },
    context_manifest: { docket: { id: "docket-1" } },
    source_manifest: [{
      document_version_id: "document-version-1",
      display_name: "Registry notice.pdf",
      sha256: "abc123",
    }],
    created_at: "2026-08-23T10:00:00Z",
  }],
  reviews: [],
  created_at: "2026-08-23T09:00:00Z",
  updated_at: "2026-08-23T10:00:00Z",
};

describe("IpPleadingWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listTemplatesMock.mockResolvedValue({
      templates: [{
        key: "trademark_opposition_notice",
        label: "Notice of opposition",
        version: "1.0",
        draft_type: "notice",
        allowed_sides: ["opponent"],
        allowed_stages: ["draft"],
        jurisdictions: ["IN"],
        format_profile: "india-trade-marks-registry-v1",
      }],
    });
    listDraftsMock.mockResolvedValue({ drafts: [draft], next_cursor: null });
    generateMock.mockResolvedValue(draft);
    saveMock.mockResolvedValue(draft);
    transitionMock.mockResolvedValue({ ...draft, status: "in_review" });
  });

  it("shows frozen sources and drives generation, editing, and submission", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <IpPleadingWorkspace
          docketId="docket-1"
          proceedingId="proceeding-1"
          canCreate
          canEdit
          canGenerate
          canReview
          canFinalize
        />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Trademark pleadings")).toBeVisible();
    expect(await screen.findByText("1 verified citation")).toBeVisible();
    fireEvent.click(screen.getByText("Frozen document versions"));
    expect(screen.getByText("Registry notice.pdf")).toBeVisible();
    expect(screen.getByText("abc123")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Generation focus"), {
      target: { value: "Emphasize the confirmed earlier-mark ground." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate revision" }));
    await waitFor(() => expect(generateMock).toHaveBeenCalledWith(
      expect.objectContaining({
        docketId: "docket-1",
        proceedingId: "proceeding-1",
        draftId: "draft-1",
        focusNote: "Emphasize the confirmed earlier-mark ground.",
      }),
      expect.any(Object),
    ));

    fireEvent.change(screen.getByLabelText("Pleading body"), {
      target: { value: `${draft.versions[0].body}\n\nLawyer revision.` },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save revision" }));
    await waitFor(() => expect(saveMock).toHaveBeenCalledOnce());

    fireEvent.change(screen.getByLabelText("Review notes"), {
      target: { value: "Ready for partner review." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(transitionMock).toHaveBeenCalledWith(
      expect.objectContaining({
        action: "submit",
        notes: "Ready for partner review.",
      }),
      expect.any(Object),
    ));
  });
});
