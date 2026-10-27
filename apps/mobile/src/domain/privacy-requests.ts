import { ContractError, dateOnly, object, string } from "./contracts.ts";
import { errorStatus } from "./repository.ts";
import type { AuthorizedRequest } from "./repository.ts";

const endpoint = "/api/account/deletion-requests";
const canonicalUuid = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
export type AccountDeletionReceipt = Readonly<{
  id: string;
  operation_id: string;
  request_type: "account_deletion";
  status: "received";
  requested_at: string;
  deletion_completed: false;
}>;
function identity(value: unknown): string {
  const id = string(value, "account request identity", 36);
  if (!canonicalUuid.test(id) || id === "00000000-0000-0000-0000-000000000000")
    throw new ContractError("account request identity");
  return id;
}
function timestamp(value: unknown): string {
  const text = string(value, "account request timestamp", 40);
  const parts =
    /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|\+00:00)$/.exec(
      text,
    );
  if (!parts) throw new ContractError("account request UTC timestamp");
  dateOnly(parts[1]);
  if (
    Number(parts[2]) > 23 ||
    Number(parts[3]) > 59 ||
    Number(parts[4]) > 59 ||
    !Number.isFinite(Date.parse(text))
  )
    throw new ContractError("account request UTC timestamp");
  return text;
}
export function decodeAccountDeletionReceipt(
  value: unknown,
): AccountDeletionReceipt {
  const row = object(value, "account deletion request receipt");
  if (
    row.request_type !== "account_deletion" ||
    row.status !== "received" ||
    row.deletion_completed !== false
  )
    throw new ContractError("account deletion request receipt");
  return Object.freeze({
    id: identity(row.id),
    operation_id: identity(row.operation_id),
    request_type: "account_deletion",
    status: "received",
    requested_at: timestamp(row.requested_at),
    deletion_completed: false,
  });
}
export function createPrivacyRequestsRepository(request: AuthorizedRequest) {
  return {
    async current(
      signal?: AbortSignal,
    ): Promise<AccountDeletionReceipt | null> {
      const row = object(
        await request<unknown>(endpoint, { method: "GET", signal }),
        "current account deletion request",
      );
      return row.request === null
        ? null
        : decodeAccountDeletionReceipt(row.request);
    },
    async read(id: string, signal?: AbortSignal) {
      const wanted = identity(id);
      const receipt = decodeAccountDeletionReceipt(
        await request<unknown>(`${endpoint}/${encodeURIComponent(wanted)}`, {
          method: "GET",
          signal,
        }),
      );
      if (receipt.id !== wanted)
        throw new ContractError("exact own account request identity");
      return receipt;
    },
    async submit(operation: string, signal?: AbortSignal) {
      const operationId = identity(operation);
      const receipt = decodeAccountDeletionReceipt(
        await request<unknown>(endpoint, {
          method: "POST",
          signal,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            operation_id: operationId,
            confirmation: "request_account_deletion",
          }),
        }),
      );
      if (receipt.operation_id !== operationId)
        throw new ContractError("exact account request operation");
      return receipt;
    },
  };
}
export type PrivacyRequestsRepository = ReturnType<
  typeof createPrivacyRequestsRepository
>;
export type PrivacyRequestView = Readonly<{
  revision: number;
  phase:
    | "inactive"
    | "idle"
    | "loading"
    | "none"
    | "confirming"
    | "submitting"
    | "received"
    | "unknown"
    | "unavailable";
  busy: boolean;
  receipt: AccountDeletionReceipt | null;
  message: string | null;
}>;

/** A single controller owns one explicit POST. Reload is GET only, including
 * after a lost acknowledgement; no uncertain operation is ever rearmed here. */
export function createPrivacyRequestController(
  repository: PrivacyRequestsRepository,
  newOperation: () => string,
) {
  let active = false,
    disposed = false,
    epoch = 0,
    attempted = false,
    hadReceipt = false;
  let operation: string | null = null;
  let lease: { kind: "read" | "submit"; abort: AbortController } | null = null;
  let view: PrivacyRequestView = Object.freeze({
    revision: 0,
    phase: "inactive",
    busy: false,
    receipt: null,
    message: null,
  });
  const listeners = new Set<() => void>();
  const publish = (
    phase: PrivacyRequestView["phase"],
    receipt: AccountDeletionReceipt | null = null,
    message: string | null = null,
  ) => {
    view = Object.freeze({
      revision: view.revision + 1,
      phase,
      busy: lease !== null,
      receipt,
      message,
    });
    for (const listener of listeners) listener();
  };
  const current = (expected: PrivacyRequestView) =>
    !disposed && active && view === expected;
  const suspend = () => {
    if (disposed) return;
    epoch++;
    active = false;
    operation = null;
    lease?.abort.abort();
    publish("inactive");
  };
  return {
    getSnapshot: () => view,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    current,
    activate() {
      if (disposed || active) return false;
      active = true;
      epoch++;
      publish(
        attempted ? "unknown" : "idle",
        null,
        attempted
          ? "A prior attempt is unconfirmed. Reload your own request; it will not be submitted again automatically."
          : null,
      );
      return true;
    },
    suspend,
    dispose() {
      if (disposed) return;
      suspend();
      disposed = true;
      listeners.clear();
    },
    begin(expected: PrivacyRequestView) {
      if (!current(expected) || lease || attempted || expected.phase !== "none")
        return false;
      try {
        operation = identity(newOperation());
        publish("confirming");
        return true;
      } catch {
        operation = null;
        publish(
          "unavailable",
          null,
          "A request identity could not be prepared. No request was sent.",
        );
        return false;
      }
    },
    cancel(expected: PrivacyRequestView) {
      if (!current(expected) || lease || expected.phase !== "confirming")
        return false;
      operation = null;
      publish("none");
      return true;
    },
    async reload(expected: PrivacyRequestView): Promise<boolean> {
      if (!current(expected) || lease) return false;
      const owned = { kind: "read" as const, abort: new AbortController() },
        generation = epoch;
      lease = owned;
      operation = null;
      publish("loading");
      try {
        const receipt = await repository.current(owned.abort.signal);
        if (!active || disposed || generation !== epoch || lease !== owned)
          return true;
        if (receipt) {
          hadReceipt = true;
          publish(
            "received",
            receipt,
            "A request is recorded for your account. Deletion has not been completed.",
          );
        } else if (attempted || hadReceipt)
          publish(
            "unknown",
            null,
            "No received request was confirmed by this read. The earlier attempt will not be submitted again from this view.",
          );
        else publish("none");
      } catch (error) {
        if (!active || disposed || generation !== epoch || lease !== owned)
          return true;
        if ([401, 403].includes(errorStatus(error) ?? 0)) suspend();
        else
          publish(
            attempted ? "unknown" : "unavailable",
            null,
            errorStatus(error) === 404
              ? "Account request intake is unavailable from this service. Publisher email remains a separate enquiry."
              : "Your account request could not be loaded. No saved receipt is shown. Reload when your connection is available.",
          );
      } finally {
        if (lease === owned) {
          lease = null;
          if (!disposed) publish(view.phase, view.receipt, view.message);
        }
      }
      return true;
    },
    async confirm(expected: PrivacyRequestView): Promise<boolean> {
      if (
        !current(expected) ||
        lease ||
        attempted ||
        expected.phase !== "confirming" ||
        operation === null
      )
        return false;
      const id = operation,
        generation = epoch,
        owned = { kind: "submit" as const, abort: new AbortController() };
      attempted = true;
      operation = null;
      lease = owned;
      publish("submitting");
      try {
        const receipt = await repository.submit(id, owned.abort.signal);
        if (!active || disposed || generation !== epoch || lease !== owned)
          return true;
        hadReceipt = true;
        publish(
          "received",
          receipt,
          "Request received. Your account and records have not been deleted.",
        );
      } catch (error) {
        if (!active || disposed || generation !== epoch || lease !== owned)
          return true;
        if ([401, 403].includes(errorStatus(error) ?? 0)) suspend();
        else
          publish(
            "unknown",
            null,
            errorStatus(error) === 409
              ? "A request may already be recorded. Reload your own receipt. No second request was sent."
              : "The acknowledgement could not be confirmed. Reload your own request; this attempt will not be submitted again automatically.",
          );
      } finally {
        if (lease === owned) {
          lease = null;
          if (!disposed) publish(view.phase, view.receipt, view.message);
        }
      }
      return true;
    },
  };
}
export type PrivacyRequestController = ReturnType<
  typeof createPrivacyRequestController
>;
