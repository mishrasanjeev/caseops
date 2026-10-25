import { ContractError } from "../domain/contracts.ts";
import { errorStatus, readFailure } from "../domain/repository.ts";
import type { ReadFailure } from "../domain/repository.ts";
import type { MatterFilesApi, StagedFile } from "./api.ts";
import { matchesSelection, uploadRestriction } from "./contracts.ts";
import type {
  FilesScope,
  FilesWorkspace,
  MatterFile,
  MatterFileSelection,
} from "./contracts.ts";
import { TempCleanupError } from "./staging.ts";
import type { FileStager } from "./staging.ts";

export type FilesView =
  | { state: "inactive" | "loading" }
  | { state: "ready"; workspace: FilesWorkspace }
  | { state: "error"; error: ReadFailure };
export type UploadOutcome = {
  state:
    | "idle"
    | "preparing"
    | "uploading"
    | "persisted"
    | "acknowledged"
    | "rejected"
    | "unknown";
  message: string;
  attachmentId?: string;
};
export type FilesSnapshot = {
  view: FilesView;
  upload: UploadOutcome;
  cleanupFailed: boolean;
};

const idle: UploadOutcome = { state: "idle", message: "" };
const unknown: UploadOutcome = {
  state: "unknown",
  message:
    "The upload outcome is unknown. The file may have been saved. Do not upload it again. Reload the files to check; this app will not resubmit it.",
};
function awaitingReadback(file: MatterFile): UploadOutcome {
  return {
    state: "acknowledged",
    attachmentId: file.id,
    message:
      "The server acknowledged this file. Its current persisted source is not confirmed. Do not upload it again; reload files to check.",
  };
}
function safeRejection(error: unknown): boolean {
  const status = errorStatus(error);
  const outcome =
    error && typeof error === "object"
      ? (error as { outcome?: unknown }).outcome
      : undefined;
  return (
    outcome !== "unknown" &&
    status !== null &&
    [400, 401, 403, 404, 409, 413, 415, 422, 429].includes(status)
  );
}
function sameSource(left: MatterFile, right: MatterFile): boolean {
  return (
    left.id === right.id &&
    left.matter_id === right.matter_id &&
    left.sha256_hex === right.sha256_hex &&
    left.size_bytes === right.size_bytes &&
    left.original_filename === right.original_filename
  );
}

export function createFilesController(
  api: MatterFilesApi,
  stager: FileStager,
  scope: FilesScope,
  capabilities: readonly string[] | (() => readonly string[]),
) {
  const currentCapabilities = () =>
    typeof capabilities === "function" ? capabilities() : capabilities;
  let snapshot: FilesSnapshot = {
    view: { state: "inactive" },
    upload: idle,
    cleanupFailed: false,
  };
  const listeners = new Set<() => void>();
  let active = false,
    epoch = 0,
    busy = false,
    uncertain = false;
  let read: AbortController | null = null,
    write: AbortController | null = null;
  let staged: StagedFile | null = null;
  let acknowledged: MatterFile | null = null;
  const attempted = new WeakSet<MatterFileSelection>();
  const publish = (change: Partial<FilesSnapshot>) => {
    snapshot = { ...snapshot, ...change };
    listeners.forEach((listener) => listener());
  };
  const current = (generation: number) => active && epoch === generation;
  const cleanup = () => {
    const file = staged;
    staged = null;
    if (!file) return;
    try {
      file.dispose();
    } catch {
      publish({ cleanupFailed: true });
    }
  };
  const reject = (message: string) =>
    publish({ upload: { state: "rejected", message } });

  const controller = {
    getSnapshot: () => snapshot,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    activate() {
      active = true;
      return controller.reload();
    },
    dispose() {
      active = false;
      epoch++;
      read?.abort();
      write?.abort();
      acknowledged = null;
      cleanup();
      publish({ view: { state: "inactive" }, upload: idle });
    },
    async reload() {
      if (!active || busy) return;
      read?.abort();
      const abort = new AbortController();
      read = abort;
      const generation = ++epoch;
      publish({
        view: { state: "loading" },
        ...(acknowledged ? { upload: awaitingReadback(acknowledged) } : {}),
      });
      try {
        const workspace = await api.workspace(abort.signal);
        if (!current(generation)) return;
        let upload = snapshot.upload;
        if (acknowledged) {
          const retained = workspace.attachments.find(
            (file) => file.id === acknowledged!.id,
          );
          if (retained && sameSource(retained, acknowledged)) {
            upload = {
              state: "persisted",
              attachmentId: retained.id,
              message:
                "Upload acknowledged and the same source confirmed after reload. A separate clean-scan receipt is not supplied by this server.",
            };
          } else upload = awaitingReadback(acknowledged);
        }
        publish({ view: { state: "ready", workspace }, upload });
      } catch (error) {
        if (current(generation)) {
          const failure = readFailure(error);
          if (failure.kind === "restricted") {
            acknowledged = null;
            publish({
              upload: {
                state: snapshot.upload.state,
                message: snapshot.upload.message,
              },
            });
          }
          publish({ view: { state: "error", error: failure } });
        }
      }
    },
    clearOutcome() {
      if (!busy && !uncertain) publish({ upload: idle });
    },
    recordCleanupFailure() {
      publish({ cleanupFailed: true });
    },
    cancel() {
      if (!busy) return;
      write?.abort();
      if (snapshot.upload.state === "uploading") {
        uncertain = true;
        publish({ upload: unknown });
      } else if (snapshot.upload.state === "preparing")
        publish({
          upload: {
            state: "preparing",
            message:
              "Cancelling preparation. No file will be sent; temporary-copy cleanup is pending.",
          },
        });
    },
    async submit(selection: MatterFileSelection) {
      if (
        !active ||
        busy ||
        uncertain ||
        snapshot.cleanupFailed ||
        snapshot.view.state !== "ready"
      )
        return;
      if (attempted.has(selection)) return;
      if (!matchesSelection(selection, scope)) {
        reject(
          "This selection belongs to another account or matter. Clear it and select the file again.",
        );
        return;
      }
      const original = snapshot.view.workspace;
      if (
        !Number.isSafeInteger(selection.expectedLifecycleVersion) ||
        selection.expectedLifecycleVersion < 0 ||
        selection.expectedLifecycleVersion !== original.matter.lifecycle_version
      ) {
        reject(
          "The matter lifecycle changed since this file was chosen. Reload and select it again.",
        );
        return;
      }
      const restriction = uploadRestriction(original, currentCapabilities());
      if (restriction) {
        reject(restriction);
        return;
      }
      busy = true;
      const abort = new AbortController();
      write = abort;
      const generation = epoch;
      let sent = false;
      publish({
        upload: {
          state: "preparing",
          message:
            "Preparing a temporary upload copy and checking current access.",
        },
      });
      const preflight = async (): Promise<FilesWorkspace | null> => {
        let latest: FilesWorkspace;
        try {
          latest = await api.workspace(abort.signal);
        } catch (error) {
          if (current(generation)) {
            publish({ view: { state: "error", error: readFailure(error) } });
            reject(
              "Current access could not be confirmed. The file was not sent.",
            );
          }
          return null;
        }
        if (!current(generation) || abort.signal.aborted) return null;
        publish({ view: { state: "ready", workspace: latest } });
        const blocked = uploadRestriction(latest, currentCapabilities());
        if (
          blocked ||
          latest.matter.lifecycle_version !== selection.expectedLifecycleVersion
        ) {
          reject(
            blocked ||
              "The matter lifecycle changed. The file was not sent. Reload and select it again.",
          );
          return null;
        }
        return latest;
      };
      try {
        const admission = await preflight();
        if (!admission) return;
        const prepared = await stager.prepare(
          selection.asset,
          admission.storage,
          abort.signal,
        );
        if (!current(generation) || abort.signal.aborted) {
          prepared.dispose();
          return;
        }
        staged = prepared;
        const latest = await preflight();
        if (!latest) return;
        if (
          prepared.size >
          Math.min(
            latest.storage.max_upload_size_bytes,
            latest.storage.remaining_bytes ?? Infinity,
          )
        ) {
          reject("The storage limit changed. The file was not sent.");
          return;
        }
        attempted.add(selection);
        sent = true;
        publish({
          upload: {
            state: "uploading",
            message:
              "Uploading once. Server file validation and malware policy apply before admission.",
          },
        });
        let file: MatterFile;
        try {
          file = await api.upload(
            prepared,
            selection.expectedLifecycleVersion,
            abort.signal,
          );
          if (!current(generation)) return;
          if (
            file.size_bytes !== prepared.size ||
            file.sha256_hex !== prepared.sha256 ||
            latest.attachments.some((item) => item.id === file.id)
          )
            throw new ContractError("uploaded source identity");
        } catch (error) {
          if (!current(generation)) return;
          if (safeRejection(error)) {
            if (readFailure(error).kind === "restricted")
              publish({ view: { state: "error", error: readFailure(error) } });
            reject(
              errorStatus(error) === 400
                ? "The server rejected this file during validation or malware scanning. No successful upload was acknowledged. Choose a safe, supported original file."
                : "The server rejected this upload. Reload to check access, lifecycle and storage before selecting a file again.",
            );
          } else {
            uncertain = true;
            publish({ upload: unknown });
          }
          return;
        }
        acknowledged = file;
        uncertain = false;
        publish({ upload: awaitingReadback(file) });
        try {
          const workspace = await api.workspace(abort.signal);
          if (!current(generation)) return;
          const retained = workspace.attachments.find(
            (item) => item.id === file.id,
          );
          if (!retained || !sameSource(retained, file))
            throw new ContractError("persisted uploaded source");
          publish({
            view: { state: "ready", workspace },
            upload: {
              state: "persisted",
              attachmentId: file.id,
              message:
                "Upload acknowledged and the same source confirmed after reload. A separate clean-scan receipt is not supplied by this server.",
            },
          });
        } catch (error) {
          if (current(generation)) {
            const failure = readFailure(error);
            if (failure.kind === "restricted") {
              acknowledged = null;
              publish({
                upload: {
                  state: "acknowledged",
                  message:
                    "The server acknowledged the upload, but current access is unavailable. No private source is retained here. Do not upload it again.",
                },
              });
            }
            publish({ view: { state: "error", error: failure } });
          }
        }
      } catch (error) {
        if (error instanceof TempCleanupError) publish({ cleanupFailed: true });
        if (current(generation)) {
          if (sent) {
            uncertain = true;
            publish({ upload: unknown });
          } else
            reject(
              abort.signal.aborted
                ? "Upload cancelled before sending. No file was submitted."
                : "The file could not be prepared safely. Check its type, size and local availability, then select it again.",
            );
        }
      } finally {
        cleanup();
        busy = false;
        write = null;
        if (current(generation) && snapshot.upload.state === "preparing")
          reject("Upload cancelled before sending. No file was submitted.");
      }
    },
  };
  return controller;
}
export type FilesController = ReturnType<typeof createFilesController>;
