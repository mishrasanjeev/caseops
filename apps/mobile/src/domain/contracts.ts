// These projections follow apps/web/lib/api/{schemas,workspace-types,endpoints}.ts.
// Unknown additive fields are ignored; missing or malformed displayed facts fail closed.
export class ContractError extends Error {
  constructor(field: string) {
    super(`The server returned an unsupported ${field} response.`);
    this.name = "ContractError";
  }
}
type ObjectValue = Record<string, unknown>;
export function object(value: unknown, field = "record"): ObjectValue {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new ContractError(field);
  return value as ObjectValue;
}
export function string(value: unknown, field: string, max = 20000): string {
  if (typeof value !== "string" || value.length > max)
    throw new ContractError(field);
  return value;
}
function id(value: unknown, field = "identity"): string {
  const result = string(value, field, 200);
  if (!result.trim()) throw new ContractError(field);
  return result;
}
function optional(value: unknown, field: string): string | null {
  return value === undefined || value === null ? null : string(value, field);
}
function integer(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0)
    throw new ContractError(field);
  return value;
}
export function array<T>(
  value: unknown,
  field: string,
  decode: (item: unknown) => T,
  max = 1000,
): T[] {
  if (!Array.isArray(value) || value.length > max)
    throw new ContractError(`${field} (response limit)`);
  return value.map(decode);
}
export function dateOnly(value: unknown): string {
  const text = string(value, "date", 10);
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (!match) throw new ContractError("date");
  const year = Number(match[1]),
    month = Number(match[2]),
    day = Number(match[3]);
  const test = new Date(0);
  test.setUTCFullYear(year, month - 1, day);
  test.setUTCHours(12, 0, 0, 0);
  if (
    year < 1 ||
    test.getUTCFullYear() !== year ||
    test.getUTCMonth() !== month - 1 ||
    test.getUTCDate() !== day
  )
    throw new ContractError("date");
  return text;
}
function optionalDate(value: unknown): string | null {
  return value == null ? null : dateOnly(value);
}
export function localDay(now = new Date()): string {
  return `${now.getFullYear().toString().padStart(4, "0")}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}
export function shiftDay(value: string, offset: number): string {
  if (!Number.isInteger(offset) || Math.abs(offset) > 366)
    throw new ContractError("date offset");
  const [year, month, day] = dateOnly(value).split("-").map(Number);
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day + offset);
  date.setUTCHours(12, 0, 0, 0);
  return dateOnly(date.toISOString().slice(0, 10));
}
export function displayDay(value: string): string {
  const [year, month, day] = dateOnly(value).split("-").map(Number);
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(12, 0, 0, 0);
  return date.toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}
export type MatterRef = { id: string; title: string; matter_code: string };
export function decodeMatterRef(value: unknown): MatterRef {
  const row = object(value, "matter");
  return {
    id: id(row.id),
    title: string(row.title, "matter title"),
    matter_code: string(row.matter_code, "matter code"),
  };
}
export type Matter = MatterRef & {
  status: string;
  lifecycle_version: number;
  updated_at: string;
  client_name: string | null;
  court_name: string | null;
  case_number: string | null;
  temporary_e_case_number: string | null;
  cnr_number: string | null;
  filing_number: string | null;
  description: string | null;
  next_hearing_on: string | null;
  next_hearing_source: string | null;
};
export function decodeMatter(value: unknown): Matter {
  const row = object(value, "matter");
  return {
    ...decodeMatterRef(row),
    status: string(row.status, "matter status"),
    lifecycle_version: integer(row.lifecycle_version, "lifecycle version"),
    updated_at: string(row.updated_at, "updated timestamp"),
    client_name: optional(row.client_name, "client"),
    court_name: optional(row.court_name, "court"),
    case_number: optional(row.case_number, "case number"),
    temporary_e_case_number: optional(
      row.temporary_e_case_number,
      "temporary identifier",
    ),
    cnr_number: optional(row.cnr_number, "CNR"),
    filing_number: optional(row.filing_number, "filing number"),
    description: optional(row.description, "description"),
    next_hearing_on: optionalDate(row.next_hearing_on),
    next_hearing_source: optional(row.next_hearing_source, "hearing source"),
  };
}
export function canAddNote(matter: Matter): boolean {
  return ["intake", "active", "on_hold"].includes(matter.status.toLowerCase());
}
export type MatterPage = { matters: Matter[]; next_cursor: string | null };
export function decodeMatterPage(value: unknown): MatterPage {
  const row = object(value, "matter list");
  return {
    matters: array(row.matters, "matter list", decodeMatter, 25),
    next_cursor: optional(row.next_cursor, "continuation"),
  };
}
export type WorkItem = {
  id: string;
  kind: "hearing" | "task" | "draft" | "deadline";
  matter: MatterRef;
  title: string;
  due_on: string | null;
  detail: string | null;
  status: string | null;
};
export const streamKeys = [
  "hearings_next_7d",
  "tasks_due_or_overdue",
  "drafts_in_review",
  "deadlines_next_7d",
] as const;
export type Today = {
  today: string;
  horizon_days: number;
  streams: {
    key: (typeof streamKeys)[number];
    items: WorkItem[];
    // The API supplies the number returned after its cap, not a total count.
    returnedCount: number | null;
    truncated: boolean | null;
  }[];
  ipActions: number;
};
export function decodeToday(value: unknown): Today {
  const row = object(value, "Today");
  const streams = streamKeys.map((key) => {
    const kind =
      key === "hearings_next_7d"
        ? "hearing"
        : key === "tasks_due_or_overdue"
          ? "task"
          : key === "drafts_in_review"
            ? "draft"
            : "deadline";
    const items = array(
      row[key],
      key,
      (value) => {
        const item = object(value, key);
        return {
          id: id(item.id),
          kind,
          matter: decodeMatterRef(item.matter),
          title:
            kind === "hearing"
              ? string(item.purpose, "hearing purpose") || "Hearing"
              : string(item.title, "work title"),
          due_on:
            kind === "hearing"
              ? dateOnly(item.hearing_on)
              : kind === "draft"
                ? null
                : optionalDate(item.due_on),
          detail:
            kind === "hearing"
              ? optional(item.forum_name, "forum")
              : kind === "draft"
                ? optional(item.draft_type, "draft type")
                : optional(item.priority ?? item.severity, "priority"),
          status: optional(item.status, "work status"),
        } as WorkItem;
      },
      100,
    );
    const returnedCount =
      row.stream_counts === undefined
        ? null
        : integer(object(row.stream_counts)[key], `${key} count`);
    const flag =
      row.stream_truncated === undefined
        ? null
        : object(row.stream_truncated)[key];
    if (flag !== null && typeof flag !== "boolean")
      throw new ContractError("stream continuation");
    if (returnedCount !== null && returnedCount !== items.length)
      throw new ContractError("stream count");
    return { key, items, returnedCount, truncated: flag as boolean | null };
  });
  return {
    today: dateOnly(row.today),
    horizon_days: integer(row.horizon_days, "horizon"),
    streams,
    ipActions:
      row.ip_coverage_actions === undefined
        ? 0
        : array(row.ip_coverage_actions, "IP coverage", (value) =>
            object(value),
          ).length,
  };
}
export type Note = {
  id: string;
  body: string;
  created_at: string;
  author_name: string | null;
};
export function decodeNote(value: unknown): Note {
  const row = object(value, "note");
  return {
    id: id(row.id),
    body: string(row.body, "note body", 4000),
    created_at: string(row.created_at, "note timestamp"),
    author_name: optional(row.author_name, "note author"),
  };
}
export type Attachment = {
  id: string;
  filename: string | null;
  processing_status: string | null;
  created_at: string;
};
export type Task = {
  id: string;
  title: string;
  status: string;
  due_on: string | null;
  owner_name: string | null;
};
export type Activity = {
  id: string;
  title: string;
  detail: string | null;
  created_at: string;
  actor_name: string | null;
};
export type Workspace = {
  matter: Matter;
  notes: Note[];
  attachments: Attachment[];
  tasks: Task[];
  activity: Activity[];
};
export function decodeWorkspace(value: unknown, expectedId: string): Workspace {
  const row = object(value, "workspace"),
    matter = decodeMatter(row.matter);
  if (matter.id !== expectedId) throw new ContractError("workspace parent");
  for (const key of ["notes", "attachments", "tasks"] as const) {
    array(row[key], key, (value) => {
      const child = object(value, key);
      if (child.matter_id !== undefined && child.matter_id !== expectedId)
        throw new ContractError(`${key} parent`);
      return child;
    });
  }
  return {
    matter,
    notes: array(row.notes, "notes", decodeNote),
    attachments: array(row.attachments, "files", (value) => {
      const item = object(value);
      return {
        id: id(item.id),
        filename: optional(item.original_filename ?? item.filename, "filename"),
        processing_status: optional(
          item.processing_status,
          "processing status",
        ),
        created_at: string(item.created_at, "file timestamp"),
      };
    }),
    tasks: array(row.tasks, "tasks", (value) => {
      const item = object(value);
      return {
        id: id(item.id),
        title: string(item.title, "task title"),
        status: string(item.status, "task status"),
        due_on: optionalDate(item.due_on),
        owner_name: optional(item.owner_name, "task owner"),
      };
    }),
    activity: array(row.activity, "activity", (value) => {
      const item = object(value);
      return {
        id: id(item.id),
        title: string(item.title, "activity title"),
        detail: optional(item.detail, "activity detail"),
        created_at: string(item.created_at, "activity timestamp"),
        actor_name: optional(item.actor_name, "actor"),
      };
    }),
  };
}
export type CalendarEvent = {
  id: string;
  kind: string;
  title: string;
  occurs_on: string;
  matter: MatterRef;
  ip_docket_id: string | null;
  detail: string | null;
  hearing_time: string | null;
  timezone: string | null;
  session_label: string | null;
  time_status: string | null;
};
export function decodeAgenda(value: unknown, day: string): CalendarEvent[] {
  const row = object(value, "calendar");
  if (dateOnly(row.range_from) !== day || dateOnly(row.range_to) !== day)
    throw new ContractError("calendar range");
  return array(row.events, "calendar events", (value) => {
    const event = object(value, "calendar event");
    if (
      !["hearing", "task", "deadline"].includes(
        string(event.kind, "event kind"),
      ) ||
      dateOnly(event.occurs_on) !== day
    )
      throw new ContractError("calendar event date or type");
    const ip = optional(event.ip_docket_id, "IP docket");
    if (!ip && !string(event.matter_id, "event parent").trim())
      throw new ContractError("calendar parent");
    if (
      event.time_status != null &&
      !["exact", "session", "time_not_published"].includes(
        string(event.time_status, "time status"),
      )
    )
      throw new ContractError("time status");
    return {
      id: id(event.id),
      kind: string(event.display_type ?? event.kind, "event type"),
      title: string(event.title, "event title"),
      occurs_on: day,
      matter: {
        id: string(event.matter_id, "event parent"),
        title: string(event.matter_title, "parent title"),
        matter_code: string(event.matter_code, "parent code"),
      },
      ip_docket_id: ip,
      detail: optional(event.detail, "event detail"),
      hearing_time: optional(event.hearing_time, "hearing time"),
      timezone: optional(event.timezone, "event timezone"),
      session_label: optional(event.session_label, "session"),
      time_status: optional(event.time_status, "time status"),
    };
  });
}
export type DraftVersion = {
  id: string;
  draft_id: string;
  revision: number;
  body: string;
  citations: string[];
  verified_citation_count: number;
};
export type Draft = {
  id: string;
  matter_id: string | null;
  title: string;
  status: string;
  current_version_id: string | null;
  current: DraftVersion | null;
};
export function decodeDraft(
  value: unknown,
  matterId: string,
  draftId: string,
): Draft {
  const row = object(value, "draft");
  if (
    id(row.id) !== draftId ||
    row.matter_id !== matterId ||
    row.ip_docket_id != null
  )
    throw new ContractError("draft parent");
  const currentId =
    row.current_version_id === null ? null : id(row.current_version_id);
  const versions = array(
    row.versions,
    "draft versions",
    (value) => {
      const version = object(value, "draft version");
      if (version.draft_id !== draftId)
        throw new ContractError("draft version parent");
      return {
        id: id(version.id),
        draft_id: draftId,
        revision: integer(version.revision, "revision"),
        body: string(version.body, "draft body", 1000000),
        citations: array(version.citations, "citations", (item) =>
          string(item, "citation"),
        ),
        verified_citation_count: integer(
          version.verified_citation_count,
          "verified citation count",
        ),
      };
    },
    100,
  );
  const current = versions.filter((version) => version.id === currentId);
  if (
    (currentId !== null && current.length !== 1) ||
    new Set(versions.map((v) => v.id)).size !== versions.length
  )
    throw new ContractError("current draft version");
  if (
    current[0] &&
    current[0].verified_citation_count > current[0].citations.length
  )
    throw new ContractError("citation count");
  return {
    id: draftId,
    matter_id: matterId,
    title: string(row.title, "draft title"),
    status: string(row.status, "draft status"),
    current_version_id: currentId,
    current: current[0] ?? null,
  };
}
