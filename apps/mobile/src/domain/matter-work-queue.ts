import { array, ContractError, dateOnly, object, string } from "./contracts.ts";
import { errorStatus, readFailure } from "./repository.ts";
import type { AuthorizedRequest, ReadFailure } from "./repository.ts";

export type QueueOwnership = "mine" | "team" | "unassigned";
export type QueueDates = "all" | "dated" | "undated";
export type QueueFilter = Readonly<{
  ownership: QueueOwnership;
  dates: QueueDates;
}>;
export type QueueTask = Readonly<{
  id: string;
  title: string;
  status: "todo" | "in_progress" | "blocked";
  priority: "low" | "medium" | "high" | "urgent";
  due_on: string | null;
  owner_membership_id: string | null;
  created_at: string;
  updated_at: string;
  matter: Readonly<{
    id: string;
    title: string;
    matter_code: string;
    status: "intake" | "active" | "on_hold";
    is_active: true;
    lifecycle_version: number;
  }>;
}>;
export type QueuePage = Readonly<{
  scope: "matter_tasks";
  ownership: QueueOwnership;
  dates: QueueDates;
  due_from: null;
  due_to: null;
  sort: "due_on_created_at_id";
  limit: 25;
  items: readonly QueueTask[];
  next_cursor: string | null;
}>;
const ownerships = ["mine", "team", "unassigned"] as const;
const dateScopes = ["all", "dated", "undated"] as const;
function choice<T extends string>(
  value: unknown,
  values: readonly T[],
  field: string,
): T {
  if (typeof value !== "string" || !values.includes(value as T))
    throw new ContractError(field);
  return value as T;
}
function identity(value: unknown): string {
  const text = string(value, "work identity", 36);
  // Existing stored task IDs include non-UUID String(36) values.
  if (!text.trim() || /[\u0000-\u001f\u007f]/.test(text))
    throw new ContractError("work identity");
  return text;
}
function cursor(value: unknown): string | null {
  if (value === null) return null;
  const text = string(value, "work continuation", 4000);
  if (!text || /\s/.test(text)) throw new ContractError("work continuation");
  return text;
}
function utc(value: unknown): string {
  const text = string(value, "work UTC timestamp", 40);
  const match =
    /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(?:Z|\+00:00)$/.exec(
      text,
    );
  if (!match) throw new ContractError("work UTC timestamp");
  dateOnly(match[1]);
  if (+match[2] > 23 || +match[3] > 59 || +match[4] > 59)
    throw new ContractError("work UTC timestamp");
  return text;
}
function timeKey(value: string): string {
  const match = /^(.*T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(?:Z|\+00:00)$/.exec(
    value,
  )!;
  return `${match[1]}.${(match[2] ?? "").padEnd(6, "0")}`;
}
function task(value: unknown): QueueTask {
  const row = object(value, "Matter task"),
    matter = object(row.matter, "work Matter");
  if (
    matter.is_active !== true ||
    !Number.isSafeInteger(matter.lifecycle_version) ||
    (matter.lifecycle_version as number) < 0
  )
    throw new ContractError("work Matter lifecycle");
  return Object.freeze({
    id: identity(row.id),
    title: string(row.title, "work title"),
    status: choice(
      row.status,
      ["todo", "in_progress", "blocked"],
      "open task status",
    ),
    priority: choice(
      row.priority,
      ["low", "medium", "high", "urgent"],
      "task priority",
    ),
    due_on: row.due_on === null ? null : dateOnly(row.due_on),
    owner_membership_id:
      row.owner_membership_id === null
        ? null
        : identity(row.owner_membership_id),
    created_at: utc(row.created_at),
    updated_at: utc(row.updated_at),
    matter: Object.freeze({
      id: identity(matter.id),
      title: string(matter.title, "work Matter title"),
      matter_code: string(matter.matter_code, "work Matter code"),
      status: choice(
        matter.status,
        ["intake", "active", "on_hold"],
        "operational Matter status",
      ),
      is_active: true as const,
      lifecycle_version: matter.lifecycle_version as number,
    }),
  });
}
/** Compare only server date/time facts. Database ordering of legacy string IDs
 * is authoritative at exact timestamp ties; JavaScript collation is not used. */
function inOrder(before: QueueTask, after: QueueTask): boolean {
  if (before.due_on === null && after.due_on !== null) return false;
  if (before.due_on !== after.due_on)
    return (
      after.due_on === null ||
      (before.due_on !== null && before.due_on < after.due_on)
    );
  return timeKey(before.created_at) <= timeKey(after.created_at);
}
export function queueFilter(value: QueueFilter): QueueFilter {
  return Object.freeze({
    ownership: choice(value.ownership, ownerships, "work ownership"),
    dates: choice(value.dates, dateScopes, "work date scope"),
  });
}
export function decodeQueuePage(
  value: unknown,
  expected: QueueFilter,
  memberId: string,
  requestedCursor: string | null = null,
): QueuePage {
  const row = object(value, "Matter work queue"),
    filter = queueFilter(expected),
    member = identity(memberId);
  if (
    row.scope !== "matter_tasks" ||
    row.sort !== "due_on_created_at_id" ||
    row.limit !== 25 ||
    row.ownership !== filter.ownership ||
    row.dates !== filter.dates ||
    row.due_from !== null ||
    row.due_to !== null
  )
    throw new ContractError("work queue scope");
  const items = array(row.items, "work page", task, 25),
    next = cursor(row.next_cursor),
    ids = new Set<string>();
  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    if (
      ids.has(item.id) ||
      (filter.ownership === "mine" && item.owner_membership_id !== member) ||
      (filter.ownership === "team" &&
        (item.owner_membership_id === null ||
          item.owner_membership_id === member)) ||
      (filter.ownership === "unassigned" &&
        item.owner_membership_id !== null) ||
      (filter.dates === "dated" && item.due_on === null) ||
      (filter.dates === "undated" && item.due_on !== null) ||
      (i > 0 && !inOrder(items[i - 1], item))
    )
      throw new ContractError("work page membership or order");
    ids.add(item.id);
  }
  if (next !== null && (items.length !== 25 || next === requestedCursor))
    throw new ContractError("work continuation");
  return Object.freeze({
    scope: "matter_tasks",
    ...filter,
    due_from: null,
    due_to: null,
    sort: "due_on_created_at_id",
    limit: 25,
    items: Object.freeze(items),
    next_cursor: next,
  });
}
export function createMatterWorkQueueRepository(
  request: AuthorizedRequest,
  memberId: string,
) {
  const member = identity(memberId);
  return {
    async page(
      filter: QueueFilter,
      continuation: string | null,
      signal: AbortSignal,
    ) {
      const scope = queueFilter(filter),
        token = cursor(continuation);
      const query = `ownership=${scope.ownership}&dates=${scope.dates}&limit=25${token === null ? "" : `&cursor=${encodeURIComponent(token)}`}`;
      return decodeQueuePage(
        await request<unknown>(`/api/matter-work-queue?${query}`, {
          method: "GET",
          signal,
        }),
        scope,
        member,
        token,
      );
    },
  };
}
export type QueueView = Readonly<{
  revision: number;
  phase:
    | "inactive"
    | "idle"
    | "loading"
    | "ready"
    | "detail"
    | "stale"
    | "error"
    | "restricted";
  filter: QueueFilter;
  page: QueuePage | null;
  selected: QueueTask | null;
  busy: boolean;
  failure: ReadFailure | null;
}>;
/** One active read lease; only the current page is retained. No persisted cache,
 * automatic retry or mutation. Continuation metadata is discarded with the view. */
export function createMatterWorkQueueController(
  repository: ReturnType<typeof createMatterWorkQueueRepository>,
  available: () => boolean,
) {
  let active = false,
    disposed = false,
    epoch = 0;
  let lease: { abort: AbortController } | null = null;
  let inputCursor: string | null = null;
  let view: QueueView = Object.freeze({
    revision: 0,
    phase: "inactive",
    filter: queueFilter({ ownership: "mine", dates: "all" }),
    page: null,
    selected: null,
    busy: false,
    failure: null,
  });
  const listeners = new Set<() => void>(),
    seenIds = new Set<string>(),
    seenCursors = new Set<string>();
  const publish = (
    phase: QueueView["phase"],
    page: QueuePage | null = null,
    failure: ReadFailure | null = null,
    filter = view.filter,
    selected: QueueTask | null = null,
  ) => {
    view = Object.freeze({
      revision: view.revision + 1,
      phase,
      filter,
      page,
      selected,
      busy: lease !== null,
      failure,
    });
    for (const notify of listeners) notify();
  };
  const clearChain = () => {
    seenIds.clear();
    seenCursors.clear();
    inputCursor = null;
  };
  const suspend = () => {
    if (disposed) return;
    active = false;
    epoch++;
    lease?.abort.abort();
    lease = null;
    clearChain();
    publish("inactive");
  };
  const admitted = () => {
    if (disposed || !active) return false;
    if (!available()) {
      suspend();
      return false;
    }
    return true;
  };
  const current = (expected: QueueView) => admitted() && view === expected;
  const read = async (
    expected: QueueView,
    first: boolean,
    filter = expected.filter,
    selected: QueueTask | null = null,
  ): Promise<boolean> => {
    if (
      !current(expected) ||
      lease ||
      (!first && (expected.phase !== "ready" || !expected.page?.next_cursor))
    )
      return false;
    if (
      selected &&
      (expected.phase !== "ready" || !expected.page?.items.includes(selected))
    )
      return false;
    const token = selected
        ? inputCursor
        : first
          ? null
          : expected.page!.next_cursor,
      preceding = first || selected ? null : expected.page;
    const owned = { abort: new AbortController() },
      generation = epoch;
    if (first && !selected) clearChain();
    lease = owned;
    publish("loading", null, null, queueFilter(filter));
    try {
      const page = await repository.page(filter, token, owned.abort.signal);
      if (!admitted() || generation !== epoch || lease !== owned) return true;
      if (
        !selected &&
        (page.items.some((item) => seenIds.has(item.id)) ||
          (page.next_cursor !== null && seenCursors.has(page.next_cursor)) ||
          (preceding?.items.length &&
            page.items.length &&
            !inOrder(
              preceding.items[preceding.items.length - 1],
              page.items[0],
            )))
      )
        throw new ContractError("work continuation membership or order");
      const confirmed = selected
        ? (page.items.find(
            (item) =>
              item.id === selected.id && item.matter.id === selected.matter.id,
          ) ?? null)
        : null;
      if (selected && !confirmed) {
        clearChain();
        publish("stale");
        return true;
      }
      inputCursor = token;
      for (const item of page.items) seenIds.add(item.id);
      if (page.next_cursor !== null) seenCursors.add(page.next_cursor);
      publish(confirmed ? "detail" : "ready", page, null, filter, confirmed);
    } catch (error) {
      if (!admitted() || generation !== epoch || lease !== owned) return true;
      clearChain();
      const status = errorStatus(error);
      if (status === 401 || status === 403)
        publish("restricted", null, readFailure(error));
      else if (status === 409) publish("stale");
      else publish("error", null, readFailure(error));
    } finally {
      if (lease === owned) {
        lease = null;
        if (!disposed)
          publish(
            view.phase,
            view.page,
            view.failure,
            view.filter,
            view.selected,
          );
      }
    }
    return true;
  };
  return {
    getSnapshot: () => view,
    subscribe(notify: () => void) {
      listeners.add(notify);
      return () => {
        listeners.delete(notify);
      };
    },
    current,
    activate() {
      if (disposed || active || !available()) return false;
      active = true;
      epoch++;
      clearChain();
      publish("idle");
      return true;
    },
    suspend,
    dispose() {
      if (!disposed) {
        suspend();
        disposed = true;
        listeners.clear();
      }
    },
    firstPage(expected: QueueView) {
      return read(expected, true);
    },
    nextPage(expected: QueueView) {
      return read(expected, false);
    },
    select(expected: QueueView, filter: QueueFilter) {
      return read(expected, true, queueFilter(filter));
    },
    showTask(expected: QueueView, item: QueueTask) {
      return read(expected, true, expected.filter, item);
    },
    backToPage(expected: QueueView) {
      if (
        !current(expected) ||
        lease ||
        expected.phase !== "detail" ||
        !expected.page
      )
        return false;
      publish("ready", expected.page);
      return true;
    },
    openMatter(expected: QueueView, navigate: (item: QueueTask) => void) {
      if (
        !current(expected) ||
        lease ||
        expected.phase !== "detail" ||
        !expected.selected
      )
        return false;
      const item = expected.selected;
      suspend();
      navigate(item);
      return true;
    },
  };
}
export type MatterWorkQueueController = ReturnType<
  typeof createMatterWorkQueueController
>;
