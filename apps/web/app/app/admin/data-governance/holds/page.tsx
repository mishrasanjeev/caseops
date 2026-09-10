"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, ChevronLeft, ChevronRight, LockKeyhole, Plus, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { apiErrorMessage } from "@/lib/api/config";
import { completeMfaStepUp, createTenantScopedDataOperationDryRun, fetchTenantDataClassCatalog } from "@/lib/api/endpoints";
import { activateLegalHold, approveHoldRelease, createLegalHold, listHoldReleaseRequests, listLegalHolds, requestHoldRelease, type LegalHold } from "@/lib/api/legal-holds";
import { useCapability } from "@/lib/capabilities";
import { useSession } from "@/lib/use-session";

const holdsKey = ["admin", "data-governance", "holds"];

export default function LegalHoldsPage() {
  const allowed = useCapability("legal_holds:manage");
  const canRequest = useCapability("audit:export");
  const { context } = useSession();
  const client = useQueryClient();
  const [title, setTitle] = useState("");
  const [authority, setAuthority] = useState("");
  const [classId, setClassId] = useState("");
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [code, setCode] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [holdPages, setHoldPages] = useState<(string | null)[]>([null]);
  const [proposalPages, setProposalPages] = useState<(string | null)[]>([null]);
  const [releaseReason, setReleaseReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const holdPageKey = [...holdsKey, "page", holdPages.at(-1)];
  const holds = useQuery({ queryKey: holdPageKey, queryFn: ({ signal }) => listLegalHolds(signal, holdPages.at(-1)), enabled: allowed });
  const catalog = useQuery({ queryKey: ["admin", "data-governance", "data-classes"], queryFn: fetchTenantDataClassCatalog, enabled: allowed && canRequest });
  const selected = holds.data?.holds.find((hold) => hold.id === selectedId);
  const proposals = useQuery({ queryKey: [...holdsKey, selectedId, "release-requests", proposalPages.at(-1)],
    queryFn: ({ signal }) => listHoldReleaseRequests(selectedId!, signal, proposalPages.at(-1)), enabled: allowed && selected?.status === "active" });
  const fail = (failure: unknown) => { setNotice(null); setError(apiErrorMessage(failure, "The preservation command could not be completed.")); };
  const saved = async (hold: LegalHold, created = false) => {
    await client.cancelQueries({ queryKey: holdsKey });
    const targetKey = created ? [...holdsKey, "page", null] : holdPageKey;
    client.setQueryData<Awaited<ReturnType<typeof listLegalHolds>>>(targetKey, (old) => ({
      holds: old?.holds.some((row) => row.id === hold.id)
        ? old.holds.map((row) => row.id === hold.id ? hold : row)
        : [hold, ...(old?.holds ?? [])].slice(0, 25),
      has_more: old?.has_more ?? false, next_before_id: old?.next_before_id ?? null,
    }));
    if (created) setHoldPages([null]);
    setProposalPages([null]);
    setSelectedId(hold.id);
    setError(null);
    await client.invalidateQueries({ queryKey: holdsKey });
  };
  const stepUp = useMutation({ mutationFn: () => completeMfaStepUp({ code, purpose: "legal_hold_change", method: "totp" }),
    onSuccess: () => { setCode(""); setError(null); setNotice("Identity verified for preservation changes."); }, onError: fail });
  const create = useMutation({ mutationFn: () => createLegalHold({ idempotency_key: key, title: title.trim(),
    authority_reference: authority.trim(), scope: classId === "__company__" ? "company" : "data_classes", data_class_ids: classId === "__company__" ? [] : [classId] }),
    onSuccess: async (hold) => { await saved(hold, true); setTitle(""); setAuthority(""); setKey(crypto.randomUUID()); setNotice("Preservation draft recorded."); }, onError: fail });
  const activate = useMutation({ mutationFn: activateLegalHold, onSuccess: async (hold) => { await saved(hold); setNotice("Preservation is active."); }, onError: fail });
  const request = useMutation({ mutationFn: async (hold: LegalHold) => {
    const manifest = await createTenantScopedDataOperationDryRun({ operationType: "tenant_offboarding", dataClassIds: hold.data_class_ids,
      requestEvidenceRef: releaseReason.trim() });
    return requestHoldRelease(hold, { idempotency_key: crypto.randomUUID(), dry_run_id: manifest.id, reason_reference: releaseReason.trim() });
  }, onSuccess: async () => { setError(null); setNotice("Release request recorded. Preservation remains active."); setReleaseReason(""); setProposalPages([null]);
    await client.invalidateQueries({ queryKey: [...holdsKey, selectedId, "release-requests"] }); }, onError: fail });
  const approve = useMutation({ mutationFn: (proposal: NonNullable<typeof proposals.data>["proposals"][number]) => approveHoldRelease(selected!, proposal),
    onSuccess: async (hold) => { await saved(hold); setNotice("Hold released. No records were deleted."); }, onError: fail });
  const busy = create.isPending || activate.isPending || request.isPending || approve.isPending;

  if (!allowed) return <p role="alert">Preservation administration access is required.</p>;
  return <div className="flex min-w-0 flex-col gap-6">
    <Link href="/app/admin" className="inline-flex items-center gap-2 text-sm"><ArrowLeft size={16} />Administration</Link>
    <PageHeader title="Legal holds" />
    {error && <p role="alert" className="break-words text-sm text-[var(--color-danger-700)]">{error}</p>}
    {notice && <p role="status" className="text-sm">{notice}</p>}
    <section className="border-b border-[var(--color-line)] pb-6" aria-labelledby="hold-step-up">
      <h2 id="hold-step-up" className="mb-3 text-lg font-semibold">Identity verification</h2>
      <form onSubmit={(event) => { event.preventDefault(); stepUp.mutate(); }} className="flex min-w-0 flex-wrap items-end gap-3">
        <div className="grid min-w-0 w-full gap-2 sm:w-56"><Label htmlFor="hold-code">Authenticator code</Label>
          <Input id="hold-code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(event) => setCode(event.target.value)} /></div>
        <Button type="submit" disabled={stepUp.isPending || !code.trim()}><LockKeyhole size={16} />Verify identity</Button>
        <Link className="text-sm underline" href="/account/security">Security settings</Link>
      </form>
    </section>
    {canRequest && <section aria-labelledby="new-hold" className="border-b border-[var(--color-line)] pb-6">
      <h2 id="new-hold" className="mb-3 text-lg font-semibold">New preservation request</h2>
      <form onSubmit={(event) => { event.preventDefault(); create.mutate(); }} className="grid min-w-0 gap-4 sm:grid-cols-2">
        <div className="grid min-w-0 gap-2"><Label htmlFor="hold-title">Title</Label><Input id="hold-title" value={title} maxLength={255} onChange={(event) => setTitle(event.target.value)} /></div>
        <div className="grid min-w-0 gap-2"><Label htmlFor="hold-authority">Authority reference</Label><Input id="hold-authority" value={authority} maxLength={512} onChange={(event) => setAuthority(event.target.value)} /></div>
        <div className="grid min-w-0 gap-2"><Label htmlFor="hold-scope">Preservation scope</Label>
          {catalog.isError ? <QueryErrorState title="Could not load preservation classes" error={catalog.error} onRetry={catalog.refetch} /> :
            <select id="hold-scope" className="h-10 min-w-0 w-full rounded-md border border-[var(--color-line)] bg-[var(--color-surface)] px-3 text-sm" value={classId} onChange={(event) => setClassId(event.target.value)}>
              <option value="">Choose scope</option><option value="__company__">Whole workspace (release unavailable)</option>{catalog.data?.data_classes.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>}
        </div>
        <div className="flex items-end"><Button disabled={busy || !classId || holds.isPending || holds.isError || catalog.isPending || catalog.isError || title.trim().length < 3 || authority.trim().length < 3} type="submit"><Plus size={16} />Record draft</Button></div>
      </form>
    </section>}
    <section aria-labelledby="preservation-register" className="min-w-0">
      <h2 id="preservation-register" className="mb-3 text-lg font-semibold">Preservation register</h2>
      {holds.isPending ? <Skeleton className="h-24 w-full" /> : holds.isError ? <QueryErrorState title="Could not load legal holds" error={holds.error} onRetry={holds.refetch} /> : <>
        {!holds.data.holds.length && <p className="text-sm">No preservation requests.</p>}
        <ul className="divide-y divide-[var(--color-line)]">{holds.data.holds.map((hold) => <li key={hold.id} className="flex min-w-0 flex-wrap items-center justify-between gap-3 py-3">
          <button type="button" disabled={busy} aria-label={`${hold.title}: ${hold.status}`} onClick={() => { setSelectedId(hold.id); setProposalPages([null]); setError(null); }} className="min-w-0 basis-64 grow text-left"><span className="block break-words font-medium">{hold.title}</span><span className="text-sm">{hold.status}</span></button>
          {hold.status === "draft" && <Button disabled={busy || !context || hold.created_by_membership_id === context?.membership.id} onClick={() => activate.mutate(hold)}><ShieldCheck size={16} />Approve preservation</Button>}
        </li>)}</ul>
      </>}
      <nav aria-label="Preservation register pages" className="mt-3 flex min-w-0 flex-wrap items-center gap-3">
        <Button title="Newer holds" aria-label="Newer holds" disabled={busy || holds.isFetching || holdPages.length === 1} onClick={() => { setHoldPages((pages) => pages.slice(0, -1)); setSelectedId(null); }}><ChevronLeft size={16} /></Button>
        <span className="text-sm">Page {holdPages.length}</span>
        <Button title="Older holds" aria-label="Older holds" disabled={busy || holds.isFetching || holds.isError || !holds.data?.next_before_id} onClick={() => { setHoldPages((pages) => [...pages, holds.data!.next_before_id]); setSelectedId(null); }}><ChevronRight size={16} /></Button>
      </nav>
    </section>
    {selected && <section aria-labelledby="hold-detail" className="min-w-0 border-t border-[var(--color-line)] pt-6">
      <h2 id="hold-detail" className="break-words text-lg font-semibold">{selected.title}</h2>
      <p className="mt-2 break-words text-sm">{selected.authority_reference}</p>
      <p className="mt-2 break-words text-sm">{selected.scope === "company" ? "Whole workspace" : selected.data_class_ids.map((id) => catalog.data?.data_classes.find((item) => item.id === id)?.label ?? id).join(", ")}</p>
      {selected.status === "active" && selected.scope === "company" && <p role="status" className="mt-4 text-sm">Release unavailable: the complete workspace data inventory is not certified.</p>}
      {selected.status === "active" && selected.scope === "data_classes" && <>
        {canRequest && <form onSubmit={(event) => { event.preventDefault(); request.mutate(selected); }} className="mt-4 flex min-w-0 flex-wrap items-end gap-3">
          <div className="grid min-w-0 w-full gap-2 sm:max-w-md"><Label htmlFor="release-authority">Release authority reference</Label><Input id="release-authority" value={releaseReason} maxLength={512} onChange={(event) => setReleaseReason(event.target.value)} /></div>
          <Button type="submit" disabled={busy || releaseReason.trim().length < 3}>Request release</Button>
        </form>}
        {proposals.isError ? <QueryErrorState title="Could not load release requests" error={proposals.error} onRetry={proposals.refetch} /> : proposals.data?.proposals.map((proposal) => <div key={proposal.id} className="mt-4 flex min-w-0 flex-wrap items-center gap-3">
          <p className="w-full break-words text-sm">{proposal.reason_reference}</p>
          <span className="text-sm">Expires {new Date(proposal.expires_at).toLocaleString()}</span>
          <Button disabled={busy || !context || proposal.requester_membership_id === context?.membership.id} onClick={() => approve.mutate(proposal)}><Check size={16} />Approve release</Button>
        </div>)}
        <nav aria-label="Release request pages" className="mt-3 flex min-w-0 flex-wrap items-center gap-3">
          <Button title="Newer release requests" aria-label="Newer release requests" disabled={busy || proposals.isFetching || proposalPages.length === 1} onClick={() => setProposalPages((pages) => pages.slice(0, -1))}><ChevronLeft size={16} /></Button>
          <span className="text-sm">Page {proposalPages.length}</span>
          <Button title="Older release requests" aria-label="Older release requests" disabled={busy || proposals.isFetching || proposals.isError || !proposals.data?.next_before_id} onClick={() => setProposalPages((pages) => [...pages, proposals.data!.next_before_id])}><ChevronRight size={16} /></Button>
        </nav>
      </>}
    </section>}
  </div>;
}
