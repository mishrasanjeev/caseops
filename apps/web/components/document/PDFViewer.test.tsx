import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const documentInput = vi.hoisted(() => vi.fn());

vi.mock("react-pdf", () => ({
  pdfjs: { GlobalWorkerOptions: {} },
  Document: ({ children, file }: { children: ReactNode; file: unknown }) => {
    documentInput(file);
    return <div data-testid="mock-pdf-document">{children}</div>;
  },
  Page: ({ pageNumber }: { pageNumber: number }) => (
    <canvas data-testid="mock-pdf-page" data-page-number={pageNumber} />
  ),
}));

import { PDFViewer } from "@/components/document/PDFViewer";

describe("PDFViewer", () => {
  beforeEach(() => { documentInput.mockReset(); });

  it("BUG-038: exposes the original PDF bytes via open and download links", async () => {
    const url = "https://api.caseops.ai/api/matters/m-1/attachments/a-1/download";
    render(<PDFViewer url={url} filename="signed-order.pdf" />);

    await waitFor(() =>
      expect(screen.getByTestId("pdf-viewer")).toBeInTheDocument(),
    );
    const openOriginal = screen.getByTestId("pdf-open-original");
    const downloadOriginal = screen.getByTestId("pdf-download-original");

    expect(openOriginal).toHaveAttribute("href", url);
    expect(openOriginal).toHaveAttribute("target", "_blank");
    expect(downloadOriginal).toHaveAttribute("href", url);
    expect(downloadOriginal).toHaveAttribute("download", "signed-order.pdf");
    expect(documentInput).toHaveBeenLastCalledWith({ url, withCredentials: true });
  });

  it("passes authorized bytes directly to the renderer without a blob-URL fetch", () => {
    const file = new Blob(["synthetic private PDF"], { type: "application/pdf" });
    render(<PDFViewer url="blob:authorized-preview" file={file} />);
    expect(documentInput).toHaveBeenLastCalledWith(file);
    expect(screen.queryByTestId("pdf-open-original")).not.toBeInTheDocument();
    expect(screen.queryByTestId("pdf-download-original")).not.toBeInTheDocument();
  });
});
