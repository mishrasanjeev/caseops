import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listMock, createMock, toastSuccess, toastError } = vi.hoisted(() => ({
  listMock: vi.fn(),
  createMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listAttachmentRenditions: listMock,
  createAttachmentRendition: createMock,
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import { OcrTranslateDialog } from "@/components/document/OcrTranslateDialog";

type Providers = {
  ocr_provider_available: boolean;
  ocr_unavailable_reason: string | null;
  translation_available: boolean;
  translation_unavailable_reason: string | null;
  third_party_processing_permitted: boolean;
  ocr_languages: string[];
  translation_pairs: Array<{ source: string; target: string }>;
};

function providers(overrides: Partial<Providers> = {}): Providers {
  return {
    ocr_provider_available: true,
    ocr_unavailable_reason: null,
    translation_available: true,
    translation_unavailable_reason: null,
    third_party_processing_permitted: true,
    ocr_languages: ["en", "hi", "mr"],
    translation_pairs: [
      { source: "hi", target: "en" },
      { source: "en", target: "hi" },
      { source: "mr", target: "en" },
      { source: "en", target: "mr" },
    ],
    ...overrides,
  };
}

function summary(overrides: Record<string, unknown> = {}) {
  return {
    id: "r1",
    attachment_id: "a1",
    kind: "ocr",
    version: 1,
    status: "queued",
    ...overrides,
  };
}

function renderDialog(onClose = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <OcrTranslateDialog
        matterId="m1"
        attachment={{ id: "a1", name: "order.pdf" }}
        onClose={onClose}
      />
    </QueryClientProvider>,
  );
  return { onClose, client };
}

function optionLabels(select: HTMLElement): string[] {
  return within(select).getAllByRole("option").map((option) => option.textContent ?? "");
}

describe("OcrTranslateDialog", () => {
  beforeEach(() => {
    listMock.mockReset();
    createMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
    listMock.mockResolvedValue({ attachment_id: "a1", providers: providers(), renditions: [] });
  });

  it("is a named dialog that loads readiness for the document", async () => {
    renderDialog();
    const dialog = screen.getByRole("dialog", { name: "OCR & Translate" });
    expect(within(dialog).getByTestId("ocr-translate-loading")).toBeInTheDocument();
    expect(await within(dialog).findByLabelText("Source language")).toBeInTheDocument();
    expect(listMock).toHaveBeenCalledWith({ matterId: "m1", attachmentId: "a1" });
  });

  it("offers the three OCR languages and only supported translation targets", async () => {
    const user = userEvent.setup();
    renderDialog();
    const source = await screen.findByLabelText("Source language");
    const target = screen.getByLabelText("Translate to");
    expect(optionLabels(source)).toEqual([
      "Choose the language of the document",
      "English",
      "Hindi",
      "Marathi",
    ]);
    expect(screen.getByTestId("ocr-translate-start")).toBeDisabled();
    expect(optionLabels(target)).toEqual(["No translation — OCR only"]);

    await user.selectOptions(source, "hi");
    expect(optionLabels(target)).toEqual(["No translation — OCR only", "English"]);
    await user.selectOptions(source, "en");
    expect(optionLabels(target)).toEqual(["No translation — OCR only", "Hindi", "Marathi"]);
    await user.selectOptions(target, "mr");
    await user.selectOptions(source, "mr");
    expect(optionLabels(target)).toEqual(["No translation — OCR only", "English"]);
    expect(target).toHaveValue("none");
  });

  // Ram BUG-005 (2026-11-26): a three-item list read as a broken dropdown. The
  // dialog states the supported set, taken from the server's readiness payload.
  it("states the supported OCR languages and translation pairs from the server", async () => {
    renderDialog();
    const source = await screen.findByLabelText("Source language");
    const supported = screen.getByTestId("ocr-supported-languages");
    expect(supported).toHaveTextContent(
      "OCR reads documents in English, Hindi and Marathi. Translation: Hindi ↔ English, Marathi ↔ English.",
    );
    expect(source).toHaveAccessibleDescription(supported.textContent ?? "");
  });

  it("names only what the server reports, and drops translation when it is off", async () => {
    listMock.mockResolvedValue({
      attachment_id: "a1",
      providers: providers({
        ocr_languages: ["en", "hi"],
        translation_available: false,
        translation_unavailable_reason: "cost_not_verified",
        translation_pairs: [{ source: "hi", target: "en" }],
      }),
      renditions: [],
    });
    renderDialog();
    await screen.findByLabelText("Source language");
    const supported = screen.getByTestId("ocr-supported-languages");
    expect(supported).toHaveTextContent(/^OCR reads documents in English and Hindi\.$/);
    expect(supported).not.toHaveTextContent("Marathi");
    expect(supported).not.toHaveTextContent("Translation:");
  });

  it("marks a one-way pair with a single arrow", async () => {
    listMock.mockResolvedValue({
      attachment_id: "a1",
      providers: providers({ translation_pairs: [{ source: "mr", target: "en" }] }),
      renditions: [],
    });
    renderDialog();
    await screen.findByLabelText("Source language");
    expect(screen.getByTestId("ocr-supported-languages")).toHaveTextContent(
      "Translation: Marathi → English.",
    );
  });

  it("disables translation with the plain reason when it is unavailable", async () => {
    listMock.mockResolvedValue({
      attachment_id: "a1",
      providers: providers({
        translation_available: false,
        translation_unavailable_reason: "cost_not_verified",
      }),
      renditions: [],
    });
    const user = userEvent.setup();
    renderDialog();
    const source = await screen.findByLabelText("Source language");
    await user.selectOptions(source, "hi");
    const target = screen.getByLabelText("Translate to");
    expect(target).toBeDisabled();
    expect(target).toHaveAccessibleDescription(
      "Translation is unavailable. This service is paused until its pricing is verified.",
    );
    expect(optionLabels(target)).toEqual(["No translation — OCR only"]);
  });

  it.each([
    ["provider_disabled", "This service is turned off for the workspace."],
    ["credentials_missing", "This service is not configured yet."],
    [
      "third_party_processing_not_permitted",
      "This document is restricted to processing inside CaseOps, so it cannot be sent to an outside service.",
    ],
  ])("explains the %s translation reason in words", async (reason, copy) => {
    listMock.mockResolvedValue({
      attachment_id: "a1",
      providers: providers({ translation_available: false, translation_unavailable_reason: reason }),
      renditions: [],
    });
    renderDialog();
    expect(await screen.findByTestId("ocr-target-language-hint")).toHaveTextContent(copy);
    expect(screen.getByTestId("ocr-target-language-hint").textContent).not.toContain(reason);
  });

  it("warns that only text-layer pages are read when OCR is unavailable", async () => {
    listMock.mockResolvedValue({
      attachment_id: "a1",
      providers: providers({ ocr_provider_available: false, ocr_unavailable_reason: "provider_disabled" }),
      renditions: [],
    });
    renderDialog();
    expect(await screen.findByTestId("ocr-provider-unavailable")).toHaveTextContent(
      "Only pages with a text layer will be read. Scanned pages will be listed as unread.",
    );
  });

  it("submits the chosen languages once and reports the queued run", async () => {
    let resolve: (value: unknown) => void = () => {};
    createMock.mockImplementation(
      () => new Promise((done) => {
        resolve = done;
      }),
    );
    const user = userEvent.setup();
    const { onClose } = renderDialog();
    await user.selectOptions(await screen.findByLabelText("Source language"), "hi");
    await user.selectOptions(screen.getByLabelText("Translate to"), "en");
    const start = screen.getByTestId("ocr-translate-start");
    await user.click(start);
    await waitFor(() => expect(start).toBeDisabled());
    await user.click(start);
    expect(createMock).toHaveBeenCalledTimes(1);
    expect(createMock).toHaveBeenCalledWith({
      matterId: "m1",
      attachmentId: "a1",
      sourceLanguage: "hi",
      targetLanguage: "en",
    });
    expect(toastSuccess).not.toHaveBeenCalled();

    resolve({ created: true, rendition: summary() });
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("OCR queued"));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("sends an OCR-only request when no translation is chosen", async () => {
    createMock.mockResolvedValue({ created: true, rendition: summary() });
    const user = userEvent.setup();
    renderDialog();
    await user.selectOptions(await screen.findByLabelText("Source language"), "mr");
    await user.click(screen.getByTestId("ocr-translate-start"));
    await waitFor(() =>
      expect(createMock).toHaveBeenCalledWith({
        matterId: "m1",
        attachmentId: "a1",
        sourceLanguage: "mr",
        targetLanguage: null,
      }),
    );
  });

  it("says the run is already going when the API returns the open run", async () => {
    createMock.mockResolvedValue({ created: false, rendition: summary({ status: "ocr_processing" }) });
    const user = userEvent.setup();
    renderDialog();
    await user.selectOptions(await screen.findByLabelText("Source language"), "en");
    await user.click(screen.getByTestId("ocr-translate-start"));
    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith("Already running", expect.anything()),
    );
    expect(toastSuccess).not.toHaveBeenCalledWith("OCR queued");
  });

  it("shows the API's reason and keeps the dialog open when the request fails", async () => {
    createMock.mockRejectedValue(
      Object.assign(new Error("PDF, JPG, JPEG and PNG files only."), {
        status: 415,
        detail: "PDF, JPG, JPEG and PNG files only.",
      }),
    );
    const user = userEvent.setup();
    const { onClose } = renderDialog();
    await user.selectOptions(await screen.findByLabelText("Source language"), "en");
    await user.click(screen.getByTestId("ocr-translate-start"));
    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("PDF, JPG, JPEG and PNG files only."),
    );
    expect(onClose).not.toHaveBeenCalled();
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("shows an error state when readiness cannot be loaded", async () => {
    listMock.mockRejectedValue(new Error("Network down"));
    renderDialog();
    expect(await screen.findByText("Could not load OCR options")).toBeInTheDocument();
    expect(screen.queryByTestId("ocr-translate-start")).toBeNull();
  });
});
