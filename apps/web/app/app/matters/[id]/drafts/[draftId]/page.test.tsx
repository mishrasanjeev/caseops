import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { ApiError } from "@/lib/api/config";

const {
  approveDraftMock,
  draftFilingBundleUrlMock,
  draftPdfUrlMock,
  fetchDraftMock,
  finalizeDraftMock,
  generateDraftVersionMock,
  listCourtFormatProfilesMock,
  requestDraftChangesMock,
  saveDraftEditsMock,
  submitDraftMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  approveDraftMock: vi.fn(),
  draftFilingBundleUrlMock: vi.fn(),
  draftPdfUrlMock: vi.fn(),
  fetchDraftMock: vi.fn(),
  finalizeDraftMock: vi.fn(),
  generateDraftVersionMock: vi.fn(),
  listCourtFormatProfilesMock: vi.fn(),
  requestDraftChangesMock: vi.fn(),
  saveDraftEditsMock: vi.fn(),
  submitDraftMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  approveDraft: approveDraftMock,
  draftDocxUrl: () => "https://api.test/draft.docx",
  draftFilingBundleUrl: draftFilingBundleUrlMock,
  draftPdfUrl: draftPdfUrlMock,
  fetchDraft: fetchDraftMock,
  finalizeDraft: finalizeDraftMock,
  generateDraftVersion: generateDraftVersionMock,
  listCourtFormatProfiles: listCourtFormatProfilesMock,
  requestDraftChanges: requestDraftChangesMock,
  saveDraftEdits: saveDraftEditsMock,
  submitDraft: submitDraftMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: useCapabilityMock,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m-1", draftId: "d-1" }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/components/drafting/DraftCompareView", () => ({
  DraftCompareView: () => <div data-testid="draft-compare" />,
}));

vi.mock("@/components/drafting/FilingChecklistCard", () => ({
  FilingChecklistCard: ({ courtProfile }: { courtProfile?: string }) => (
    <div
      data-testid="filing-checklist"
      data-court-profile={courtProfile ?? "auto"}
    />
  ),
}));

import DraftDetailPage from "@/app/app/matters/[id]/drafts/[draftId]/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const BASE_DRAFT = {
  id: "d-1",
  matter_id: "m-1",
  created_by_membership_id: "mem-1",
  title: "Bail application",
  draft_type: "brief" as const,
  template_type: "bail_application",
  status: "approved" as const,
  review_required: false,
  current_version_id: "v-1",
  versions: [
    {
      id: "v-1",
      draft_id: "d-1",
      revision: 1,
      body: "Original draft body citing 2024 SCC OnLine SC 777.",
      citations: ["2024 SCC OnLine SC 777"],
      verified_citation_count: 1,
      summary: null,
      generated_by_membership_id: "mem-1",
      model_run_id: "mr-1",
      created_at: "2026-05-04T08:00:00Z",
    },
  ],
  reviews: [
    {
      id: "r-1",
      draft_id: "d-1",
      version_id: "v-1",
      actor_membership_id: "mem-2",
      action: "approve" as const,
      notes: null,
      created_at: "2026-05-04T08:05:00Z",
    },
  ],
  created_at: "2026-05-04T07:59:00Z",
  updated_at: "2026-05-04T08:05:00Z",
};

describe("MatterDraftDetailPage", () => {
  beforeEach(() => {
    approveDraftMock.mockReset();
    draftFilingBundleUrlMock.mockReset();
    draftPdfUrlMock.mockReset();
    fetchDraftMock.mockReset();
    finalizeDraftMock.mockReset();
    generateDraftVersionMock.mockReset();
    listCourtFormatProfilesMock.mockReset();
    requestDraftChangesMock.mockReset();
    saveDraftEditsMock.mockReset();
    submitDraftMock.mockReset();
    draftPdfUrlMock.mockImplementation(
      (_matterId: string, _draftId: string, courtProfile?: string) =>
        courtProfile
          ? `https://api.test/draft.pdf?court_profile=${courtProfile}`
          : "https://api.test/draft.pdf",
    );
    draftFilingBundleUrlMock.mockImplementation(
      (
        _matterId: string,
        _draftId: string,
        options?: { courtProfile?: string },
      ) =>
        options?.courtProfile
          ? `https://api.test/bundle.zip?court_profile=${options.courtProfile}`
          : "https://api.test/bundle.zip",
    );
    listCourtFormatProfilesMock.mockResolvedValue([
      {
        key: "supreme_court",
        display_name: "Supreme Court of India",
        category: "supreme_court",
        page_format: "A4",
        layout_rules: ["A4 paper with wider margins."],
        heading_rules: ["Uppercase cause title."],
        body_font_size_pt: 12,
        page_number_position: "center",
        page_number_format: "{n}",
        margin_left_mm: 38.1,
        margin_right_mm: 38.1,
        margin_top_mm: 38.1,
        margin_bottom_mm: 38.1,
        cause_title_separator: "VERSUS",
        cause_title_party_case: "upper",
        cause_title_numbered: true,
        required_fields: [],
      },
      {
        key: "district_court",
        display_name: "District Court",
        category: "district_court",
        page_format: "A4",
        layout_rules: ["A4 paper with one inch margins."],
        heading_rules: ["Title-case cause title."],
        body_font_size_pt: 11,
        page_number_position: "right",
        page_number_format: "Page {n} of {total}",
        margin_left_mm: 25.4,
        margin_right_mm: 25.4,
        margin_top_mm: 25.4,
        margin_bottom_mm: 25.4,
        cause_title_separator: "v.",
        cause_title_party_case: "title",
        cause_title_numbered: false,
        required_fields: [],
      },
    ]);
    useCapabilityMock.mockReset();
    useCapabilityMock.mockImplementation((cap: string) => cap === "drafts:edit");
  });

  it("B3-DRAFT-01: explains the latest zero-citation approval block before a mutation", async () => {
    fetchDraftMock.mockResolvedValue({
      ...BASE_DRAFT, status: "in_review", review_required: true,
      versions: [{ ...BASE_DRAFT.versions[0], citations: [] as string[], verified_citation_count: 0 }],
    });
    useCapabilityMock.mockReturnValue(true);
    render(withClient(<DraftDetailPage />));
    const approve = await screen.findByTestId("draft-approve");
    expect(approve).toBeDisabled();
    expect(approve).toHaveAttribute("aria-describedby", "draft-citation-status");
    expect(screen.getByTestId("draft-citation-status")).toHaveTextContent(
      "Revision 1 has no verified citations",
    );
    expect(screen.getByRole("link", { name: "Matter context" })).toHaveAttribute(
      "href", "/app/matters/m-1",
    );
    expect(screen.getByRole("link", { name: "Matter context" })).toHaveClass("min-h-9");
    await userEvent.click(approve);
    expect(approveDraftMock).not.toHaveBeenCalled();
  });

  it("B3-DRAFT-04: a verified older revision cannot authorize the current unverified one", async () => {
    fetchDraftMock.mockResolvedValue({
      ...BASE_DRAFT, status: "in_review", review_required: true, current_version_id: "v-2",
      versions: [BASE_DRAFT.versions[0], {
        ...BASE_DRAFT.versions[0], id: "v-2", revision: 2,
        citations: [], verified_citation_count: 0,
      }],
    });
    useCapabilityMock.mockReturnValue(true);
    render(withClient(<DraftDetailPage />));
    expect(await screen.findByTestId("draft-approve")).toBeDisabled();
    expect(screen.getByTestId("draft-citation-status")).toHaveTextContent("Revision 2");
  });

  it("B3-DRAFT-02/03: bounded focus regenerates a new revision before review and approval", async () => {
    let latest = {
      ...BASE_DRAFT, status: "in_review", review_required: true,
      versions: [{ ...BASE_DRAFT.versions[0], citations: [] as string[], verified_citation_count: 0 }],
    };
    fetchDraftMock.mockImplementation(async () => latest);
    generateDraftVersionMock.mockImplementation(async () => {
      latest = {
        ...latest, status: "draft", current_version_id: "v-2",
        versions: [...latest.versions, { ...BASE_DRAFT.versions[0], id: "v-2", revision: 2 }],
      };
      return latest;
    });
    submitDraftMock.mockImplementation(async () => {
      latest = { ...latest, status: "in_review" };
      return latest;
    });
    approveDraftMock.mockImplementation(async () => {
      latest = { ...latest, status: "approved", review_required: false };
      return latest;
    });
    useCapabilityMock.mockReturnValue(true);
    render(withClient(<DraftDetailPage />));
    const focus = await screen.findByLabelText("Regeneration focus");
    expect(focus).toHaveAttribute("maxlength", "4000");
    await userEvent.type(focus, "  Address the reviewed limitation issue.  ");
    await userEvent.click(screen.getByTestId("draft-generate"));
    await waitFor(() => expect(generateDraftVersionMock).toHaveBeenCalledWith({
      matterId: "m-1", draftId: "d-1", focusNote: "Address the reviewed limitation issue.",
    }));
    expect(await screen.findByTestId("draft-submit")).toBeEnabled();
    expect(screen.getByTestId("draft-current-revision")).toHaveTextContent("Revision 2");
    await userEvent.click(screen.getByTestId("draft-submit"));
    expect(await screen.findByTestId("draft-approve")).toBeEnabled();
    await userEvent.click(screen.getByTestId("draft-approve"));
    await waitFor(() => expect(approveDraftMock).toHaveBeenCalledWith("m-1", "d-1"));
    expect(await screen.findByTestId("draft-finalize")).toBeVisible();
  });

  it.each(["filed", "served"])("B3-DRAFT-05: %s drafts keep regeneration and editing locked", async (status) => {
    fetchDraftMock.mockResolvedValue({ ...BASE_DRAFT, status });
    useCapabilityMock.mockReturnValue(true);
    render(withClient(<DraftDetailPage />));
    expect(await screen.findByTestId("draft-generate")).toBeDisabled();
    expect(screen.queryByTestId("draft-edit-toggle")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Regeneration focus")).not.toBeInTheDocument();
    expect(screen.queryByTestId("draft-approve")).not.toBeInTheDocument();
  });

  it("B3-DRAFT-05: read-only viewers are not offered reviewer or generator commands", async () => {
    fetchDraftMock.mockResolvedValue({ ...BASE_DRAFT, status: "in_review" });
    useCapabilityMock.mockReturnValue(false);
    render(withClient(<DraftDetailPage />));
    expect(await screen.findByTestId("draft-generate")).toBeDisabled();
    expect(screen.queryByTestId("draft-approve")).not.toBeInTheDocument();
    expect(screen.queryByTestId("draft-request-changes")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Regeneration focus")).not.toBeInTheDocument();
  });

  it("B3-DRAFT-05: a generation refusal preserves focus and does not retry or approve", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    fetchDraftMock.mockResolvedValue({
      ...BASE_DRAFT, status: "in_review",
      versions: [{ ...BASE_DRAFT.versions[0], citations: [], verified_citation_count: 0 }],
    });
    generateDraftVersionMock.mockRejectedValue(new ApiError(
      403, "Automated paid-provider calls are not allowed.", null, "automated_provider_calls_disabled",
    ));
    useCapabilityMock.mockReturnValue(true);
    try {
      render(withClient(<DraftDetailPage />));
      const focus = await screen.findByLabelText("Regeneration focus");
      await userEvent.type(focus, "Reviewed source clarification.");
      await userEvent.click(screen.getByTestId("draft-generate"));
      await waitFor(() => expect(toast.error).toHaveBeenCalledWith(
        "Automated paid-provider calls are not allowed.",
      ));
      expect(focus).toHaveValue("Reviewed source clarification.");
      expect(generateDraftVersionMock).toHaveBeenCalledTimes(1);
      expect(approveDraftMock).not.toHaveBeenCalled();
      expect(screen.getByTestId("draft-approve")).toBeDisabled();
    } finally {
      consoleError.mockRestore();
    }
  });

  it("BUG-036: edits generated draft text and saves it as a review-required revision", async () => {
    const editedDraft = {
      ...BASE_DRAFT,
      status: "draft" as const,
      review_required: true,
      current_version_id: "v-2",
      versions: [
        ...BASE_DRAFT.versions,
        {
          ...BASE_DRAFT.versions[0],
          id: "v-2",
          revision: 2,
          body:
            "Original draft body citing 2024 SCC OnLine SC 777.\n\nLawyer edit added after review.",
          model_run_id: null,
          created_at: "2026-05-04T08:10:00Z",
        },
      ],
      reviews: [
        ...BASE_DRAFT.reviews,
        {
          id: "r-2",
          draft_id: "d-1",
          version_id: "v-2",
          actor_membership_id: "mem-1",
          action: "edit" as const,
          notes: "Manual body edit saved.",
          created_at: "2026-05-04T08:10:00Z",
        },
      ],
      updated_at: "2026-05-04T08:10:00Z",
    };
    fetchDraftMock.mockResolvedValue(editedDraft);
    fetchDraftMock.mockResolvedValueOnce(BASE_DRAFT);
    saveDraftEditsMock.mockResolvedValue(editedDraft);

    render(withClient(<DraftDetailPage />));

    await userEvent.click(await screen.findByTestId("draft-edit-toggle"));
    const editor = screen.getByTestId("draft-body-editor");
    expect(editor).toHaveValue(BASE_DRAFT.versions[0].body);

    await userEvent.type(editor, "\n\nLawyer edit added after review.");
    await userEvent.click(screen.getByTestId("draft-save-edit"));

    await waitFor(() =>
      expect(saveDraftEditsMock).toHaveBeenCalledWith({
        matterId: "m-1",
        draftId: "d-1",
        body:
          "Original draft body citing 2024 SCC OnLine SC 777.\n\nLawyer edit added after review.",
      }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("draft-current-revision")).toHaveTextContent(
        "Revision 2",
      ),
    );
    expect(screen.getByText(/Review required/)).toBeInTheDocument();
    expect(screen.getByText("Edited")).toBeInTheDocument();
  });

  it("BUG-036: finalized drafts stay immutable in the UI", async () => {
    fetchDraftMock.mockResolvedValue({
      ...BASE_DRAFT,
      status: "finalized" as const,
      review_required: false,
    });

    render(withClient(<DraftDetailPage />));

    await waitFor(() =>
      expect(screen.getByTestId("draft-body-readonly")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("draft-edit-toggle")).not.toBeInTheDocument();
    expect(screen.queryByTestId("draft-body-editor")).not.toBeInTheDocument();
  });

  it("ADP-16: applies selected court profile to export links and checklist", async () => {
    fetchDraftMock.mockResolvedValue(BASE_DRAFT);

    render(withClient(<DraftDetailPage />));

    const selector = await screen.findByTestId("court-profile-select");
    await waitFor(() =>
      expect(screen.getByText("Supreme Court of India")).toBeInTheDocument(),
    );
    await userEvent.selectOptions(selector, "supreme_court");

    expect(await screen.findByTestId("court-profile-details")).toHaveTextContent(
      "Supreme Court",
    );
    expect(screen.getByTestId("filing-checklist")).toHaveAttribute(
      "data-court-profile",
      "supreme_court",
    );
    expect(screen.getByTestId("draft-download-pdf")).toHaveAttribute(
      "href",
      "https://api.test/draft.pdf?court_profile=supreme_court",
    );
    expect(screen.getByTestId("draft-download-filing-bundle")).toHaveAttribute(
      "href",
      "https://api.test/bundle.zip?court_profile=supreme_court",
    );
  });
});
