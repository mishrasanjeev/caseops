import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NetworkError } from "./config";
import {
  downloadAttachmentRendition,
  downloadBulkImportErrors,
  downloadIpPleadingDraft,
  downloadIpPleadingFilingBundle,
  downloadIpPortfolioExport,
  downloadIpPortfolioImportErrors,
  downloadMatterBulkUpdateTemplate,
  fetchMatterAttachmentBlob,
} from "./endpoints";
import { downloadNoticeFile } from "./notices";

// Issue #613: every authenticated download must keep cancellation and the
// one request deadline through authentication recovery and the whole body.

const API = "http://localhost:8000";
const DEADLINE_MS = 90_000;
const OBJECT_URL = "blob:caseops-download";
const createObjectURL = vi.fn<(blob: Blob) => string>(() => OBJECT_URL);
const revokeObjectURL = vi.fn();
const savedNames: string[] = [];
const createDescriptor = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
const revokeDescriptor = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");

async function savedFile(save: () => Promise<void>): Promise<Blob> {
  await save();
  const blob = createObjectURL.mock.calls.at(-1)?.[0];
  if (!blob) throw new Error("No object URL was created.");
  return blob;
}

type Caller = {
  name: string;
  path: string;
  type: string;
  savedName?: string;
  run: () => Promise<Blob>;
};

const callers: Caller[] = [
  {
    name: "downloadMatterBulkUpdateTemplate",
    path: "/api/matters/bulk-update/template?format=xlsx",
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    run: () => downloadMatterBulkUpdateTemplate("xlsx"),
  },
  {
    name: "downloadIpPleadingDraft",
    path: "/api/ip/dockets/docket%2F1/proceedings/proc-1/drafts/draft-1/export.docx",
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    run: () => downloadIpPleadingDraft({ docketId: "docket/1", proceedingId: "proc-1", draftId: "draft-1" }),
  },
  {
    name: "downloadIpPleadingFilingBundle",
    path: "/api/ip/dockets/docket-1/proceedings/proc-1/drafts/draft-1/filing-bundle.zip",
    type: "application/zip",
    run: () => downloadIpPleadingFilingBundle({ docketId: "docket-1", proceedingId: "proc-1", draftId: "draft-1" }),
  },
  {
    name: "fetchMatterAttachmentBlob",
    path: "/api/matters/matter-1/attachments/attachment-1/download?inline=true",
    type: "image/png",
    run: () => fetchMatterAttachmentBlob({ matterId: "matter-1", attachmentId: "attachment-1", inline: true }),
  },
  {
    name: "downloadIpPortfolioExport",
    path: "/api/ip/portfolio/exports/export%201/download",
    type: "text/csv",
    run: () => downloadIpPortfolioExport("export 1"),
  },
  {
    name: "downloadIpPortfolioImportErrors",
    path: "/api/ip/imports/import-1/errors",
    type: "text/csv",
    run: () => downloadIpPortfolioImportErrors("import-1"),
  },
  {
    name: "downloadBulkImportErrors",
    path: "/api/imports/matter/job-1/errors",
    type: "text/csv",
    run: () => downloadBulkImportErrors("matter", "job-1"),
  },
  {
    name: "downloadNoticeFile",
    path: "/api/notices/notice%2F1/download",
    type: "application/pdf",
    savedName: "server-notice.pdf",
    run: () => savedFile(() => downloadNoticeFile("notice/1", "fallback.pdf")),
  },
  {
    name: "downloadAttachmentRendition",
    path: "/api/matters/matter-1/attachments/attachment-1/renditions/rendition-1/download",
    type: "application/pdf",
    savedName: "server-rendition.pdf",
    run: () => savedFile(() => downloadAttachmentRendition({
      matterId: "matter-1", attachmentId: "attachment-1", renditionId: "rendition-1", fallbackName: "fallback.pdf",
    })),
  },
];

// Bytes that a text decode would corrupt: the original must survive intact.
const CHUNKS = [
  new Uint8Array([0x50, 0x4b, 0x03, 0x04]),
  new Uint8Array([0x00, 0xff, 0xfe, 0x80]),
  new Uint8Array([0x25, 0x50, 0x44, 0x46]),
];
const ORIGINAL = new Uint8Array(CHUNKS.flatMap((chunk) => [...chunk]));

function headersFor(caller: Caller): Record<string, string> {
  return {
    "content-type": caller.type,
    ...(caller.savedName ? { "content-disposition": `attachment; filename="${caller.savedName}"` } : {}),
  };
}

function chunkedBody(): ReadableStream<Uint8Array> {
  let index = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (index < CHUNKS.length) controller.enqueue(CHUNKS[index++]);
      else controller.close();
    },
  });
}

/** Headers arrive with one chunk; the rest of the body never does. */
function stalledBody(cancel: (reason: unknown) => void): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) { controller.enqueue(CHUNKS[0]); },
    cancel,
  });
}

function truncatedBody(): ReadableStream<Uint8Array> {
  let pulls = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      pulls += 1;
      if (pulls === 1) controller.enqueue(CHUNKS[0]);
      else controller.error(new TypeError("terminated: other side closed"));
    },
  });
}

function json(body: unknown, status: number, contentType = "application/json"): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": contentType } });
}

describe("authenticated downloads read the complete body inside one deadline", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.stubGlobal("fetch", vi.fn());
    createObjectURL.mockClear();
    revokeObjectURL.mockClear();
    savedNames.length = 0;
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      savedNames.push(this.download);
    });
  });

  afterEach(async () => {
    vi.useRealTimers();
    await new Promise((resolve) => setTimeout(resolve, 0));
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    window.localStorage.clear();
    if (createDescriptor) Object.defineProperty(URL, "createObjectURL", createDescriptor);
    else Reflect.deleteProperty(URL, "createObjectURL");
    if (revokeDescriptor) Object.defineProperty(URL, "revokeObjectURL", revokeDescriptor);
    else Reflect.deleteProperty(URL, "revokeObjectURL");
  });

  it.each(callers)("$name returns the original chunked bytes from a private no-store request", async (caller) => {
    vi.useFakeTimers();
    vi.mocked(fetch).mockResolvedValue(new Response(chunkedBody(), { headers: headersFor(caller) }));

    const blob = await caller.run();

    expect(new Uint8Array(await blob.arrayBuffer())).toEqual(ORIGINAL);
    expect(blob.type).toBe(caller.type);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith(`${API}${caller.path}`, expect.objectContaining({
      method: "GET",
      credentials: "include",
      cache: "no-store",
      headers: expect.objectContaining({ Accept: "*/*" }),
    }));
    expect(vi.getTimerCount()).toBe(caller.savedName ? 1 : 0);
    if (caller.savedName) {
      // The saved file keeps the server's Content-Disposition name, and the
      // object URL stays owned by the download until its revoke timer.
      expect(savedNames).toEqual([caller.savedName]);
      expect(revokeObjectURL).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(30_000);
      expect(revokeObjectURL).toHaveBeenCalledExactlyOnceWith(OBJECT_URL);
    }
  });

  it.each(callers)("$name fails at the deadline and cancels a body that stalls after headers", async (caller) => {
    vi.useFakeTimers();
    const cancel = vi.fn();
    vi.mocked(fetch).mockResolvedValue(new Response(stalledBody(cancel), { headers: headersFor(caller) }));

    const assertion = expect(caller.run()).rejects.toMatchObject({
      name: "NetworkError", message: expect.stringContaining("90 seconds"),
    });
    await vi.advanceTimersByTimeAsync(DEADLINE_MS);
    await assertion;

    expect(cancel).toHaveBeenCalled();
    expect(vi.mocked(fetch).mock.calls[0][1]?.signal?.aborted).toBe(true);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(savedNames).toEqual([]);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(callers)("$name reports a truncated body as a network failure, never a partial file", async (caller) => {
    vi.mocked(fetch).mockResolvedValue(new Response(truncatedBody(), { headers: headersFor(caller) }));

    const failure = await caller.run().then(() => null, (error: unknown) => error);

    expect(failure).toBeInstanceOf(NetworkError);
    expect(failure).toMatchObject({ message: expect.stringContaining("Could not reach the workspace API") });
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(savedNames).toEqual([]);
  });

  it.each(callers)("$name keeps one deadline across session refresh and the retried body", async (caller) => {
    vi.useFakeTimers();
    window.localStorage.setItem("caseops.session.context", "{}");
    const cancel = vi.fn();
    vi.mocked(fetch)
      .mockResolvedValueOnce(json({ type: "invalid_token", detail: "Expired" }, 401, "application/problem+json"))
      .mockResolvedValueOnce(json({ access_token: "fresh", token_type: "bearer", company: {}, user: {}, membership: {} }, 200))
      .mockResolvedValueOnce(new Response(stalledBody(cancel), { headers: headersFor(caller) }));

    const assertion = expect(caller.run()).rejects.toMatchObject({
      name: "NetworkError", message: expect.stringContaining("90 seconds"),
    });
    await vi.advanceTimersByTimeAsync(DEADLINE_MS);
    await assertion;

    expect(fetch).toHaveBeenCalledTimes(3);
    expect(vi.mocked(fetch).mock.calls[1][0]).toBe(`${API}/api/auth/refresh`);
    expect(vi.mocked(fetch).mock.calls[2][0]).toBe(`${API}${caller.path}`);
    expect(vi.mocked(fetch).mock.calls[2][1]?.signal?.aborted).toBe(true);
    expect(cancel).toHaveBeenCalled();
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("cancels a Matter attachment body when the caller aborts after headers", async () => {
    const controller = new AbortController();
    const cancel = vi.fn();
    let pulled!: () => void;
    const reading = new Promise<void>((resolve) => { pulled = resolve; });
    vi.mocked(fetch).mockResolvedValue(new Response(new ReadableStream<Uint8Array>({ pull: pulled, cancel }), {
      headers: { "content-type": "image/png" },
    }));

    const operation = fetchMatterAttachmentBlob({
      matterId: "matter-1", attachmentId: "attachment-1", inline: true, signal: controller.signal,
    });
    await reading;
    controller.abort(new DOMException("Viewer unmounted", "AbortError"));

    await expect(operation).rejects.toMatchObject({ name: "AbortError" });
    expect(cancel).toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
