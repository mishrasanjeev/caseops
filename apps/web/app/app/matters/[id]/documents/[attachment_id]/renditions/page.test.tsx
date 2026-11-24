import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  listMock,
  detailMock,
  retryMock,
  reviewMock,
  translateMock,
  downloadMock,
  blobMock,
  useCapabilityMock,
  toastSuccess,
  toastError,
  viewerProps,
} = vi.hoisted(() => ({
  listMock: vi.fn(),
  detailMock: vi.fn(),
  retryMock: vi.fn(),
  reviewMock: vi.fn(),
  translateMock: vi.fn(),
  downloadMock: vi.fn(),
  blobMock: vi.fn(),
  useCapabilityMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  viewerProps: { current: null as null | { page?: number; url?: string; onPageChange?: (page: number) => void } },
}));

vi.mock("@/lib/api/endpoints", () => ({
  listAttachmentRenditions: listMock,
  fetchAttachmentRendition: detailMock,
  retryAttachmentRendition: retryMock,
  reviewAttachmentRendition: reviewMock,
  createRenditionTranslation: translateMock,
  downloadAttachmentRendition: downloadMock,
  fetchMatterAttachmentBlob: blobMock,
  matterAttachmentDownloadUrl: ({ matterId, attachmentId }: { matterId: string; attachmentId: string }) =>
    `http://api.test/api/matters/${matterId}/attachments/${attachmentId}/download?inline=true`,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (cap: string) => useCapabilityMock(cap),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m1", attachment_id: "a1" }),
}));

vi.mock("next/dynamic", () => ({
  default: () =>
    function PDFViewerStub(props: { page?: number; url?: string; onPageChange?: (page: number) => void }) {
      viewerProps.current = props;
      return <div data-testid="pdf-viewer-stub" data-page={props.page} />;
    },
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import AttachmentRenditionsPage from "@/app/app/matters/[id]/documents/[attachment_id]/renditions/page";

const now = "2026-11-23T10:00:00Z";

function summary(overrides: Record<string, unknown> = {}) {
  return {
    id: "ocr-1",
    company_id: "c1",
    matter_id: "m1",
    attachment_id: "a1",
    source_rendition_id: null,
    kind: "ocr",
    version: 1,
    status: "ocr_completed",
    review_status: "unreviewed",
    source_language: "hi",
    target_language: null,
    chain_target_language: null,
    provider: "sarvam",
    model: null,
    page_count: 2,
    pages_ok: 1,
    pages_review: 0,
    pages_failed: 1,
    error_code: null,
    error_message: null,
    has_output_file: false,
    output_size_bytes: null,
    requested_by_name: "Asha Rao",
    reviewed_by_name: null,
    reviewed_at: null,
    review_note: null,
    retry_allowed: false,
    created_at: now,
    updated_at: now,
    completed_at: now,
    ...overrides,
  };
}

const providers = {
  ocr_provider_available: true,
  ocr_unavailable_reason: null,
  translation_available: true,
  translation_unavailable_reason: null,
  third_party_processing_permitted: true,
  ocr_languages: ["en", "hi", "mr"],
  translation_pairs: [{ source: "hi", target: "en" }],
};

const ocrPages = [
  { page: 1, source: "ocr", status: "ok", reasons: [], text: "पहली पंक्ति\nSecond line", char_count: 20, blocks: [], paragraphs: [] },
  {
    page: 2,
    source: "none",
    status: "failed",
    reasons: ["inspect_no_text_layer", "paid_provider_blocked_for_test"],
    text: null,
    char_count: 0,
    blocks: [],
    paragraphs: [],
  },
];

function detail(base: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  return {
    ...base,
    attachment_filename: "order.pdf",
    failed_pages: [2],
    review_pages: [],
    pages: ocrPages,
    ...extra,
  };
}

function setVersions(versions: Array<Record<string, unknown>>, details: Record<string, Record<string, unknown>> = {}) {
  listMock.mockResolvedValue({ attachment_id: "a1", providers, renditions: versions });
  detailMock.mockImplementation(({ renditionId }: { renditionId: string }) => {
    const version = versions.find((item) => item.id === renditionId)!;
    return Promise.resolve(detail(version, details[renditionId] ?? {}));
  });
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AttachmentRenditionsPage />
    </QueryClientProvider>,
  );
}

describe("AttachmentRenditionsPage", () => {
  beforeEach(() => {
    for (const mock of [listMock, detailMock, retryMock, reviewMock, translateMock, downloadMock, blobMock, toastSuccess, toastError, useCapabilityMock]) {
      mock.mockReset();
    }
    useCapabilityMock.mockImplementation(() => false);
    viewerProps.current = null;
  });

  it("shows a skeleton while versions load", () => {
    listMock.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByTestId("renditions-loading")).toHaveAttribute("aria-busy", "true");
  });

  it("shows an error state with a way back when versions cannot be loaded", async () => {
    listMock.mockRejectedValue(new Error("Server unavailable"));
    renderPage();
    expect(await screen.findByText("Could not load OCR and translation versions")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to documents" })).toHaveAttribute("href", "/app/matters/m1/documents");
  });

  it("explains how to create a version when there are none", async () => {
    listMock.mockResolvedValue({ attachment_id: "a1", providers, renditions: [] });
    renderPage();
    expect(await screen.findByText("No OCR or translation versions yet")).toBeInTheDocument();
    expect(detailMock).not.toHaveBeenCalled();
  });

  it("shows OCR text page by page beside the original and keeps the PDF on the same page", async () => {
    setVersions([summary()]);
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByLabelText("Loading file name")).toBeInTheDocument();
    const text = await screen.findByTestId("renditions-ocr-text");
    expect(screen.getByTestId("renditions-filename")).toHaveTextContent("order.pdf");
    expect(text.textContent).toBe("पहली पंक्ति\nSecond line");
    expect(text).toHaveClass("whitespace-pre-wrap");
    expect(screen.getByTestId("renditions-page-indicator")).toHaveTextContent("Page 1 of 2");
    expect(screen.getByTestId("renditions-page-meta")).toHaveTextContent("Read fromOCR");
    expect(screen.getByTestId("renditions-review-line")).toHaveTextContent("Machine OCR text — not reviewed");
    expect(screen.getByTestId("renditions-failed-pages")).toHaveTextContent("Unread pages: 2");
    expect(screen.getByTestId("renditions-view-original")).toHaveAttribute("href", "/app/matters/m1/documents/a1/view");
    expect(screen.getByTestId("pdf-viewer-stub")).toHaveAttribute("data-page", "1");

    await user.click(screen.getByTestId("renditions-next-page"));
    expect(screen.getByTestId("renditions-page-indicator")).toHaveTextContent("Page 2 of 2");
    expect(screen.getByTestId("pdf-viewer-stub")).toHaveAttribute("data-page", "2");
    const meta = screen.getByTestId("renditions-page-meta");
    expect(meta).toHaveTextContent("Not read");
    expect(meta).toHaveTextContent("Unread — Scanned page with no text layer; Paid OCR disabled for automated verification");
    expect(screen.getByTestId("renditions-no-text")).toBeInTheDocument();
    expect(screen.getByTestId("renditions-next-page")).toBeDisabled();

    fireEvent.keyDown(screen.getByTestId("renditions-processed-pane"), { key: "ArrowLeft" });
    expect(screen.getByTestId("renditions-page-indicator")).toHaveTextContent("Page 1 of 2");
    fireEvent.keyDown(screen.getByTestId("renditions-processed-pane"), { key: "ArrowRight" });
    expect(screen.getByTestId("renditions-page-indicator")).toHaveTextContent("Page 2 of 2");

    viewerProps.current?.onPageChange?.(1);
    await waitFor(() => expect(screen.getByTestId("renditions-page-indicator")).toHaveTextContent("Page 1 of 2"));
  });

  it("lists every version with kind, languages, status, review status, requester and date", async () => {
    setVersions([
      summary({ id: "tr-1", kind: "translation", source_rendition_id: "ocr-1", target_language: "en", status: "review_required", review_status: "needs_correction" }),
      summary(),
    ]);
    renderPage();
    const list = await screen.findByTestId("renditions-version-list");
    const translation = within(list).getByTestId("renditions-version-tr-1");
    expect(translation).toHaveTextContent("Translation v1");
    expect(translation).toHaveTextContent("Hindi to English");
    expect(translation).toHaveTextContent("Needs correction");
    expect(translation).toHaveTextContent("Review required");
    expect(translation).toHaveTextContent("Asha Rao");
    expect(translation).toHaveAttribute("aria-pressed", "true");
    const ocr = within(list).getByTestId("renditions-version-ocr-1");
    expect(ocr).toHaveTextContent("OCR v1");
    expect(ocr).toHaveTextContent("OCR completed");
    expect(ocr).toHaveTextContent("Not reviewed");
  });

  it("renders translation paragraphs with flags as words and lists changed numbers", async () => {
    setVersions(
      [summary({ id: "tr-1", kind: "translation", source_rendition_id: "ocr-1", target_language: "en", status: "review_required" }), summary()],
      {
        "tr-1": {
          failed_pages: [],
          review_pages: [1],
          pages: [
            {
              page: 1,
              source: "ocr",
              status: "review",
              reasons: ["number_missing"],
              char_count: 10,
              paragraphs: [
                {
                  index: 0,
                  kind: "paragraph",
                  source: "धारा 12 के अंतर्गत",
                  translated: "Under section",
                  source_unavailable: false,
                  flags: ["number_missing", "identifier_changed", "citation_abbreviation_changed", "possible_omission", "unclear_source", "source_needs_review"],
                  missing_numbers: ["12"],
                  added_numbers: [],
                  missing_identifiers: ["CS(OS) 45/2024"],
                  missing_abbreviations: [],
                },
              ],
            },
          ],
        },
      },
    );
    const user = userEvent.setup();
    renderPage();
    const paragraph = await screen.findByTestId("renditions-paragraph-0");
    for (const label of ["Number missing", "Identifier changed", "Citation abbreviation changed", "Possible omission", "Source unclear", "Source needs review"]) {
      expect(within(paragraph).getByText(label)).toBeInTheDocument();
    }
    expect(paragraph).toHaveTextContent("Source (Hindi)");
    expect(paragraph).toHaveTextContent("Translation (English)");
    expect(paragraph).toHaveTextContent("Missing numbers12");
    expect(paragraph).toHaveTextContent("Missing identifiersCS(OS) 45/2024");
    expect(paragraph.textContent).not.toMatch(/number_missing|certified|verified/i);
    expect(screen.getByTestId("renditions-review-line")).toHaveTextContent("Machine translation — not reviewed");
    expect(screen.getByTestId("renditions-review-pages")).toHaveTextContent("Pages needing review: 1");

    await user.click(screen.getByTestId("renditions-view-ocr"));
    expect(await screen.findByTestId("renditions-ocr-text")).toBeInTheDocument();
    await user.click(screen.getByTestId("renditions-view-translation"));
    expect(await screen.findByTestId("renditions-paragraph-0")).toBeInTheDocument();
  });

  it("names the reviewer once a version is reviewed", async () => {
    setVersions([summary({ review_status: "reviewed", reviewed_by_name: "Vikram Shah", reviewed_at: "2026-11-23T12:00:00Z" })]);
    renderPage();
    const line = await screen.findByTestId("renditions-review-line");
    expect(line.textContent).toMatch(/^Reviewed by Vikram Shah on /);
    expect(line.textContent).not.toMatch(/not reviewed|certified|verified/i);
  });

  it("shows the failure message for a failed version", async () => {
    setVersions([summary({ status: "failed", error_message: "The PDF is password-protected. Upload an unlocked copy.", pages_ok: 0 })]);
    renderPage();
    expect(await screen.findByTestId("renditions-error")).toHaveTextContent("The PDF is password-protected. Upload an unlocked copy.");
    expect(screen.getAllByText("OCR failed").length).toBeGreaterThan(0);
  });

  it("hides review controls from members without documents:manage", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "documents:upload");
    setVersions([summary()]);
    renderPage();
    await screen.findByTestId("renditions-ocr-text");
    expect(screen.queryByTestId("renditions-review")).toBeNull();
    expect(screen.queryByTestId("renditions-mark-reviewed")).toBeNull();
  });

  it("requires a note before marking a version with unread pages reviewed", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "documents:manage");
    setVersions([summary({ pages_failed: 1 })]);
    reviewMock.mockResolvedValue(summary({ review_status: "reviewed" }));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByTestId("renditions-mark-reviewed"));
    expect(screen.getByText("Add a note explaining how the unread pages were checked.")).toBeInTheDocument();
    expect(reviewMock).not.toHaveBeenCalled();

    const note = screen.getByLabelText(/Note \(required/);
    await user.type(note, "Page 2 checked against the certified copy");
    await user.click(screen.getByTestId("renditions-mark-reviewed"));
    await waitFor(() =>
      expect(reviewMock).toHaveBeenCalledWith({
        matterId: "m1",
        attachmentId: "a1",
        renditionId: "ocr-1",
        reviewStatus: "reviewed",
        note: "Page 2 checked against the certified copy",
      }),
    );
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Marked reviewed"));
  });

  it("records needs-correction without a note", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "documents:manage");
    setVersions([summary()]);
    reviewMock.mockResolvedValue(summary({ review_status: "needs_correction" }));
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByTestId("renditions-needs-correction"));
    await waitFor(() =>
      expect(reviewMock).toHaveBeenCalledWith(expect.objectContaining({ reviewStatus: "needs_correction", note: null })),
    );
  });

  it("offers the translated PDF only when the version has an output file", async () => {
    setVersions([summary({ id: "tr-1", kind: "translation", source_rendition_id: "ocr-1", target_language: "en", status: "translation_completed", has_output_file: true }), summary()]);
    downloadMock.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByTestId("renditions-download"));
    await waitFor(() =>
      expect(downloadMock).toHaveBeenCalledWith({
        matterId: "m1",
        attachmentId: "a1",
        renditionId: "tr-1",
        fallbackName: "order-translation-v1.pdf",
      }),
    );
    await user.click(screen.getByTestId("renditions-version-ocr-1"));
    await waitFor(() => expect(screen.queryByTestId("renditions-download")).toBeNull());
  });

  it("offers retry only for retryable versions and only to uploaders", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "documents:upload");
    setVersions([summary({ status: "failed", retry_allowed: true, pages_ok: 0 }), summary({ id: "ocr-0", version: 0 })]);
    retryMock.mockResolvedValue({ created: true, rendition: summary({ status: "queued" }) });
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByTestId("renditions-retry"));
    await waitFor(() => expect(retryMock).toHaveBeenCalledWith({ matterId: "m1", attachmentId: "a1", renditionId: "ocr-1" }));
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Retry queued"));

    await user.click(screen.getByTestId("renditions-version-ocr-0"));
    expect(screen.queryByTestId("renditions-retry")).toBeNull();
  });

  it("hides retry from members without documents:upload", async () => {
    setVersions([summary({ status: "failed", retry_allowed: true })]);
    renderPage();
    await screen.findByTestId("renditions-error");
    expect(screen.queryByTestId("renditions-retry")).toBeNull();
  });

  it("translates a finished OCR version that has no translation yet", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "documents:upload");
    setVersions([summary()]);
    translateMock.mockResolvedValue({ created: true, rendition: summary({ id: "tr-9", kind: "translation", status: "queued" }) });
    const user = userEvent.setup();
    renderPage();
    const form = await screen.findByTestId("renditions-translate");
    expect(within(form).getByLabelText("Translate this OCR version to")).toHaveValue("en");
    await user.click(within(form).getByTestId("renditions-translate-start"));
    await waitFor(() =>
      expect(translateMock).toHaveBeenCalledWith({ matterId: "m1", attachmentId: "a1", ocrRenditionId: "ocr-1", targetLanguage: "en" }),
    );
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Translation queued"));
  });

  it("switches between original and processed panes on narrow screens", async () => {
    setVersions([summary()]);
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("renditions-ocr-text");
    const original = screen.getByTestId("renditions-original-pane");
    const processed = screen.getByTestId("renditions-processed-pane");
    expect(screen.getByTestId("renditions-pane-processed")).toHaveAttribute("aria-pressed", "true");
    expect(original).toHaveClass("hidden", "lg:flex");
    expect(processed).not.toHaveClass("hidden");

    await user.click(screen.getByTestId("renditions-pane-original"));
    expect(screen.getByTestId("renditions-pane-original")).toHaveAttribute("aria-pressed", "true");
    expect(original).not.toHaveClass("hidden");
    expect(processed).toHaveClass("hidden", "lg:flex");
  });

  it("copies the current page and the whole version", async () => {
    setVersions([summary()]);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("renditions-ocr-text");
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    await user.click(screen.getByTestId("renditions-copy-page"));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("पहली पंक्ति\nSecond line"));
    expect(toastSuccess).toHaveBeenCalledWith("Page copied");
    await user.click(screen.getByTestId("renditions-copy-all"));
    await waitFor(() => expect(writeText).toHaveBeenLastCalledWith("Page 1\n\nपहली पंक्ति\nSecond line"));
    expect(toastSuccess).toHaveBeenCalledWith("All pages copied");
  });

  it("polls while the selected version is still processing", async () => {
    const versions = [summary({ status: "ocr_processing", pages_ok: 0, pages_failed: 0 })];
    listMock
      .mockResolvedValueOnce({ attachment_id: "a1", providers, renditions: versions })
      .mockResolvedValue({ attachment_id: "a1", providers, renditions: [summary()] });
    detailMock.mockImplementation(() => Promise.resolve(detail(summary())));
    renderPage();
    expect(await screen.findByText("Processing. This page updates on its own.")).toBeInTheDocument();
    await waitFor(() => expect(listMock.mock.calls.length).toBeGreaterThan(1), { timeout: 4000 });
    await waitFor(() => expect(screen.queryByText("Processing. This page updates on its own.")).toBeNull());
  });
});
