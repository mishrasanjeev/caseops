import { array, ContractError, dateOnly, object, string } from "./contracts.ts";
import type { AuthorizedRequest } from "./repository.ts";

export type InboxState = "unread" | "read" | "dismissed";
export type InboxView = "active" | "dismissed";
export type InboxTarget = { kind: "matter" | "ip_docket"; id: string };
export type InboxRecord = {
  id: string;
  title: string;
  body: string | null;
  status: InboxState;
  createdAt: string;
  readAt: string | null;
  target: InboxTarget;
  targetLabel: string | null;
};
export type InboxPage = {
  items: InboxRecord[];
  nextCursor: string | null;
  historyExhausted: boolean;
};
const PAGE_SIZE = 25;
function identity(value: unknown, field: string): string {
  const result = string(value, field, 200);
  if (!result.trim() || /[\x00-\x1f\x7f]/.test(result))
    throw new ContractError(field);
  return result;
}
function timestamp(value: unknown): string {
  const result = string(value, "notification timestamp", 64);
  const match =
    /^(\d{4}-\d{2}-\d{2})T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.exec(
      result,
    );
  if (!match) throw new ContractError("notification timestamp");
  dateOnly(match[1]);
  return result;
}
function state(value: unknown): InboxState {
  if (value !== "unread" && value !== "read" && value !== "dismissed")
    throw new ContractError("notification status");
  return value;
}
function cursor(value: unknown): string {
  const result = string(value, "notification continuation", 4000);
  if (!result || /[\x00-\x20\x7f]/.test(result))
    throw new ContractError("notification continuation");
  return result;
}
export function decodeInboxRecord(value: unknown): InboxRecord {
  const row = object(value, "notification");
  const target = object(row.target, "notification target");
  if (target.kind !== "matter" && target.kind !== "ip_docket")
    throw new ContractError("notification target");
  return {
    id: identity(row.id, "notification identity"),
    title: string(row.title, "notification title", 255),
    body:
      row.body === null ? null : string(row.body, "notification body", 1000),
    status: state(row.status),
    createdAt: timestamp(row.created_at),
    readAt: row.read_at === null ? null : timestamp(row.read_at),
    target: {
      kind: target.kind,
      id: identity(target.id, "notification target identity"),
    },
    targetLabel:
      row.target_label === null
        ? null
        : string(row.target_label, "notification target label", 255),
  };
}
export function decodeInboxPage(
  value: unknown,
  view: InboxView,
  previous: string | null,
): InboxPage {
  const row = object(value, "notification page");
  if (
    row.scope !== "delivered_hearing_and_ip_renewal" ||
    typeof row.history_exhausted !== "boolean"
  )
    throw new ContractError("notification scope");
  const items = array(
    row.items,
    "notification page",
    decodeInboxRecord,
    PAGE_SIZE,
  );
  if (
    new Set(items.map((item) => item.id)).size !== items.length ||
    items.some(
      (item) => (item.status === "dismissed") !== (view === "dismissed"),
    )
  )
    throw new ContractError("notification page identity or view");
  const nextCursor = row.next_cursor === null ? null : cursor(row.next_cursor);
  if (
    (nextCursor === previous && nextCursor !== null) ||
    row.history_exhausted !== (nextCursor === null)
  )
    throw new ContractError("notification continuation");
  // An empty candidate page with a continuation is intentional. Do not infer
  // that the entire inbox is empty or scan unbounded history to fill it.
  return { items, nextCursor, historyExhausted: row.history_exhausted };
}
export function advanceInboxPage(
  history: readonly (string | null)[],
  next: string,
): (string | null)[] {
  cursor(next);
  if (
    !history.length ||
    history[0] !== null ||
    history.includes(next) ||
    history.length >= 100
  )
    throw new ContractError("notification continuation; reload notifications");
  return [...history, next];
}
export function createInboxRepository(request: AuthorizedRequest) {
  return {
    async page(
      view: InboxView,
      after: string | null,
      signal?: AbortSignal,
    ): Promise<InboxPage> {
      if (view !== "active" && view !== "dismissed")
        throw new ContractError("notification view");
      const params = new URLSearchParams({ view, limit: String(PAGE_SIZE) });
      if (after !== null) params.set("cursor", cursor(after));
      return decodeInboxPage(
        await request<unknown>(`/api/recipient-inbox?${params}`, { signal }),
        view,
        after,
      );
    },
    async change(
      original: InboxRecord,
      next: InboxState,
    ): Promise<InboxRecord> {
      state(next);
      const result = decodeInboxRecord(
        await request<unknown>(
          `/api/recipient-inbox/${encodeURIComponent(original.id)}`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              status: next,
              expected_status: original.status,
            }),
          },
        ),
      );
      if (
        result.id !== original.id ||
        result.status !== next ||
        result.target.id !== original.target.id ||
        result.target.kind !== original.target.kind
      )
        throw new ContractError("saved notification identity");
      return result;
    },
  };
}
export type InboxRepository = ReturnType<typeof createInboxRepository>;

export type InboxFrame = Readonly<{ key: string; data: unknown }>;
export function createInboxViewLease() {
  let active = true;
  let current: InboxFrame | null = null;
  let owner: InboxFrame | null = null;
  return {
    bind(key: string, data: unknown): InboxFrame {
      if (!active) throw new ContractError("closed notification view");
      if (!current || current.key !== key || current.data !== data)
        current = Object.freeze({ key, data });
      return current;
    },
    current: (frame: InboxFrame) => active && current === frame,
    busy: () => owner !== null,
    begin(frame: InboxFrame): boolean {
      if (!active || current !== frame || owner !== null) return false;
      owner = frame;
      return true;
    },
    finish(frame: InboxFrame) {
      if (owner === frame) owner = null;
    },
    navigate(frame: InboxFrame, action: () => void): boolean {
      if (!active || current !== frame || owner !== null) return false;
      current = null;
      action();
      return true;
    },
    leave(): boolean {
      if (!active || owner !== null) return false;
      current = null;
      return true;
    },
    dispose() {
      active = false;
      current = null;
    },
  };
}
export type InboxViewLease = ReturnType<typeof createInboxViewLease>;

export function createInboxAction(
  repository: InboxRepository,
  binding?: {
    lease: InboxViewLease;
    frame: InboxFrame;
  },
) {
  let active = true;
  let inFlight = false;
  let uncertain = false;
  const current = () =>
    active && (!binding || binding.lease.current(binding.frame));
  return {
    busy: () => inFlight,
    blocked: () => uncertain || !current(),
    dispose() {
      active = false;
    },
    async change(
      original: InboxRecord,
      next: InboxState,
    ): Promise<
      | { state: "confirmed"; record: InboxRecord }
      | { state: "busy" | "unverified" }
    > {
      if (!current()) return { state: "unverified" };
      if (inFlight) return { state: "busy" };
      if (uncertain) return { state: "unverified" };
      if (binding && !binding.lease.begin(binding.frame))
        return { state: "busy" };
      inFlight = true;
      try {
        const record = await repository.change(original, next);
        uncertain = true; // This snapshot is consumed; require fresh server state.
        if (!current()) return { state: "unverified" };
        return { state: "confirmed", record };
      } catch {
        // A response failure can follow a committed change. Never replay it.
        // A fresh, explicit read is required before creating a new action.
        uncertain = true;
        return { state: "unverified" };
      } finally {
        inFlight = false;
        if (binding) binding.lease.finish(binding.frame);
      }
    },
  };
}
