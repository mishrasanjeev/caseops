import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

const { workspace, blob, validate } = vi.hoisted(() => ({ workspace: vi.fn(), blob: vi.fn(), validate: vi.fn() }));
vi.mock("@/lib/api/endpoints", () => ({ fetchContractWorkspace: workspace }));
vi.mock("@/lib/api/contracts", () => ({ fetchContractAttachmentBlob: blob, validateContractDocxPreview: validate }));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "c1", attachment_id: "a1" }) }));
vi.mock("next/dynamic", () => ({ default: (_load: unknown) => (props: { filename: string; url?: string }) => <div data-testid="private-viewer" data-url={props.url}>{props.filename}</div> }));

import Viewer from "./page";

beforeEach(() => {
  workspace.mockReset(); blob.mockReset(); validate.mockReset();
  workspace.mockResolvedValue({ attachments: [{ id: "a1", original_filename: "source.pdf", content_type: "application/pdf", size_bytes: 1024, processing_status: "indexed" }] });
  blob.mockResolvedValue(new Blob(["private original"])); validate.mockResolvedValue({});
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:private"), revokeObjectURL: vi.fn() }));
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});
function setup() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><Viewer /></QueryClientProvider>);
}
it("passes only authenticated local bytes to the PDF viewer and reauthorizes original downloads", async () => {
  const { unmount } = setup();
  expect(await screen.findByTestId("private-viewer")).toHaveAttribute("data-url", "blob:private");
  expect(blob).toHaveBeenCalledWith("c1", "a1", expect.any(AbortSignal));
  expect(validate).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Download original" }));
  await waitFor(() => expect(blob).toHaveBeenCalledTimes(2));
  expect(blob).toHaveBeenLastCalledWith("c1", "a1");
  unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:private");
});
it("validates inert DOCX content before retrieving viewer bytes", async () => {
  workspace.mockResolvedValue({ attachments: [{ id: "a1", original_filename: "source.docx", size_bytes: 10, processing_status: "indexed" }] });
  setup();
  await screen.findByTestId("private-viewer");
  expect(validate).toHaveBeenCalledWith("c1", "a1", expect.any(AbortSignal));
  expect(validate.mock.invocationCallOrder[0]).toBeLessThan(blob.mock.invocationCallOrder[0]);
});
it("does not retrieve a document absent from the authorized workspace", async () => {
  workspace.mockResolvedValue({ attachments: [] });
  setup();
  expect(await screen.findByRole("alert")).toHaveTextContent("unavailable");
  expect(blob).not.toHaveBeenCalled();
  expect(screen.queryByTestId("private-viewer")).not.toBeInTheDocument();
});
it("does not mount an unsafe DOCX but leaves an authenticated original-download action", async () => {
  workspace.mockResolvedValue({ attachments: [{ id: "a1", original_filename: "unsafe.docx", size_bytes: 10, processing_status: "indexed" }] });
  validate.mockRejectedValue(new Error("Unsafe external resource"));
  setup();
  await screen.findByText("Could not preview this document");
  expect(screen.queryByTestId("private-viewer")).not.toBeInTheDocument();
  expect(blob).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Download original" }));
  await waitFor(() => expect(blob).toHaveBeenCalledWith("c1", "a1"));
});
