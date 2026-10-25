import type { AuthorizedRequest } from "../domain/repository.ts";
import { ContractError } from "../domain/contracts.ts";
import {
  decodeFilesWorkspace,
  decodeMatterFile,
  identity,
  MAX_NATIVE_UPLOAD_BYTES,
} from "./contracts.ts";
import type { FilesScope } from "./contracts.ts";

export type NativeFilePart = Readonly<{
  uri: string;
  name: string;
  type: string;
}>;
export type StagedFile = {
  part: NativeFilePart;
  size: number;
  sha256: string;
  dispose: () => void;
};
export type MultipartFactory = (
  part: NativeFilePart,
  expectedLifecycleVersion: number,
  expectedSize: number,
) => FormData;

function validateLifecycleVersion(value: number): void {
  if (!Number.isSafeInteger(value) || value < 0)
    throw new ContractError("upload lifecycle version");
}

export function stagedMultipartUri(value: string, rootValue: string): string {
  const root = new URL(rootValue),
    uri = new URL(value);
  if (!root.pathname.endsWith("/")) root.pathname += "/";
  if (
    [root, uri].some(
      (item) =>
        item.protocol !== "file:" ||
        item.hostname ||
        item.username ||
        item.password ||
        item.search ||
        item.hash,
    ) ||
    !uri.href.startsWith(root.href) ||
    !/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\.(pdf|docx|doc|txt|png|jpg|jpeg)$/.test(
      uri.href.slice(root.href.length),
    )
  )
    throw new ContractError("owned staged multipart URI");
  return uri.href;
}

export function multipartFilename(value: string): string {
  if (!value.trim() || value.length > 255 || /[\x00-\x1f\x7f/\\]/.test(value))
    throw new ContractError("native multipart filename");
  // Mirror the server's existing display-filename normalization before Expo's
  // percent-encoding, which would otherwise turn spaces into a literal _20.
  return (
    value
      .trim()
      .replace(/[^A-Za-z0-9._-]+/g, "_")
      .slice(0, 255) || "document"
  );
}

export function nativeMultipart(
  part: NativeFilePart,
  expectedLifecycleVersion: number,
  readBytes?: () => Promise<Uint8Array>,
  expectedSize?: number,
): FormData {
  validateLifecycleVersion(expectedLifecycleVersion);
  if (
    typeof readBytes !== "function" ||
    typeof expectedSize !== "number" ||
    !Number.isSafeInteger(expectedSize) ||
    expectedSize < 1 ||
    expectedSize > MAX_NATIVE_UPLOAD_BYTES
  )
    throw new ContractError("native multipart file reader and size");
  const body = new FormData();
  // Expo fetch accepts its File-like bytes interface, not RN's URI descriptor.
  // Keep the server-normalized filename/MIME and read only the staged copy.
  const file = {
    name: multipartFilename(part.name),
    type: part.type,
    bytes: async () => {
      const value = await readBytes();
      if (
        !(value instanceof Uint8Array) ||
        value.length !== expectedSize ||
        value.length > MAX_NATIVE_UPLOAD_BYTES
      )
        throw new ContractError("native multipart staged bytes");
      return value;
    },
  };
  body.append("file", file as unknown as Blob);
  body.append("expected_lifecycle_version", String(expectedLifecycleVersion));
  return body;
}
export function createMatterFilesApi(
  request: AuthorizedRequest,
  scope: FilesScope,
  multipart?: MultipartFactory,
) {
  identity(scope.companyId, "company identity");
  identity(scope.userId, "user identity");
  identity(scope.sessionKey, "session generation");
  const base = `/api/matters/${encodeURIComponent(identity(scope.matterId, "matter identity"))}`;
  return {
    workspace: async (signal?: AbortSignal) =>
      decodeFilesWorkspace(
        await request<unknown>(`${base}/workspace`, { signal }),
        scope,
      ),
    upload: async (
      file: StagedFile,
      expectedLifecycleVersion: number,
      signal: AbortSignal,
    ) => {
      validateLifecycleVersion(expectedLifecycleVersion);
      if (!multipart)
        throw new ContractError("native multipart adapter required");
      return decodeMatterFile(
        await request<unknown>(`${base}/attachments`, {
          method: "POST",
          body: multipart(file.part, expectedLifecycleVersion, file.size),
          signal,
          // Native fetch supplies the multipart boundary. No JSON or guessed fields.
        }),
        scope.matterId,
      );
    },
  };
}
export type MatterFilesApi = ReturnType<typeof createMatterFilesApi>;
