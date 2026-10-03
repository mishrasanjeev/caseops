import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { fetchWorkspace, fetchImage, listAnnotations } = vi.hoisted(() => ({
  fetchWorkspace: vi.fn(),
  fetchImage: vi.fn(),
  listAnnotations: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "matter-1", attachment_id: "attachment-1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchMatterWorkspace: fetchWorkspace,
  fetchMatterAttachmentBlob: fetchImage,
  fetchMatterAttachmentPreview: vi.fn(),
  listMatterAttachmentAnnotations: listAnnotations,
  matterAttachmentDownloadUrl: () => "/download",
}));

import AttachmentViewerPage from "./page";

const createObjectURLDescriptor = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
const revokeObjectURLDescriptor = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");

function renderViewer() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AttachmentViewerPage />
    </QueryClientProvider>,
  );
}

describe("Matter attachment viewer metadata", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listAnnotations.mockResolvedValue([]);
    fetchImage.mockResolvedValue(new Blob(["image"], { type: "image/png" }));
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:caseops-image") });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  });

  afterEach(() => {
    if (createObjectURLDescriptor) Object.defineProperty(URL, "createObjectURL", createObjectURLDescriptor);
    else Reflect.deleteProperty(URL, "createObjectURL");
    if (revokeObjectURLDescriptor) Object.defineProperty(URL, "revokeObjectURL", revokeObjectURLDescriptor);
    else Reflect.deleteProperty(URL, "revokeObjectURL");
  });

  it("does not call a still-loading image an unsupported file", async () => {
    let resolveWorkspace!: (value: unknown) => void;
    fetchWorkspace.mockReturnValue(new Promise((resolve) => { resolveWorkspace = resolve; }));
    renderViewer();

    expect(screen.getByRole("status")).toHaveTextContent("Loading document…");
    expect(screen.queryByText("This file type cannot be previewed inline.")).not.toBeInTheDocument();

    resolveWorkspace({ attachments: [{
      id: "attachment-1",
      original_filename: "matter-inline-view.png",
      content_type: "image/png",
    }] });
    expect(await screen.findByRole("img", { name: "matter-inline-view.png" })).toBeInTheDocument();
    expect(fetchImage).toHaveBeenCalled();
  });

  it("shows a retryable metadata error instead of an unsupported-file verdict", async () => {
    fetchWorkspace.mockRejectedValue(new Error("Workspace unavailable"));
    renderViewer();

    expect(await screen.findByText("Could not load document")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.queryByText("This file type cannot be previewed inline.")).not.toBeInTheDocument();
  });
});
