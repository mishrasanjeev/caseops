import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiBlobRequestMock, apiRequestMock } = vi.hoisted(() => ({
  apiBlobRequestMock: vi.fn(),
  apiRequestMock: vi.fn(),
}));

vi.mock("@/lib/api/client", () => ({
  apiBlobRequest: apiBlobRequestMock,
  apiRequest: apiRequestMock,
}));

import {
  createNotice,
  downloadNoticeFile,
  getNotice,
  listNotices,
  listNoticeOwners,
  updateNotice,
  uploadNoticeFile,
} from "@/lib/api/notices";

describe("notices API client", () => {
  beforeEach(() => {
    apiBlobRequestMock.mockReset();
    apiRequestMock.mockReset();
    apiRequestMock.mockResolvedValue({ id: "notice-1" });
  });

  it("serializes every supported unified-list filter", async () => {
    await listNotices({
      limit: 50,
      cursor: "next page",
      query: "tax demand",
      direction: "received",
      status: "Open",
      matter_id: "matter-1",
      owner_membership_id: "owner-1",
      due_from: "2026-07-01",
      due_to: "2026-07-31",
    });

    expect(apiRequestMock).toHaveBeenCalledWith(
      "/api/notices/?limit=50&cursor=next+page&query=tax+demand&direction=received&status=Open&matter_id=matter-1&owner_membership_id=owner-1&due_from=2026-07-01&due_to=2026-07-31",
    );
  });

  it("uses JSON POST and PATCH without routing through matter attachments", async () => {
    const createInput = {
      direction: "sent" as const,
      subject: "Response",
      status: "Open",
      owner_membership_id: null,
      matter_ids: ["matter-1", "matter-2"],
    };
    await createNotice(createInput);
    await updateNotice("notice/unsafe", {
      status: "Closed",
      matter_ids: [],
      expected_updated_at: "2026-07-15T09:00:00Z",
    });

    expect(apiRequestMock).toHaveBeenNthCalledWith(1, "/api/notices/", {
      method: "POST",
      body: createInput,
    });
    expect(apiRequestMock).toHaveBeenNthCalledWith(
      2,
      "/api/notices/notice%2Funsafe",
      {
        method: "PATCH",
        body: {
          status: "Closed",
          matter_ids: [],
          expected_updated_at: "2026-07-15T09:00:00Z",
        },
      },
    );
  });

  it("uploads the optional file as multipart after a notice id exists", async () => {
    const file = new File(["notice"], "notice.pdf", {
      type: "application/pdf",
    });
    await uploadNoticeFile("notice-1", file, "2026-07-15T10:00:00Z");

    expect(apiRequestMock).toHaveBeenCalledTimes(1);
    const [path, init] = apiRequestMock.mock.calls[0] as [
      string,
      { method: string; body: FormData },
    ];
    expect(path).toBe("/api/notices/notice-1/file");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.body.get("file")).toBe(file);
    expect(init.body.get("expected_updated_at")).toBe("2026-07-15T10:00:00Z");
  });

  it("reads one standalone notice for stale-form recovery", async () => {
    await getNotice("notice/unsafe");

    expect(apiRequestMock).toHaveBeenCalledWith("/api/notices/notice%2Funsafe");
  });

  it("uses the notice-scoped owner directory instead of the employee-admin API", async () => {
    await listNoticeOwners();

    expect(apiRequestMock).toHaveBeenCalledWith("/api/notices/owners");
  });

  it("downloads through the shared authenticated binary transport", async () => {
    const createObjectUrl = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:notice");
    const revokeObjectUrl = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    apiBlobRequestMock.mockResolvedValue(
      new Response("notice bytes", {
        status: 200,
        headers: {
          "content-disposition": 'attachment; filename="server-name.txt"',
        },
      }),
    );

    await downloadNoticeFile("notice/unsafe", "fallback.txt");

    expect(apiBlobRequestMock).toHaveBeenCalledWith(
      "/api/notices/notice%2Funsafe/download",
    );
    const downloadedBlob = createObjectUrl.mock.calls[0]?.[0] as Blob | undefined;
    expect(downloadedBlob).toBeDefined();
    expect(downloadedBlob).toMatchObject({
      size: 12,
      type: "text/plain;charset=utf-8",
    });
    expect(await downloadedBlob?.text()).toBe("notice bytes");
    expect(click).toHaveBeenCalledTimes(1);

    createObjectUrl.mockRestore();
    revokeObjectUrl.mockRestore();
    click.mockRestore();
  });
});
