import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

const { workspace, blob, previewInput } = vi.hoisted(() => ({ workspace: vi.fn(), blob: vi.fn(), previewInput: vi.fn() }));
vi.mock("@/lib/api/endpoints", () => ({ fetchContractWorkspace: workspace }));
vi.mock("@/lib/api/contracts", () => ({ fetchContractAttachmentBlob: blob }));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "c1", attachment_id: "a1" }) }));
vi.mock("next/dynamic", () => ({ default: (_load: unknown) => (props: { filename?: string; url?: string; file?: Blob }) => {
  previewInput(props);
  return <div data-testid="private-viewer" data-url={props.url}>
  {props.filename ? <a href={props.url}>Cached download bypass</a> : null}
</div>;
} }));

import Viewer from "./page";
import { ApiError } from "@/lib/api/config";
import { apiBlobDataRequest } from "@/lib/api/client";

beforeEach(() => {
  workspace.mockReset(); blob.mockReset(); previewInput.mockReset();
  workspace.mockResolvedValue({ attachments: [{ id: "a1", original_filename: "source.pdf", content_type: "application/pdf", size_bytes: 1024, sha256_hex: "a".repeat(64), processing_status: "indexed" }] });
  blob.mockResolvedValue(new Blob(["private original"]));
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:private"), revokeObjectURL: vi.fn() }));
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});
function setup() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><Viewer /></QueryClientProvider>);
}
it("passes only authenticated local bytes to the PDF viewer and reauthorizes original downloads", async () => {
  const { unmount } = setup();
  expect(await screen.findByTestId("private-viewer")).toHaveAttribute("data-url", "blob:private");
  expect(previewInput).toHaveBeenLastCalledWith(expect.objectContaining({ file: await blob.mock.results[0].value }));
  expect(blob).toHaveBeenCalledWith("c1", "a1", expect.objectContaining({ sha256_hex: "a".repeat(64) }), expect.any(AbortSignal), true);
  expect(screen.queryByRole("link", { name: "Cached download bypass" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Download original" }));
  await waitFor(() => expect(blob).toHaveBeenCalledTimes(2));
  expect(blob).toHaveBeenLastCalledWith("c1", "a1", expect.objectContaining({ sha256_hex: "a".repeat(64) }), expect.any(AbortSignal));
  unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:private");
});
it("uses only the server-validated byte response for DOCX, without a second source read", async () => {
  workspace.mockResolvedValue({ attachments: [{ id: "a1", original_filename: "source.docx", size_bytes: 10, sha256_hex: "a".repeat(64), processing_status: "indexed" }] });
  setup();
  await screen.findByTestId("private-viewer");
  expect(blob).toHaveBeenCalledTimes(1);
  expect(blob).toHaveBeenCalledWith("c1", "a1", expect.objectContaining({ original_filename: "source.docx" }), expect.any(AbortSignal), true);
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
  blob.mockRejectedValueOnce(new Error("Unsafe external resource")).mockResolvedValueOnce(new Blob(["private original"]));
  setup();
  await screen.findByText("Could not preview this document");
  expect(screen.queryByTestId("private-viewer")).not.toBeInTheDocument();
  expect(blob).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole("button", { name: "Download original" }));
  await waitFor(() => expect(blob).toHaveBeenCalledTimes(2));
});

it("removes cached preview access after a fresh authorized download is rejected", async () => {
  setup();
  await screen.findByTestId("private-viewer");
  blob.mockRejectedValueOnce(new ApiError(403, "Access revoked", null));
  await userEvent.click(screen.getByRole("button", { name: "Download original" }));
  await screen.findByText("Document access is no longer available.");
  expect(screen.queryByTestId("private-viewer")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Cached download bypass" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Download original" })).toBeDisabled();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:private");
});

it("aborts a pending download when the viewer unmounts", async () => {
  const view = setup();
  await screen.findByTestId("private-viewer");
  let signal: AbortSignal | undefined;
  blob.mockImplementationOnce((_c, _a, _source, supplied) => {
    signal = supplied;
    return new Promise((_resolve, reject) => supplied.addEventListener("abort", () => reject(supplied.reason)));
  });
  await userEvent.click(screen.getByRole("button", { name: "Download original" }));
  view.unmount();
  expect(signal?.aborted).toBe(true);
});

it.each(["oversize", "truncated", "stalled"])("clears cached preview for a real 403 with %s error body", async (kind) => {
  setup();
  await screen.findByTestId("private-viewer");
  const body = kind === "oversize" ? "x".repeat(65537)
    : kind === "truncated" ? new ReadableStream<Uint8Array>({ start(controller) { controller.error(new TypeError("Truncated")); } })
    : new ReadableStream<Uint8Array>();
  const fetchMock = vi.fn().mockResolvedValue(new Response(body, { status: 403, headers: { "content-type": "application/problem+json" } }));
  vi.stubGlobal("fetch", fetchMock);
  blob.mockImplementationOnce(async (_c, _a, _source, signal) =>
    (await apiBlobDataRequest("/api/private/denied", { signal, timeoutMs: 40 })).blob);
  try {
    await userEvent.click(screen.getByRole("button", { name: "Download original" }));
    await screen.findByText("Document access is no longer available.");
    expect(screen.queryByTestId("private-viewer")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Cached download bypass" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download original" })).toBeDisabled();
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:private");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  } finally { vi.unstubAllGlobals(); }
});
