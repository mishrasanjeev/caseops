import {
  array,
  canAddNote,
  ContractError,
  dateOnly,
  decodeMatter,
  object,
  string,
} from "./contracts.ts";
import type { Matter } from "./contracts.ts";
import type { AuthorizedRequest } from "./repository.ts";

export type QuickKind = "task" | "hearing";
export type QuickTarget = { kind: QuickKind; id?: string };
export type QuickFields = Record<string, string>;
export const taskStatuses = [
  "todo",
  "in_progress",
  "blocked",
  "completed",
] as const;
export const hearingStatuses = [
  "scheduled",
  "completed",
  "adjourned",
  "cancelled",
] as const;
export type QuickRecord = {
  kind: QuickKind;
  id: string;
  matter_id: string;
  fields: QuickFields;
  version: string | null;
  immutable: boolean | null;
  owner_name: string | null;
  reminderChannels?: string[];
  reminderCritical?: boolean;
};
export type QuickSnapshot = {
  matter: Matter;
  tasks: QuickRecord[];
  hearings: QuickRecord[];
};
const uuid = (value: unknown) => {
  const result = string(value, "work identity", 36);
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      result,
    )
  )
    throw new ContractError("work identity");
  return result;
};
const nullableText = (value: unknown) =>
  value === null ? "" : string(value, "work text", 4000);
function choice(value: unknown, choices: readonly string[]) {
  const result = string(value, "work state", 80);
  if (!choices.includes(result)) throw new ContractError("work state");
  return result;
}
function aware(value: unknown) {
  const result = string(value, "work version", 64);
  if (
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(
      result,
    ) ||
    !Number.isFinite(Date.parse(result))
  )
    throw new ContractError("work version");
  dateOnly(result.slice(0, 10));
  return result;
}
function legalTime(value: string) {
  if (
    !/^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)?)?$/.test(
      value,
    )
  )
    throw new ContractError("hearing time");
  return value.length === 5 ? `${value}:00` : value;
}
function zone(value: string) {
  if (value.length < 3 || value.length > 64)
    throw new ContractError("hearing timezone");
  try {
    new Intl.DateTimeFormat("en", { timeZone: value }).format(0);
  } catch {
    throw new ContractError("hearing timezone");
  }
  return value;
}
export function decodeQuickRecord(
  value: unknown,
  kind: QuickKind,
  parent: string,
): QuickRecord {
  const row = object(value, "work record");
  if (row.matter_id !== parent) throw new ContractError("work parent");
  if (typeof row.cancelled_by_matter_disposal !== "boolean")
    throw new ContractError("work lifecycle flag");
  const immutable =
    row.immutable_lifecycle_history === undefined
      ? null
      : row.immutable_lifecycle_history;
  if (immutable !== null && typeof immutable !== "boolean")
    throw new ContractError("work history flag");
  const base = {
    kind,
    id: uuid(row.id),
    matter_id: parent,
    immutable: row.cancelled_by_matter_disposal ? true : immutable,
  };
  if (kind === "task") {
    const source = choice(row.source_type, ["user", "proceeding_intelligence"]);
    return {
      ...base,
      immutable: source !== "user" ? true : base.immutable,
      version: (() => {
        try {
          return aware(row.updated_at);
        } catch {
          return null;
        }
      })(),
      owner_name:
        row.owner_name === null ? null : string(row.owner_name, "task owner"),
      fields: {
        title: string(row.title, "task title", 255),
        description: nullableText(row.description),
        due_on: row.due_on === null ? "" : dateOnly(row.due_on),
        status: choice(row.status, [...taskStatuses, "cancelled"]),
        priority: choice(row.priority, ["low", "medium", "high", "urgent"]),
      },
    };
  }
  let version =
    row.record_version === null || row.record_version === undefined
      ? null
      : string(row.record_version, "hearing version", 69);
  if (version !== null && !/^mhv1:[0-9a-f]{64}$/.test(version))
    throw new ContractError("hearing version");
  const timeStatus = choice(row.time_status, [
    "exact",
    "session",
    "time_not_published",
  ]);
  const fields = {
    hearing_on: dateOnly(row.hearing_on),
    forum_name: string(row.forum_name, "forum", 255),
    judge_name: nullableText(row.judge_name),
    purpose: string(row.purpose, "purpose", 255),
    status: choice(row.status, hearingStatuses),
    outcome_note: nullableText(row.outcome_note),
    time_status: timeStatus,
    hearing_time:
      row.hearing_time === null
        ? ""
        : legalTime(string(row.hearing_time, "hearing time", 32)),
    session_label: nullableText(row.session_label),
    timezone: string(row.timezone, "hearing timezone", 64),
    create_follow_up: "yes",
  };
  if (
    (timeStatus === "exact") !== !!fields.hearing_time ||
    (timeStatus === "session") !== !!fields.session_label
  )
    version = null; // Retained incomplete time facts remain visible, without edit authority.
  // Creation acknowledgement must retain its actual server reminder plan.
  const policy =
    row.reminder_policy === null
      ? null
      : object(row.reminder_policy, "reminder plan");
  let channels: string[] | undefined;
  let critical: boolean | undefined;
  try {
    if (!policy || typeof policy.critical !== "boolean")
      throw new ContractError("reminder plan");
    channels = array(
      policy.channels,
      "reminder channels",
      (v) => choice(v, ["in_app", "email", "sms", "whatsapp"]),
      4,
    );
    if (new Set(channels).size !== channels.length)
      throw new ContractError("reminder channels");
    critical = policy.critical;
  } catch {
    // A legacy missing plan can invoke server defaults on reschedule. Keep the
    // record visible, but require a supplied plan before native editing.
    version = null;
  }
  return {
    ...base,
    version,
    owner_name: null,
    fields,
    ...(channels
      ? { reminderChannels: channels, reminderCritical: critical }
      : {}),
  };
}
export function decodeQuickSnapshot(
  value: unknown,
  parent: string,
): QuickSnapshot {
  const raw = object(value, "work workspace");
  const matter = decodeMatter(raw.matter);
  if (matter.id !== parent) throw new ContractError("work parent");
  const records = (value: unknown, kind: QuickKind) => {
    const rows = array(
      value,
      "work records",
      (item) => decodeQuickRecord(item, kind, parent),
      1000,
    );
    if (new Set(rows.map((row) => row.id)).size !== rows.length)
      throw new ContractError("duplicate work identity");
    return rows;
  };
  return {
    matter,
    tasks: records(raw.tasks, "task"),
    hearings: records(raw.hearings, "hearing"),
  };
}
export function createQuickWorkRepository(request: AuthorizedRequest) {
  return {
    load: async (parent: string) =>
      decodeQuickSnapshot(
        await request<unknown>(
          `/api/matters/${encodeURIComponent(parent)}/workspace`,
        ),
        parent,
      ),
    write: async (
      parent: string,
      target: QuickTarget,
      payload: Record<string, unknown>,
    ) => {
      const path = `/api/matters/${encodeURIComponent(parent)}/${target.kind === "task" ? "tasks" : "hearings"}${target.id ? `/${encodeURIComponent(target.id)}` : ""}`;
      return decodeQuickRecord(
        await request<unknown>(path, {
          method: target.id ? "PATCH" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }),
        target.kind,
        parent,
      );
    },
  };
}
export type QuickWorkRepository = ReturnType<typeof createQuickWorkRepository>;
export function quickDefaults(kind: QuickKind): QuickFields {
  return kind === "task"
    ? {
        title: "",
        description: "",
        due_on: "",
        status: "todo",
        priority: "medium",
      }
    : {
        hearing_on: "",
        forum_name: "",
        judge_name: "",
        purpose: "",
        status: "scheduled",
        outcome_note: "",
        time_status: "time_not_published",
        hearing_time: "",
        session_label: "",
        timezone: "",
        create_follow_up: "yes",
      };
}
function normalized(
  kind: QuickKind,
  value: QuickFields,
  creating: boolean,
  changed: Set<string>,
) {
  const fields = { ...value };
  for (const key of Object.keys(fields)) fields[key] = fields[key].trim();
  const validate = (key: string) => creating || changed.has(key);
  const required = (key: string, max: number) => {
    if ((fields[key]?.length ?? 0) < 2 || fields[key].length > max)
      throw new ContractError(key);
  };
  if (kind === "task") {
    if (validate("title")) required("title", 255);
    if (validate("description") && fields.description.length > 4000)
      throw new ContractError("task description");
    if (validate("due_on") && fields.due_on) dateOnly(fields.due_on);
    if (validate("status")) choice(fields.status, taskStatuses);
    if (validate("priority"))
      choice(fields.priority, ["low", "medium", "high", "urgent"]);
  } else {
    if (validate("hearing_on")) dateOnly(fields.hearing_on);
    if (creating) {
      required("forum_name", 255);
      required("purpose", 255);
      if (fields.judge_name) required("judge_name", 255);
    }
    if (validate("outcome_note") && fields.outcome_note.length > 4000)
      throw new ContractError("hearing outcome");
    if (validate("status")) choice(fields.status, hearingStatuses);
    if (validate("timezone")) zone(fields.timezone);
    if (
      creating ||
      ["time_status", "hearing_time", "session_label"].some((key) =>
        changed.has(key),
      )
    ) {
      choice(fields.time_status, ["exact", "session", "time_not_published"]);
      fields.hearing_time =
        fields.time_status === "exact" ? legalTime(fields.hearing_time) : "";
      fields.session_label =
        fields.time_status === "session" ? fields.session_label : "";
      if (
        fields.time_status === "session" &&
        (!fields.session_label || fields.session_label.length > 80)
      )
        throw new ContractError("hearing session");
    }
    if (
      creating ||
      changed.has("create_follow_up") ||
      fields.status === "completed"
    )
      choice(fields.create_follow_up, ["yes", "no"]);
  }
  return fields;
}

export function quickPayload(
  kind: QuickKind,
  fields: QuickFields,
  original: QuickRecord | null,
) {
  const changed = new Set(
    Object.keys(fields).filter(
      (key) => !original || fields[key] !== original.fields[key],
    ),
  );
  const normalizedFields = normalized(kind, fields, original === null, changed);
  const keys =
    kind === "task"
      ? ["title", "description", "due_on", "status", "priority"]
      : original
        ? [
            "hearing_on",
            "status",
            "outcome_note",
            "time_status",
            "hearing_time",
            "session_label",
            "timezone",
          ]
        : [
            "hearing_on",
            "forum_name",
            "judge_name",
            "purpose",
            "status",
            "outcome_note",
            "time_status",
            "hearing_time",
            "session_label",
            "timezone",
          ];
  const payload: Record<string, unknown> = {};
  for (const key of keys)
    if (
      !original ||
      (changed.has(key) && normalizedFields[key] !== original.fields[key])
    )
      payload[key] = normalizedFields[key] || null;
  if (kind === "hearing") {
    if ("time_status" in payload) {
      payload.hearing_time = normalizedFields.hearing_time || null;
      payload.session_label = normalizedFields.session_label || null;
    }
    if (!original)
      Object.assign(payload, {
        reminder_channels: [],
        reminder_recipient_membership_ids: [],
        notification_critical: false,
      });
    else if (payload.status === "completed")
      payload.create_follow_up = normalizedFields.create_follow_up === "yes";
  }
  return payload;
}
export function quickEditable(record: QuickRecord) {
  return (
    record.immutable === false &&
    record.version !== null &&
    record.fields.status !== "cancelled"
  );
}
export type QuickOutcome = {
  state: "confirmed" | "acknowledged" | "rejected" | "unknown" | "superseded";
  message: string;
  record?: QuickRecord;
};
export type QuickState = {
  phase: "loading" | "editing" | "saving" | "outcome" | "closed";
  matter: Matter | null;
  contentAvailable: boolean;
  fields: QuickFields;
  record: QuickRecord | null;
  dirty: boolean;
  outcome: QuickOutcome | null;
  reviewed: boolean;
  reviewError: string | null;
  history: readonly { fields: QuickFields; outcome: QuickOutcome }[];
};
export function createQuickWorkController(
  api: QuickWorkRepository,
  matter: Matter,
  target: QuickTarget,
  capabilities: readonly string[],
) {
  target = { ...target };
  const matterId = matter.id;
  capabilities = [...capabilities];
  let state: QuickState = {
    phase: "loading",
    matter: null,
    contentAvailable: false,
    fields: {},
    record: null,
    dirty: false,
    outcome: null,
    reviewed: false,
    reviewError: null,
    history: [],
  };
  let active = true,
    lease = false,
    attempted = false;
  let reviewed: QuickSnapshot | null = null;
  let uncertainCreate = false;
  const listeners = new Set<() => void>();
  const emit = (next: Partial<QuickState>) => {
    if (!active) return;
    state = { ...state, ...next };
    for (const fn of listeners) fn();
  };
  const find = (snapshot: QuickSnapshot) =>
    (target.kind === "task" ? snapshot.tasks : snapshot.hearings).find(
      (item) => item.id === target.id,
    ) ?? null;
  const allowed = (snapshot: QuickSnapshot) =>
    capabilities.includes("matters:write") &&
    canAddNote(snapshot.matter) &&
    (!target.id || (!!find(snapshot) && quickEditable(find(snapshot)!)));
  const withoutRecord = ({ state, message }: QuickOutcome): QuickOutcome => ({
    state,
    message,
  });
  const hideContent = () => {
    reviewed = null;
    emit({
      matter: null,
      contentAvailable: false,
      fields: {},
      record: null,
      dirty: false,
      reviewed: false,
      outcome: state.outcome ? withoutRecord(state.outcome) : null,
      history: state.history.map((entry) => ({
        fields: {},
        outcome: withoutRecord(entry.outcome),
      })),
    });
  };
  const stop = (outcome: QuickOutcome, purge = false) => {
    if (!target.id && outcome.state === "unknown") uncertainCreate = true;
    const history =
      state.history.length < 10
        ? [...state.history, { fields: { ...state.fields }, outcome }]
        : state.history;
    if (purge) reviewed = null;
    emit({
      phase: "outcome",
      outcome: purge ? withoutRecord(outcome) : outcome,
      history: purge
        ? history.map((entry) => ({
            fields: {},
            outcome: withoutRecord(entry.outcome),
          }))
        : history,
      ...(purge
        ? {
            matter: null,
            contentAvailable: false,
            fields: {},
            record: null,
            dirty: false,
            reviewed: false,
          }
        : {}),
    });
  };
  const sameRecord = (a: QuickRecord, b: QuickRecord) =>
    JSON.stringify(a) === JSON.stringify(b);
  const controller = {
    getSnapshot: () => state,
    subscribe: (fn: () => void) => {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
    async load() {
      if (!active || lease) return;
      lease = true;
      reviewed = null;
      emit({ contentAvailable: false, reviewed: false, reviewError: null });
      try {
        const snapshot = await api.load(matterId);
        if (!active) return;
        if (!allowed(snapshot)) {
          hideContent();
          if (state.outcome)
            emit({
              reviewError:
                "Current access or record state no longer permits editing. The prior save outcome is unchanged.",
            });
          else
            stop({
              state: "rejected",
              message:
                "This account, Matter or retained record is read-only. Editing is unavailable.",
            });
          return;
        }
        if (state.outcome) {
          emit({
            contentAvailable: true,
            matter: snapshot.matter,
            ...(!Object.keys(state.fields).length
              ? {
                  record: target.id ? find(snapshot) : null,
                  fields: target.id
                    ? { ...find(snapshot)!.fields }
                    : quickDefaults(target.kind),
                }
              : {}),
          });
          reviewed = snapshot;
          const acknowledged = state.outcome.record;
          const retained =
            acknowledged &&
            (target.kind === "task" ? snapshot.tasks : snapshot.hearings).find(
              (item) => item.id === acknowledged.id,
            );
          if (acknowledged && retained && sameRecord(acknowledged, retained))
            stop({
              state: "confirmed",
              message:
                "The acknowledged record was verified by a new current read, without submitting again.",
              record: acknowledged,
            });
          emit({ reviewed: true });
          return;
        }
        const record = target.id ? find(snapshot) : null;
        emit({
          phase: "editing",
          contentAvailable: true,
          matter: snapshot.matter,
          record,
          fields: record ? { ...record.fields } : quickDefaults(target.kind),
          dirty: false,
        });
      } catch {
        hideContent();
        if (state.outcome)
          emit({
            reviewError:
              "Current work could not be reloaded. The prior save outcome is unchanged; no request was replayed.",
          });
        else
          stop({
            state: "rejected",
            message:
              "Current work could not be loaded. No save was sent. Reload to check access and state.",
          });
      } finally {
        lease = false;
      }
    },
    change(key: string, value: string) {
      if (
        !active ||
        lease ||
        state.phase !== "editing" ||
        !Object.hasOwn(state.fields, key) ||
        value.length > 4000
      )
        return;
      if (
        target.id &&
        target.kind === "hearing" &&
        ["forum_name", "purpose", "judge_name"].includes(key)
      )
        return;
      emit({ fields: { ...state.fields, [key]: value }, dirty: true });
    },
    async save() {
      if (
        !active ||
        lease ||
        attempted ||
        state.phase !== "editing" ||
        !state.matter ||
        !state.contentAvailable
      )
        return;
      lease = true;
      const candidate = { ...state.fields };
      emit({ phase: "saving" });
      try {
        let payload: Record<string, unknown>;
        try {
          payload = quickPayload(target.kind, candidate, state.record);
          if (!Object.keys(payload).length)
            throw new ContractError("changed work fields");
        } catch {
          stop({
            state: "rejected",
            message:
              "Check required fields, legal dates, time and timezone. No save was sent.",
          });
          return;
        }
        let latest: QuickSnapshot;
        try {
          latest = await api.load(matterId);
        } catch {
          stop(
            {
              state: "rejected",
              message:
                "Current access could not be checked. No save was sent. Reload before a new request.",
            },
            true,
          );
          return;
        }
        if (!active) return;
        const child = find(latest);
        if (
          !allowed(latest) ||
          latest.matter.lifecycle_version !== state.matter.lifecycle_version ||
          (target.id &&
            (!child || !state.record || !sameRecord(child, state.record)))
        ) {
          stop(
            {
              state: "superseded",
              message:
                "The Matter lifecycle, access or record changed. No save was sent. Reload before a new request.",
            },
            !allowed(latest),
          );
          return;
        }
        payload.expected_lifecycle_version = state.matter.lifecycle_version;
        if (state.record)
          payload[
            target.kind === "task"
              ? "expected_updated_at"
              : "expected_record_version"
          ] = state.record.version;
        attempted = true;
        let record: QuickRecord;
        try {
          record = await api.write(matterId, target, payload);
          if (target.id && record.id !== target.id)
            throw new ContractError("saved work identity");
          for (const [key, value] of Object.entries(payload)) {
            if (
              key.startsWith("expected_") ||
              [
                "reminder_channels",
                "reminder_recipient_membership_ids",
                "notification_critical",
                "create_follow_up",
              ].includes(key)
            )
              continue;
            if ((record.fields[key] || null) !== value)
              throw new ContractError("saved work fields");
          }
          if (
            !target.id &&
            target.kind === "hearing" &&
            (JSON.stringify(record.reminderChannels) !== "[]" ||
              record.reminderCritical !== false)
          )
            throw new ContractError("saved reminder plan");
        } catch (error) {
          const status =
            error && typeof error === "object"
              ? (error as { status?: unknown }).status
              : null;
          const unknown =
            error &&
            typeof error === "object" &&
            (error as { outcome?: unknown }).outcome === "unknown";
          stop(
            !unknown &&
              typeof status === "number" &&
              [400, 401, 403, 404, 409, 422, 429].includes(status)
              ? {
                  state: "rejected",
                  message:
                    "The server rejected this request. Reload current access and versions before a new request.",
                }
              : {
                  state: "unknown",
                  message:
                    "This request may already be saved. It will not be sent again. Reload and inspect current work before deciding what to do next.",
                },
            typeof status === "number" && [401, 403, 404].includes(status),
          );
          return;
        }
        if (!active) return;
        try {
          const persisted = await api.load(matterId);
          const retained = (
            target.kind === "task" ? persisted.tasks : persisted.hearings
          ).find((item) => item.id === record.id);
          if (!retained || !sameRecord(retained, record))
            throw new ContractError("persisted work");
          stop({
            state: "confirmed",
            message:
              "The acknowledged record was read back with the same identity, version and fields.",
            record,
          });
        } catch {
          stop(
            {
              state: "acknowledged",
              message:
                "The server acknowledged this record. Current reload could not be verified; do not submit it again.",
              record,
            },
            true,
          );
        }
      } finally {
        lease = false;
      }
    },
    beginNewRequest() {
      if (
        !active ||
        lease ||
        !reviewed ||
        state.phase !== "outcome" ||
        state.history.length >= 10 ||
        state.outcome?.state === "confirmed" ||
        state.outcome?.state === "acknowledged" ||
        uncertainCreate
      )
        return;
      const snapshot = reviewed;
      reviewed = null;
      if (!allowed(snapshot)) return;
      const record = target.id ? find(snapshot) : null;
      attempted = false;
      emit({
        phase: "editing",
        contentAvailable: true,
        matter: snapshot.matter,
        record,
        fields: record ? { ...record.fields } : quickDefaults(target.kind),
        dirty: false,
        outcome: null,
        reviewed: false,
        reviewError: null,
      });
    },
    leaveDecision: () =>
      !active
        ? "closed"
        : lease
          ? "blocked"
          : state.outcome?.state === "confirmed" ||
              state.outcome?.state === "acknowledged"
            ? "allow"
            : state.dirty || state.outcome?.state === "unknown"
              ? "confirm"
              : "allow",
    leave(confirmed: boolean, action: () => void) {
      const decision = controller.leaveDecision();
      if (
        decision === "closed" ||
        decision === "blocked" ||
        (decision === "confirm" && !confirmed)
      )
        return false;
      controller.dispose();
      action();
      return true;
    },
    dispose() {
      active = false;
      reviewed = null;
      state = {
        ...state,
        phase: "closed",
        matter: null,
        contentAvailable: false,
        fields: {},
        record: null,
        history: [],
        outcome: null,
        reviewed: false,
        reviewError: null,
      };
      listeners.clear();
    },
  };
  return controller;
}
export type QuickWorkController = ReturnType<typeof createQuickWorkController>;
