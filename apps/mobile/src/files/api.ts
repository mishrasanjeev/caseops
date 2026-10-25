import type { AuthorizedRequest } from "../domain/repository.ts";
import { ContractError } from "../domain/contracts.ts";
import {
  decodeFilesWorkspace,
  decodeMatterFile,
  identity,
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
) => FormData;

function validateLifecycleVersion(value: number): void {
  if (!Number.isSafeInteger(value) || value < 0)
    throw new ContractError("upload lifecycle version");
}

export function nativeMultipart(
  part: NativeFilePart,
  expectedLifecycleVersion: number,
): FormData {
  validateLifecycleVersion(expectedLifecycleVersion);
  const body = new FormData();
  // React Native's installed FormData accepts a file URI, not a web Blob.
  (
    body as unknown as { append(name: string, value: NativeFilePart): void }
  ).append("file", part);
  body.append("expected_lifecycle_version", String(expectedLifecycleVersion));
  return body;
}
export function createMatterFilesApi(
  request: AuthorizedRequest,
  scope: FilesScope,
  multipart: MultipartFactory = nativeMultipart,
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
      return decodeMatterFile(
        await request<unknown>(`${base}/attachments`, {
          method: "POST",
          body: multipart(file.part, expectedLifecycleVersion),
          signal,
          // Native fetch supplies the multipart boundary. No JSON or guessed fields.
        }),
        scope.matterId,
      );
    },
  };
}
export type MatterFilesApi = ReturnType<typeof createMatterFilesApi>;
