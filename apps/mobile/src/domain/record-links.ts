import {
  allowsNativeRedirect,
  type NativeLinkPolicy,
} from "../../../web/lib/native-link-policy.cjs";
import type { LocalSessionBinding, SessionIdentity } from "../auth/types.ts";

export type RecordLinkRoute =
  | Readonly<{
      type: "matter";
      matterId: string;
      section: "Summary" | "Activity" | "Files" | "Work";
    }>
  | Readonly<{ type: "draft"; matterId: string; draftId: string }>
  | Readonly<{ type: "counsel"; matterId: string }>
  | Readonly<{
      type: "source";
      source: Readonly<{ kind: "contract" | "ip_docket"; id: string }>;
    }>;
export type RecordLinkTarget = Readonly<{
  companyId: string;
  route: RecordLinkRoute;
}>;
export type PendingRecordLink = Readonly<{
  id: number;
  target: RecordLinkTarget;
}>;
const uuid = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const sections = {
  files: "Files",
  work: "Work",
  activity: "Activity",
} as const;

// URLs carry only a typed locator. Normal authenticated repositories still
// revalidate the exact tenant, parent, current ACL and record on every read.
export function parseRecordLink(
  value: unknown,
  policy: NativeLinkPolicy,
): RecordLinkTarget | null {
  if (
    typeof value !== "string" ||
    value.length > 512 ||
    /[^\x21-\x7e]|[%?#\\]/.test(value) ||
    policy.mode === "disabled" ||
    !allowsNativeRedirect(policy.redirectUri, policy)
  )
    return null;
  const prefix =
    policy.mode === "local"
      ? "caseops://open/"
      : `${new URL(policy.redirectUri).origin}/native/open/`;
  if (!value.startsWith(prefix)) return null;
  const parts = value.slice(prefix.length).split("/");
  if (parts[0] !== "workspaces" || !uuid.test(parts[1] ?? "")) return null;
  const companyId = parts[1];
  let route: RecordLinkRoute;
  if (parts[2] === "matters" && uuid.test(parts[3] ?? "")) {
    const matterId = parts[3];
    if (parts.length === 4)
      route = { type: "matter", matterId, section: "Summary" };
    else if (parts.length === 5 && Object.hasOwn(sections, parts[4]))
      route = {
        type: "matter",
        matterId,
        section: sections[parts[4] as keyof typeof sections],
      };
    else if (parts.length === 5 && parts[4] === "counsel")
      route = { type: "counsel", matterId };
    else if (parts.length === 6 && parts[4] === "drafts" && uuid.test(parts[5]))
      route = { type: "draft", matterId, draftId: parts[5] };
    else return null;
  } else if (
    parts.length === 5 &&
    parts[2] === "sources" &&
    ["contracts", "ip-dockets"].includes(parts[3]) &&
    uuid.test(parts[4])
  ) {
    route = {
      type: "source",
      source: Object.freeze({
        kind: parts[3] === "contracts" ? "contract" : "ip_docket",
        id: parts[4],
      }),
    };
  } else return null;
  return Object.freeze({ companyId, route: Object.freeze(route) });
}

const bindingFields = [
  "userId",
  "companyId",
  "membershipId",
  "sessionId",
  "sessionKey",
] as const;
function bindingKey(binding: LocalSessionBinding): string {
  if (
    !bindingFields.every(
      (key) =>
        typeof binding[key] === "string" &&
        binding[key].length > 0 &&
        binding[key].length <= 200 &&
        binding[key].trim() === binding[key] &&
        !/[\x00-\x1f\x7f]/.test(binding[key]),
    )
  )
    throw new Error("The private session could not be verified.");
  return JSON.stringify(bindingFields.map((key) => binding[key]));
}

export function createRecordLinkInbox(
  policy: NativeLinkPolicy,
  current: () => {
    binding: LocalSessionBinding | null;
    allowed: boolean;
  },
  changed: () => void,
) {
  const pinnedPolicy: NativeLinkPolicy = Object.freeze({ ...policy });
  let serial = 0;
  let pending: PendingRecordLink | null = null;
  let owner: string | null = null;
  let message = "";
  const clear = () => {
    pending = null;
    owner = null;
  };
  return {
    get snapshot() {
      return Object.freeze({ pending, message });
    },
    receive(value: unknown): boolean {
      const target = parseRecordLink(value, pinnedPolicy);
      if (!target) return false;
      const live = current();
      const nextOwner = live.binding ? bindingKey(live.binding) : null;
      if (
        pending &&
        owner === nextOwner &&
        JSON.stringify(pending.target) === JSON.stringify(target)
      )
        return false;
      if (serial >= Number.MAX_SAFE_INTEGER)
        throw new Error("Reopen CaseOps to use this link.");
      pending = Object.freeze({ id: ++serial, target });
      owner = nextOwner;
      message = "";
      changed();
      return true;
    },
    claim(id: number, expected: LocalSessionBinding): RecordLinkRoute | null {
      const live = current();
      // Retained leave/alert callbacks must read live authority synchronously.
      if (
        !pending ||
        pending.id !== id ||
        live.allowed !== true ||
        !live.binding
      )
        return null;
      const key = bindingKey(live.binding);
      if (key !== bindingKey(expected)) return null;
      if (owner !== null && owner !== key) {
        clear();
        message = "The session changed. Open the link again when ready.";
        changed();
        return null;
      }
      if (pending.target.companyId !== live.binding.companyId) {
        clear();
        message =
          "Sign in to the matching workspace, then open this link again.";
        changed();
        return null;
      }
      const route = pending.target.route;
      clear();
      message = "";
      changed();
      return route;
    },
    invalidate() {
      clear();
      message = "";
      changed();
    },
  };
}
export type RecordLinkInbox = ReturnType<typeof createRecordLinkInbox>;

export function navigateRecordLink(
  inbox: RecordLinkInbox,
  binding: LocalSessionBinding,
  identity: SessionIdentity,
  sessionKey: string,
  guarded: (leave: () => void) => void,
  navigate: (route: RecordLinkRoute) => void,
): void {
  const pending = inbox.snapshot.pending;
  if (!pending) return;
  guarded(() => {
    if (
      binding.companyId !== identity.company.id ||
      binding.userId !== identity.user.id ||
      binding.membershipId !== identity.membership.id ||
      binding.sessionKey !== sessionKey
    )
      return;
    const route = inbox.claim(pending.id, binding);
    if (route) navigate(route);
  });
}
