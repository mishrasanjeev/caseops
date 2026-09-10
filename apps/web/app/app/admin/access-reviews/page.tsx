"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, ChevronLeft, ChevronRight, LockKeyhole, Plus, Search, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { apiErrorMessage } from "@/lib/api/config";
import { completeMfaStepUp } from "@/lib/api/endpoints";
import { createAccessReview, decideAccessReview, fetchAccessReview, fetchReviewScope, finalizeAccessReview, listAccessReviews, listReviewTargets, type Campaign, type ReviewTarget, type ReviewTrigger } from "@/lib/api/access-reviews";
import { useCapability } from "@/lib/capabilities";
import { useSession } from "@/lib/use-session";

const key = ["access-reviews"];
const selectClass = "h-10 min-w-0 w-full rounded-md border border-[var(--color-line)] bg-[var(--color-surface)] px-3 text-sm";
const triggers: [ReviewTrigger, string][] = [["periodic", "Periodic review"], ["client_team_change", "Client team change"], ["ethical_wall_change", "Ethical wall change"], ["portal_inactivity", "Portal inactivity"], ["employee_change", "Employee change"], ["counsel_completion", "Counsel engagement ended"], ["incident", "Incident"]];

export default function AccessReviewsPage() {
  const allowed = useCapability("matter_access:manage");
  const { context } = useSession();
  const client = useQueryClient();
  const [kind, setKind] = useState<ReviewTarget>("ip_docket");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [targetPages, setTargetPages] = useState<(string | null)[]>([null]);
  const [pages, setPages] = useState<(string | null)[]>([null]);
  const [targetId, setTargetId] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [title, setTitle] = useState("");
  const [reason, setReason] = useState("");
  const [trigger, setTrigger] = useState<ReviewTrigger>("periodic");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const targets = useQuery({ queryKey: [...key, "targets", kind, query, targetPages.at(-1)], queryFn: ({ signal }) => listReviewTargets(kind, query, targetPages.at(-1) ?? null, signal), enabled: allowed });
  const scope = useQuery({ queryKey: [...key, "scope", kind, targetId], queryFn: ({ signal }) => fetchReviewScope(kind, targetId, signal), enabled: allowed && !!targetId });
  const register = useQuery({ queryKey: [...key, "register", pages.at(-1)], queryFn: ({ signal }) => listAccessReviews(pages.at(-1) ?? null, signal), enabled: allowed });
  const detail = useQuery({ queryKey: [...key, "detail", selectedId], queryFn: ({ signal }) => fetchAccessReview(selectedId, signal), enabled: allowed && !!selectedId });
  const fail = (value: unknown) => { setNotice(null); setError(apiErrorMessage(value, "The access review could not be saved.")); };
  const saved = async (campaign: Campaign) => {
    await client.cancelQueries({ queryKey: key });
    client.setQueryData([...key, "detail", campaign.id], campaign);
    setSelectedId(campaign.id); setError(null);
    await client.invalidateQueries({ queryKey: key });
  };
  const verify = useMutation({ mutationFn: () => completeMfaStepUp({ code, purpose: "record_access_change", method: "totp" }), onSuccess: () => { setCode(""); setError(null); setNotice("Identity verified for access changes."); }, onError: fail });
  const create = useMutation({ mutationFn: () => createAccessReview(scope.data!, title.trim(), reason.trim(), trigger), onSuccess: async (campaign) => { await saved(campaign); setPages([null]); setTitle(""); setReason(""); setNotice("Access review opened."); }, onError: fail });
  const decision = useMutation({ mutationFn: ({ grantId, outcome, note }: { grantId: string; outcome: "keep" | "revoke"; note: string }) => decideAccessReview(detail.data!, grantId, outcome, note), onSuccess: async (campaign) => { await saved(campaign); setNotice("Independent decision recorded."); }, onError: fail });
  const finalize = useMutation({ mutationFn: () => finalizeAccessReview(detail.data!), onSuccess: async (campaign) => { await saved(campaign); setNotice("Review finalized. Requested revocations applied."); }, onError: fail });
  const busy = create.isPending || decision.isPending || finalize.isPending;
  const campaign = detail.data;
  if (!allowed) return <p role="alert">Access administration is required.</p>;
  return <div className="flex min-w-0 flex-col gap-6">
    <Link href="/app/admin" className="inline-flex items-center gap-2 text-sm"><ArrowLeft size={16} />Administration</Link>
    <PageHeader title="Access reviews" />
    {error && <p role="alert" className="break-words text-sm text-[var(--color-danger-700)]">{error}</p>}
    {notice && <p role="status" className="text-sm">{notice}</p>}
    <section className="border-b border-[var(--color-line)] pb-5" aria-labelledby="review-identity">
      <h2 id="review-identity" className="mb-3 text-lg font-semibold">Identity verification</h2>
      <form className="flex min-w-0 flex-wrap items-end gap-3" onSubmit={(event) => { event.preventDefault(); verify.mutate(); }}>
        <div className="grid w-full min-w-0 gap-2 sm:w-56"><Label htmlFor="review-code">Authenticator code</Label><Input id="review-code" value={code} onChange={(event) => setCode(event.target.value)} inputMode="numeric" autoComplete="one-time-code" /></div>
        <Button disabled={verify.isPending || !code.trim()}><LockKeyhole size={16} />Verify identity</Button><Link href="/account/security" className="text-sm underline">Security settings</Link>
      </form>
    </section>
    <section className="min-w-0 border-b border-[var(--color-line)] pb-5" aria-labelledby="new-review">
      <h2 id="new-review" className="mb-3 text-lg font-semibold">New campaign</h2>
      <form className="mb-4 flex min-w-0 flex-wrap items-end gap-3" onSubmit={(event) => { event.preventDefault(); setQuery(search.trim()); setTargetPages([null]); setTargetId(""); }}>
        <div className="grid w-full min-w-0 gap-2 sm:w-44"><Label htmlFor="review-kind">Record type</Label><select id="review-kind" className={selectClass} value={kind} onChange={(event) => { setKind(event.target.value as ReviewTarget); setTargetId(""); setTargetPages([null]); }}><option value="ip_docket">IP docket</option><option value="matter">Matter</option></select></div>
        <div className="grid min-w-0 basis-56 grow gap-2"><Label htmlFor="review-search">Record title</Label><Input id="review-search" value={search} onChange={(event) => setSearch(event.target.value)} maxLength={100} /></div>
        <Button title="Find records" aria-label="Find records" type="submit"><Search size={16} /></Button>
      </form>
      {targets.isError ? <QueryErrorState title="Could not load review targets" error={targets.error} onRetry={targets.refetch} /> : <div className="grid gap-2"><Label htmlFor="review-target">Review target</Label><select id="review-target" className={selectClass} disabled={targets.isFetching || busy} value={targetId} onChange={(event) => setTargetId(event.target.value)}><option value="">Choose record</option>{targets.data?.targets.map((target) => <option key={target.id} value={target.id}>{target.title}</option>)}</select></div>}
      <nav aria-label="Review target pages" className="my-3 flex gap-3"><Button aria-label="Previous targets" title="Previous targets" disabled={targets.isFetching || targetPages.length === 1} onClick={() => { setTargetPages((old) => old.slice(0, -1)); setTargetId(""); }}><ChevronLeft size={16} /></Button><Button aria-label="Next targets" title="Next targets" disabled={targets.isFetching || !targets.data?.next_after_id} onClick={() => { setTargetPages((old) => [...old, targets.data!.next_after_id]); setTargetId(""); }}><ChevronRight size={16} /></Button></nav>
      {scope.isError && <QueryErrorState title="Could not load current grants" error={scope.error} onRetry={scope.refetch} />}
      {targetId && scope.data && <p className="mb-4 text-sm">{scope.data.grants.length} standing grants. Access version {scope.data.access_policy_version}.</p>}
      <form className="grid min-w-0 gap-4 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
        <div className="grid min-w-0 gap-2"><Label htmlFor="review-title">Campaign title</Label><Input id="review-title" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} /></div>
        <div className="grid min-w-0 gap-2"><Label htmlFor="review-trigger">Review trigger</Label><select id="review-trigger" className={selectClass} value={trigger} onChange={(event) => setTrigger(event.target.value as ReviewTrigger)}>{triggers.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
        <div className="grid min-w-0 gap-2"><Label htmlFor="review-reason">Reason or ticket</Label><Input id="review-reason" value={reason} onChange={(event) => setReason(event.target.value)} maxLength={1000} /></div>
        <div className="flex items-end"><Button disabled={busy || !targetId || scope.isFetching || scope.isError || !scope.data?.grants.length || register.isPending || register.isError || title.trim().length < 3 || reason.trim().length < 5}><Plus size={16} />Open campaign</Button></div>
      </form>
    </section>
    <section className="min-w-0" aria-labelledby="review-register"><h2 id="review-register" className="mb-3 text-lg font-semibold">Campaign register</h2>
      {register.isError ? <QueryErrorState title="Could not load access reviews" error={register.error} onRetry={register.refetch} /> : register.isPending ? <p role="status">Loading reviews...</p> : <ul className="divide-y divide-[var(--color-line)]">{register.data.campaigns.map((row) => <li key={row.id} className="min-w-0 py-3"><button className="w-full min-w-0 text-left" disabled={busy} onClick={() => { setSelectedId(row.id); setError(null); }}><span className="block break-words font-medium">{row.title}</span><span className="block break-words text-sm">{row.snapshot.target_title} / {row.status}</span></button></li>)}</ul>}
      <nav aria-label="Campaign pages" className="mt-3 flex items-center gap-3"><Button title="Newer campaigns" aria-label="Newer campaigns" disabled={busy || register.isFetching || pages.length === 1} onClick={() => setPages((old) => old.slice(0, -1))}><ChevronLeft size={16} /></Button><span className="text-sm">Page {pages.length}</span><Button title="Older campaigns" aria-label="Older campaigns" disabled={busy || register.isFetching || !register.data?.next_before_id} onClick={() => setPages((old) => [...old, register.data!.next_before_id])}><ChevronRight size={16} /></Button></nav>
    </section>
    {detail.isError && <QueryErrorState title="Could not load campaign" error={detail.error} onRetry={detail.refetch} />}
    {campaign && <section className="min-w-0 border-t border-[var(--color-line)] pt-5" aria-labelledby="review-detail"><h2 id="review-detail" className="break-words text-lg font-semibold">{campaign.title}</h2><p className="mt-2 break-words text-sm">{campaign.reason}</p><p className="mt-2 text-sm">Status: {campaign.status}. Version {campaign.version}.</p>
      <ul className="mt-4 divide-y divide-[var(--color-line)]">{campaign.snapshot.grants.map((grant) => {
        const recorded = campaign.decisions.find((row) => row.grant_id === grant.id);
        return <li key={grant.id} className="min-w-0 py-4"><p className="break-words font-medium">{grant.subject_label}</p><p className="break-words text-sm">{grant.subject_type} / {grant.reason ?? "No original reason"}</p><p className="text-sm">Expiry: {grant.expires_at ? new Date(grant.expires_at).toLocaleString() : "No expiry"}</p>
          {recorded ? <p className="mt-2 break-words text-sm">Decision: {recorded.decision}. {recorded.reason}</p> : <DecisionForm key={`${campaign.id}:${grant.id}`} disabled={busy || campaign.status !== "open" || campaign.creator_user_id === context?.user.id || (grant.subject_type === "membership" && grant.subject_id === context?.membership.id)} save={(outcome, note) => decision.mutate({ grantId: grant.id, outcome, note })} />}
        </li>;
      })}</ul>
      {campaign.status === "open" && <Button className="mt-4" disabled={busy || campaign.decisions.length !== campaign.snapshot.grants.length || campaign.decisions.some((row) => row.reviewer_user_id === context?.user.id)} onClick={() => finalize.mutate()}><ShieldCheck size={16} />Finalize review</Button>}
      {campaign.finalized_at && <p className="mt-4 text-sm">Finalized {new Date(campaign.finalized_at).toLocaleString()}</p>}
    </section>}
  </div>;
}

function DecisionForm({ disabled, save }: { disabled: boolean; save: (outcome: "keep" | "revoke", note: string) => void }) {
  const [outcome, setOutcome] = useState<"keep" | "revoke">("keep");
  const [note, setNote] = useState("");
  return <form className="mt-3 flex min-w-0 flex-wrap items-end gap-3" onSubmit={(event) => { event.preventDefault(); save(outcome, note.trim()); }}>
    <label className="grid w-full min-w-0 gap-2 text-sm sm:w-40">Decision<select aria-label="Decision" className={selectClass} value={outcome} disabled={disabled} onChange={(event) => setOutcome(event.target.value as "keep" | "revoke")}><option value="keep">Keep grant</option><option value="revoke">Revoke grant</option></select></label>
    <label className="grid min-w-0 basis-56 grow gap-2 text-sm">Decision reason<Input aria-label="Decision reason" value={note} disabled={disabled} maxLength={1000} onChange={(event) => setNote(event.target.value)} /></label>
    <Button disabled={disabled || note.trim().length < 5}><Check size={16} />Record decision</Button>
  </form>;
}
