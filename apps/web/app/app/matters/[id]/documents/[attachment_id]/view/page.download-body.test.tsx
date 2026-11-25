import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Issue #613: the Matter private preview reads its image through the real
// authenticated download client; only workspace metadata is stubbed.
const { fetchWorkspace, listAnnotations } = vi.hoisted(() => ({
  fetchWorkspace: vi.fn(),
  listAnnotations: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "matter-1", attachment_id: "attachment-1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/api/endpoints", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/endpoints")>()),
  fetchMatterWorkspace: fetchWorkspace,
  fetchMatterAttachmentPreview: vi.fn(),
  listMatterAttachmentAnnotations: listAnnotations,
}));

import AttachmentViewerPage from "./page";

const IMAGE_URL = "http://localhost:8000/api/matters/matter-1/attachments/attachment-1/download?inline=true";
const PNG = [new Uint8Array([0x89, 0x50, 0x4e, 0x47]), new Uint8Array([0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0xff])];
const createObjectURL = vi.fn<(blob: Blob) => string>(() => "blob:matter-preview");
const revokeObjectURL = vi.fn();
const createDescriptor = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
const revokeDescriptor = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");

function renderViewer() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AttachmentViewerPage />
    </QueryClientProvider>,
  );
}

describe("Matter private preview body consumption", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listAnnotations.mockResolvedValue([]);
    fetchWorkspace.mockResolvedValue({ attachments: [{
      id: "attachment-1", original_filename: "exhibit-a.png", content_type: "image/png",
    }] });
    vi.stubGlobal("fetch", vi.fn());
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    if (createDescriptor) Object.defineProperty(URL, "createObjectURL", createDescriptor);
    else Reflect.deleteProperty(URL, "createObjectURL");
    if (revokeDescriptor) Object.defineProperty(URL, "revokeObjectURL", revokeDescriptor);
    else Reflect.deleteProperty(URL, "revokeObjectURL");
  });

  it("previews the original chunked bytes from a no-store read and revokes its URL on unmount", async () => {
    let index = 0;
    vi.mocked(fetch).mockResolvedValue(new Response(new ReadableStream<Uint8Array>({
      pull(controller) {
        if (index < PNG.length) controller.enqueue(PNG[index++]);
        else controller.close();
      },
    }), { headers: { "content-type": "image/png" } }));

    const view = renderViewer();

    expect(await screen.findByRole("img", { name: "exhibit-a.png" })).toHaveAttribute("src", "blob:matter-preview");
    expect(fetch).toHaveBeenCalledExactlyOnceWith(IMAGE_URL, expect.objectContaining({
      credentials: "include", cache: "no-store",
    }));
    const blob = createObjectURL.mock.calls[0][0];
    expect(blob.type).toBe("image/png");
    expect(new Uint8Array(await blob.arrayBuffer())).toEqual(new Uint8Array([...PNG[0], ...PNG[1]]));
    view.unmount();
    expect(revokeObjectURL).toHaveBeenCalledExactlyOnceWith("blob:matter-preview");
  });

  it("cancels the stalled image body when the viewer unmounts after headers", async () => {
    const cancel = vi.fn();
    let pulled!: () => void;
    const reading = new Promise<void>((resolve) => { pulled = resolve; });
    vi.mocked(fetch).mockResolvedValue(new Response(new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(PNG[0]); },
      pull() { pulled(); },
      cancel,
    }), { headers: { "content-type": "image/png" } }));

    const view = renderViewer();
    await reading;
    expect(screen.getByText("Loading image…")).toBeInTheDocument();
    view.unmount();

    await waitFor(() => expect(cancel).toHaveBeenCalled());
    expect(vi.mocked(fetch).mock.calls[0][1]?.signal?.aborted).toBe(true);
    expect(createObjectURL).not.toHaveBeenCalled();
  });
});
