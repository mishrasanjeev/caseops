"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, Eye } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import { previewIpDocketLifecycle, transitionIpDocketLifecycle, type IpLifecycleInput } from "@/lib/api/endpoints";
import {
  fetchPatentFamilyLifecycleHistory, fetchPatentApplicationLifecycleHistory,
  type PatentApplication, type PatentFamily,
} from "@/lib/api/ip-patents";

const label = (value: string) => value.replaceAll("_", " ");

export function PatentFamilyLifecycle({ family, canReview }: { family: PatentFamily; canReview: boolean }) {
  return <PatentRecordLifecycle record={family} canReview={canReview} />;
}

export function PatentRecordLifecycle({ record: family, canReview }: {
  record: PatentFamily | PatentApplication; canReview: boolean;
}) {
  const queryClient = useQueryClient();
  const isFamily = family.record_kind === "patent_family";
  const recordKey = isFamily ? "patent-family" : "patent-application";
  const [cursor, setCursor] = useState<number>();
  const [target, setTarget] = useState<"closed" | "abandoned" | "retired">("closed");
  const [effectiveAt, setEffectiveAt] = useState(() => {
    const now = new Date();
    return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
  });
  const [reason, setReason] = useState("");
  const [outcome, setOutcome] = useState("");
  const [evidence, setEvidence] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [acknowledged, setAcknowledged] = useState<string[]>([]);
  const history = useQuery({
    queryKey: ["ip", recordKey, family.id, "lifecycle-history", cursor],
    queryFn: ({ signal }) => isFamily ? fetchPatentFamilyLifecycleHistory(family.id, cursor, signal)
      : fetchPatentApplicationLifecycleHistory(family.id, cursor, signal),
  });
  const date = new Date(effectiveAt);
  const input: IpLifecycleInput = {
    lifecycleVersion: family.lifecycle_version, toStatus: family.is_active ? target : "ready",
    effectiveAt: Number.isNaN(date.getTime()) ? "" : date.toISOString(),
    reason: reason.trim(), outcome: outcome.trim(), evidenceRef: evidence.trim(),
    linkedMatterHandling: "reviewed",
  };
  const preview = useMutation({
    mutationFn: async (snapshot: IpLifecycleInput) => ({
      input: snapshot, result: await previewIpDocketLifecycle(family.docket_id, snapshot),
    }),
    onMutate: () => { setConfirmed(false); setAcknowledged([]); },
  });
  const reviewed = preview.data && JSON.stringify(preview.data.input) === JSON.stringify(input)
    && preview.data.result.expected_lifecycle_version === family.lifecycle_version
    && preview.data.result.from_status === family.lifecycle_status
    ? preview.data : undefined;
  const apply = useMutation({
    mutationFn: (snapshot: IpLifecycleInput) => transitionIpDocketLifecycle(family.docket_id, snapshot),
    onSuccess: async (result) => {
      const familyKey = ["ip", recordKey, family.id];
      await queryClient.cancelQueries({ queryKey: familyKey, exact: true });
      queryClient.setQueryData<PatentFamily | PatentApplication>(familyKey, (saved) => ({
        ...(saved ?? family), lifecycle_status: result.status,
        lifecycle_version: result.lifecycle_version, is_active: result.is_active,
      }));
      preview.reset(); setConfirmed(false); setAcknowledged([]); setCursor(undefined);
      setReason(""); setOutcome(""); setEvidence("");
      await queryClient.invalidateQueries({ queryKey: familyKey });
      await queryClient.invalidateQueries({ queryKey: ["ip", isFamily ? "patent-families" : "patent-applications"] });
    },
  });
  const busy = preview.isPending || apply.isPending;
  return <section className="min-w-0 space-y-5 border-t border-line pt-4" aria-label={isFamily ? "Family lifecycle" : "Application lifecycle"}>
    <h2 className="text-lg font-semibold">Lifecycle</h2>
    <p className="text-sm capitalize">{label(family.lifecycle_status)} · Lifecycle version {family.lifecycle_version}</p>
    {canReview && <form className="min-w-0 space-y-4" aria-label={isFamily ? "Family lifecycle command" : "Application lifecycle command"} onSubmit={(event) => {
      event.preventDefault(); apply.reset(); preview.mutate(input);
    }} onChange={() => { setConfirmed(false); setAcknowledged([]); }}>
      <fieldset disabled={busy} className="min-w-0 space-y-4">
        <div className="grid min-w-0 gap-4 sm:grid-cols-2">
          <div><Label htmlFor="patent-lifecycle-target">New status</Label>
            {family.is_active ? <select id="patent-lifecycle-target" className="h-10 w-full min-w-0 rounded-sm border border-line bg-surface px-3 text-sm" value={target}
              onChange={(event) => setTarget(event.target.value as typeof target)}>
              <option value="closed">Closed</option><option value="abandoned">Abandoned</option><option value="retired">Retired</option>
            </select> : <Input id="patent-lifecycle-target" value="Ready (explicit reopening)" readOnly />}
          </div>
          <div><Label htmlFor="patent-lifecycle-date">Effective date and time</Label>
            <Input id="patent-lifecycle-date" type="datetime-local" required value={effectiveAt} onChange={(event) => setEffectiveAt(event.target.value)} /></div>
        </div>
        <div><Label htmlFor="patent-lifecycle-reason">Reason</Label><Textarea id="patent-lifecycle-reason" required minLength={5} maxLength={2000} value={reason} onChange={(event) => setReason(event.target.value)} /></div>
        <div><Label htmlFor="patent-lifecycle-outcome">Outcome</Label><Input id="patent-lifecycle-outcome" required minLength={2} maxLength={120} value={outcome} onChange={(event) => setOutcome(event.target.value)} /></div>
        <div><Label htmlFor="patent-lifecycle-evidence">Instruction or evidence reference</Label><Input id="patent-lifecycle-evidence" required minLength={2} maxLength={512} value={evidence} onChange={(event) => setEvidence(event.target.value)} /></div>
        <Button type="submit" variant="secondary"><Eye size={16} />{preview.isPending ? "Checking impacts..." : "Preview lifecycle change"}</Button>
      </fieldset>
    </form>}
    {preview.isError && <p role="alert" className="break-words text-sm text-danger-500">{apiErrorMessage(preview.error, "Lifecycle preview failed.")}</p>}
    {reviewed && canReview && <div className="min-w-0 space-y-3 border-y border-line py-4" aria-label="Lifecycle impact review">
      <p className="capitalize">{label(reviewed.result.from_status)} to {label(reviewed.result.to_status)}</p>
      {reviewed.result.reopen_without_child_resurrection && <p className="text-sm">Previously cancelled tasks, hearings and deadlines remain cancelled.</p>}
      {reviewed.result.impacts.length ? <ul className="space-y-2 text-sm">
        {reviewed.result.impacts.map((impact, index) => <li key={`${impact.record_id}:${index}`} className="break-words">
          {label(impact.impact_kind)}: {label(impact.current_state)} to {label(impact.proposed_outcome)}
        </li>)}
      </ul> : <p className="text-sm text-mute">No linked operational items are affected.</p>}
      {reviewed.result.blocker_codes.map((code) => <label key={code} className="flex items-start gap-2 text-sm">
        <input type="checkbox" disabled={busy} checked={acknowledged.includes(code)} onChange={(event) => {
          setConfirmed(false); setAcknowledged((old) => event.target.checked ? [...old, code] : old.filter((item) => item !== code));
        }} /><span className="min-w-0 break-words">Reviewed exception: {label(code)}</span>
      </label>)}
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" disabled={busy} checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
        <span className="min-w-0">I confirm this lifecycle change and its recorded impacts.</span></label>
      <Button disabled={busy || !confirmed || reviewed.result.blocker_codes.some((code) => !acknowledged.includes(code))}
        onClick={() => apply.mutate({ ...reviewed.input, acknowledgedExceptionCodes: acknowledged })}>
        <Check size={16} />{apply.isPending ? "Saving lifecycle..." : "Confirm lifecycle change"}
      </Button>
    </div>}
    {apply.isError && <p role="alert" className="break-words text-sm text-danger-500">{apiErrorMessage(apply.error, "Lifecycle change failed. Reload the record before trying again.")}</p>}
    <h3 className="font-semibold">Lifecycle history</h3>
    {history.isPending ? <Skeleton className="h-24 w-full" /> : history.isError
      ? <QueryErrorState title="Could not load lifecycle history" error={history.error} onRetry={history.refetch} />
      : <>
        <ol className="divide-y divide-line" aria-label="Lifecycle events">
          {history.data.events.map((event) => <li key={event.id} className="min-w-0 space-y-1 py-3 text-sm">
            <p className="font-medium capitalize">{label(event.from_status ?? "unknown")} to {label(event.to_status ?? "unknown")}</p>
            <p className="text-mute">Effective {new Date(event.effective_at).toLocaleString()} · Recorded {new Date(event.entered_at).toLocaleString()}</p>
            <p className="whitespace-pre-wrap break-words">{event.reason}</p>
            {event.evidence_refs.map((reference, index) => <p key={index} className="break-words">{reference}</p>)}
          </li>)}
        </ol>
        {!history.data.events.length && <p className="text-sm text-mute">No lifecycle changes on this page.</p>}
        <div className="flex flex-wrap justify-between gap-2">
          <Button variant="ghost" disabled={cursor === undefined} onClick={() => setCursor(undefined)}><ArrowLeft size={16} />Latest events</Button>
          <Button variant="ghost" disabled={!history.data.next_cursor} onClick={() => setCursor(history.data.next_cursor ?? undefined)}>Older events<ArrowRight size={16} /></Button>
        </div>
      </>}
  </section>;
}
