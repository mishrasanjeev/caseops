/**
 * Shared vocabulary for IP rule and calendar governance.
 *
 * Every control reads the server projection (`governance.*`, `can_activate`,
 * `activation_blocked_reasons`, `eligible_rule_version_ids`); these helpers
 * only turn its reason codes into the sentence a lawyer acts on. They never
 * decide availability themselves.
 */
import type {
  IpDeadlineRuleVersion,
  IpDeadlineWorkspace,
  IpGovernanceActionDecision,
  IpGovernanceBlockReason,
  IpWorkingCalendarVersion,
} from "@/lib/api/endpoints";

export type GovernanceBlockCategory =
  | "Paused by CaseOps"
  | "Not in your plan"
  | "Your role cannot"
  | "Needs another approver"
  | "Needs setup";

const CATEGORY: Record<IpGovernanceBlockReason, GovernanceBlockCategory> = {
  rollout_disabled: "Paused by CaseOps",
  rollout_expired: "Paused by CaseOps",
  missing_entitlement: "Not in your plan",
  missing_capability: "Your role cannot",
  proposer_cannot_self_approve: "Needs another approver",
  no_qualified_reviewer: "Needs another approver",
  proposer_unavailable: "Needs setup",
  fixtures_not_passing: "Needs setup",
  not_candidate: "Needs setup",
  rule_kind_unsupported: "Needs setup",
};

export type GovernanceSubject = "calendar" | "rule";
export type GovernanceAction = "propose" | "activate";

/** The sentence for one reason code, worded for the action it blocks. */
export function governanceReasonText(
  reason: IpGovernanceBlockReason,
  subject: GovernanceSubject,
  action: GovernanceAction,
): string {
  const noun = subject === "rule" ? "deadline rules" : "working calendars";
  switch (reason) {
    case "rollout_disabled":
      return "Rule publication is paused by CaseOps while governance ownership is rolled out. Existing active rules and confirmed deadlines keep working.";
    case "rollout_expired":
      return "The approved rule-governance rollout window has expired. CaseOps must renew it before rules can change.";
    case "missing_entitlement":
      return "Rule and calendar governance is not in this workspace's plan. A workspace owner can ask CaseOps to add it.";
    case "missing_capability":
      return action === "propose"
        ? `Your role cannot propose ${noun}. Ask a workspace owner or admin.`
        : `Your role cannot activate ${noun}. Ask a workspace owner, admin or partner.`;
    case "proposer_cannot_self_approve":
      return "You proposed this version, so another owner, admin or partner must activate it.";
    case "no_qualified_reviewer":
      return "No colleague other than you and the proposer can review the fixtures. Add another owner, admin or partner to the workspace.";
    case "proposer_unavailable":
      return "The proposer is no longer an active member. Propose this version again.";
    case "fixtures_not_passing":
      return "The server fixture check does not pass for this version. Propose a corrected version.";
    case "not_candidate":
      return "Only candidate versions can be activated.";
    case "rule_kind_unsupported":
      return "Only deadline rules can be activated; CaseOps cannot yet evaluate form or fee rules.";
  }
}

export function governanceCategory(reason: IpGovernanceBlockReason): GovernanceBlockCategory {
  return CATEGORY[reason];
}

/** Every reason of a blocked decision, labelled; empty when available. */
export function describeGovernanceDecision(
  decision: IpGovernanceActionDecision,
  subject: GovernanceSubject,
  action: GovernanceAction,
): Array<{ reason: IpGovernanceBlockReason; category: GovernanceBlockCategory; text: string }> {
  if (decision.available) return [];
  const reasons = decision.reasons.length
    ? decision.reasons
    : decision.code === "available" ? [] : [decision.code];
  return reasons.map((reason) => ({
    reason,
    category: governanceCategory(reason),
    text: governanceReasonText(reason, subject, action),
  }));
}

/**
 * Deep link to the Hearings and deadlines tab's governance card. `view` is the
 * docket page's existing tab parameter and `tab` the shared deep-link contract;
 * both name the same tab value.
 */
export function ipGovernanceHref(docketId: string, ruleScope?: RuleScopeId): string {
  const params = new URLSearchParams({ docket: docketId, view: "schedule", tab: "schedule" });
  if (ruleScope) params.set("rule_scope", ruleScope);
  return `/app/ip?${params.toString()}#ip-deadline-governance`;
}

export type RuleScope = {
  id: string;
  label: string;
  proceedingKind: "opposition" | null;
  role: "opponent" | "applicant" | null;
  stage: string;
  triggerKind: string;
  calendarMethod: "calendar_days" | "business_days" | "month_anniversary";
};

/**
 * Structural rule scopes the deadline validators match exactly. Durations and
 * citations are legal content, so the proposer always supplies them.
 */
export const RULE_SCOPES = [
  { id: "docket_examination", label: "Docket deadline · examination response", proceedingKind: null, role: null, stage: "examination", triggerKind: "examination_report_received", calendarMethod: "business_days" },
  { id: "opponent_notice", label: "Opposition, opponent · notice of opposition due", proceedingKind: "opposition", role: "opponent", stage: "notice_filing_due", triggerKind: "trademark_advertised", calendarMethod: "month_anniversary" },
  { id: "opponent_evidence", label: "Opposition, opponent · Rule 45 evidence due", proceedingKind: "opposition", role: "opponent", stage: "opponent_evidence_due", triggerKind: "counterstatement_served", calendarMethod: "month_anniversary" },
  { id: "opponent_reply", label: "Opposition, opponent · Rule 47 reply evidence due", proceedingKind: "opposition", role: "opponent", stage: "reply_evidence_due", triggerKind: "applicant_evidence_served", calendarMethod: "month_anniversary" },
  { id: "applicant_counterstatement", label: "Opposition, applicant · counterstatement due", proceedingKind: "opposition", role: "applicant", stage: "counterstatement_due", triggerKind: "notice_of_opposition_served", calendarMethod: "month_anniversary" },
  { id: "applicant_evidence", label: "Opposition, applicant · Rule 46 evidence due", proceedingKind: "opposition", role: "applicant", stage: "applicant_evidence_due", triggerKind: "opponent_evidence_served", calendarMethod: "month_anniversary" },
] as const satisfies readonly RuleScope[];

export type RuleScopeId = (typeof RULE_SCOPES)[number]["id"];

export function ruleScopeFor(
  proceedingKind: string | null,
  role: string | null,
  stage: string,
): (typeof RULE_SCOPES)[number] | undefined {
  return RULE_SCOPES.find((scope) =>
    scope.proceedingKind === proceedingKind && scope.role === role && scope.stage === stage);
}

export function isRuleScopeId(value: string | null): value is RuleScopeId {
  return RULE_SCOPES.some((scope) => scope.id === value);
}

export function ruleScopeLabel(rule: Pick<IpDeadlineRuleVersion, "proceeding_kind" | "role" | "stage">): string {
  return ruleScopeFor(rule.proceeding_kind, rule.role, rule.stage)?.label
    ?? [rule.proceeding_kind, rule.role, (rule.stage ?? "").replaceAll("_", " ")].filter(Boolean).join(" · ");
}

export function governedRuleCaption(rule: IpDeadlineRuleVersion): string {
  const citation = typeof rule.definition?.rule_citation === "string" ? ` · ${rule.definition.rule_citation}` : "";
  return `${rule.key} v${rule.version} · ${ruleScopeLabel(rule)} · ${rule.jurisdiction}${rule.office ? ` · ${rule.office}` : ""}${citation}`;
}

export function workingCalendarOptionCaption(calendar: IpWorkingCalendarVersion): string {
  return `${calendar.name} v${calendar.version} · ${calendar.jurisdiction}${calendar.office ? ` · ${calendar.office}` : ""} · ${calendar.timezone}`;
}

/**
 * Rules the deadline validators accept for an exact scope: active, a deadline
 * rule the company policy selects (the server's `eligible_rule_version_ids`),
 * and the exact proceeding kind, role and stage.
 */
export function eligibleScopedRules(
  workspace: IpDeadlineWorkspace,
  scope: { proceedingKind: string | null; role: string | null; stage: string },
): IpDeadlineRuleVersion[] {
  const eligible = new Set(workspace.eligible_rule_version_ids ?? []);
  return workspace.rules.filter((rule) =>
    eligible.has(rule.id)
    && rule.status === "active"
    && rule.proceeding_kind === scope.proceedingKind
    && rule.role === scope.role
    && rule.stage === scope.stage);
}

/** Calendars the deadline validator accepts: the company's active versions. */
export function activeWorkingCalendars(workspace: IpDeadlineWorkspace): IpWorkingCalendarVersion[] {
  return workspace.calendars.filter((calendar) => calendar.status === "active");
}

const SHA256_HEX = /^[0-9a-fA-F]{64}$/;

/** Null when valid; otherwise the field message (mirrors the API pattern). */
export function sourceHashError(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return "Enter the source SHA-256, or compute it from the source file.";
  if (SHA256_HEX.test(trimmed)) return null;
  return `Source SHA-256 must be exactly 64 hexadecimal characters (0-9, a-f); this has ${trimmed.length}.`;
}

export async function sha256HexOfFile(file: Blob): Promise<string> {
  // A typed view, not the bare buffer: a buffer from another realm (an iframe,
  // a test DOM) is refused by SubtleCrypto, a view of it is not.
  const digest = await crypto.subtle.digest("SHA-256", new Uint8Array(await file.arrayBuffer()));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function isoDate(year: number, month: number, day: number): string | null {
  const value = new Date(Date.UTC(year, month - 1, day));
  if (value.getUTCFullYear() !== year || value.getUTCMonth() !== month - 1 || value.getUTCDate() !== day) return null;
  return value.toISOString().slice(0, 10);
}

/**
 * Holiday list typed as YYYY-MM-DD or DD/MM/YYYY (the en-IN date display),
 * separated by commas, semicolons or new lines. Every token is a date or an
 * error naming it.
 */
export function parseHolidayDates(input: string): { dates: string[]; errors: string[] } {
  const dates: string[] = [];
  const errors: string[] = [];
  for (const token of input.split(/[,;\n]+/).map((part) => part.trim()).filter(Boolean)) {
    const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(token);
    const indian = /^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$/.exec(token);
    const value = iso
      ? isoDate(Number(iso[1]), Number(iso[2]), Number(iso[3]))
      : indian ? isoDate(Number(indian[3]), Number(indian[2]), Number(indian[1])) : null;
    if (!value) errors.push(`"${token}" is not a date. Use YYYY-MM-DD or DD/MM/YYYY.`);
    else if (!dates.includes(value)) dates.push(value);
  }
  return { dates, errors };
}
