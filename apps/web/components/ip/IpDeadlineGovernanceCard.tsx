"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { SourceHashField } from "@/components/ip/SourceHashField";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PersonPicker } from "@/components/ui/PersonPicker";
import { API_FORM_ERROR_KEY, apiErrorMessage, apiFieldErrors, apiValidationIssues, isApiErrorShape } from "@/lib/api/config";
import {
  activateIpDeadlineRule,
  activateIpWorkingCalendar,
  fetchIpDeadlineRuleImpact,
  fetchIpDeadlineWorkspace,
  fetchIpRulePolicies,
  proposeIpDeadlineRule,
  proposeIpWorkingCalendar,
  selectIpRulePolicy,
  transitionIpDeadlineRule,
  withdrawIpWorkingCalendar,
  type IpCompanyRulePolicy,
  type IpDeadlineRuleImpact,
  type IpDeadlineRuleVersion,
  type IpDeadlineWorkspace,
  type IpDocket,
  type IpGovernanceActionDecision,
  type IpGovernanceBlockReason,
  type IpWorkingCalendarVersion,
} from "@/lib/api/endpoints";
import {
  RULE_SCOPES,
  activeCalendarsForJurisdiction,
  activeWorkingCalendars,
  awaitingActivationText,
  calendarKeyFor,
  describeGovernanceDecision,
  governanceReasonText,
  isRuleScopeId,
  normalJurisdiction,
  parseHolidayDates,
  ruleKeyFor,
  ruleScopeLabel,
  ruleVersionName,
  sourceHashError,
  workingCalendarOptionCaption,
  type GovernanceAction,
  type GovernanceSubject,
  type RuleScopeId,
} from "@/lib/ip/governance";

const TODAY = new Date().toISOString().slice(0, 10);
const FORM_GRID = "grid min-w-0 grid-cols-[repeat(auto-fit,minmax(min(100%,14rem),1fr))] gap-3";
const SELECT_CLASS =
  "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm disabled:cursor-not-allowed disabled:opacity-60";

type FieldErrors = Record<string, string>;

function problemCode(error: unknown): string | null {
  if (!isApiErrorShape(error) || !error.data || typeof error.data !== "object") return null;
  const code = (error.data as Record<string, unknown>).code;
  return typeof code === "string" ? code : null;
}

/** The API refused a rule because of its fixture calendar (proposal 422 or activation 409). */
function isFixtureCalendarRefusal(error: unknown): boolean {
  if (!isApiErrorShape(error)) return false;
  return (problemCode(error) ?? "").startsWith("ip_rule_fixture_calendar_")
    || apiValidationIssues(error.data).some((issue) => (issue.type ?? "").startsWith("ip_rule_fixture_calendar_"));
}

function Field({
  id,
  label,
  error,
  hint,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  children: (describedBy: string | undefined, invalid: boolean) => React.ReactNode;
}) {
  const describedBy = [error ? `${id}-error` : null, hint ? `${id}-hint` : null].filter(Boolean).join(" ") || undefined;
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <Label htmlFor={id} className="break-words leading-snug">{label}</Label>
      {children(describedBy, Boolean(error))}
      {hint ? <p id={`${id}-hint`} className="min-w-0 break-words text-xs text-[var(--color-mute)]">{hint}</p> : null}
      {error ? <p id={`${id}-error`} className="min-w-0 break-words text-xs text-[var(--color-danger)]">{error}</p> : null}
    </div>
  );
}

const EMPLOYEE_DIRECTORY = "/app/admin/employees";

function ReasonLink({ reason }: { reason: IpGovernanceBlockReason }) {
  if (reason !== "no_other_approver") return null;
  return (
    <>
      {" "}
      <a className="font-medium underline underline-offset-2" href={EMPLOYEE_DIRECTORY}>Open the employee directory</a>
    </>
  );
}

function FormError({ id, message }: { id: string; message?: string | null }) {
  if (!message) return null;
  return <p id={id} role="alert" className="col-span-full min-w-0 break-words text-sm text-[var(--color-danger)]">{message}</p>;
}

function BlockedReasons({
  testId,
  title,
  reasons,
  subject,
  action,
}: {
  testId?: string;
  title?: string;
  reasons: IpGovernanceBlockReason[];
  subject: GovernanceSubject;
  action: GovernanceAction;
}) {
  if (!reasons?.length) return null;
  return (
    <div data-testid={testId} className="min-w-0 text-sm">
      {title ? <div className="font-medium">{title}</div> : null}
      <ul className="mt-1 flex min-w-0 flex-col gap-1">
        {reasons.map((reason) => (
          <li key={reason} className="min-w-0 break-words text-[var(--color-mute)]" data-reason={reason}>
            {governanceReasonText(reason, subject, action)}
            <ReasonLink reason={reason} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function DecisionStatus({
  label,
  decision,
  subject,
  action,
}: {
  label: string;
  decision: IpGovernanceActionDecision;
  subject: GovernanceSubject;
  action: GovernanceAction;
}) {
  const rows = describeGovernanceDecision(decision, subject, action);
  if (!rows.length) return null;
  return (
    <li className="min-w-0" data-testid={`ip-governance-blocked-${subject}-${action}`}>
      <div className="flex min-w-0 flex-wrap items-center gap-2 font-medium">
        {label}
        {Array.from(new Set(rows.map((row) => row.category))).map((category) => (
          <Badge key={category} tone="warning">{category}</Badge>
        ))}
      </div>
      <ul className="mt-1 flex min-w-0 flex-col gap-1">
        {rows.map((row) => (
          <li key={row.reason} data-reason={row.reason} className="min-w-0 break-words text-[var(--color-mute)]">
            {row.text}
            <ReasonLink reason={row.reason} />
          </li>
        ))}
      </ul>
    </li>
  );
}

/**
 * Rule and calendar governance for one docket's deadline workspace. Every
 * write control is rendered only when the server projection says the viewer
 * can use it; otherwise the card is read-only and names each reason.
 */
export function IpDeadlineGovernanceCard({ docket }: { docket: IpDocket }) {
  const workspace = useQuery({
    queryKey: ["ip", "deadline-workspace", docket.id],
    queryFn: () => fetchIpDeadlineWorkspace(docket.id),
  });
  const governance = workspace.data?.governance;
  // Deep links from empty deadline pickers land here; the card renders after
  // its data loads, so the browser's own hash scroll has nothing to reach.
  useEffect(() => {
    if (workspace.isSuccess && window.location.hash === "#ip-deadline-governance") {
      document.getElementById("ip-deadline-governance")?.scrollIntoView?.({ block: "start" });
    }
  }, [workspace.isSuccess]);

  return (
    <Card id="ip-deadline-governance" className="min-w-0 scroll-mt-24 xl:col-span-2" data-testid="ip-deadline-governance">
      <CardHeader><CardTitle as="h3">Rule and calendar governance</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-5">
        <p className="text-sm text-[var(--color-mute)]">
          Your firm authors its own versioned deadline rules and working calendars. Each version
          needs independent approval: the proposer cannot activate it, and a rule&apos;s proposer,
          fixture reviewer and legal approver must be three different people.
        </p>
        {workspace.isPending ? <p className="text-sm" role="status">Loading rule and calendar governance…</p> : null}
        {workspace.isError ? (
          <div className="flex min-w-0 flex-wrap items-center gap-2" role="alert">
            <p className="min-w-0 flex-1 break-words text-sm text-[var(--color-danger)]">
              {apiErrorMessage(workspace.error, "Rule and calendar governance could not be loaded.")}
            </p>
            <Button size="sm" variant="secondary" onClick={() => workspace.refetch()}>Retry governance</Button>
          </div>
        ) : null}
        {workspace.data && governance ? (
          <GovernanceBody data={workspace.data} />
        ) : null}
      </CardContent>
    </Card>
  );
}

function GovernanceBody({ data }: { data: IpDeadlineWorkspace }) {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const requestedScope = searchParams?.get("rule_scope") ?? null;
  const governance = data.governance;
  const canSeePolicies = !(
    governance.rule_proposal.reasons.includes("missing_capability")
    && governance.rule_activation.reasons.includes("missing_capability")
  );
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["ip", "deadline-workspace"] }),
      queryClient.invalidateQueries({ queryKey: ["ip", "rule-policies"] }),
    ]);
  };
  const anyBlocked = [
    governance.calendar_proposal,
    governance.calendar_activation,
    governance.rule_proposal,
    governance.rule_activation,
  ].some((decision) => !decision.available);
  const rulesPaused = governance.rule_proposal.reasons.some((reason) => reason.startsWith("rollout_"));

  return (
    <>
      {anyBlocked ? (
        <div
          className="min-w-0 rounded-md border border-[var(--color-warn-border)] bg-[var(--color-warn-bg)] p-3 text-sm text-[var(--color-warn-text)]"
          data-testid="ip-governance-status"
        >
          <div className="font-semibold">What you cannot do here, and why</div>
          <ul className="mt-2 flex min-w-0 flex-col gap-3">
            <DecisionStatus label="Propose working calendars" decision={governance.calendar_proposal} subject="calendar" action="propose" />
            <DecisionStatus label="Activate working calendars" decision={governance.calendar_activation} subject="calendar" action="activate" />
            <DecisionStatus label="Propose deadline rules" decision={governance.rule_proposal} subject="rule" action="propose" />
            <DecisionStatus label="Activate, select, disable or retire deadline rules" decision={governance.rule_activation} subject="rule" action="activate" />
          </ul>
          {rulesPaused && governance.calendar_proposal.available ? (
            <p className="mt-3 min-w-0 break-words" data-testid="ip-governance-calendars-open">
              Working calendars stay open while rule publication is paused: a calendar only lists working
              days and holidays, and no deadline uses it until an active rule is selected with it.
            </p>
          ) : null}
        </div>
      ) : null}

      {governance.calendar_proposal.available || governance.rule_proposal.available ? (
        <div className="grid min-w-0 grid-cols-[repeat(auto-fit,minmax(min(100%,24rem),1fr))] gap-5">
          {governance.calendar_proposal.available ? <CalendarProposalForm onSaved={refresh} /> : null}
          {governance.rule_proposal.available ? (
            <RuleProposalForm
              data={data}
              initialScope={isRuleScopeId(requestedScope) ? requestedScope : "docket_examination"}
              onSaved={refresh}
            />
          ) : null}
        </div>
      ) : null}

      {/* Columns only when each keeps room for its controls (the reviewer
          picker and notes); a fixed lg split left them 160px wide at 1024px. */}
      <div className="grid min-w-0 grid-cols-[repeat(auto-fit,minmax(min(100%,24rem),1fr))] gap-3">
        <div className="flex min-w-0 flex-col gap-2" data-testid="ip-governance-calendars">
          <div className="text-xs font-semibold uppercase tracking-wide text-[var(--color-mute)]">Calendar versions</div>
          {data.calendars.map((row) => <CalendarVersionRow key={row.id} row={row} onSaved={refresh} />)}
          {data.calendars.length === 0 ? (
            <p className="text-sm text-[var(--color-mute)]">No working calendar has been proposed for this workspace yet.</p>
          ) : null}
        </div>
        <div className="flex min-w-0 flex-col gap-2" data-testid="ip-governance-rules">
          <div className="text-xs font-semibold uppercase tracking-wide text-[var(--color-mute)]">Rule versions</div>
          {data.rules.map((row) => (
            <RuleVersionRow
              key={row.id}
              row={row}
              transition={governance.rule_activation}
              selected={(data.eligible_rule_version_ids ?? []).includes(row.id)}
              onSaved={refresh}
            />
          ))}
          {data.rules.length === 0 ? (
            <p className="text-sm text-[var(--color-mute)]">No deadline rule has been proposed for this workspace yet.</p>
          ) : null}
        </div>
      </div>

      {canSeePolicies ? (
        <RulePolicySection data={data} selection={governance.rule_activation} onSaved={refresh} />
      ) : null}
    </>
  );
}

function CalendarProposalForm({ onSaved }: { onSaved: () => Promise<void> }) {
  const [name, setName] = useState("IP India working calendar");
  const [jurisdiction, setJurisdiction] = useState("IN");
  const [office, setOffice] = useState("IP India");
  const [holidays, setHolidays] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState(TODAY);
  const [sourceReference, setSourceReference] = useState("");
  const [sourceHash, setSourceHash] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const clear = (key: string) => setErrors((current) => {
    if (!(key in current)) return current;
    const next = { ...current };
    delete next[key];
    return next;
  });

  const propose = useMutation({
    mutationFn: (holidayDates: string[]) =>
      proposeIpWorkingCalendar({
        key: calendarKeyFor(name),
        name,
        jurisdiction,
        office,
        timezone: "Asia/Kolkata",
        holidays: holidayDates,
        sourceReference,
        sourceHash,
        effectiveFrom,
      }),
    onSuccess: async (row) => {
      toast.success(`Working calendar ${row.name} v${row.version} proposed. Another approver must activate it.`);
      setHolidays("");
      setSourceReference("");
      setSourceHash("");
      setErrors({});
      await onSaved();
    },
    onError: (error) => {
      const fields = apiFieldErrors(error, {
        key: "calendar-name",
        name: "calendar-name",
        jurisdiction: "calendar-jurisdiction",
        office: "calendar-office",
        holidays: "calendar-holidays",
        effective_from: "calendar-effective-from",
        source_reference: "calendar-source-reference",
        source_hash: "calendar-source-hash",
      });
      setErrors(Object.keys(fields).length
        ? fields
        : { [API_FORM_ERROR_KEY]: apiErrorMessage(error, "The working calendar proposal was rejected.") });
    },
  });

  const submit = () => {
    const parsed = parseHolidayDates(holidays);
    const next: FieldErrors = {};
    if (!calendarKeyFor(name)) next["calendar-name"] = "Enter a calendar name with letters or numbers.";
    if (!jurisdiction.trim()) next["calendar-jurisdiction"] = "Enter the jurisdiction, for example IN.";
    if (parsed.errors.length) next["calendar-holidays"] = parsed.errors.join(" ");
    if (!effectiveFrom) next["calendar-effective-from"] = "Choose the date this calendar takes effect.";
    if (!sourceReference.trim()) next["calendar-source-reference"] = "Enter the official source reference (for example the gazette notification or its URL).";
    const hashError = sourceHashError(sourceHash);
    if (hashError) next["calendar-source-hash"] = hashError;
    setErrors(next);
    if (Object.keys(next).length === 0) propose.mutate(parsed.dates);
  };

  return (
    <form
      className={FORM_GRID}
      noValidate
      data-testid="ip-calendar-proposal"
      onSubmit={(event) => { event.preventDefault(); submit(); }}
    >
      <div className="col-span-full text-sm font-semibold">Propose working calendar</div>
      <Field
        id="calendar-name"
        label="Calendar name"
        error={errors["calendar-name"]}
        hint="Proposing again under the same name creates its next version."
      >
        {(describedBy, invalid) => <Input id="calendar-name" value={name} aria-invalid={invalid || undefined} aria-describedby={describedBy} onChange={(e) => { setName(e.target.value); clear("calendar-name"); }} />}
      </Field>
      <Field id="calendar-jurisdiction" label="Jurisdiction" error={errors["calendar-jurisdiction"]}>
        {(describedBy, invalid) => <Input id="calendar-jurisdiction" value={jurisdiction} aria-invalid={invalid || undefined} aria-describedby={describedBy} onChange={(e) => { setJurisdiction(e.target.value); clear("calendar-jurisdiction"); }} />}
      </Field>
      <Field id="calendar-office" label="Office" error={errors["calendar-office"]}>
        {(describedBy, invalid) => <Input id="calendar-office" value={office} aria-invalid={invalid || undefined} aria-describedby={describedBy} onChange={(e) => { setOffice(e.target.value); clear("calendar-office"); }} />}
      </Field>
      <Field
        id="calendar-holidays"
        label="Holiday dates"
        error={errors["calendar-holidays"]}
        hint="YYYY-MM-DD or DD/MM/YYYY, separated by commas."
      >
        {(describedBy, invalid) => <Input id="calendar-holidays" value={holidays} aria-invalid={invalid || undefined} aria-describedby={describedBy} onChange={(e) => { setHolidays(e.target.value); clear("calendar-holidays"); }} placeholder="26/01/2026, 15/08/2026" />}
      </Field>
      <Field id="calendar-effective-from" label="Effective from" error={errors["calendar-effective-from"]}>
        {(describedBy, invalid) => <Input id="calendar-effective-from" type="date" value={effectiveFrom} aria-invalid={invalid || undefined} aria-describedby={describedBy} onChange={(e) => { setEffectiveFrom(e.target.value); clear("calendar-effective-from"); }} />}
      </Field>
      <Field id="calendar-source-reference" label="Official source reference" error={errors["calendar-source-reference"]}>
        {(describedBy, invalid) => <Input id="calendar-source-reference" value={sourceReference} aria-invalid={invalid || undefined} aria-describedby={describedBy} onChange={(e) => { setSourceReference(e.target.value); clear("calendar-source-reference"); }} />}
      </Field>
      <SourceHashField id="calendar-source-hash" value={sourceHash} onChange={(value) => { setSourceHash(value); clear("calendar-source-hash"); }} error={errors["calendar-source-hash"]} />
      <FormError id="calendar-form-error" message={errors[API_FORM_ERROR_KEY]} />
      <div className="col-span-full min-w-0">
        <Button className="h-auto min-h-10 max-w-full whitespace-normal py-2" type="submit" disabled={propose.isPending}>
          {propose.isPending ? "Proposing calendar…" : "Propose calendar version"}
        </Button>
      </div>
    </form>
  );
}

function RuleProposalForm({
  data,
  initialScope,
  onSaved,
}: {
  data: IpDeadlineWorkspace;
  initialScope: RuleScopeId;
  onSaved: () => Promise<void>;
}) {
  const [jurisdiction, setJurisdiction] = useState("IN");
  const ruleJurisdiction = normalJurisdiction(jurisdiction);
  // The API runs fixtures only on an active calendar of the rule's jurisdiction.
  const allActiveCalendars = activeWorkingCalendars(data);
  const calendars = activeCalendarsForJurisdiction(data, jurisdiction);
  const otherJurisdictions = Array.from(new Set(allActiveCalendars.map((row) => normalJurisdiction(row.jurisdiction)))).sort();
  const pendingCalendars = data.calendars.filter((row) => row.status === "candidate" && normalJurisdiction(row.jurisdiction) === ruleJurisdiction);
  const [scopeId, setScopeId] = useState<RuleScopeId>(initialScope);
  const scope = RULE_SCOPES.find((row) => row.id === scopeId) ?? RULE_SCOPES[0];
  const [office, setOffice] = useState("IP India");
  const triggerKind = scope.triggerKind;
  const [method, setMethod] = useState<"business_days" | "calendar_days" | "month_anniversary">(scope.calendarMethod);
  const [duration, setDuration] = useState("");
  const [citation, setCitation] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState(TODAY);
  const [sourceReference, setSourceReference] = useState("");
  const [sourceHash, setSourceHash] = useState("");
  const [calendarId, setCalendarId] = useState("");
  const [fixtureBase, setFixtureBase] = useState(TODAY);
  const [fixtureExpected, setFixtureExpected] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const clear = (key: string) => setErrors((current) => {
    if (!(key in current)) return current;
    const next = { ...current };
    delete next[key];
    return next;
  });
  // One active calendar is the only choice; with several, the proposer picks one.
  const calendar = calendars.length === 1 ? calendars[0] : calendars.find((row) => row.id === calendarId);
  const prerequisiteId = "rule-proposal-prerequisite";

  const propose = useMutation({
    mutationFn: () => {
      if (!calendar) throw new Error("An active working calendar is required for the fixture.");
      const durationValue = Number(duration);
      const calculation = {
        deadline_kind: "legal_deadline",
        trigger_kind: triggerKind,
        base_date: fixtureBase,
        base_date_certainty: "certain",
        duration_value: durationValue,
        duration_unit: method === "month_anniversary" ? "months" : "days",
        calendar_method: method,
        direction: "after",
        include_base_date: false,
        next_working_day: true,
        extension_days: 0,
        rule_version_id: "governance-fixture-rule",
        rule_citation: citation,
        source_version: "governance-fixture-source",
        engine_version: "caseops-ip-deadline-v1",
        calendar: {
          calendar_version_id: calendar.id,
          timezone: calendar.timezone,
          weekend_days: calendar.weekend_days,
          holidays: calendar.holidays,
          exceptional_working_days: calendar.exceptional_working_days,
          source_reference: calendar.source_reference,
          source_hash: calendar.source_hash,
        },
      };
      return proposeIpDeadlineRule({
        key: ruleKeyFor(scope.id, jurisdiction),
        jurisdiction,
        office,
        rightKind: "trademark",
        proceedingKind: scope.proceedingKind,
        role: scope.role,
        stage: scope.stage,
        sourceRecordId: `verified-source-${effectiveFrom}`,
        sourceReference,
        sourceHash,
        effectiveFrom,
        triggerKind,
        durationValue,
        calendarMethod: method,
        ruleCitation: citation,
        fixtureCalculation: calculation,
        fixtureExpectedState: "candidate",
        fixtureExpectedResultOn: fixtureExpected || null,
      });
    },
    onSuccess: async (row) => {
      toast.success(`${ruleVersionName(row)} proposed. Another approver must run its fixtures and activate it.`);
      setSourceReference("");
      setSourceHash("");
      setErrors({});
      await onSaved();
    },
    onError: async (error) => {
      const fields = apiFieldErrors(error, {
        key: "rule-scope",
        jurisdiction: "rule-jurisdiction",
        office: "rule-office",
        source_reference: "rule-source-reference",
        source_hash: "rule-source-hash",
        effective_from: "rule-effective-from",
        calendar_version_id: "rule-fixture-calendar",
      });
      setErrors(Object.keys(fields).length
        ? fields
        : { [API_FORM_ERROR_KEY]: apiErrorMessage(error, "The deadline rule proposal was rejected.") });
      if (isFixtureCalendarRefusal(error)) {
        // The calendar changed under this form (replaced, withdrawn, edited):
        // drop the stale choice and reload the calendars the API now accepts.
        setCalendarId("");
        await onSaved();
      }
    },
  });

  const submit = () => {
    const next: FieldErrors = {};
    if (!jurisdiction.trim()) next["rule-jurisdiction"] = "Enter the jurisdiction, for example IN.";
    if (!/^\d+$/.test(duration.trim()) || Number(duration) < 1) next["rule-duration"] = "Enter the period as a whole number of at least 1.";
    if (!citation.trim()) next["rule-citation"] = "Enter the statutory citation, for example the section and rule.";
    if (!sourceReference.trim()) next["rule-source-reference"] = "Enter the official source reference for this rule.";
    const hashError = sourceHashError(sourceHash);
    if (hashError) next["rule-source-hash"] = hashError;
    if (calendars.length && !calendar) next["rule-fixture-calendar"] = "Choose the active working calendar the fixture is calculated on.";
    if (!fixtureBase) next["rule-fixture-base"] = "Choose the fixture trigger date.";
    if (!fixtureExpected) next["rule-fixture-expected"] = "Enter the deadline you expect for the fixture trigger date; the server checks it.";
    setErrors(next);
    if (Object.keys(next).length === 0) propose.mutate();
  };
  const unit = method === "month_anniversary" ? "months" : method === "business_days" ? "working days" : "calendar days";

  return (
    <form
      className={FORM_GRID}
      noValidate
      data-testid="ip-rule-proposal"
      onSubmit={(event) => { event.preventDefault(); submit(); }}
    >
      <div className="col-span-full text-sm font-semibold">Propose tested deadline rule</div>
      <Field
        id="rule-scope"
        label="Applies to"
        error={errors["rule-scope"]}
        hint={`Starts from: ${scope.triggerLabel}. Opposition deadline pickers list only rules of their exact scope; proposing the same scope again creates its next version.`}
      >
        {(describedBy, invalid) => (
          <select
            id="rule-scope"
            className={SELECT_CLASS}
            value={scopeId}
            aria-invalid={invalid || undefined}
            aria-describedby={describedBy}
            onChange={(event) => {
              const nextScope = RULE_SCOPES.find((row) => row.id === event.target.value) ?? RULE_SCOPES[0];
              setScopeId(nextScope.id);
              setMethod(nextScope.calendarMethod);
              clear("rule-scope");
            }}
          >
            {RULE_SCOPES.map((row) => <option key={row.id} value={row.id}>{row.label}</option>)}
          </select>
        )}
      </Field>
      <Field id="rule-jurisdiction" label="Jurisdiction" error={errors["rule-jurisdiction"]}>
        {(describedBy, invalid) => <Input id="rule-jurisdiction" value={jurisdiction} aria-invalid={invalid || undefined} aria-describedby={describedBy} onChange={(e) => { setJurisdiction(e.target.value); clear("rule-jurisdiction"); }} />}
      </Field>
      <Field id="rule-office" label="Office" error={errors["rule-office"]}>
        {(describedBy, invalid) => <Input id="rule-office" value={office} aria-invalid={invalid || undefined} aria-describedby={describedBy} onChange={(e) => { setOffice(e.target.value); clear("rule-office"); }} />}
      </Field>
      <Field id="rule-method" label="Period counted in">
        {(describedBy) => (
          <select id="rule-method" className={SELECT_CLASS} value={method} aria-describedby={describedBy} onChange={(event) => setMethod(event.target.value as typeof method)}>
            <option value="month_anniversary">Months (same day of month)</option>
            <option value="calendar_days">Calendar days</option>
            <option value="business_days">Working days</option>
          </select>
        )}
      </Field>
      <Field id="rule-duration" label={`Period (${unit})`} error={errors["rule-duration"]}>
        {(describedBy, invalid) => <Input id="rule-duration" type="number" min={1} inputMode="numeric" value={duration} aria-invalid={invalid || undefined} aria-describedby={describedBy} onChange={(e) => { setDuration(e.target.value); clear("rule-duration"); }} />}
      </Field>
      <Field id="rule-citation" label="Rule citation" error={errors["rule-citation"]}>
        {(describedBy, invalid) => <Input id="rule-citation" value={citation} aria-invalid={invalid || undefined} aria-describedby={describedBy} onChange={(e) => { setCitation(e.target.value); clear("rule-citation"); }} placeholder="Trade Marks Act 1999, s.21(1)" />}
      </Field>
      <Field id="rule-effective-from" label="Effective from" error={errors["rule-effective-from"]}>
        {(describedBy, invalid) => <Input id="rule-effective-from" type="date" value={effectiveFrom} aria-invalid={invalid || undefined} aria-describedby={describedBy} onChange={(e) => { setEffectiveFrom(e.target.value); clear("rule-effective-from"); }} />}
      </Field>
      <Field id="rule-source-reference" label="Rule source reference" error={errors["rule-source-reference"]}>
        {(describedBy, invalid) => <Input id="rule-source-reference" value={sourceReference} aria-invalid={invalid || undefined} aria-describedby={describedBy} onChange={(e) => { setSourceReference(e.target.value); clear("rule-source-reference"); }} />}
      </Field>
      <SourceHashField id="rule-source-hash" label="Rule source file" value={sourceHash} onChange={(value) => { setSourceHash(value); clear("rule-source-hash"); }} error={errors["rule-source-hash"]} />
      <Field id="rule-fixture-calendar" label="Fixture working calendar" error={errors["rule-fixture-calendar"]}>
        {(describedBy, invalid) => (
          <>
            <select
              id="rule-fixture-calendar"
              className={SELECT_CLASS}
              value={calendar?.id ?? ""}
              disabled={!calendars.length}
              aria-invalid={invalid || undefined}
              aria-describedby={calendars.length ? [describedBy, calendar ? "rule-fixture-calendar-detail" : null].filter(Boolean).join(" ") || undefined : prerequisiteId}
              onChange={(event) => { setCalendarId(event.target.value); clear("rule-fixture-calendar"); }}
            >
              {!calendars.length ? <option value="">{ruleJurisdiction ? `No active ${ruleJurisdiction} working calendar` : "Enter the jurisdiction first"}</option> : null}
              {calendars.length > 1 && !calendar ? <option value="" disabled>Choose a working calendar</option> : null}
              {calendars.map((row) => <option key={row.id} value={row.id}>{workingCalendarOptionCaption(row)}</option>)}
            </select>
            {/* A long calendar name is clipped inside the select; spell the chosen one out in full. */}
            {calendar ? <p id="rule-fixture-calendar-detail" data-selected-option-value={calendar.id} className="min-w-0 whitespace-normal break-all text-sm text-[var(--color-mute)]">{workingCalendarOptionCaption(calendar)}</p> : null}
          </>
        )}
      </Field>
      <Field id="rule-fixture-base" label="Fixture trigger date" error={errors["rule-fixture-base"]}>
        {(describedBy, invalid) => <Input id="rule-fixture-base" type="date" value={fixtureBase} aria-invalid={invalid || undefined} aria-describedby={describedBy} onChange={(e) => { setFixtureBase(e.target.value); clear("rule-fixture-base"); }} />}
      </Field>
      <Field id="rule-fixture-expected" label="Expected fixture deadline" error={errors["rule-fixture-expected"]}>
        {(describedBy, invalid) => <Input id="rule-fixture-expected" type="date" value={fixtureExpected} aria-invalid={invalid || undefined} aria-describedby={describedBy} onChange={(e) => { setFixtureExpected(e.target.value); clear("rule-fixture-expected"); }} />}
      </Field>
      {!calendars.length ? (
        <p id={prerequisiteId} className="col-span-full min-w-0 break-words text-sm text-[var(--color-warn-text)]">
          {ruleJurisdiction
            ? `A rule's fixture is calculated on an active working calendar of the rule's jurisdiction (${ruleJurisdiction}).`
            : "Enter the rule's jurisdiction; its fixture is calculated on an active working calendar of that jurisdiction."}{" "}
          {otherJurisdictions.length && ruleJurisdiction
            ? `Active calendars exist only for ${otherJurisdictions.join(", ")}. `
            : ""}
          {!ruleJurisdiction
            ? null
            : pendingCalendars.length
              ? awaitingActivationText(pendingCalendars.map((row) => `${row.name} v${row.version}`))
              : `Propose a working calendar for ${ruleJurisdiction} first; another owner, admin or partner must activate it.`}
        </p>
      ) : null}
      <FormError id="rule-form-error" message={errors[API_FORM_ERROR_KEY]} />
      <div className="col-span-full min-w-0">
        <Button
          className="h-auto min-h-10 max-w-full whitespace-normal py-2"
          type="submit"
          disabled={!calendars.length || propose.isPending}
          aria-describedby={!calendars.length ? prerequisiteId : undefined}
        >
          {propose.isPending ? "Proposing rule…" : "Propose rule and fixture"}
        </Button>
      </div>
    </form>
  );
}

function calendarStatusLabel(row: IpWorkingCalendarVersion): string {
  // A retired version nobody activated was withdrawn by its proposer.
  return row.status === "retired" && !row.approved_at ? "withdrawn" : row.status;
}

function CalendarVersionRow({ row, onSaved }: { row: IpWorkingCalendarVersion; onSaved: () => Promise<void> }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [withdrawReason, setWithdrawReason] = useState("");
  const [withdrawError, setWithdrawError] = useState<string | null>(null);
  const reasonId = `calendar-activation-reason-${row.id}`;
  const withdrawId = `calendar-withdraw-reason-${row.id}`;
  const withdraw = useMutation({
    mutationFn: () => withdrawIpWorkingCalendar({ calendarVersionId: row.id, reason: withdrawReason }),
    onSuccess: async () => {
      toast.success(`${row.name} v${row.version} was withdrawn.`);
      setWithdrawError(null);
      await onSaved();
    },
    onError: (failure) => setWithdrawError(apiErrorMessage(failure, "The calendar could not be withdrawn.")),
  });
  const activate = useMutation({
    mutationFn: () => activateIpWorkingCalendar({ calendarVersionId: row.id, reason, conflictReviewed: true }),
    onSuccess: async () => {
      toast.success(`${row.name} v${row.version} is active.`);
      setError(null);
      await onSaved();
    },
    onError: (failure) => setError(apiErrorMessage(failure, "The calendar activation was rejected.")),
  });
  return (
    <div className="min-w-0 rounded-lg border border-[var(--color-line)] p-3 text-sm" data-testid={`ip-calendar-version-${row.id}`}>
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="break-words font-semibold">{row.name} v{row.version}</span>
        <Badge tone={row.status === "active" ? "success" : row.status === "candidate" ? "warning" : "neutral"}>{calendarStatusLabel(row)}</Badge>
      </div>
      <div className="mt-1 break-words text-xs text-[var(--color-mute)]">
        {row.jurisdiction}{row.office ? ` · ${row.office}` : ""} · {row.source_reference} · proposed by {row.proposer_label_snapshot}
        {row.approver_label_snapshot ? ` · activated by ${row.approver_label_snapshot}` : ""}
      </div>
      {row.status === "candidate" && row.can_activate ? (
        <div className="mt-3 flex min-w-0 flex-col gap-2">
          <Label htmlFor={reasonId}>Activation reason</Label>
          <Input
            id={reasonId}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            aria-describedby={`${reasonId}-hint${error ? ` ${reasonId}-error` : ""}`}
            aria-invalid={error ? true : undefined}
          />
          <p id={`${reasonId}-hint`} className="text-xs text-[var(--color-mute)]">State what you checked against the official source (at least 5 characters).</p>
          {error ? <p id={`${reasonId}-error`} className="break-words text-xs text-[var(--color-danger)]">{error}</p> : null}
          <Button
            className="w-full sm:w-auto"
            size="sm"
            disabled={reason.trim().length < 5 || activate.isPending}
            aria-describedby={`${reasonId}-hint`}
            onClick={() => activate.mutate()}
          >
            Independently activate calendar
          </Button>
        </div>
      ) : null}
      {row.status === "candidate" && !row.can_activate ? (
        <div className="mt-2">
          <BlockedReasons
            testId={`ip-calendar-activation-blocked-${row.id}`}
            title="Awaiting activation"
            reasons={row.activation_blocked_reasons}
            subject="calendar"
            action="activate"
          />
        </div>
      ) : null}
      {row.can_withdraw ? (
        <div className="mt-3 flex min-w-0 flex-col gap-2" data-testid={`ip-calendar-withdraw-${row.id}`}>
          <Label htmlFor={withdrawId}>Reason to withdraw your proposal</Label>
          <Input
            id={withdrawId}
            value={withdrawReason}
            onChange={(event) => { setWithdrawReason(event.target.value); setWithdrawError(null); }}
            aria-describedby={`${withdrawId}-hint${withdrawError ? ` ${withdrawId}-error` : ""}`}
            aria-invalid={withdrawError ? true : undefined}
          />
          <p id={`${withdrawId}-hint`} className="text-xs text-[var(--color-mute)]">
            At least 5 characters. The version is kept as withdrawn evidence and can no longer be activated.
          </p>
          {withdrawError ? <p id={`${withdrawId}-error`} className="break-words text-xs text-[var(--color-danger)]">{withdrawError}</p> : null}
          <Button
            className="w-full sm:w-auto"
            size="sm"
            variant="secondary"
            disabled={withdrawReason.trim().length < 5 || withdraw.isPending}
            aria-describedby={`${withdrawId}-hint`}
            onClick={() => withdraw.mutate()}
          >
            Withdraw my proposal
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function RuleVersionRow({
  row,
  transition,
  selected,
  onSaved,
}: {
  row: IpDeadlineRuleVersion;
  transition: IpGovernanceActionDecision;
  selected: boolean;
  onSaved: () => Promise<void>;
}) {
  const [reviewerId, setReviewerId] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [reviewerError, setReviewerError] = useState<string | null>(null);
  const [impact, setImpact] = useState<IpDeadlineRuleImpact | null>(null);
  // Activation sends only the token of the preview this person saw.
  const [activationImpact, setActivationImpact] = useState<IpDeadlineRuleImpact | null>(null);
  const [impactReviewed, setImpactReviewed] = useState(false);
  const [supersede, setSupersede] = useState(false);
  const reviewerFieldId = `rule-reviewer-${row.id}`;
  const reasonId = `rule-reason-${row.id}`;
  const name = ruleVersionName(row);
  const affects = activationImpact
    ? activationImpact.company_policy_count + activationImpact.open_deadline_count > 0
    : false;
  const superseded = activationImpact?.superseded_versions ?? [];
  const activationMissing = [
    !reviewerId ? "choose the fixture reviewer" : null,
    reason.trim().length < 5 ? "write an activation note (at least 5 characters)" : null,
    !activationImpact ? "preview the activation impact" : null,
    affects && !impactReviewed ? "confirm you reviewed the impact" : null,
    superseded.length && !supersede ? "confirm the replacement of the active version" : null,
  ].filter((item): item is string => Boolean(item));

  const previewActivation = useMutation({
    mutationFn: () => fetchIpDeadlineRuleImpact(row.id),
    onSuccess: (result) => {
      setActivationImpact(result);
      setImpactReviewed(false);
      setSupersede(false);
      setError(null);
    },
    onError: (failure) => setError(apiErrorMessage(failure, "The activation impact could not be loaded.")),
  });
  const activate = useMutation({
    mutationFn: () => {
      if (!activationImpact) throw new Error("Preview the activation impact first.");
      return activateIpDeadlineRule({
        ruleVersionId: row.id,
        reviewerMembershipId: reviewerId,
        impactAcknowledged: affects ? impactReviewed : false,
        impactReason: reason,
        impactToken: activationImpact.impact_token,
        supersedeOverlapping: superseded.length > 0 && supersede,
      });
    },
    onSuccess: async () => {
      toast.success(`${name} is active and selected for company deadlines.`);
      setError(null);
      setReviewerError(null);
      await onSaved();
    },
    onError: (failure) => {
      const message = apiErrorMessage(failure, "The rule activation was rejected.");
      if (problemCode(failure) === "ip_rule_reviewer_unqualified") {
        setReviewerError(message);
      } else if (isFixtureCalendarRefusal(failure)) {
        // The record now carries the blocked reason; reload it so the
        // activate control is withdrawn instead of failing again.
        setError(message);
        void onSaved();
      } else if (/preview again|impact must be reviewed|overlaps active version/i.test(message)) {
        // The impact moved after the preview: never activate on a stale one.
        setActivationImpact(null);
        setImpactReviewed(false);
        setSupersede(false);
        setError("The rules or deadlines this activation affects changed after your preview. Preview the impact again, then confirm.");
      } else {
        setError(message);
      }
    },
  });
  const preview = useMutation({
    mutationFn: () => fetchIpDeadlineRuleImpact(row.id),
    onSuccess: (result) => { setImpact(result); setError(null); },
    onError: (failure) => setError(apiErrorMessage(failure, "The impact preview could not be loaded.")),
  });
  const transitionRule = useMutation({
    mutationFn: (emergencyDisable: boolean) => {
      if (!impact) throw new Error("Preview the impact first.");
      return transitionIpDeadlineRule({
        ruleVersionId: row.id,
        impactToken: impact.impact_token,
        reason,
        emergencyDisable,
      });
    },
    onSuccess: async (result) => {
      toast.success(`${name} is ${result.status}. Owners of dependent deadlines were alerted.`);
      setImpact(null);
      setError(null);
      await onSaved();
    },
    onError: (failure) => {
      const code = problemCode(failure);
      const stale = code === "ip_rule_transition_recipients_changed"
        || /preview again/i.test(apiErrorMessage(failure, ""));
      if (stale) {
        setImpact(null);
        setError("The people affected by this change moved while you were deciding. Preview the impact again, then confirm.");
      } else {
        setError(apiErrorMessage(failure, "The rule change was rejected."));
      }
    },
  });

  return (
    <div className="min-w-0 rounded-lg border border-[var(--color-line)] p-3 text-sm" data-testid={`ip-rule-version-${row.id}`}>
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="break-words font-semibold">{name}</span>
        <Badge tone={row.status === "active" ? "success" : row.status === "candidate" ? "warning" : "neutral"}>{row.status}</Badge>
        {selected ? <Badge tone="brand">Selected for company deadlines</Badge> : null}
      </div>
      <div className="mt-1 break-words text-xs text-[var(--color-mute)]">
        {ruleScopeLabel(row)} · {row.jurisdiction}{row.office ? ` · ${row.office}` : ""} · proposed by {row.proposer_label_snapshot}
        {row.legal_approver_label_snapshot ? ` · activated by ${row.legal_approver_label_snapshot}` : ""}
      </div>

      {row.status === "candidate" && row.can_activate ? (
        <div className="mt-3 grid min-w-0 gap-2">
          <Label htmlFor={reviewerFieldId}>Independent fixture reviewer</Label>
          <PersonPicker
            id={reviewerFieldId}
            value={reviewerId}
            onChange={setReviewerId}
            onlyMembershipIds={row.eligible_reviewer_membership_ids ?? []}
            placeholder="Select the fixture reviewer…"
            emptyText="No colleague other than you and the proposer can review the fixtures."
            errorId={reviewerError ? `${reviewerFieldId}-error` : undefined}
          />
          {reviewerError ? <p id={`${reviewerFieldId}-error`} className="break-words text-xs text-[var(--color-danger)]">{reviewerError}</p> : null}
          <Label htmlFor={reasonId}>Activation note</Label>
          <Input id={reasonId} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Reviewed against the official source…" />
          <Button
            className="w-full sm:w-auto"
            size="sm"
            variant="secondary"
            disabled={previewActivation.isPending}
            onClick={() => previewActivation.mutate()}
          >
            {activationImpact ? "Preview activation impact again" : "Preview activation impact"}
          </Button>
          {activationImpact ? (
            <div className="min-w-0 rounded-md border border-[var(--color-line)] p-2 text-xs" role="status" data-testid={`ip-rule-activation-impact-${row.id}`}>
              <p className="break-words">
                {affects
                  ? `Activating affects ${activationImpact.company_policy_count} company selection(s), ${activationImpact.open_deadline_count} open deadline(s) and ${activationImpact.candidate_deadline_count} unconfirmed deadline(s). Confirmed deadlines keep their dates.`
                  : "No company selection or open deadline uses this rule yet."}
              </p>
              {superseded.length ? (
                <p className="mt-1 break-words">
                  Its effective dates overlap active version{superseded.length > 1 ? "s" : ""} {superseded.map((version) => `v${version}`).join(", ")}, which activation retires.
                </p>
              ) : null}
              {affects ? (
                <label className="mt-2 flex min-w-0 items-start gap-2">
                  <input type="checkbox" className="mt-0.5" checked={impactReviewed} onChange={(event) => setImpactReviewed(event.target.checked)} />
                  <span className="min-w-0 break-words">I reviewed this impact; the activation note explains why it is acceptable.</span>
                </label>
              ) : null}
              {superseded.length ? (
                <label className="mt-2 flex min-w-0 items-start gap-2">
                  <input type="checkbox" className="mt-0.5" checked={supersede} onChange={(event) => setSupersede(event.target.checked)} />
                  <span className="min-w-0 break-words">Retire {superseded.map((version) => `v${version}`).join(", ")} and use v{row.version} from {row.effective_from}.</span>
                </label>
              ) : null}
            </div>
          ) : null}
          {error ? <p role="alert" className="break-words text-xs text-[var(--color-danger)]">{error}</p> : null}
          <Button
            className="w-full sm:w-auto"
            size="sm"
            disabled={activationMissing.length > 0 || activate.isPending}
            aria-describedby={`${reasonId}-requirement`}
            onClick={() => activate.mutate()}
          >
            Run fixtures and activate rule
          </Button>
          <p id={`${reasonId}-requirement`} className="text-xs text-[var(--color-mute)]">
            {activationMissing.length
              ? `To activate: ${activationMissing.join("; ")}.`
              : "Ready. The server re-runs every fixture and checks the impact again before activating."}
          </p>
        </div>
      ) : null}
      {row.status === "candidate" && !row.can_activate ? (
        <div className="mt-2">
          <BlockedReasons
            testId={`ip-rule-activation-blocked-${row.id}`}
            title="Awaiting activation"
            reasons={row.activation_blocked_reasons}
            subject="rule"
            action="activate"
          />
        </div>
      ) : null}

      {row.status === "active" && transition.available ? (
        <div className="mt-3 grid min-w-0 gap-2" data-testid={`ip-rule-transition-${row.id}`}>
          <Label htmlFor={`${reasonId}-transition`}>Reason to disable or retire</Label>
          <Input id={`${reasonId}-transition`} value={reason} onChange={(event) => setReason(event.target.value)} />
          {impact ? (
            <p className="break-words text-xs" role="status">
              Impact: {impact.company_policy_count} company selection(s), {impact.open_deadline_count} open deadline(s), {impact.candidate_deadline_count} unconfirmed deadline(s). Confirmed deadlines are preserved; their owners are alerted.
            </p>
          ) : null}
          {error ? <p role="alert" className="break-words text-xs text-[var(--color-danger)]">{error}</p> : null}
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:flex-wrap">
            <Button className="w-full sm:w-auto" size="sm" variant="secondary" disabled={preview.isPending} onClick={() => preview.mutate()}>
              {impact ? "Preview impact again" : "Preview impact"}
            </Button>
            <Button
              className="w-full sm:w-auto"
              size="sm"
              variant="secondary"
              disabled={!impact || reason.trim().length < 5 || transitionRule.isPending}
              aria-describedby={`${reasonId}-transition-requirement`}
              onClick={() => transitionRule.mutate(true)}
            >
              Emergency-disable rule
            </Button>
            <Button
              className="w-full sm:w-auto"
              size="sm"
              variant="secondary"
              disabled={!impact || reason.trim().length < 5 || transitionRule.isPending}
              aria-describedby={`${reasonId}-transition-requirement`}
              onClick={() => transitionRule.mutate(false)}
            >
              Retire rule
            </Button>
          </div>
          <p id={`${reasonId}-transition-requirement`} className="text-xs text-[var(--color-mute)]">
            Preview the impact and give a reason (at least 5 characters) before disabling or retiring.
          </p>
        </div>
      ) : null}
    </div>
  );
}

function RulePolicySection({
  data,
  selection,
  onSaved,
}: {
  data: IpDeadlineWorkspace;
  selection: IpGovernanceActionDecision;
  onSaved: () => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const policies = useQuery({ queryKey: ["ip", "rule-policies"], queryFn: fetchIpRulePolicies });
  const [conflict, setConflict] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const select = useMutation({
    mutationFn: (input: { rule: IpDeadlineRuleVersion; policy: IpCompanyRulePolicy | undefined }) =>
      selectIpRulePolicy({
        ruleVersionId: input.rule.id,
        expectedPolicyVersion: input.policy?.version ?? null,
        autoConfirmEligible: input.policy?.auto_confirm_eligible ?? false,
      }),
    onSuccess: async (policy) => {
      toast.success(`Version ${policy.active_rule_version} is selected for company deadlines.`);
      setConflict(null);
      setError(null);
      await onSaved();
    },
    onError: (failure) => {
      if (problemCode(failure) === "ip_rule_policy_version_conflict") {
        setConflict("Someone changed the company selection after you loaded it. Reload it, check the current version, then select again.");
      } else {
        setError(apiErrorMessage(failure, "The company rule selection was rejected."));
      }
    },
  });
  const ruleSets = Array.from(new Set(data.rules.map((row) => row.rule_set_id)));

  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid="ip-rule-policies">
      <div className="text-xs font-semibold uppercase tracking-wide text-[var(--color-mute)]">Company rule selection</div>
      <p className="text-sm text-[var(--color-mute)]">
        Deadline pickers offer only the active version your company has selected for each rule.
        Activating a rule selects it; select again here after a policy change.
      </p>
      {policies.isPending ? <p className="text-sm" role="status">Loading company rule selection…</p> : null}
      {policies.isError ? (
        <div className="flex min-w-0 flex-wrap items-center gap-2" role="alert">
          <p className="min-w-0 flex-1 break-words text-sm text-[var(--color-danger)]">
            {apiErrorMessage(policies.error, "The company rule selection could not be loaded.")}
          </p>
          <Button size="sm" variant="secondary" onClick={() => policies.refetch()}>Retry</Button>
        </div>
      ) : null}
      {conflict ? (
        <div className="flex min-w-0 flex-wrap items-center gap-2" role="alert">
          <p className="min-w-0 flex-1 break-words text-sm text-[var(--color-danger)]">{conflict}</p>
          <Button
            size="sm"
            variant="secondary"
            onClick={async () => {
              setConflict(null);
              await queryClient.invalidateQueries({ queryKey: ["ip", "rule-policies"] });
              await queryClient.invalidateQueries({ queryKey: ["ip", "deadline-workspace"] });
            }}
          >
            Reload company selection
          </Button>
        </div>
      ) : null}
      {error ? <p role="alert" className="break-words text-sm text-[var(--color-danger)]">{error}</p> : null}
      {policies.isSuccess ? ruleSets.map((ruleSetId) => {
        const versions = data.rules.filter((row) => row.rule_set_id === ruleSetId);
        const policy = policies.data.find((row) => row.rule_set_id === ruleSetId);
        const active = versions.find((row) => row.status === "active");
        const needsSelection = Boolean(active && policy?.active_rule_version_id !== active.id);
        return (
          <div key={ruleSetId} className="min-w-0 rounded-lg border border-[var(--color-line)] p-3 text-sm" data-testid={`ip-rule-policy-${ruleSetId}`}>
            <div className="break-words font-semibold">{versions[0] ? ruleScopeLabel(versions[0]) : null}{versions[0] ? ` · ${versions[0].jurisdiction}` : null}</div>
            <div className="mt-1 break-words text-xs text-[var(--color-mute)]">
              {policy
                ? `Selected: v${policy.active_rule_version} (${policy.active_rule_status}) · policy version ${policy.version} · updated by ${policy.updater_label_snapshot}`
                : "Not selected for company deadlines."}
              {policy?.auto_confirm_suspended_reason ? ` · auto-confirm suspended: ${policy.auto_confirm_suspended_reason}` : ""}
            </div>
            {policy && policy.active_rule_status !== "active" && !active ? (
              <p className="mt-1 break-words text-xs text-[var(--color-warn-text)]">
                The selected version is {policy.active_rule_status}, so no deadline can use this rule until a new version is proposed and activated.
              </p>
            ) : null}
            {needsSelection && active && selection.available ? (
              <Button
                className="mt-2 w-full sm:w-auto"
                size="sm"
                disabled={select.isPending}
                onClick={() => select.mutate({ rule: active, policy })}
              >
                Select v{active.version} for company deadlines
              </Button>
            ) : null}
            {needsSelection && !selection.available ? (
              <div className="mt-2">
                <BlockedReasons reasons={selection.reasons} subject="rule" action="activate" />
              </div>
            ) : null}
          </div>
        );
      }) : null}
      {policies.isSuccess && ruleSets.length === 0 ? (
        <p className="text-sm text-[var(--color-mute)]">No rule has been proposed yet, so there is nothing to select.</p>
      ) : null}
    </div>
  );
}
