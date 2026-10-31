import { createQuickWorkRepository } from "./quick-work.ts";
import {
  array,
  canAddNote,
  ContractError,
  dateOnly,
  decodeAgenda,
  decodeDraft,
  decodeMatter,
  decodeMatterPage,
  decodeNote,
  decodeToday,
  decodeWorkspace,
  object,
  string,
} from "./contracts.ts";
import type { Matter, Note, Workspace } from "./contracts.ts";

export type AuthorizedRequest = <T>(
  path: string,
  init?: RequestInit,
) => Promise<T>;
export type ReadFailure = {
  kind: "restricted" | "offline" | "contract" | "unavailable";
  title: string;
  message: string;
};
export function errorStatus(error: unknown): number | null {
  if (!error || typeof error !== "object") return null;
  const row = error as Record<string, unknown>;
  return typeof row.status === "number"
    ? row.status
    : typeof row.statusCode === "number"
      ? row.statusCode
      : null;
}
function unknownOutcome(error: unknown): boolean {
  return (
    !!error &&
    typeof error === "object" &&
    (error as Record<string, unknown>).outcome === "unknown"
  );
}
export function readFailure(error: unknown): ReadFailure {
  const status = errorStatus(error);
  if (status === 401 || status === 403 || status === 404)
    return {
      kind: "restricted",
      title: "Not available to this account",
      message: "Access may have changed. Refresh or return to your workspace.",
    };
  if (error instanceof ContractError)
    return {
      kind: "contract",
      title: "Response could not be verified",
      message: error.message,
    };
  if (
    status === 0 ||
    error instanceof TypeError ||
    (error instanceof Error &&
      ["AbortError", "TimeoutError"].includes(error.name))
  )
    return {
      kind: "offline",
      title: "Connection unavailable",
      message: "Check your connection, then reload. No offline copy is shown.",
    };
  return {
    kind: "unavailable",
    title: "Could not load this view",
    message: "The server did not provide a usable response. Try loading again.",
  };
}
export function createRepository(request: AuthorizedRequest) {
  const get = (path: string, signal?: AbortSignal) =>
    request<unknown>(path, { signal });
  return {
    quickWork: createQuickWorkRepository(request),
    today: async (signal?: AbortSignal) =>
      decodeToday(await get("/api/me/today?horizon_days=7", signal)),
    matters: async (
      query: string,
      cursor: string | null = null,
      signal?: AbortSignal,
    ) => {
      const normalized = query.trim();
      if (normalized.length > 200 || (cursor?.length ?? 0) > 8000)
        throw new ContractError("search");
      const params = new URLSearchParams({ limit: "25" });
      if (normalized) params.set("q", normalized);
      if (cursor) params.set("cursor", cursor);
      const page = decodeMatterPage(
        await get(`/api/matters/?${params}`, signal),
      );
      if (page.next_cursor && page.next_cursor === cursor)
        throw new ContractError("repeating continuation");
      return page;
    },
    matter: async (matterId: string, signal?: AbortSignal) => {
      const result = decodeMatter(
        await get(`/api/matters/${encodeURIComponent(matterId)}`, signal),
      );
      if (result.id !== matterId) throw new ContractError("matter identity");
      return result;
    },
    workspace: async (matterId: string, signal?: AbortSignal) =>
      decodeWorkspace(
        await get(
          `/api/matters/${encodeURIComponent(matterId)}/workspace`,
          signal,
        ),
        matterId,
      ),
    agenda: async (day: string, signal?: AbortSignal) => {
      dateOnly(day);
      return decodeAgenda(
        await get(
          `/api/calendar/events?${new URLSearchParams({ from: day, to: day })}`,
          signal,
        ),
        day,
      );
    },
    draft: async (matterId: string, draftId: string, signal?: AbortSignal) =>
      decodeDraft(
        await get(
          `/api/matters/${encodeURIComponent(matterId)}/drafts/${encodeURIComponent(draftId)}`,
          signal,
        ),
        matterId,
        draftId,
      ),
    drafts: async (matterId: string, signal?: AbortSignal) => {
      const response = object(
        await get(
          `/api/matters/${encodeURIComponent(matterId)}/drafts`,
          signal,
        ),
        "draft list",
      );
      if (response.next_cursor != null)
        throw new ContractError("unsupported draft continuation");
      return array(
        response.drafts,
        "draft list",
        (value) => {
          const row = object(value, "draft");
          return decodeDraft(row, matterId, string(row.id, "draft identity"));
        },
        100,
      );
    },
    createNote: async (
      matterId: string,
      body: string,
      expectedLifecycleVersion: number,
    ): Promise<Note> => {
      if (
        !Number.isSafeInteger(expectedLifecycleVersion) ||
        expectedLifecycleVersion < 0
      )
        throw new ContractError("expected lifecycle version");
      const raw = object(
        await request<unknown>(
          `/api/matters/${encodeURIComponent(matterId)}/notes`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              body,
              expected_lifecycle_version: expectedLifecycleVersion,
            }),
          },
        ),
        "saved note",
      );
      if (
        string(raw.matter_id, "saved parent") !== matterId ||
        raw.body !== body
      )
        throw new ContractError("saved note identity");
      return decodeNote(raw);
    },
  };
}
export type Repository = ReturnType<typeof createRepository>;
export type NoteSaveResult =
  | { state: "confirmed"; note: Note; workspace: Workspace }
  | { state: "acknowledged"; note: Note; message: string; restricted: boolean }
  | { state: "rejected"; message: string; restricted: boolean }
  | { state: "unknown"; message: string };

export async function verifySavedNote(
  repository: Repository,
  matterId: string,
  note: Note,
): Promise<NoteSaveResult> {
  try {
    const workspace = await repository.workspace(matterId);
    const retained = workspace.notes.find((item) => item.id === note.id);
    if (!retained || retained.body !== note.body)
      throw new ContractError("persisted note");
    return { state: "confirmed", note, workspace };
  } catch (error) {
    return {
      state: "acknowledged",
      note,
      restricted: readFailure(error).kind === "restricted",
      message:
        "The server acknowledged this note. Persisted reload could not be confirmed; reload activity without submitting again.",
    };
  }
}

export function createNoteSubmission(
  repository: Repository,
  original: Matter,
  body: string,
) {
  let attempted = false;
  let inFlight = false;
  return {
    async save(): Promise<NoteSaveResult> {
      if (attempted || inFlight)
        return {
          state: "unknown",
          message:
            "This save has already been submitted. It will not be sent again.",
        };
      const normalized = body.trim();
      if (normalized.length < 2 || normalized.length > 4000)
        return {
          state: "rejected",
          restricted: false,
          message: "Enter a note between 2 and 4000 characters.",
        };
      inFlight = true;
      try {
        let latest: Matter;
        try {
          latest = await repository.matter(original.id);
        } catch (error) {
          return {
            state: "rejected",
            restricted: readFailure(error).kind === "restricted",
            message:
              "Current access could not be checked. The note was not sent.",
          };
        }
        if (
          !canAddNote(latest) ||
          latest.lifecycle_version !== original.lifecycle_version
        )
          return {
            state: "rejected",
            restricted: false,
            message:
              "The matter lifecycle has changed. Close this editor and reload the matter. The note was not sent.",
          };
        attempted = true;
        let note: Note;
        try {
          note = await repository.createNote(
            original.id,
            normalized,
            original.lifecycle_version,
          );
        } catch (error) {
          const status = errorStatus(error);
          if (
            !unknownOutcome(error) &&
            status !== null &&
            [400, 401, 403, 404, 409, 422, 429].includes(status)
          )
            return {
              state: "rejected",
              restricted: [401, 403, 404].includes(status),
              message:
                status === 422
                  ? "The server rejected this note. Check its length and reload the matter before editing again."
                  : "The server did not accept this note. Reload the matter to check current access and state.",
            };
          return {
            state: "unknown",
            message:
              "The server may have saved this note, but no valid acknowledgement arrived. Do not submit it again. Check the matter activity when connected.",
          };
        }
        return await verifySavedNote(repository, original.id, note);
      } finally {
        inFlight = false;
      }
    },
  };
}
