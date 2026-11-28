import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { paramsMock, verifyMock } = vi.hoisted(() => ({
  paramsMock: vi.fn(() => ({ token: "A".repeat(43) })),
  verifyMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useParams: () => paramsMock() }));
vi.mock("@/lib/api/document-branding", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/document-branding")>();
  return { ...actual, fetchBillingDocumentVerification: verifyMock };
});

import { ApiError } from "@/lib/api/config";
import { sha256Hex } from "@/lib/api/document-branding";

import VerifyBillingDocumentPage from "./page";

function withClient(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

const pdfBytes = new TextEncoder().encode("%PDF-1.5 issued copy");

async function result(overrides: object = {}) {
  return {
    state: "valid",
    document_type: "Tax invoice",
    document_number: "INV-0007",
    issued_on: "2026-11-27",
    issuer_name: "Mehta Legal Chambers LLP",
    issuer_supplied_by_counsel: false,
    amount_minor: 2065000,
    currency: "INR",
    status_at_generation: "Issued",
    current_status: "Issued",
    generated_at: "2026-11-27T10:00:00Z",
    pdf_sha256: await sha256Hex(new Blob([pdfBytes])),
    revoked_at: null,
    revoked_reason: null,
    ...overrides,
  };
}

describe("billing document verification page (ENH-001)", () => {
  beforeEach(() => {
    verifyMock.mockReset();
    paramsMock.mockReturnValue({ token: "A".repeat(43) });
  });

  it("shows the issuer, number, amount and status of a genuine document", async () => {
    verifyMock.mockResolvedValue(await result());
    render(withClient(<VerifyBillingDocumentPage />));
    expect(await screen.findByText("Genuine document")).toBeInTheDocument();
    expect(verifyMock).toHaveBeenCalledWith("A".repeat(43));
    expect(screen.getByTestId("verify-number")).toHaveTextContent("INV-0007");
    expect(screen.getByTestId("verify-issued-by")).toHaveTextContent("Mehta Legal Chambers LLP");
    expect(screen.getByTestId("verify-amount")).toHaveTextContent("INR 20,650.00");
    expect(screen.getByTestId("verify-status-now")).toHaveTextContent("Issued");
  });

  it("tells a matching copy from an altered one without uploading it", async () => {
    verifyMock.mockResolvedValue(await result());
    const user = userEvent.setup();
    render(withClient(<VerifyBillingDocumentPage />));
    const input = await screen.findByTestId("verify-file-input");
    await user.upload(input, new File([pdfBytes], "INV-0007.pdf", { type: "application/pdf" }));
    expect(await screen.findByTestId("verify-file-result")).toHaveTextContent("INV-0007.pdf is the issued file, unchanged.");
    const altered = new File([new TextEncoder().encode("%PDF-1.5 issued copy!")], "edited.pdf", { type: "application/pdf" });
    await user.upload(input, altered);
    await waitFor(() =>
      expect(screen.getByTestId("verify-file-result")).toHaveTextContent("edited.pdf does not match"),
    );
  });

  it("marks a voided document as revoked with the reason", async () => {
    verifyMock.mockResolvedValue(await result({
      state: "revoked", current_status: "Void (cancelled)", revoked_reason: "The invoice was voided.",
      revoked_at: "2026-11-27T11:00:00Z",
    }));
    render(withClient(<VerifyBillingDocumentPage />));
    expect(await screen.findByText("Revoked")).toBeInTheDocument();
    expect(screen.getByTestId("verify-state")).toHaveTextContent("The invoice was voided.");
    expect(screen.queryByText("Genuine document")).not.toBeInTheDocument();
  });

  it("does not call a draft genuine, but still confirms its fingerprint", async () => {
    verifyMock.mockResolvedValue(await result({
      state: "not_issued", status_at_generation: "Draft (not issued)", current_status: "Draft (not issued)",
    }));
    const user = userEvent.setup();
    render(withClient(<VerifyBillingDocumentPage />));
    expect(await screen.findByText("Not an issued document")).toBeInTheDocument();
    expect(screen.queryByText("Genuine document")).not.toBeInTheDocument();
    expect(screen.getByTestId("verify-state")).toHaveTextContent(
      "This copy was generated as: Draft (not issued). It is not an issued document",
    );
    expect(screen.getByTestId("verify-state")).not.toHaveTextContent("Issued by");
    expect(screen.getByText("Fingerprint of this copy")).toBeInTheDocument();
    await user.upload(
      screen.getByTestId("verify-file-input"),
      new File([pdfBytes], "INV-0007.pdf", { type: "application/pdf" }),
    );
    expect(await screen.findByTestId("verify-file-result")).toHaveTextContent(
      "INV-0007.pdf is the file generated for this link, unchanged. It is still not an issued document.",
    );
  });

  it("labels an outside counsel's supplier details as entered by the counsel", async () => {
    verifyMock.mockResolvedValue(await result({
      state: "not_issued", document_type: "Outside counsel invoice", issuer_name: "Khanna Advisory Chambers",
      issuer_supplied_by_counsel: true, status_at_generation: "Submitted for review (not approved)",
      current_status: "Submitted for review (not approved)",
    }));
    render(withClient(<VerifyBillingDocumentPage />));
    expect(await screen.findByText("Not an issued document")).toBeInTheDocument();
    expect(screen.getByTestId("verify-issued-by-label")).toHaveTextContent("Supplier (as entered by the counsel)");
    expect(screen.getByTestId("verify-issued-by")).toHaveTextContent("Khanna Advisory Chambers");
    expect(screen.getByTestId("verify-state")).toHaveTextContent("Submitted for review (not approved)");
  });

  it("keeps the counsel label on an approved counsel invoice", async () => {
    verifyMock.mockResolvedValue(await result({
      document_type: "Outside counsel invoice", issuer_name: "Khanna Advisory Chambers", issuer_supplied_by_counsel: true,
    }));
    render(withClient(<VerifyBillingDocumentPage />));
    expect(await screen.findByText("Genuine document")).toBeInTheDocument();
    expect(screen.getByTestId("verify-state")).toHaveTextContent(
      "Supplier details as entered by the counsel: Khanna Advisory Chambers.",
    );
    expect(screen.getByTestId("verify-issued-by-label")).toHaveTextContent("Supplier (as entered by the counsel)");
  });

  it("never calls the API for a malformed link", async () => {
    paramsMock.mockReturnValue({ token: "not-a-token" });
    render(withClient(<VerifyBillingDocumentPage />));
    expect(await screen.findByTestId("verify-not-found")).toHaveTextContent("This link does not verify any document.");
    expect(verifyMock).not.toHaveBeenCalled();
  });

  it("explains an unknown link from the server's 404", async () => {
    verifyMock.mockRejectedValue(new ApiError(404, "This verification link is not valid.", null));
    render(withClient(<VerifyBillingDocumentPage />));
    expect(await screen.findByTestId("verify-not-found")).toHaveTextContent("This verification link is not valid.");
  });
});
