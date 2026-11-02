"use client";

import type { UseQueryResult } from "@tanstack/react-query";

import { Button } from "@/components/ui/Button";
import { Label } from "@/components/ui/Label";
import { apiErrorMessage } from "@/lib/api/config";
import type {
  IpDeadlineRuleVersion,
  IpDeadlineWorkspace,
  IpWorkingCalendarVersion,
} from "@/lib/api/endpoints";
import {
  activeCalendarsForJurisdiction,
  activeWorkingCalendars,
  awaitingActivationText,
  boundedNameList,
  describeGovernanceDecision,
  eligibleScopedRules,
  governedRuleCaption,
  ipGovernanceHref,
  normalJurisdiction,
  ruleScopeFor,
  ruleScopeLabel,
  ruleVersionName,
  sameJurisdiction,
  workingCalendarOptionCaption,
} from "@/lib/ip/governance";

const SELECT_CLASS =
  "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm disabled:cursor-not-allowed disabled:opacity-60";

export type GovernedScope = { proceedingKind: string | null; role: string | null; stage: string };

export type GovernedSelection = {
  rules: IpDeadlineRuleVersion[];
  calendars: IpWorkingCalendarVersion[];
  rule: IpDeadlineRuleVersion | undefined;
  calendar: IpWorkingCalendarVersion | undefined;
  /** The proceeding's jurisdiction the rule must apply in, when known. */
  jurisdiction: string | null;
  /** The jurisdiction the working calendar must belong to: the chosen rule's, else the proceeding's. */
  calendarJurisdiction: string | null;
};

/**
 * Options come from the validators' own predicate: a rule of the exact scope
 * and of the proceeding's jurisdiction, and an active calendar of the rule's
 * jurisdiction (the API refuses any other, B4-ADJ-08). A single eligible
 * option is preselected; with several, the lawyer must choose (a stale or
 * missing choice selects nothing rather than silently the first).
 */
export function resolveGovernedSelection(
  workspace: IpDeadlineWorkspace | undefined,
  scope: GovernedScope,
  ruleId: string,
  calendarId: string,
  jurisdiction: string | null = null,
): GovernedSelection {
  const scoped = workspace ? eligibleScopedRules(workspace, scope) : [];
  const rules = jurisdiction ? scoped.filter((row) => sameJurisdiction(row.jurisdiction, jurisdiction)) : scoped;
  const rule = rules.find((row) => row.id === ruleId) ?? (rules.length === 1 ? rules[0] : undefined);
  const calendarJurisdiction = rule?.jurisdiction ?? jurisdiction;
  const calendars = !workspace
    ? []
    : calendarJurisdiction
      ? activeCalendarsForJurisdiction(workspace, calendarJurisdiction)
      : activeWorkingCalendars(workspace);
  return {
    rules,
    calendars,
    rule,
    calendar: calendars.find((row) => row.id === calendarId) ?? (calendars.length === 1 ? calendars[0] : undefined),
    jurisdiction: jurisdiction ? normalJurisdiction(jurisdiction) : null,
    calendarJurisdiction: calendarJurisdiction ? normalJurisdiction(calendarJurisdiction) : null,
  };
}

function sameScope(rule: IpDeadlineRuleVersion, scope: GovernedScope) {
  return rule.proceeding_kind === scope.proceedingKind && rule.role === scope.role && rule.stage === scope.stage;
}

/**
 * Governed rule and working-calendar pickers for a scoped deadline proposal.
 * When nothing is eligible the selects are disabled and the reason names what
 * is missing, who can fix it, and links to the governance card.
 */
export function IpGovernedDeadlinePickers({
  docketId,
  idPrefix,
  scope,
  workspace,
  selection,
  onRuleChange,
  onCalendarChange,
}: {
  docketId: string;
  idPrefix: string;
  scope: GovernedScope;
  workspace: UseQueryResult<IpDeadlineWorkspace>;
  selection: GovernedSelection;
  onRuleChange: (id: string) => void;
  onCalendarChange: (id: string) => void;
}) {
  const ruleStatusId = `${idPrefix}-rule-status`;
  const calendarStatusId = `${idPrefix}-calendar-status`;
  const ruleCaptionId = `${idPrefix}-rule-caption`;
  const calendarCaptionId = `${idPrefix}-calendar-caption`;
  const data = workspace.data;
  const scopeDef = ruleScopeFor(scope.proceedingKind, scope.role, scope.stage);
  const scopeLabel = scopeDef?.label ?? ruleScopeLabel({ proceeding_kind: scope.proceedingKind, role: scope.role, stage: scope.stage });
  const governanceHref = ipGovernanceHref(docketId, scopeDef?.id);
  const placeholder = (loaded: string) =>
    workspace.isPending ? "Loading…" : workspace.isError ? "Unavailable — retry below" : loaded;
  // Absent during a deploy skew with an older API: fall back to the generic path.
  const governance = data?.governance;

  let ruleStatus: string[] = [];
  let calendarStatus: string[] = [];
  if (data && !selection.rules.length) {
    const anyJurisdiction = data.rules.filter((row) => sameScope(row, scope));
    const scoped = selection.jurisdiction
      ? anyJurisdiction.filter((row) => sameJurisdiction(row.jurisdiction, selection.jurisdiction))
      : anyJurisdiction;
    const elsewhere = anyJurisdiction.filter((row) => row.status === "active" && !scoped.includes(row));
    const pending = scoped.filter((row) => row.status === "candidate");
    const unselected = scoped.filter((row) => row.status === "active");
    if (!scoped.length && elsewhere.length && selection.jurisdiction) {
      const names = elsewhere.map((row) => `${ruleVersionName(row)} (${normalJurisdiction(row.jurisdiction)})`);
      ruleStatus = [`${boundedNameList(names)} ${names.length === 1 ? "applies" : "apply"} in another jurisdiction than this proceeding (${selection.jurisdiction}). Propose one for ${selection.jurisdiction} in Rule and calendar governance; another owner, admin or partner must activate it.`];
    } else if (pending.length) {
      ruleStatus = [awaitingActivationText(pending.map(ruleVersionName))];
    } else if (unselected.length) {
      const names = unselected.map(ruleVersionName);
      ruleStatus = [`${boundedNameList(names)} ${names.length === 1 ? "is" : "are"} active but not selected by company policy. An approver can select it in Rule and calendar governance.`];
    } else {
      const blocked = governance ? describeGovernanceDecision(governance.rule_proposal, "rule", "propose") : [];
      ruleStatus = [
        `No active governed rule exists for ${scopeLabel}. Your firm authors its own rules.`,
        ...(blocked.length
          ? blocked.map((row) => `${row.category}: ${row.text}`)
          : ["Propose one in Rule and calendar governance; another owner, admin or partner must activate it."]),
      ];
    }
  }
  if (data && !selection.calendars.length) {
    const wanted = selection.calendarJurisdiction;
    const pending = data.calendars.filter((row) => row.status === "candidate" && (!wanted || sameJurisdiction(row.jurisdiction, wanted)));
    const elsewhere = Array.from(new Set(activeWorkingCalendars(data).map((row) => normalJurisdiction(row.jurisdiction)))).sort();
    if (pending.length) {
      calendarStatus = [awaitingActivationText(pending.map((row) => `${row.name} v${row.version}`))];
    } else if (wanted && elsewhere.length) {
      calendarStatus = [
        `No active ${wanted} working calendar exists; active calendars exist only for ${elsewhere.join(", ")}.`,
        `Propose one for ${wanted} in Rule and calendar governance; another owner, admin or partner must activate it.`,
      ];
    } else {
      const blocked = governance ? describeGovernanceDecision(governance.calendar_proposal, "calendar", "propose") : [];
      calendarStatus = [
        "No active working calendar exists for this workspace.",
        ...(blocked.length
          ? blocked.map((row) => `${row.category}: ${row.text}`)
          : ["Propose one in Rule and calendar governance; another owner, admin or partner must activate it."]),
      ];
    }
  }

  return (
    <div className="col-span-full grid min-w-0 gap-3 sm:grid-cols-2" data-testid={`${idPrefix}-governed-pickers`}>
      <div className="flex min-w-0 flex-col gap-1">
        <Label htmlFor={`${idPrefix}-rule`}>Governed rule</Label>
        <select
          id={`${idPrefix}-rule`}
          className={SELECT_CLASS}
          value={selection.rule?.id ?? ""}
          disabled={!data || !selection.rules.length}
          aria-describedby={selection.rule ? ruleCaptionId : data ? ruleStatusId : undefined}
          onChange={(event) => onRuleChange(event.target.value)}
        >
          {!selection.rules.length ? <option value="">{placeholder(`No eligible rule for ${scopeLabel}`)}</option> : null}
          {selection.rules.length > 1 && !selection.rule ? <option value="">Choose a governed rule…</option> : null}
          {selection.rules.map((row) => (
            <option key={row.id} value={row.id}>{governedRuleCaption(row)}</option>
          ))}
        </select>
        {selection.rule ? (
          <p id={ruleCaptionId} className="min-w-0 break-words text-xs text-[var(--color-mute)]">{governedRuleCaption(selection.rule)}</p>
        ) : null}
      </div>
      <div className="flex min-w-0 flex-col gap-1">
        <Label htmlFor={`${idPrefix}-calendar`}>Working calendar</Label>
        <select
          id={`${idPrefix}-calendar`}
          className={SELECT_CLASS}
          value={selection.calendar?.id ?? ""}
          disabled={!data || !selection.calendars.length}
          aria-describedby={selection.calendar ? calendarCaptionId : data ? calendarStatusId : undefined}
          onChange={(event) => onCalendarChange(event.target.value)}
        >
          {!selection.calendars.length ? <option value="">{placeholder(selection.calendarJurisdiction ? `No active ${selection.calendarJurisdiction} working calendar` : "No active working calendar")}</option> : null}
          {selection.calendars.length > 1 && !selection.calendar ? <option value="">Choose a working calendar…</option> : null}
          {selection.calendars.map((row) => (
            <option key={row.id} value={row.id}>{workingCalendarOptionCaption(row)}</option>
          ))}
        </select>
        {selection.calendar ? (
          <p id={calendarCaptionId} className="min-w-0 break-words text-xs text-[var(--color-mute)]">{workingCalendarOptionCaption(selection.calendar)}</p>
        ) : null}
      </div>
      {workspace.isError ? (
        <div className="col-span-full flex min-w-0 flex-wrap items-center gap-2" role="alert">
          <p className="min-w-0 flex-1 break-words text-sm text-[var(--color-danger)]">
            {apiErrorMessage(workspace.error, "Governed rules and calendars could not be loaded.")}
          </p>
          <Button type="button" size="sm" variant="secondary" onClick={() => workspace.refetch()}>Retry</Button>
        </div>
      ) : null}
      {ruleStatus.length || calendarStatus.length ? (
        <div className="col-span-full min-w-0 rounded-md border border-[var(--color-warn-border)] bg-[var(--color-warn-bg)] p-3 text-sm text-[var(--color-warn-text)]">
          {ruleStatus.length ? (
            <div id={ruleStatusId} className="min-w-0 break-words">
              <strong>Governed rule. </strong>{ruleStatus.join(" ")}
            </div>
          ) : null}
          {calendarStatus.length ? (
            <div id={calendarStatusId} className="mt-1 min-w-0 break-words">
              <strong>Working calendar. </strong>{calendarStatus.join(" ")}
            </div>
          ) : null}
          <a className="mt-2 inline-block font-medium underline underline-offset-2" href={governanceHref}>
            Open rule and calendar governance
          </a>
        </div>
      ) : null}
    </div>
  );
}
