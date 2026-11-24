import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { type ReactNode, useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const documentInput = vi.hoisted(() => vi.fn());
const reportedPages = vi.hoisted(() => ({ current: null as number | null }));

vi.mock("react-pdf", () => ({
  pdfjs: { GlobalWorkerOptions: {} },
  Document: ({
    children,
    file,
    onLoadSuccess,
  }: {
    children: ReactNode;
    file: unknown;
    onLoadSuccess?: (doc: { numPages: number }) => void;
  }) => {
    documentInput(file);
    useEffect(() => {
      if (reportedPages.current !== null) onLoadSuccess?.({ numPages: reportedPages.current });
    }, [onLoadSuccess]);
    return <div data-testid="mock-pdf-document">{children}</div>;
  },
  Page: ({ pageNumber }: { pageNumber: number }) => (
    <canvas data-testid="mock-pdf-page" data-page-number={pageNumber} />
  ),
}));

import { PDFViewer } from "@/components/document/PDFViewer";

describe("PDFViewer", () => {
  beforeEach(() => {
    documentInput.mockReset();
    reportedPages.current = null;
  });

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

  it("keeps its own page when uncontrolled", async () => {
    reportedPages.current = 3;
    render(<PDFViewer url="https://api.caseops.ai/x.pdf" />);
    await waitFor(() =>
      expect(screen.getByTestId("mock-pdf-page")).toHaveAttribute("data-page-number", "1"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByTestId("mock-pdf-page")).toHaveAttribute("data-page-number", "2");
    fireEvent.keyDown(screen.getByTestId("pdf-viewer"), { key: "ArrowRight" });
    expect(screen.getByTestId("mock-pdf-page")).toHaveAttribute("data-page-number", "3");
  });

  it("shows the controlled page and reports page requests instead of moving itself", async () => {
    reportedPages.current = 4;
    const onPageChange = vi.fn();
    const onNumPages = vi.fn();
    const { rerender } = render(
      <PDFViewer
        url="https://api.caseops.ai/x.pdf"
        page={2}
        onPageChange={onPageChange}
        onNumPages={onNumPages}
      />,
    );
    await waitFor(() => expect(onNumPages).toHaveBeenCalledWith(4));
    expect(screen.getByTestId("mock-pdf-page")).toHaveAttribute("data-page-number", "2");

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(onPageChange).toHaveBeenLastCalledWith(3);
    expect(screen.getByTestId("mock-pdf-page")).toHaveAttribute("data-page-number", "2");
    fireEvent.keyDown(screen.getByTestId("pdf-viewer"), { key: "ArrowLeft" });
    expect(onPageChange).toHaveBeenLastCalledWith(1);

    rerender(
      <PDFViewer
        url="https://api.caseops.ai/x.pdf"
        page={4}
        onPageChange={onPageChange}
        onNumPages={onNumPages}
      />,
    );
    expect(screen.getByTestId("mock-pdf-page")).toHaveAttribute("data-page-number", "4");
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });
});
