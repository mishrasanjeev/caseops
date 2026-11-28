import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchDocumentBrandingMock,
  updateDocumentBrandingMock,
  uploadBrandingImageMock,
  removeBrandingImageMock,
  fetchBrandingImageMock,
} = vi.hoisted(() => ({
  fetchDocumentBrandingMock: vi.fn(),
  updateDocumentBrandingMock: vi.fn(),
  uploadBrandingImageMock: vi.fn(),
  removeBrandingImageMock: vi.fn(),
  fetchBrandingImageMock: vi.fn(),
}));

vi.mock("@/lib/api/document-branding", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/document-branding")>();
  return {
    ...actual,
    fetchDocumentBranding: fetchDocumentBrandingMock,
    updateDocumentBranding: updateDocumentBrandingMock,
    uploadBrandingImage: uploadBrandingImageMock,
    removeBrandingImage: removeBrandingImageMock,
    fetchBrandingImage: fetchBrandingImageMock,
  };
});

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { DocumentBrandingCard, dirtyBrandingFields } from "./DocumentBrandingCard";

function withClient(node: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

const saved = {
  signatory_name: "Anil Mehta",
  signatory_designation: "Partner",
  watermark_enabled: true,
  watermark_text: null,
  effective_watermark_text: "Mehta Legal Chambers LLP",
  has_logo: true,
  logo_width: 600,
  logo_height: 300,
  logo_sha256: "a".repeat(64),
  has_signature: false,
  signature_width: null,
  signature_height: null,
  signature_sha256: null,
  updated_at: "2026-11-27T10:00:00Z",
  letterhead: {
    issuer_name: "Mehta Legal Chambers LLP",
    detail_lines: ["Chamber 12, Delhi High Court", "GSTIN: 07ABCDE1234F1Z5 | PAN: ABCDE1234F"],
    source: "billing_profile" as const,
  },
};

describe("DocumentBrandingCard (ENH-001)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchDocumentBrandingMock.mockResolvedValue(saved);
    fetchBrandingImageMock.mockResolvedValue(new Blob([new Uint8Array([137, 80, 78, 71])], { type: "image/png" }));
    globalThis.URL.createObjectURL = vi.fn(() => "blob:preview");
    globalThis.URL.revokeObjectURL = vi.fn();
  });

  it("hydrates the saved signatory and previews the stored logo", async () => {
    render(withClient(<DocumentBrandingCard enabled />));
    expect(await screen.findByTestId("branding-signatory-name")).toHaveValue("Anil Mehta");
    expect(screen.getByTestId("branding-signatory-designation")).toHaveValue("Partner");
    expect(await screen.findByTestId("branding-logo-preview")).toHaveAttribute("src", "blob:preview");
    expect(fetchBrandingImageMock).toHaveBeenCalledWith("logo");
    expect(fetchBrandingImageMock).not.toHaveBeenCalledWith("signature");
    expect(screen.getByTestId("branding-letterhead")).toHaveTextContent("GSTIN: 07ABCDE1234F1Z5");
    expect(screen.getByTestId("branding-save")).toBeDisabled();
  });

  it("saves only the field the admin changed", async () => {
    updateDocumentBrandingMock.mockResolvedValue({ ...saved, signatory_designation: "Managing Partner" });
    const user = userEvent.setup();
    render(withClient(<DocumentBrandingCard enabled />));
    const designation = await screen.findByTestId("branding-signatory-designation");
    await user.clear(designation);
    await user.type(designation, "Managing Partner");
    await user.click(screen.getByTestId("branding-save"));
    await waitFor(() => expect(updateDocumentBrandingMock).toHaveBeenCalledTimes(1));
    expect(updateDocumentBrandingMock).toHaveBeenCalledWith({ signatory_designation: "Managing Partner" });
    await waitFor(() => expect(screen.getByTestId("branding-save")).toBeDisabled());
  });

  it("refuses an SVG before anything is uploaded", async () => {
    const user = userEvent.setup({ applyAccept: false });
    render(withClient(<DocumentBrandingCard enabled />));
    const input = await screen.findByTestId("branding-signature-input");
    const svg = new File(["<svg><script>alert(1)</script></svg>"], "sign.svg", { type: "image/svg+xml" });
    await user.upload(input, svg);
    expect(await screen.findByRole("alert")).toHaveTextContent("SVG files are not accepted");
    expect(uploadBrandingImageMock).not.toHaveBeenCalled();
  });

  it("uploads a PNG signature and shows the server's refusal when it rejects one", async () => {
    uploadBrandingImageMock.mockResolvedValueOnce({ ...saved, has_signature: true, signature_sha256: "b".repeat(64) });
    const user = userEvent.setup();
    render(withClient(<DocumentBrandingCard enabled />));
    const input = await screen.findByTestId("branding-signature-input");
    const png = new File([new Uint8Array([137, 80, 78, 71])], "sign.png", { type: "image/png" });
    await user.upload(input, png);
    await waitFor(() => expect(uploadBrandingImageMock).toHaveBeenCalledWith("signature", png));
    expect(await screen.findByTestId("branding-signature-remove")).toBeInTheDocument();

    const { ApiError } = await import("@/lib/api/config");
    uploadBrandingImageMock.mockRejectedValueOnce(
      new ApiError(400, "The image must be at least 32 pixels on each side.", null),
    );
    await user.upload(screen.getByTestId("branding-logo-input"), png);
    expect(await screen.findByRole("alert")).toHaveTextContent("at least 32 pixels");
  });

  it("removes the logo through the API", async () => {
    removeBrandingImageMock.mockResolvedValue({ ...saved, has_logo: false, logo_sha256: null });
    const user = userEvent.setup();
    render(withClient(<DocumentBrandingCard enabled />));
    await user.click(await screen.findByTestId("branding-logo-remove"));
    await waitFor(() => expect(removeBrandingImageMock).toHaveBeenCalledWith("logo"));
    await waitFor(() => expect(screen.queryByTestId("branding-logo-remove")).not.toBeInTheDocument());
  });

  it("diffs blank text to null and leaves untouched fields out", () => {
    const base = { signatory_name: "A", signatory_designation: "B", watermark_enabled: true, watermark_text: "W" };
    expect(dirtyBrandingFields(base, { ...base })).toEqual({});
    expect(dirtyBrandingFields(base, { ...base, watermark_text: "  ", watermark_enabled: false })).toEqual({
      watermark_text: null,
      watermark_enabled: false,
    });
  });
});
