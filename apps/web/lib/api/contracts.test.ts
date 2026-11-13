import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { fetchContractAttachmentBlob, type ContractAttachmentSource, CONTRACT_ORIGINAL_MAX_BYTES } from "./contracts";

const { binary } = vi.hoisted(() => ({ binary: vi.fn() }));
vi.mock("./client", () => ({ apiBlobDataRequest: binary, apiRequest: vi.fn() }));
const bytes = new TextEncoder().encode("%PDF-private-source");
let source: ContractAttachmentSource;
beforeEach(async () => {
  binary.mockReset();
  vi.stubGlobal("crypto", webcrypto);
  source = { original_filename: "source.pdf", content_type: "application/pdf", size_bytes: bytes.byteLength,
    sha256_hex: Array.from(new Uint8Array(await webcrypto.subtle.digest("SHA-256", bytes))).map((x) => x.toString(16).padStart(2, "0")).join("") };
  binary.mockResolvedValue({ blob: new Blob([bytes]), headers: new Headers({ "content-type": "application/pdf" }), status: 200 });
});
afterEach(() => { vi.unstubAllGlobals(); });

it("binds preview bytes to the workspace hash, MIME and exact byte length in one request", async () => {
  const signal = new AbortController().signal;
  const result = await fetchContractAttachmentBlob("c1", "a1", source, signal, true);
  expect(result.size).toBe(bytes.byteLength);
  expect(binary).toHaveBeenCalledWith("/api/contracts/c1/attachments/a1/preview", {
    signal, maxBytes: bytes.byteLength, headers: { Accept: "application/pdf" },
  });
  expect(binary).toHaveBeenCalledTimes(1);
});
it.each(["hash", "mime", "size"])("rejects a successful response with mismatched %s", async (kind) => {
  if (kind === "hash") source.sha256_hex = "0".repeat(64);
  if (kind === "size") source.size_bytes += 1;
  if (kind === "mime") binary.mockResolvedValue({ blob: new Blob([bytes]), headers: new Headers({ "content-type": "text/html" }), status: 200 });
  await expect(fetchContractAttachmentBlob("c1", "a1", source, undefined, true)).rejects.toMatchObject({ status: 409 });
});
it("rejects unbounded source metadata before fetching bytes", async () => {
  await expect(fetchContractAttachmentBlob("c1", "a1", { ...source, size_bytes: CONTRACT_ORIGINAL_MAX_BYTES + 1 })).rejects.toMatchObject({ status: 413 });
  expect(binary).not.toHaveBeenCalled();
});

it("keeps a 33 MiB original downloadable while rejecting inline preview above 32 MiB", async () => {
  const large = new Uint8Array(33 * 1024 * 1024);
  large.set(bytes);
  source.size_bytes = large.byteLength;
  source.sha256_hex = Array.from(new Uint8Array(await webcrypto.subtle.digest("SHA-256", large))).map((x) => x.toString(16).padStart(2, "0")).join("");
  binary.mockResolvedValue({ blob: new Blob([large]), headers: new Headers({ "content-type": "application/pdf" }), status: 200 });
  await expect(fetchContractAttachmentBlob("c1", "a1", source, undefined, true)).rejects.toMatchObject({ status: 413, detail: expect.stringContaining("download the original") });
  expect(binary).not.toHaveBeenCalled();
  expect((await fetchContractAttachmentBlob("c1", "a1", source)).size).toBe(large.byteLength);
  expect(binary).toHaveBeenCalledWith("/api/contracts/c1/attachments/a1/download", expect.objectContaining({ maxBytes: large.byteLength }));
});

it.each(["application/octet-stream", "application/zip; profile=office", "application/vnd.openxmlformats-officedocument.wordprocessingml.document; version=1"])("normalizes admitted DOCX MIME %s", async (mime) => {
  const canonical = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  source.original_filename = "source.docx";
  source.content_type = mime;
  binary.mockResolvedValue({ blob: new Blob([bytes]), headers: new Headers({ "content-type": canonical }), status: 200 });
  await expect(fetchContractAttachmentBlob("c1", "a1", source, undefined, true)).resolves.toBeInstanceOf(Blob);
  await expect(fetchContractAttachmentBlob("c1", "a1", source)).resolves.toBeInstanceOf(Blob);
});
it("normalizes parameterized PDF MIME without accepting a genuine type conflict", async () => {
  source.content_type = "Application/PDF; charset=binary";
  await expect(fetchContractAttachmentBlob("c1", "a1", source, undefined, true)).resolves.toBeInstanceOf(Blob);
  source.content_type = "text/html";
  binary.mockClear();
  await expect(fetchContractAttachmentBlob("c1", "a1", source)).rejects.toMatchObject({ status: 409 });
  expect(binary).not.toHaveBeenCalled();
});
