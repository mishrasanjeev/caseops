import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { ApiError } from "@/lib/api/config";

const {
  bundleMock,
  compareMock,
  createMock,
  downloadMock,
  generateMock,
  getDraftMock,
  listDraftsMock,
  listTemplatesMock,
  lifecycleMock,
  saveMock,
  transitionMock,
  validationMock,
} = vi.hoisted(() => ({
  bundleMock: vi.fn(),
  compareMock: vi.fn(),
  createMock: vi.fn(),
  downloadMock: vi.fn(),
  generateMock: vi.fn(),
  getDraftMock: vi.fn(),
  listDraftsMock: vi.fn(),
  listTemplatesMock: vi.fn(),
  lifecycleMock: vi.fn(),
  saveMock: vi.fn(),
  transitionMock: vi.fn(),
  validationMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  compareIpPleadingDraftRevisions: compareMock,
  createIpPleadingDraft: createMock,
  downloadIpPleadingDraft: downloadMock,
  downloadIpPleadingFilingBundle: bundleMock,
  generateIpPleadingDraft: generateMock,
  getIpPleadingDraft: getDraftMock,
  listIpPleadingDrafts: listDraftsMock,
  listIpPleadingTemplates: listTemplatesMock,
  saveIpPleadingDraft: saveMock,
  transitionIpPleadingLifecycle: lifecycleMock,
  transitionIpPleadingDraft: transitionMock,
  validateIpPleadingDraft: validationMock,
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

function renderReviewWorkspace(deepLink: boolean) {
  const reviewed = { ...draft, status: "in_review" as const };
  listDraftsMock.mockResolvedValue({ drafts: deepLink ? [] : [reviewed], next_cursor: null });
  getDraftMock.mockResolvedValue(reviewed);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <IpPleadingWorkspace docketId="docket-1" proceedingId="proceeding-1"
        initialDraftId={deepLink ? reviewed.id : undefined}
        canCreate canEdit canGenerate canReview canFinalize />
    </QueryClientProvider>,
  );
  return { queryClient, reviewed };
}

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
    getDraftMock.mockResolvedValue(draft);
    generateMock.mockResolvedValue(draft);
    saveMock.mockResolvedValue(draft);
    transitionMock.mockResolvedValue({ ...draft, status: "in_review" });
    lifecycleMock.mockResolvedValue({ ...draft, status: "filed" });
    bundleMock.mockResolvedValue(new Blob(["bundle"]));
    validationMock.mockResolvedValue({
      draft_id: "draft-1",
      version_id: "version-1",
      revision: 1,
      evaluated_at: "2026-08-24T10:00:00Z",
      blocker_count: 0,
      warning_count: 0,
      placeholder_count: 0,
      source_count: 1,
      source_anchor_count: 0,
      exhibit_anchor_count: 0,
      can_approve: true,
      can_file: true,
      findings: [],
    });
    compareMock.mockResolvedValue({
      draft_id: "draft-1",
      prev_revision: 1,
      next_revision: 2,
      prev_version_id: "version-1",
      next_version_id: "version-2",
      hunks: [],
      citations_added: [],
      citations_removed: [],
      citations_kept: ["2026 SCC OnLine Del 450"],
      lines_added: 1,
      lines_removed: 0,
      summary: "r1 → r2: +1 lines",
    });
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:test"),
      revokeObjectURL: vi.fn(),
    });
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
    expect(await screen.findByText("Current identifiers, sources, citations, exhibits, and placeholders passed.")).toBeVisible();
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

  it("selects the exact deep-linked intelligent-review Draft", async () => {
    const requestedDraft = {
      ...draft,
      id: "draft-from-review",
      title: "Approved intelligent review",
      current_version_id: "version-from-review",
      versions: [{
        ...draft.versions[0],
        id: "version-from-review",
        draft_id: "draft-from-review",
        body: "Approved source-bounded intelligent review.",
      }],
    };
    let resolveRequestedDraft: ((value: typeof requestedDraft) => void) | undefined;
    getDraftMock.mockReturnValue(new Promise((resolve) => {
      resolveRequestedDraft = resolve;
    }));
    listDraftsMock.mockReturnValue(new Promise(() => {}));
    listTemplatesMock.mockReturnValue(new Promise(() => {}));
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
          initialDraftId="draft-from-review"
        />
      </QueryClientProvider>,
    );

    const workspace = screen.getByTestId("ip-pleading-workspace");
    expect(workspace).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("status", { name: "Loading pleading workspace" })).toBeVisible();

    await waitFor(() => expect(getDraftMock).toHaveBeenCalledWith({
      docketId: "docket-1",
      proceedingId: "proceeding-1",
      draftId: "draft-from-review",
    }));
    expect(listDraftsMock).not.toHaveBeenCalled();
    expect(listTemplatesMock).not.toHaveBeenCalled();

    resolveRequestedDraft?.(requestedDraft);

    const draftSelect = await screen.findByRole("combobox", {
      name: /^Pleading draft$/,
    });
    expect(workspace).toHaveAttribute("aria-busy", "false");
    expect(draftSelect).toHaveValue("draft-from-review");
    expect(screen.getAllByLabelText("Pleading draft", { exact: true })).toEqual([
      draftSelect,
    ]);
    expect(draftSelect).toHaveAccessibleName("Pleading draft");
    expect(screen.getByLabelText("Pleading body", { exact: true })).toHaveValue(
      "Approved source-bounded intelligent review.",
    );
    expect(validationMock).toHaveBeenCalledWith({
      docketId: "docket-1",
      proceedingId: "proceeding-1",
      draftId: "draft-from-review",
    });
    expect(listDraftsMock).toHaveBeenCalledOnce();
    expect(listTemplatesMock).toHaveBeenCalledOnce();
  });

  it.each([false, true])("refreshes a rejected stale approval without replay (deep link: %s)", async (deepLink) => {
    const { queryClient, reviewed } = renderReviewWorkspace(deepLink);
    await screen.findByText("Current identifiers, sources, citations, exhibits, and placeholders passed.");
    const approve = screen.getByRole("button", { name: "Approve", exact: true });
    expect(approve).toBeEnabled();
    await waitFor(() => expect(listDraftsMock).toHaveBeenCalledOnce());
    const previousValidation = await validationMock.mock.results[0].value;
    const latest = { ...reviewed, current_version_id: "version-2", versions: [reviewed.versions[0], {
      ...reviewed.versions[0], id: "version-2", revision: 2,
      body: "Synthetic independent-tab edit without an authority.", citations: [], verified_citation_count: 0,
    }] };
    let releaseRead!: (value: typeof latest) => void;
    const recovered = new Promise<typeof latest>((resolve) => { releaseRead = resolve; });
    if (deepLink) getDraftMock.mockReturnValue(recovered);
    else listDraftsMock.mockImplementation(() => recovered.then((row) => ({ drafts: [row], next_cursor: null })));
    validationMock.mockResolvedValue({ ...previousValidation, version_id: "version-2", revision: 2,
      blocker_count: 1, can_approve: false, can_file: false, findings: [{
        code: "citation.none_verified", severity: "blocker",
        message: "At least one current verified authority is required before approval or filing.", references: [],
      }] });
    transitionMock.mockRejectedValue(new ApiError(422, "Cannot approve a draft with zero verified citations.",
      null, "verified_citations_required"));
    fireEvent.change(screen.getByLabelText("Review notes"), { target: { value: "Retain my review note." } });
    fireEvent.click(approve);

    await waitFor(() => expect(deepLink ? getDraftMock : listDraftsMock).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: "Request changes", exact: true })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Approve", exact: true }));
    expect(transitionMock).toHaveBeenCalledOnce();
    releaseRead(latest);
    expect(await screen.findByText("Revision 2")).toBeVisible();
    expect(screen.getByText("0 verified citations")).toBeVisible();
    await waitFor(() => expect(screen.getByTestId("ip-draft-validation")).toHaveTextContent("1 blockers"));
    expect(screen.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
    expect(screen.getByLabelText("Pleading body")).toHaveValue(latest.versions[1].body);
    expect(screen.getByRole("combobox", { name: "Pleading draft", exact: true })).toHaveValue(reviewed.id);
    expect(screen.getByLabelText("Review notes")).toHaveValue("Retain my review note.");
    expect(transitionMock).toHaveBeenCalledOnce();
    expect(transitionMock).toHaveBeenCalledWith(expect.objectContaining({ action: "approve", draftId: reviewed.id }), expect.any(Object));
    expect(listDraftsMock).toHaveBeenCalledTimes(2);
    expect(getDraftMock).toHaveBeenCalledTimes(deepLink ? 2 : 0);
    if (deepLink) {
      expect(queryClient.getQueryData(["ip", "pleading-drafts", "docket-1", "proceeding-1", "detail", reviewed.id])).toEqual(latest);
    } else {
      expect(queryClient.getQueryData(["ip", "pleading-drafts", "docket-1", "proceeding-1"])).toEqual({ drafts: [latest], next_cursor: null });
    }
    expect(toast.error).toHaveBeenCalledWith("Cannot approve a draft with zero verified citations.");
  });

  it.each([false, true])("keeps approval unavailable after a failed recovery read (deep link: %s)", async (deepLink) => {
    const { reviewed } = renderReviewWorkspace(deepLink);
    await screen.findByText("Current identifiers, sources, citations, exhibits, and placeholders passed.");
    await waitFor(() => expect(listDraftsMock).toHaveBeenCalledOnce());
    const approve = screen.getByRole("button", { name: "Approve", exact: true });
    expect(approve).toBeEnabled();
    const readError = new Error("Synthetic recovery read is unavailable.");
    if (deepLink) getDraftMock.mockRejectedValue(readError);
    else listDraftsMock.mockRejectedValue(readError);
    transitionMock.mockRejectedValue(new ApiError(422, "Cannot approve a draft with zero verified citations.",
      null, "verified_citations_required"));
    fireEvent.click(approve);

    await screen.findByText(deepLink ? "Could not load the linked pleading draft" : "Could not load pleading drafts");
    expect(screen.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
    expect(transitionMock).toHaveBeenCalledOnce();
    if (deepLink) getDraftMock.mockResolvedValue({ ...reviewed, status: "finalized", review_required: false });
    else listDraftsMock.mockResolvedValue({ drafts: [{ ...reviewed, status: "finalized", review_required: false }], next_cursor: null });
    fireEvent.click(screen.getByRole("button", { name: "Try again", exact: true }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Approve", exact: true })).not.toBeInTheDocument());
    expect(transitionMock).toHaveBeenCalledOnce();
    expect(toast.error).toHaveBeenCalledWith("Cannot approve a draft with zero verified citations.");
  });

  it.each(["missing", "loading", "error", "mismatched", "blocked"])("requires current successful validation before approval: %s", async (state) => {
    const { queryClient } = renderReviewWorkspace(false);
    await screen.findByText("Current identifiers, sources, citations, exhibits, and placeholders passed.");
    const previousValidation = await validationMock.mock.results[0].value;
    expect(screen.getByRole("button", { name: "Approve", exact: true })).toBeEnabled();
    if (state === "missing") validationMock.mockResolvedValue(null);
    else if (state === "loading") validationMock.mockReturnValue(new Promise(() => {}));
    else if (state === "error") validationMock.mockRejectedValue(new Error("Synthetic validation read failed."));
    else validationMock.mockResolvedValue({ ...previousValidation,
      version_id: state === "mismatched" ? "unseen-version" : "version-1",
      can_approve: state !== "blocked",
    });
    const refresh = queryClient.invalidateQueries({ queryKey: ["ip", "pleading-validation"] });
    if (state === "loading") {
      await waitFor(() => expect(queryClient.isFetching({ queryKey: ["ip", "pleading-validation"] })).toBe(1));
    } else await refresh;
    await waitFor(() => expect(screen.getByRole("button", { name: "Approve", exact: true })).toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Approve", exact: true }));
    expect(transitionMock).not.toHaveBeenCalled();
  });

  it("compares revisions, exports a filing bundle, and records filing", async () => {
    const revisionTwo = {
      ...draft.versions[0],
      id: "version-2",
      revision: 2,
      body: `${draft.versions[0].body}\nCorrected line.`,
    };
    listDraftsMock.mockResolvedValue({
      drafts: [{
        ...draft,
        status: "finalized",
        review_required: false,
        current_version_id: "version-2",
        versions: [draft.versions[0], revisionTwo],
      }],
      next_cursor: null,
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <IpPleadingWorkspace docketId="docket-1" proceedingId="proceeding-1" canCreate canEdit canGenerate canReview canFinalize />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("r1 → r2: +1 lines")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Filing bundle" }));
    await waitFor(() => expect(bundleMock).toHaveBeenCalledOnce());
    fireEvent.change(screen.getByLabelText("Registry reference"), {
      target: { value: "TM-O/2026/451" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Mark filed" }));
    await waitFor(() => expect(lifecycleMock).toHaveBeenCalledWith(
      expect.objectContaining({ action: "file", reference: "TM-O/2026/451" }),
      expect.any(Object),
    ));
  });

  it("keeps rejection and service as distinct human actions", async () => {
    listDraftsMock.mockResolvedValue({
      drafts: [{ ...draft, status: "filed", review_required: false }],
      next_cursor: null,
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <IpPleadingWorkspace docketId="docket-1" proceedingId="proceeding-1" canCreate canEdit canGenerate canReview canFinalize />
      </QueryClientProvider>,
    );
    await screen.findByRole("button", { name: "Rejected" });
    fireEvent.change(screen.getByLabelText("Registry reference"), {
      target: { value: "SERVICE/2026/9" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Rejected" }));
    await waitFor(() => expect(lifecycleMock).toHaveBeenCalledWith(
      expect.objectContaining({
        action: "reject-filing",
        reference: "SERVICE/2026/9",
      }),
      expect.any(Object),
    ));
    lifecycleMock.mockClear();
    fireEvent.change(screen.getByLabelText("Registry reference"), {
      target: { value: "SERVICE/2026/9" },
    });
    fireEvent.change(screen.getByLabelText("Service method"), {
      target: { value: "registered-post" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Mark served" }));
    await waitFor(() => expect(lifecycleMock).toHaveBeenCalledWith(
      expect.objectContaining({
        action: "serve",
        reference: "SERVICE/2026/9",
        method: "registered-post",
      }),
      expect.any(Object),
    ));
  });
});
