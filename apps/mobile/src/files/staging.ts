import { ContractError } from "../domain/contracts.ts";
import type { StagedFile } from "./api.ts";
import type { MatterFileAsset, UploadPolicy } from "./contracts.ts";
import { MAX_NATIVE_UPLOAD_BYTES } from "./contracts.ts";

// services/file_security.py: ALLOWED_UPLOADS and DEFAULT_MAX_BYTES.
const kinds: Record<string, readonly string[]> = {
  pdf: ["application/pdf"],
  docx: [
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",
    "application/zip",
  ],
  doc: ["application/msword", "application/octet-stream"],
  txt: ["text/plain", "application/octet-stream"],
  png: ["image/png"],
  jpg: ["image/jpeg"],
  jpeg: ["image/jpeg"],
};
export const pickerMimeTypes = [...new Set(Object.values(kinds).flat())];
export const MAX_STAGING_AGE_MS = 120_000;
export class TempCleanupError extends Error {
  constructor() {
    super("Temporary upload cleanup could not be confirmed.");
    this.name = "TempCleanupError";
  }
}
export async function copyBounded(
  read: (length: number) => Promise<Uint8Array>,
  write: (bytes: Uint8Array) => Promise<void>,
  limit: number,
  check: () => void,
): Promise<number> {
  let total = 0;
  while (true) {
    check();
    const requested = Math.min(1024 * 1024, limit - total + 1);
    const chunk = await read(requested);
    check();
    if (chunk.length === 0) return total;
    if (chunk.length > requested || total + chunk.length > limit)
      throw new Error("The file exceeds the current upload limit.");
    await write(chunk);
    total += chunk.length;
  }
}
export function uploadByteLimit(policy: UploadPolicy): number {
  return Math.min(
    MAX_NATIVE_UPLOAD_BYTES,
    policy.max_upload_size_bytes,
    policy.remaining_bytes ?? Infinity,
  );
}
export function validateAsset(asset: MatterFileAsset, policy: UploadPolicy) {
  if (
    !asset.name.trim() ||
    asset.name.length > 255 ||
    /[\x00-\x1f\x7f/\\]/.test(asset.name)
  )
    throw new Error(
      "Choose a file with a filename of at most 255 characters, without path separators.",
    );
  const extension = asset.name.trim().split(".").pop()?.toLowerCase() ?? "";
  if (
    asset.name.trim().lastIndexOf(".") <= 0 ||
    !Object.hasOwn(kinds, extension)
  )
    throw new Error("Choose a PDF, Word, plain-text, PNG or JPEG file.");
  const mime =
    asset.mimeType?.split(";", 1)[0].trim().toLowerCase() ||
    kinds[extension][0];
  if (!kinds[extension].includes(mime))
    throw new Error(
      "The selected file type does not match its filename. Choose the original file.",
    );
  const uri = new URL(asset.uri);
  if (
    !["file:", "content:"].includes(uri.protocol) ||
    (uri.protocol === "file:" && uri.hostname) ||
    uri.username ||
    uri.password ||
    uri.search ||
    uri.hash
  )
    throw new Error("Choose a local file from the system file picker.");
  const limit = uploadByteLimit(policy);
  if (!Number.isSafeInteger(limit) || limit <= 0)
    throw new Error(
      "No upload capacity is available. Reload the workspace storage policy.",
    );
  if (
    asset.size !== undefined &&
    (!Number.isSafeInteger(asset.size) || asset.size < 0 || asset.size > limit)
  )
    throw new Error(
      "The selected file exceeds the current upload or storage limit.",
    );
  return { extension, mime, limit };
}
export type LocalFile = {
  exists: boolean;
  size: number;
  copyTo: (uri: string, limit: number, check: () => void) => Promise<void>;
  digest: () => Promise<string>;
  delete: () => void;
};
export type StagingIO = {
  rootUri: string;
  ensureRoot: () => void;
  uniqueUri: (extension: string) => string;
  file: (uri: string) => LocalFile;
  purgeRoot: () => void;
};
export function isOwnedStagingUri(uri: string, rootUri: string): boolean {
  const root = rootUri.replace(/\/$/, "");
  return (
    uri.startsWith(`${root}/`) &&
    /^[a-f0-9-]{36}\.(pdf|docx|doc|txt|png|jpg|jpeg)$/.test(
      uri.slice(root.length + 1),
    )
  );
}

export function createStagingArea(io: StagingIO, now: () => number = Date.now) {
  let generation = 0;
  const clean = (uri: string) => {
    if (!isOwnedStagingUri(uri, io.rootUri)) return;
    try {
      const file = io.file(uri);
      if (file.exists) file.delete();
    } catch {
      throw new TempCleanupError();
    }
  };
  return {
    cleanupPickedFile(asset: MatterFileAsset) {
      clean(asset.uri);
    },
    purge() {
      generation++;
      try {
        io.purgeRoot();
      } catch {
        throw new TempCleanupError();
      }
    },
    async prepare(
      asset: MatterFileAsset,
      policy: UploadPolicy,
      signal: AbortSignal,
    ): Promise<StagedFile> {
      const { extension, mime, limit } = validateAsset(asset, policy);
      const started = now(),
        epoch = generation;
      const check = () => {
        if (
          signal.aborted ||
          epoch !== generation ||
          now() - started >= MAX_STAGING_AGE_MS
        )
          throw new Error(
            "File preparation ended. Select the file again after reloading this matter.",
          );
      };
      check();
      io.ensureRoot();
      const uri = io.uniqueUri(extension);
      if (!isOwnedStagingUri(uri, io.rootUri))
        throw new ContractError("owned upload staging path");
      const target = io.file(uri);
      let retained = false;
      try {
        const source = io.file(asset.uri);
        if (
          !source.exists ||
          !Number.isSafeInteger(source.size) ||
          source.size < 1 ||
          source.size > limit
        )
          throw new Error(
            "The file is empty, unavailable or exceeds the current size limit. Choose the original file again.",
          );
        await source.copyTo(uri, limit, check);
        check();
        const size = target.size;
        if (
          !target.exists ||
          !Number.isSafeInteger(size) ||
          size < 1 ||
          size > limit ||
          size !== source.size
        )
          throw new Error(
            "The selected file could not be copied completely within the upload limit.",
          );
        const sha256 = await target.digest();
        check();
        if (!/^[a-f0-9]{64}$/.test(sha256))
          throw new ContractError("local source hash");
        retained = true;
        return {
          part: { uri, name: asset.name, type: mime },
          size,
          sha256,
          dispose: () => clean(uri),
        };
      } finally {
        if (!retained) clean(uri);
      }
    },
  };
}
export type FileStager = Pick<ReturnType<typeof createStagingArea>, "prepare">;
