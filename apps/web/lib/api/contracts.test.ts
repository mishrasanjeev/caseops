import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { fetchContractAttachmentBlob, type ContractAttachmentSource } from "./contracts";

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
  await expect(fetchContractAttachmentBlob("c1", "a1", { ...source, size_bytes: 32 * 1024 * 1024 + 1 })).rejects.toMatchObject({ status: 409 });
  expect(binary).not.toHaveBeenCalled();
});
