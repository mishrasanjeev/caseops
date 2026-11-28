import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClientKycDocument, ClientKycDocumentList, ClientRecord } from "@/lib/api/endpoints";

// BUG-003 (Nov 27 2026, Ram): "The KYC form only asks users to enter document
// names or numbers. There is no option to upload actual KYC documents, so the
// admin cannot check the documents submitted by the client."

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  upload: vi.fn(),
  remove: vi.fn(),
  blob: vi.fn(),
  submit: vi.fn(),
  verify: vi.fn(),
  reject: vi.fn(),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// The PDF preview is the shared pdf.js viewer (no iframe); jsdom cannot run
// pdf.js, so the stub records the bytes and URL it was given.
vi.mock("next/dynamic", () => ({
  default: () =>
    function PDFViewerStub(props: { url: string; file?: Blob }) {
      return (
        <div
          data-testid="pdf-viewer-stub"
          data-url={props.url}
          data-has-file={String(Boolean(props.file))}
        />
      );
    },
}));

vi.mock("@/lib/api/endpoints", () => ({
  listClientKycDocuments: mocks.list,
  uploadClientKycDocument: mocks.upload,
  removeClientKycDocument: mocks.remove,
  fetchClientKycDocumentBlob: mocks.blob,
  submitClientKyc: mocks.submit,
  verifyClientKyc: mocks.verify,
  rejectClientKyc: mocks.reject,
}));

import { ClientKycPanel } from "@/components/clients/ClientKycPanel";

const TYPES: ClientKycDocumentList["document_types"] = [
  { value: "pan", label: "PAN card", hint: "Front of the PAN card.", requires_label: false },
  {
    value: "aadhaar_masked",
    label: "Aadhaar (masked)",
    hint: "Upload a masked Aadhaar only.",
    requires_label: false,
  },
  { value: "passport", label: "Passport", hint: "Photo page.", requires_label: false },
  { value: "address_proof", label: "Other address proof", hint: "Utility bill.", requires_label: false },
  { value: "other", label: "Other document", hint: "Board resolution.", requires_label: true },
];

function doc(id: string, type: ClientKycDocument["document_type"], filename: string): ClientKycDocument {
  return {
    id,
    client_id: "client-1",
    document_type: type,
    label: null,
    original_filename: filename,
    content_type: filename.endsWith(".pdf") ? "application/pdf" : "image/png",
    size_bytes: 2048,
    uploaded_by_membership_id: "m-1",
    uploaded_by_name: "Ram",
    uploaded_by_portal: false,
    review_decision: null,
    reviewed_at: null,
    reviewed_by_membership_id: null,
    previewable: true,
    created_at: "2026-11-27T10:00:00Z",
  };
}

function listing(
  documents: ClientKycDocument[],
  status: ClientKycDocumentList["kyc_status"] = "rejected",
): ClientKycDocumentList {
  const types = new Set(documents.map((d) => d.document_type));
  const requirements = [
    { key: "pan", label: "PAN card", satisfied_by: ["pan" as const], satisfied: types.has("pan") },
    {
      key: "identity_address_proof",
      label: "Masked Aadhaar, passport or another address proof",
      satisfied_by: ["aadhaar_masked" as const, "passport" as const, "address_proof" as const],
      satisfied: ["aadhaar_masked", "passport", "address_proof"].some((t) =>
        types.has(t as ClientKycDocument["document_type"]),
      ),
    },
  ];
  return {
    client_id: "client-1",
    kyc_status: status,
    documents,
    requirements,
    requirements_met: requirements.every((r) => r.satisfied),
    upload_allowed: !["under_review", "verified"].includes(status),
    document_types: TYPES,
    accepted_extensions: [".pdf", ".png", ".jpg", ".jpeg"],
    max_upload_bytes: 25 * 1024 * 1024,
  };
}

type PanelClient = Pick<
  ClientRecord,
  "id" | "kyc_status" | "kyc_submitted_at" | "kyc_verified_at" | "kyc_rejection_reason" | "kyc_documents"
>;

function client(overrides: Partial<PanelClient> = {}): PanelClient {
  return {
    id: "client-1",
    kyc_status: "rejected",
    kyc_submitted_at: "2026-11-26T10:00:00Z",
    kyc_verified_at: "2026-11-26T12:00:00Z",
    kyc_rejection_reason: "Address proof missing",
    kyc_documents: [],
    ...overrides,
  };
}

function renderPanel(props: { client: PanelClient; canSubmit?: boolean; canReview?: boolean }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrap = (children: ReactNode) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return render(
    wrap(
      <ClientKycPanel
        client={props.client}
        canSubmit={props.canSubmit ?? true}
        canReview={props.canReview ?? false}
      />,
    ),
  );
}

const PAN = doc("doc-pan", "pan", "pan.pdf");
const AADHAAR = doc("doc-aadhaar", "aadhaar_masked", "aadhaar-masked.png");

beforeEach(() => {
  Object.values(mocks).forEach((m) => m.mockReset());
  mocks.blob.mockResolvedValue(new Blob(["%PDF-1.4"], { type: "application/pdf" }));
  if (!("createObjectURL" in URL)) {
    Object.assign(URL, { createObjectURL: () => "blob:kyc", revokeObjectURL: () => undefined });
  } else {
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:kyc");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  }
});

describe("ClientKycPanel — submitter (Re-submit verification)", () => {
  it("uploads PAN and a masked Aadhaar as files, then re-submits once the requirements are met", async () => {
    let docs: ClientKycDocument[] = [];
    mocks.list.mockImplementation(async () => listing(docs));
    mocks.upload.mockImplementation(async (input: { documentType: string; file: File }) => {
      const created = input.documentType === "pan" ? PAN : AADHAAR;
      docs = [...docs, created];
      return created;
    });
    mocks.submit.mockResolvedValue({});
    const user = userEvent.setup();
    renderPanel({ client: client() });

    await user.click(await screen.findByRole("button", { name: /Re-submit verification/ }));
    // The form no longer asks for names: it asks for a document type and a file.
    expect(screen.queryByTestId("kyc-submit-docs")).not.toBeInTheDocument();
    const fileInput = screen.getByTestId("kyc-upload-file") as HTMLInputElement;
    expect(fileInput.type).toBe("file");
    expect(fileInput.accept).toBe(".pdf,.png,.jpg,.jpeg");
    expect(screen.getByTestId("kyc-aadhaar-notice")).toHaveTextContent(/masked Aadhaar/);
    const submit = screen.getByTestId("kyc-submit");
    expect(submit).toBeDisabled();
    expect(screen.getByTestId("kyc-submit-blocked")).toHaveTextContent(
      "Upload PAN card and Masked Aadhaar, passport or another address proof before submitting.",
    );

    await user.selectOptions(screen.getByTestId("kyc-upload-type"), "pan");
    await user.upload(fileInput, new File(["%PDF-1.4"], "pan.pdf", { type: "application/pdf" }));
    await user.click(screen.getByTestId("kyc-upload-submit"));
    await waitFor(() => expect(mocks.upload).toHaveBeenCalledTimes(1));
    expect(mocks.upload.mock.calls[0][0]).toMatchObject({ clientId: "client-1", documentType: "pan" });
    expect(mocks.upload.mock.calls[0][0].file.name).toBe("pan.pdf");
    expect(await screen.findByText("pan.pdf")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("kyc-submit-blocked")).toHaveTextContent(
        "Upload Masked Aadhaar, passport or another address proof before submitting.",
      ),
    );

    await user.selectOptions(screen.getByTestId("kyc-upload-type"), "aadhaar_masked");
    expect(screen.getByTestId("kyc-upload-hint")).toHaveTextContent("Upload a masked Aadhaar only.");
    await user.upload(
      screen.getByTestId("kyc-upload-file"),
      new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], "aadhaar-masked.png", { type: "image/png" }),
    );
    await user.click(screen.getByTestId("kyc-upload-submit"));
    expect(await screen.findByText("aadhaar-masked.png")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("kyc-submit")).toBeEnabled());
    await user.click(screen.getByTestId("kyc-submit"));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledWith({ clientId: "client-1", documents: [] }));
  });

  it("refuses a file type the API will not accept before sending it", async () => {
    mocks.list.mockResolvedValue(listing([]));
    const user = userEvent.setup({ applyAccept: false });
    renderPanel({ client: client() });
    await user.click(await screen.findByRole("button", { name: /Re-submit verification/ }));
    await user.upload(
      screen.getByTestId("kyc-upload-file"),
      new File(["x"], "aadhaar.docx", { type: "application/octet-stream" }),
    );
    expect(screen.getByTestId("kyc-upload-submit")).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Only .pdf, .png, .jpg, .jpeg files are accepted.");
    expect(mocks.upload).not.toHaveBeenCalled();
  });

  it("asks for a name when the type is Other", async () => {
    mocks.list.mockResolvedValue(listing([]));
    mocks.upload.mockResolvedValue(doc("doc-other", "other", "resolution.pdf"));
    const user = userEvent.setup();
    renderPanel({ client: client() });
    await user.click(await screen.findByRole("button", { name: /Re-submit verification/ }));
    await user.selectOptions(screen.getByTestId("kyc-upload-type"), "other");
    await user.upload(
      screen.getByTestId("kyc-upload-file"),
      new File(["%PDF"], "resolution.pdf", { type: "application/pdf" }),
    );
    expect(screen.getByTestId("kyc-upload-submit")).toBeDisabled();
    await user.type(screen.getByTestId("kyc-upload-label"), "Board resolution");
    await user.click(screen.getByTestId("kyc-upload-submit"));
    await waitFor(() =>
      expect(mocks.upload.mock.calls[0][0]).toMatchObject({ documentType: "other", label: "Board resolution" }),
    );
  });

  it("removes an uploaded file from the pack", async () => {
    mocks.list.mockResolvedValue(listing([PAN]));
    mocks.remove.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderPanel({ client: client() });
    await user.click(await screen.findByRole("button", { name: "Remove PAN card" }));
    await waitFor(() =>
      expect(mocks.remove).toHaveBeenCalledWith({ clientId: "client-1", documentId: "doc-pan" }),
    );
  });
});

describe("ClientKycPanel — reviewer", () => {
  it("opens each uploaded document inline, records which were reviewed, and only then approves", async () => {
    mocks.list.mockResolvedValue(listing([PAN, AADHAAR], "submitted"));
    mocks.blob.mockImplementation(async ({ documentId }: { documentId: string }) =>
      documentId === "doc-pan"
        ? new Blob(["%PDF-1.4"], { type: "application/pdf" })
        : new Blob([new Uint8Array([0x89, 0x50])], { type: "image/png" }),
    );
    mocks.verify.mockResolvedValue({});
    const user = userEvent.setup();
    renderPanel({
      client: client({ kyc_status: "submitted", kyc_rejection_reason: null }),
      canSubmit: false,
      canReview: true,
    });

    const approve = await screen.findByTestId("kyc-verify");
    expect(approve).toHaveTextContent("Approve");
    await waitFor(() => expect(screen.getAllByTestId("kyc-document-row")).toHaveLength(2));
    expect(approve).toBeDisabled();
    expect(screen.getByTestId("kyc-verify-blocked")).toHaveTextContent(
      "Open and mark every document reviewed before approving (2 left).",
    );
    const boxes = screen.getAllByTestId("kyc-document-reviewed");
    // A document cannot be marked reviewed before it is opened.
    expect(boxes.every((b) => (b as HTMLInputElement).disabled)).toBe(true);

    await user.click(screen.getByRole("button", { name: "Open PAN card" }));
    const pdfPreview = await screen.findByTestId("kyc-document-preview-pdf");
    // Rendered by the shared pdf.js viewer from the fetched bytes: no iframe.
    const viewer = within(pdfPreview).getByTestId("pdf-viewer-stub");
    expect(viewer).toHaveAttribute("data-url", "blob:kyc");
    expect(viewer).toHaveAttribute("data-has-file", "true");
    expect(document.querySelector("iframe")).toBeNull();
    expect(mocks.blob).toHaveBeenCalledWith(
      expect.objectContaining({ clientId: "client-1", documentId: "doc-pan", inline: true }),
    );
    const panBox = screen.getByRole("checkbox", { name: "Reviewed PAN card" });
    await waitFor(() => expect(panBox).toBeEnabled());
    await user.click(panBox);
    expect(approve).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Open Aadhaar (masked)" }));
    expect(await screen.findByTestId("kyc-document-preview-image")).toHaveAttribute("src", "blob:kyc");
    const aadhaarBox = screen.getByRole("checkbox", { name: "Reviewed Aadhaar (masked)" });
    await waitFor(() => expect(aadhaarBox).toBeEnabled());
    await user.click(aadhaarBox);
    await waitFor(() => expect(approve).toBeEnabled());
    await user.click(approve);
    await waitFor(() =>
      expect(mocks.verify).toHaveBeenCalledWith({
        clientId: "client-1",
        reviewedDocumentIds: ["doc-pan", "doc-aadhaar"],
      }),
    );
  });

  it("keeps Approve disabled when a required document is missing and explains the way forward", async () => {
    mocks.list.mockResolvedValue(listing([PAN], "submitted"));
    mocks.reject.mockResolvedValue({});
    const user = userEvent.setup();
    renderPanel({
      client: client({ kyc_status: "submitted", kyc_rejection_reason: null }),
      canSubmit: false,
      canReview: true,
    });
    await user.click(await screen.findByRole("button", { name: "Open PAN card" }));
    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: "Reviewed PAN card" })).toBeEnabled(),
    );
    await user.click(screen.getByRole("checkbox", { name: "Reviewed PAN card" }));
    expect(screen.getByTestId("kyc-verify")).toBeDisabled();
    expect(screen.getByTestId("kyc-verify-blocked")).toHaveTextContent(
      "Approval needs Masked Aadhaar, passport or another address proof. Reject the pack with a reason",
    );
    // The way forward works: reject with a reason, recording the reviewed file.
    await user.click(screen.getByTestId("kyc-reject-toggle"));
    await user.type(screen.getByTestId("kyc-reject-reason"), "Upload a masked Aadhaar");
    await user.click(screen.getByTestId("kyc-reject"));
    await waitFor(() =>
      expect(mocks.reject).toHaveBeenCalledWith({
        clientId: "client-1",
        reason: "Upload a masked Aadhaar",
        reviewedDocumentIds: ["doc-pan"],
      }),
    );
  });

  it("starts a fresh review when the pack is submitted again", async () => {
    mocks.list.mockResolvedValue(listing([PAN, AADHAAR], "submitted"));
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const first = client({ kyc_status: "submitted", kyc_submitted_at: "2026-11-27T10:00:00Z" });
    const view = render(
      <QueryClientProvider client={queryClient}>
        <ClientKycPanel client={first} canSubmit={false} canReview />
      </QueryClientProvider>,
    );
    await user.click(await screen.findByRole("button", { name: "Open PAN card" }));
    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: "Reviewed PAN card" })).toBeEnabled(),
    );
    await user.click(screen.getByRole("checkbox", { name: "Reviewed PAN card" }));
    expect(screen.getByRole("checkbox", { name: "Reviewed PAN card" })).toBeChecked();
    view.rerender(
      <QueryClientProvider client={queryClient}>
        <ClientKycPanel
          client={{ ...first, kyc_submitted_at: "2026-11-27T12:00:00Z" }}
          canSubmit={false}
          canReview
        />
      </QueryClientProvider>,
    );
    const box = screen.getByRole("checkbox", { name: "Reviewed PAN card" });
    expect(box).not.toBeChecked();
    expect(box).toBeDisabled();
    expect(screen.queryByTestId("kyc-document-preview")).not.toBeInTheDocument();
  });

  it("keeps the Reviewed tick locked when the file could not be opened", async () => {
    mocks.list.mockResolvedValue(listing([PAN, AADHAAR], "submitted"));
    mocks.blob.mockRejectedValue(new Error("The KYC document file is no longer available."));
    const user = userEvent.setup();
    renderPanel({ client: client({ kyc_status: "submitted" }), canSubmit: false, canReview: true });
    await user.click(await screen.findByRole("button", { name: "Open PAN card" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The KYC document file is no longer available.",
    );
    // The server records an open only when it serves the bytes; so does the panel.
    expect(screen.getByRole("checkbox", { name: "Reviewed PAN card" })).toBeDisabled();
  });

  it("shows the API's reason when the server refuses an approval", async () => {
    mocks.list.mockResolvedValue(listing([PAN, AADHAAR], "submitted"));
    mocks.verify.mockRejectedValue(
      new Error(
        "Open each KYC document before you approve the pack. You have not opened: PAN card (pan.pdf).",
      ),
    );
    const user = userEvent.setup();
    renderPanel({ client: client({ kyc_status: "submitted" }), canSubmit: false, canReview: true });
    for (const label of ["PAN card", "Aadhaar (masked)"]) {
      await user.click(await screen.findByRole("button", { name: `Open ${label}` }));
      const box = screen.getByRole("checkbox", { name: `Reviewed ${label}` });
      await waitFor(() => expect(box).toBeEnabled());
      await user.click(box);
    }
    await user.click(screen.getByTestId("kyc-verify"));
    expect(await screen.findByTestId("kyc-verify-error")).toHaveTextContent(
      "Open each KYC document before you approve the pack. You have not opened: PAN card (pan.pdf).",
    );
  });

  it("downloads a document", async () => {
    mocks.list.mockResolvedValue(listing([PAN], "submitted"));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const user = userEvent.setup();
    renderPanel({ client: client({ kyc_status: "submitted" }), canReview: true });
    await user.click(await screen.findByRole("button", { name: "Download PAN card" }));
    await waitFor(() => expect(click).toHaveBeenCalled());
    expect(mocks.blob).toHaveBeenCalledWith({ clientId: "client-1", documentId: "doc-pan" });
    // Downloading counts as opening: the reviewed box unlocks.
    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: "Reviewed PAN card" })).toBeEnabled(),
    );
    click.mockRestore();
  });

  it("shows each document's recorded decision after review", async () => {
    mocks.list.mockResolvedValue(
      listing([{ ...PAN, review_decision: "approved" }, { ...AADHAAR, review_decision: "approved" }], "verified"),
    );
    renderPanel({ client: client({ kyc_status: "verified", kyc_rejection_reason: null }), canReview: true });
    const table = await screen.findByTestId("kyc-documents");
    expect(within(table).getAllByText("approved")).toHaveLength(2);
    expect(screen.queryByTestId("kyc-verify")).not.toBeInTheDocument();
    expect(screen.queryByTestId("kyc-submit-toggle")).not.toBeInTheDocument();
  });
});

describe("ClientKycPanel — roles", () => {
  it("does not request identity documents for a role without KYC capabilities", async () => {
    renderPanel({ client: client(), canSubmit: false, canReview: false });
    expect(
      await screen.findByText("Your role can see the KYC status but not the identity documents."),
    ).toBeInTheDocument();
    expect(mocks.list).not.toHaveBeenCalled();
  });

  it("keeps legacy name-only checklists visible and labelled as having no files", async () => {
    mocks.list.mockResolvedValue(listing([], "verified"));
    renderPanel({
      client: client({
        kyc_status: "verified",
        kyc_documents: [{ name: "PAN", status: "received", note: null }],
      }),
      canReview: true,
    });
    expect(
      await screen.findByText("Checklist recorded with an earlier submission (names only, no files)"),
    ).toBeInTheDocument();
    expect(screen.getByText("PAN")).toBeInTheDocument();
    // A frozen (verified) legacy pack does not invite an upload it cannot take.
    expect(await screen.findByTestId("kyc-documents-empty")).toHaveTextContent(
      "No KYC files are on record for this client; this verification predates file uploads.",
    );
  });
});
