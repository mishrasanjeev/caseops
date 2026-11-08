import { ContractError, dateOnly, object, string } from "./contracts.ts";
import type { AuthorizedRequest } from "./repository.ts";

const endpoint = "/api/account/workspace-conduct";
export const workspaceUsePolicyUrl = "https://caseops.ai/workspace-use";
const utcTimestamp =
  /^([0-9]{4}-[0-9]{2}-[0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.[0-9]{1,6})?(?:Z|\+00:00)$/;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const uuidV4 =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export const workspaceReportReasons = [
  { value: "harassment_threats", label: "Harassment or threats" },
  { value: "exploitation", label: "Abuse or exploitation" },
  { value: "impersonation", label: "Impersonation" },
  { value: "unlawful_content", label: "Unlawful content" },
  { value: "spam_malware_fraud", label: "Spam, malware, or fraud" },
  { value: "unauthorized_disclosure", label: "Unauthorized disclosure" },
  { value: "other", label: "Something else" },
] as const;

export type WorkspaceReportReason =
  (typeof workspaceReportReasons)[number]["value"];
export type WorkspaceReportTarget =
  | Readonly<{ kind: "note" | "file"; matter_id: string; item_id: string }>
  | Readonly<{
      kind: "user";
      membership_id: string;
      matter_id: string;
      item_id: string;
      source_kind: "note" | "file";
    }>;
export type WorkspaceReportReceipt = Readonly<{
  id: string;
  operation_id: string;
  status: "received";
  received_at: string;
}>;

export type WorkspaceConduct = Readonly<{
  version: string;
  policy_url: typeof workspaceUsePolicyUrl;
  accepted_at: string | null;
}>;

function decodeTime(value: unknown) {
  const text = string(value, "workspace use UTC timestamp", 35);
  const parts = utcTimestamp.exec(text);
  if (
    !parts ||
    Number(parts[2]) > 23 ||
    Number(parts[3]) > 59 ||
    Number(parts[4]) > 59 ||
    !Number.isFinite(Date.parse(text))
  )
    throw new ContractError("workspace use UTC timestamp");
  dateOnly(parts[1]);
  return text;
}

export function decodeWorkspaceConduct(value: unknown): WorkspaceConduct {
  const row = object(value, "workspace use receipt");
  if (row.policy_url !== workspaceUsePolicyUrl)
    throw new ContractError("workspace use policy URL");
  return Object.freeze({
    version: dateOnly(row.version),
    policy_url: workspaceUsePolicyUrl,
    accepted_at: row.accepted_at === null ? null : decodeTime(row.accepted_at),
  });
}

function decodeIdentity(value: unknown, operation = false) {
  const id = string(value, "workspace report identity", 36);
  if (
    !(operation ? uuidV4 : uuid).test(id) ||
    id === "00000000-0000-0000-0000-000000000000"
  )
    throw new ContractError("workspace report identity");
  return id;
}

function encodeTarget(target: WorkspaceReportTarget): WorkspaceReportTarget {
  if (target.kind === "user") {
    if (target.source_kind !== "note" && target.source_kind !== "file")
      throw new ContractError("workspace report author source");
    return {
      kind: "user",
      membership_id: decodeIdentity(target.membership_id),
      matter_id: decodeIdentity(target.matter_id),
      item_id: decodeIdentity(target.item_id),
      source_kind: target.source_kind,
    };
  }
  if (target.kind !== "note" && target.kind !== "file")
    throw new ContractError("workspace report target");
  return {
    kind: target.kind,
    matter_id: decodeIdentity(target.matter_id),
    item_id: decodeIdentity(target.item_id),
  };
}

export function workspaceConductRepository(request: AuthorizedRequest) {
  return {
    async current(signal?: AbortSignal) {
      return decodeWorkspaceConduct(
        await request<unknown>(endpoint, { method: "GET", signal }),
      );
    },
    async accept(displayedVersion: string, signal?: AbortSignal) {
      const version = dateOnly(displayedVersion);
      const result = decodeWorkspaceConduct(
        await request<unknown>(`${endpoint}/accept`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ version }),
          signal,
        }),
      );
      if (result.version !== version || result.accepted_at === null)
        throw new ContractError("exact workspace use acceptance");
      return result;
    },
    async report(
      operation: string,
      reason: WorkspaceReportReason,
      target: WorkspaceReportTarget,
      signal?: AbortSignal,
    ): Promise<WorkspaceReportReceipt> {
      const operationId = decodeIdentity(operation, true);
      if (!workspaceReportReasons.some((item) => item.value === reason))
        throw new ContractError("workspace report reason");
      const row = object(
        await request<unknown>(`${endpoint}/reports`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            operation_id: operationId,
            reason,
            target: encodeTarget(target),
          }),
          signal,
        }),
        "workspace report receipt",
      );
      if (row.status !== "received" || row.operation_id !== operationId)
        throw new ContractError("exact workspace report receipt");
      return Object.freeze({
        id: decodeIdentity(row.id),
        operation_id: operationId,
        status: "received",
        received_at: decodeTime(row.received_at),
      });
    },
  };
}

export type WorkspaceConductRepository = ReturnType<
  typeof workspaceConductRepository
>;
