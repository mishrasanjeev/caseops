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
  activeWorkingCalendars,
  describeGovernanceDecision,
  eligibleScopedRules,
  governedRuleCaption,
  ipGovernanceHref,
  ruleScopeFor,
  ruleScopeLabel,
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
};

/** Options come from the validators' own predicate; a stale choice falls back to the first eligible one. */
export function resolveGovernedSelection(
  workspace: IpDeadlineWorkspace | undefined,
  scope: GovernedScope,
  ruleId: string,
  calendarId: string,
): GovernedSelection {
  const rules = workspace ? eligibleScopedRules(workspace, scope) : [];
  const calendars = workspace ? activeWorkingCalendars(workspace) : [];
  return {
    rules,
    calendars,
    rule: rules.find((row) => row.id === ruleId) ?? rules[0],
    calendar: calendars.find((row) => row.id === calendarId) ?? calendars[0],
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

  let ruleStatus: string[] = [];
  let calendarStatus: string[] = [];
  if (data && !selection.rules.length) {
    const scoped = data.rules.filter((row) => sameScope(row, scope));
    const pending = scoped.filter((row) => row.status === "candidate");
    const unselected = scoped.filter((row) => row.status === "active");
    if (pending.length) {
      ruleStatus = [`${pending.map((row) => `${row.key} v${row.version}`).join(", ")} is awaiting activation by an approver other than its proposer.`];
    } else if (unselected.length) {
      ruleStatus = [`${unselected.map((row) => `${row.key} v${row.version}`).join(", ")} is active but not selected by company policy. An approver can select it in Rule and calendar governance.`];
    } else {
      const blocked = describeGovernanceDecision(data.governance.rule_proposal, "rule", "propose");
      ruleStatus = [
        `No active governed rule exists for ${scopeLabel}. Your firm authors its own rules.`,
        ...(blocked.length
          ? blocked.map((row) => `${row.category}: ${row.text}`)
          : ["Propose one in Rule and calendar governance; another owner, admin or partner must activate it."]),
      ];
    }
  }
  if (data && !selection.calendars.length) {
    const pending = data.calendars.filter((row) => row.status === "candidate");
    if (pending.length) {
      calendarStatus = [`${pending.map((row) => `${row.name} v${row.version}`).join(", ")} is awaiting activation by an approver other than its proposer.`];
    } else {
      const blocked = describeGovernanceDecision(data.governance.calendar_proposal, "calendar", "propose");
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
          {!selection.calendars.length ? <option value="">{placeholder("No active working calendar")}</option> : null}
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
