import { array, ContractError, dateOnly, object, string } from "./contracts.ts";
import type { AuthorizedRequest } from "./repository.ts";

export const OBLIGATION_PAGE_SIZE = 10;
export type ContractObligation = {
  id: string;
  contract_id: string;
  title: string;
  description: string | null;
  description_truncated: boolean;
  due_on: string | null;
  status: string;
  priority: string;
  owner_membership_id: string | null;
  owner_name: string | null;
  completed_at: string | null;
  created_at: string;
};
export type ObligationPage = {
  company_id: string;
  contract_id: string;
  obligations: ContractObligation[];
  next_after: string | null;
  limit: number;
  ordering: "id_ascending";
};
function uuid(value: unknown) {
  const result = string(value, "obligation identity", 36);
  if (!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(result))
    throw new ContractError("obligation identity");
  return result;
}
function timestamp(value: unknown) {
  const result = string(value, "obligation timestamp", 64);
  const match =
    /^(\d{4}-\d{2}-\d{2})T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.exec(
      result,
    );
  if (!match || !Number.isFinite(Date.parse(result)))
    throw new ContractError("obligation timestamp");
  dateOnly(match[1]);
  return result;
}
const nullable = <T>(
  value: unknown,
  decode: (value: unknown) => T,
): T | null => (value === null ? null : decode(value));
function boundedText(value: unknown, field: string, maximum: number) {
  const result = string(value, field, maximum * 2);
  if ([...result].length > maximum) throw new ContractError(field);
  return result;
}

export function decodeObligationPage(
  value: unknown,
  companyId: string,
  contractId: string,
  after: string | null,
): ObligationPage {
  contractIdentity(contractId);
  if (after !== null) uuid(after);
  const row = object(value, "contract obligation page");
  if (
    row.company_id !== companyId ||
    row.contract_id !== contractId ||
    row.limit !== OBLIGATION_PAGE_SIZE ||
    row.ordering !== "id_ascending"
  )
    throw new ContractError("contract obligation scope");
  const records = array(
    row.obligations,
    "contract obligations",
    (value) => {
      const item = object(value, "contract obligation");
      if (
        item.contract_id !== contractId ||
        typeof item.description_truncated !== "boolean"
      )
        throw new ContractError("contract obligation identity/preview");
      const description = nullable(item.description, (value) =>
        string(value, "obligation description preview", 8000),
      );
      if (
        (description !== null && [...description].length > 4000) ||
        (item.description_truncated &&
          (description === null || [...description].length !== 4000))
      )
        throw new ContractError("obligation description preview");
      const owner = nullable(item.owner_membership_id, (value) =>
        retainedIdentity(value, "responsible membership identity"),
      );
      const name = nullable(item.owner_name, (value) =>
        boundedText(value, "responsible person", 255),
      );
      if (owner === null && name !== null)
        throw new ContractError("obligation responsible person");
      return {
        id: uuid(item.id),
        contract_id: contractId,
        title: boundedText(item.title, "obligation title", 255),
        description,
        description_truncated: item.description_truncated,
        due_on: nullable(item.due_on, dateOnly),
        status: boundedText(item.status, "recorded obligation status", 24),
        priority: boundedText(
          item.priority,
          "recorded obligation priority",
          16,
        ),
        owner_membership_id: owner,
        owner_name: name,
        completed_at: nullable(item.completed_at, timestamp),
        created_at: timestamp(item.created_at),
      };
    },
    OBLIGATION_PAGE_SIZE,
  );
  if (
    records.some(
      (item, index) =>
        item.id <= (index ? records[index - 1].id : (after ?? "")),
    )
  )
    throw new ContractError("obligation page order");
  const next = nullable(row.next_after, uuid);
  if (
    next !== null &&
    (records.length !== OBLIGATION_PAGE_SIZE ||
      records.at(-1)!.id !== next ||
      next === after)
  )
    throw new ContractError("obligation continuation");
  return {
    company_id: companyId,
    contract_id: contractId,
    obligations: records,
    next_after: next,
    limit: OBLIGATION_PAGE_SIZE,
    ordering: "id_ascending",
  };
}

export function createContractObligationsRepository(
  request: AuthorizedRequest,
  companyId: string,
) {
  return {
    async load(contractId: string, after: string | null, signal?: AbortSignal) {
      contractIdentity(contractId);
      const params = new URLSearchParams({
        limit: String(OBLIGATION_PAGE_SIZE),
      });
      if (after !== null) params.set("after", uuid(after));
      return decodeObligationPage(
        await request<unknown>(
          `/api/contracts/${encodeURIComponent(contractId)}/obligations?${params}`,
          { signal },
        ),
        companyId,
        contractId,
        after,
      );
    },
  };
}

function contractIdentity(value: unknown) {
  // The parent schema is a retained String(36), not a UUID-only contract.
  return retainedIdentity(value, "contract identity");
}
function retainedIdentity(value: unknown, field: string) {
  const identity = boundedText(value, field, 36);
  if (
    !identity.trim() ||
    identity.trim() !== identity ||
    /[\x00-\x1f\x7f]/.test(identity) ||
    identity === "." ||
    identity === ".."
  )
    throw new ContractError(field);
  return identity;
}

/** A retained Open/Close callback may only change its own current disclosure.
 * No private record or page history is stored here. */
export function createObligationDisclosure() {
  let active = true;
  let frame: Readonly<{ open: boolean; revision: number }> = Object.freeze({
    open: false,
    revision: 0,
  });
  const listeners = new Set<() => void>();
  const current = (expected: typeof frame) => active && frame === expected;
  const set = (expected: typeof frame, open: boolean) => {
    if (!current(expected) || frame.open === open) return false;
    frame = Object.freeze({ open, revision: frame.revision + 1 });
    for (const listener of listeners) listener();
    return true;
  };
  return {
    current,
    getSnapshot: () => frame,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    open: (expected: typeof frame) => set(expected, true),
    close: (expected: typeof frame) => set(expected, false),
    dispose() {
      active = false;
      listeners.clear();
    },
  };
}

// One constant-size frame, independent of React's render timing. Forward cursors
// are strictly increasing record IDs; no private pages or growing history stay.
export function createObligationNavigator() {
  let active = true;
  let frame: Readonly<{
    after: string | null;
    page: number;
    revision: number;
  }> = Object.freeze({
    after: null as string | null,
    page: 1,
    revision: 0,
  });
  const listeners = new Set<() => void>();
  const current = (expected: typeof frame) => active && frame === expected;
  const update = (
    expected: typeof frame,
    after: string | null,
    page: number,
  ) => {
    if (!current(expected) || !Number.isSafeInteger(page) || page < 1)
      return false;
    frame = Object.freeze({ after, page, revision: frame.revision + 1 });
    for (const listener of listeners) listener();
    return true;
  };
  return {
    getSnapshot: () => frame,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    current,
    next(expected: typeof frame, cursor: string) {
      if (!current(expected)) return false;
      uuid(cursor);
      if (cursor <= (frame.after ?? ""))
        throw new ContractError("obligation continuation");
      return update(expected, cursor, frame.page + 1);
    },
    first: (expected: typeof frame) => update(expected, null, 1),
    reload: (expected: typeof frame) =>
      update(expected, frame.after, frame.page),
    dispose() {
      active = false;
      listeners.clear();
    },
  };
}
