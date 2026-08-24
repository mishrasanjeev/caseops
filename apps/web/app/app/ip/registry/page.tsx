"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowUpRight,
  Check,
  FileClock,
  Link2,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  Unlink,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  createIpRegistryLink,
  createIpTrackedCaseReference,
  decideIpRegistryMatch,
  decideIpTrackedCaseReference,
  fetchIpCoreRecords,
  fetchIpDockets,
  fetchIpRegistryWorkspaces,
  fetchIpTrackedCaseReferences,
  listCaseTrackingBookmarks,
  recordIpRegistryFailure,
  recordIpRegistryManualSnapshot,
  resolveIpRegistryDiff,
  type IpRegistryDiff,
  type IpRegistryWorkspace,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import { useSession } from "@/lib/use-session";

const STAMP = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

function stamp(value: string | null) {
  return value ? STAMP.format(new Date(value)) : "Never";
}

function jsonValue(value: unknown) {
  return JSON.stringify(value, null, 2);
}

function parseObject(value: string, label: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(`${label} must be valid JSON.`);
  }
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label} must be a JSON object.`);
  }
  return parsed as Record<string, unknown>;
}

function randomKey(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function statusTone(value: string) {
  if (["confirmed", "current", "succeeded", "no_change", "accepted", "active"].includes(value)) {
    return "success" as const;
  }
  if (["candidate", "pending", "mapped", "deferred", "stale"].includes(value)) {
    return "warning" as const;
  }
  return "neutral" as const;
}

export default function IpRegistryPage() {
  const canRead = useCapability("ip:read");
  const canSync = useCapability("ip:registry_sync");
  const session = useSession();
  const queryClient = useQueryClient();
  const [selectedDocketId, setSelectedDocketId] = useState("");
  const [selectedLinkId, setSelectedLinkId] = useState("");

  const dockets = useQuery({
    queryKey: ["ip", "dockets"],
    queryFn: fetchIpDockets,
    enabled: canRead,
  });
  const workspaces = useQuery({
    queryKey: ["ip", "registry", "workspaces"],
    queryFn: () => fetchIpRegistryWorkspaces(),
    enabled: canRead,
  });
  const core = useQuery({
    queryKey: ["ip", "core-records", selectedDocketId],
    queryFn: () => fetchIpCoreRecords(selectedDocketId),
    enabled: canRead && Boolean(selectedDocketId),
  });
  const references = useQuery({
    queryKey: ["ip", "tracked-case-references", selectedDocketId],
    queryFn: () => fetchIpTrackedCaseReferences(selectedDocketId),
    enabled: canRead && Boolean(selectedDocketId),
  });
  const bookmarks = useQuery({
    queryKey: ["case-tracking", "bookmarks"],
    queryFn: listCaseTrackingBookmarks,
    enabled: canRead,
  });

  useEffect(() => {
    if (!selectedDocketId && dockets.data?.dockets[0]) {
      setSelectedDocketId(dockets.data.dockets[0].id);
    }
  }, [dockets.data, selectedDocketId]);

  const visibleWorkspaces = useMemo(
    () =>
      (workspaces.data ?? []).filter(
        (workspace) => !selectedDocketId || workspace.link.docket_id === selectedDocketId,
      ),
    [selectedDocketId, workspaces.data],
  );

  useEffect(() => {
    if (!visibleWorkspaces.some((row) => row.link.id === selectedLinkId)) {
      setSelectedLinkId(visibleWorkspaces[0]?.link.id ?? "");
    }
  }, [selectedLinkId, visibleWorkspaces]);

  const selectedWorkspace =
    visibleWorkspaces.find((row) => row.link.id === selectedLinkId) ?? null;
  const selectedDocket = dockets.data?.dockets.find((row) => row.id === selectedDocketId) ?? null;

  async function refreshAll() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["ip", "registry"] }),
      queryClient.invalidateQueries({ queryKey: ["ip", "tracked-case-references"] }),
      queryClient.invalidateQueries({ queryKey: ["case-tracking", "bookmarks"] }),
    ]);
  }

  if (!canRead) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title="Registry reconciliation" />
        <EmptyState
          title="IP access required"
          description="Ask an owner or admin for the IP read capability."
        />
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        eyebrow="IP operations"
        title="Registry reconciliation"
        description="Match registry identities, preserve source snapshots, review changes, and reference court tracking."
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => refreshAll()}
            disabled={workspaces.isFetching}
          >
            <RefreshCw className={workspaces.isFetching ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
            Refresh
          </Button>
        }
      />

      {dockets.isPending || workspaces.isPending ? (
        <div className="grid gap-4 lg:grid-cols-3">
          <Skeleton className="h-48" />
          <Skeleton className="h-48 lg:col-span-2" />
        </div>
      ) : dockets.isError || workspaces.isError ? (
        <QueryErrorState
          error={dockets.error ?? workspaces.error}
          title="Could not load registry reconciliation"
          onRetry={() => refreshAll()}
        />
      ) : (
        <>
          <Card>
            <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <CardTitle as="h2">Docket scope</CardTitle>
                <p className="mt-1 text-sm text-[var(--color-mute)]">
                  Registry observations remain separate from accepted CaseOps legal state.
                </p>
              </div>
              <div className="w-full sm:max-w-md">
                <Label className="sr-only" htmlFor="registry-docket">IP docket</Label>
                <select
                  id="registry-docket"
                  className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                  value={selectedDocketId}
                  onChange={(event) => setSelectedDocketId(event.target.value)}
                >
                  <option value="">Select an IP docket</option>
                  {(dockets.data?.dockets ?? []).map((docket) => (
                    <option key={docket.id} value={docket.id}>
                      {docket.title} · {docket.primary_identifier ?? "No primary identifier"}
                    </option>
                  ))}
                </select>
              </div>
            </CardHeader>
            <CardContent>
              {selectedDocket ? (
                <div className="grid gap-4 text-sm sm:grid-cols-3">
                  <div><span className="text-[var(--color-mute)]">Record</span><strong className="mt-1 block">{selectedDocket.title}</strong></div>
                  <div><span className="text-[var(--color-mute)]">Matter</span><strong className="mt-1 block">{selectedDocket.matter_id ? "Linked" : "Not linked"}</strong></div>
                  <div><span className="text-[var(--color-mute)]">Registry identities</span><strong className="mt-1 block tabular-nums">{visibleWorkspaces.length}</strong></div>
                </div>
              ) : (
                <p className="text-sm text-[var(--color-mute)]">Select a docket to begin.</p>
              )}
            </CardContent>
          </Card>

          {selectedDocketId && canSync ? (
            <CreateRegistryLink
              docketId={selectedDocketId}
              records={core.data ?? null}
              pending={core.isPending}
              onCreated={async (linkId) => {
                await refreshAll();
                setSelectedLinkId(linkId);
              }}
            />
          ) : null}

          <div className="grid min-w-0 gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
            <Card className="min-w-0">
              <CardHeader><CardTitle as="h2">Registry identities</CardTitle></CardHeader>
              <CardContent className="p-0">
                {visibleWorkspaces.length === 0 ? (
                  <div className="p-6 text-sm text-[var(--color-mute)]">No registry identity is linked to this docket.</div>
                ) : (
                  <div className="divide-y divide-[var(--color-line)]">
                    {visibleWorkspaces.map((workspace) => (
                      <button
                        key={workspace.link.id}
                        className={workspace.link.id === selectedLinkId ? "w-full bg-[var(--color-brand-50)] px-5 py-4 text-left" : "w-full px-5 py-4 text-left hover:bg-[var(--color-bg-2)]"}
                        onClick={() => setSelectedLinkId(workspace.link.id)}
                      >
                        <span className="block break-words font-semibold">{workspace.link.raw_identifier}</span>
                        <span className="mt-2 flex flex-wrap gap-2">
                          <Badge tone={statusTone(workspace.link.match_status)}>{workspace.link.match_status}</Badge>
                          <Badge tone={statusTone(workspace.link.freshness_status)}>{workspace.link.freshness_status}</Badge>
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {selectedWorkspace ? (
              <RegistryWorkspace
                workspace={selectedWorkspace}
                canSync={canSync}
                membershipId={session.context?.membership.id ?? null}
                onChanged={refreshAll}
              />
            ) : (
              <Card><CardContent className="py-12"><EmptyState title="Select a registry identity" description="Choose an identity to inspect its evidence and reconciliation queue." /></CardContent></Card>
            )}
          </div>

          {selectedDocketId ? (
            <CourtReferences
              docket={selectedDocket}
              proceedings={core.data?.proceedings ?? []}
              references={references.data ?? []}
              bookmarks={bookmarks.data?.bookmarks ?? []}
              canSync={canSync}
              onChanged={refreshAll}
            />
          ) : null}
        </>
      )}
    </div>
  );
}

function CreateRegistryLink({
  docketId,
  records,
  pending,
  onCreated,
}: {
  docketId: string;
  records: Awaited<ReturnType<typeof fetchIpCoreRecords>> | null;
  pending: boolean;
  onCreated: (linkId: string) => Promise<void>;
}) {
  const [target, setTarget] = useState("");
  const [office, setOffice] = useState("IP India");
  const [jurisdiction, setJurisdiction] = useState("IN");
  const [kind, setKind] = useState("application");
  const [identifier, setIdentifier] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [confidence, setConfidence] = useState("0.95");

  useEffect(() => {
    const first = records?.applications[0];
    if (!target && first) setTarget(`application:${first.id}`);
  }, [records, target]);

  const create = useMutation({
    mutationFn: async () => {
      const [targetKind, targetId] = target.split(":");
      if (!targetId) throw new Error("Select an application or proceeding.");
      return createIpRegistryLink({
        docketId,
        applicationId: targetKind === "application" ? targetId : null,
        proceedingId: targetKind === "proceeding" ? targetId : null,
        office,
        jurisdiction,
        identifierKind: kind,
        rawIdentifier: identifier,
        sourceUrl,
        matchConfidence: Number(confidence),
        matchEvidence: { capture: "manual", identifier, office, jurisdiction },
      });
    },
    onSuccess: async (link) => {
      toast.success("Registry identity added for match review.");
      setIdentifier("");
      setSourceUrl("");
      await onCreated(link.id);
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not add registry identity.")),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2">Add registry identity</CardTitle>
        <p className="text-sm text-[var(--color-mute)]">Manual evidence intake only. No provider call is made.</p>
      </CardHeader>
      <CardContent>
        <form className="grid gap-4 md:grid-cols-2 xl:grid-cols-6" onSubmit={submit}>
          <div className="xl:col-span-2"><Label htmlFor="registry-target">Legal record</Label><select id="registry-target" className="mt-1 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={target} onChange={(event) => setTarget(event.target.value)} disabled={pending}><option value="">Select record</option>{records?.applications.map((row) => <option value={`application:${row.id}`} key={row.id}>Application · {row.office} · {row.filing_phase}</option>)}{records?.proceedings.map((row) => <option value={`proceeding:${row.id}`} key={row.id}>Proceeding · {row.proceeding_kind} · {row.stage}</option>)}</select></div>
          <div><Label htmlFor="registry-kind">Identifier type</Label><Input id="registry-kind" className="mt-1" value={kind} onChange={(event) => setKind(event.target.value)} required /></div>
          <div><Label htmlFor="registry-identifier">Identifier</Label><Input id="registry-identifier" className="mt-1" value={identifier} onChange={(event) => setIdentifier(event.target.value)} required /></div>
          <div><Label htmlFor="registry-office">Office</Label><Input id="registry-office" className="mt-1" value={office} onChange={(event) => setOffice(event.target.value)} required /></div>
          <div><Label htmlFor="registry-jurisdiction">Jurisdiction</Label><Input id="registry-jurisdiction" className="mt-1" value={jurisdiction} onChange={(event) => setJurisdiction(event.target.value)} required /></div>
          <div className="md:col-span-2 xl:col-span-4"><Label htmlFor="registry-source">Official source URL</Label><Input id="registry-source" type="url" className="mt-1" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} required /></div>
          <div><Label htmlFor="registry-confidence">Match confidence</Label><Input id="registry-confidence" type="number" min="0" max="1" step="0.01" className="mt-1" value={confidence} onChange={(event) => setConfidence(event.target.value)} required /></div>
          <div className="flex items-end"><Button className="w-full" disabled={create.isPending}>{create.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />}Add identity</Button></div>
        </form>
      </CardContent>
    </Card>
  );
}

function RegistryWorkspace({
  workspace,
  canSync,
  membershipId,
  onChanged,
}: {
  workspace: IpRegistryWorkspace;
  canSync: boolean;
  membershipId: string | null;
  onChanged: () => Promise<void>;
}) {
  const { link } = workspace;
  const [matchReason, setMatchReason] = useState("");
  const [raw, setRaw] = useState('{\n  "register_record": {}\n}');
  const [normalized, setNormalized] = useState(jsonValue(link.accepted_state_json));
  const [snapshotSource, setSnapshotSource] = useState(link.source_url);
  const [parserVersion, setParserVersion] = useState("manual-normalizer-v1");
  const [supersedes, setSupersedes] = useState("");
  const [correctionReason, setCorrectionReason] = useState("");
  const [failureClass, setFailureClass] = useState<"authentication" | "rate_limit" | "parse_error" | "provider_outage" | "configuration" | "policy" | "unknown">("parse_error");
  const [failureMessage, setFailureMessage] = useState("");
  const [reviewReason, setReviewReason] = useState("");
  const [mappedPath, setMappedPath] = useState("");

  useEffect(() => {
    setNormalized(jsonValue(link.accepted_state_json));
    setSnapshotSource(link.source_url);
  }, [link.accepted_state_json, link.source_url]);

  const decideMatch = useMutation({
    mutationFn: (decision: "confirm" | "mismatch" | "retire") =>
      decideIpRegistryMatch({ linkId: link.id, expectedVersion: link.version, decision, reason: matchReason }),
    onSuccess: async () => { toast.success("Registry match decision recorded."); setMatchReason(""); await onChanged(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not record the match decision.")),
  });
  const addSnapshot = useMutation({
    mutationFn: () => recordIpRegistryManualSnapshot({
      linkId: link.id,
      expectedLinkVersion: link.version,
      idempotencyKey: randomKey("manual-snapshot"),
      sourceUrl: snapshotSource,
      sourceRetrievedAt: new Date().toISOString(),
      parserVersion,
      attribution: { publisher: link.office, capture_method: "manual" },
      rawSnapshot: parseObject(raw, "Raw snapshot"),
      normalizedSnapshot: parseObject(normalized, "Normalized snapshot"),
      supersedesSnapshotId: supersedes || null,
      correctionReason: correctionReason || null,
    }),
    onSuccess: async (result) => { toast.success(result.no_change ? "No-change poll recorded." : `${result.diffs.length} registry change${result.diffs.length === 1 ? "" : "s"} queued.`); setSupersedes(""); setCorrectionReason(""); await onChanged(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not record the registry snapshot.")),
  });
  const addFailure = useMutation({
    mutationFn: () => recordIpRegistryFailure({ linkId: link.id, expectedLinkVersion: link.version, idempotencyKey: randomKey("manual-failure"), responseClass: failureClass, error: failureMessage, externalCall: false }),
    onSuccess: async () => { toast.success("Failure evidence recorded; accepted legal state was preserved."); setFailureMessage(""); await onChanged(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not record failure evidence.")),
  });
  const resolveDiff = useMutation({
    mutationFn: ({ diff, decision }: { diff: IpRegistryDiff; decision: "accept" | "reject" | "map" | "defer" }) => resolveIpRegistryDiff({
      diffId: diff.id,
      expectedVersion: diff.version,
      decision,
      reason: reviewReason,
      mappedFieldPath: decision === "map" ? mappedPath : null,
      effectiveAt: decision === "accept" ? new Date().toISOString() : null,
      responsibleMembershipId: decision === "accept" ? membershipId : null,
    }),
    onSuccess: async () => { toast.success("Registry field decision recorded."); setReviewReason(""); setMappedPath(""); await onChanged(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not resolve the registry change.")),
  });

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <Card>
        <CardHeader className="gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0"><CardTitle as="h2">{link.raw_identifier}</CardTitle><p className="mt-1 break-words text-sm text-[var(--color-mute)]">{link.office} · {link.jurisdiction} · {link.provider_key}</p></div>
          <a className="inline-flex items-center gap-2 text-sm font-semibold text-[var(--color-brand-700)] hover:underline" href={link.source_url} target="_blank" rel="noreferrer">Open source <ArrowUpRight className="h-4 w-4" /></a>
        </CardHeader>
        <CardContent className="grid gap-4 text-sm sm:grid-cols-2 xl:grid-cols-4">
          <div><span className="text-[var(--color-mute)]">Match</span><div className="mt-1"><Badge tone={statusTone(link.match_status)}>{link.match_status}</Badge></div></div>
          <div><span className="text-[var(--color-mute)]">Freshness</span><div className="mt-1"><Badge tone={statusTone(link.freshness_status)}>{link.freshness_status}</Badge></div></div>
          <div><span className="text-[var(--color-mute)]">Last success</span><strong className="mt-1 block">{stamp(link.last_successful_at)}</strong></div>
          <div><span className="text-[var(--color-mute)]">Confidence</span><strong className="mt-1 block tabular-nums">{Number(link.match_confidence).toLocaleString("en-IN", { style: "percent", maximumFractionDigits: 1 })}</strong></div>
          {link.last_error_redacted ? <div className="sm:col-span-2 xl:col-span-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-amber-900"><AlertTriangle className="mr-2 inline h-4 w-4" />{link.last_error_redacted}</div> : null}
        </CardContent>
      </Card>

      {canSync ? (
        <Card>
          <CardHeader><CardTitle as="h3">Match decision</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-3"><Label htmlFor="match-reason">Reason</Label><Input id="match-reason" value={matchReason} onChange={(event) => setMatchReason(event.target.value)} placeholder="Evidence supporting this decision" /><div className="flex flex-wrap gap-2"><Button size="sm" disabled={matchReason.trim().length < 5 || decideMatch.isPending} onClick={() => decideMatch.mutate("confirm")}><Check className="h-4 w-4" />Confirm</Button><Button size="sm" variant="outline" disabled={matchReason.trim().length < 5 || decideMatch.isPending} onClick={() => decideMatch.mutate("mismatch")}><Unlink className="h-4 w-4" />Mismatch</Button><Button size="sm" variant="ghost" disabled={matchReason.trim().length < 5 || decideMatch.isPending} onClick={() => decideMatch.mutate("retire")}>Retire</Button></div></CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader><CardTitle as="h3">Field reconciliation</CardTitle><p className="text-sm text-[var(--color-mute)]">High-risk proprietor, status, opposition, refusal, cancellation and deadline fields require IP approval.</p></CardHeader>
        <CardContent className="flex min-w-0 flex-col gap-4">
          {workspace.diffs.length === 0 ? <p className="text-sm text-[var(--color-mute)]">No field changes are awaiting or carrying a decision.</p> : <><div className="grid gap-3 sm:grid-cols-2"><div><Label htmlFor="review-reason">Decision reason</Label><Input id="review-reason" className="mt-1" value={reviewReason} onChange={(event) => setReviewReason(event.target.value)} /></div><div><Label htmlFor="mapped-path">Canonical mapped path</Label><Input id="mapped-path" className="mt-1" value={mappedPath} onChange={(event) => setMappedPath(event.target.value)} placeholder="/status" /></div></div><div className="overflow-x-auto"><table className="w-full min-w-[920px] border-collapse text-left text-sm"><thead><tr className="border-b border-[var(--color-line)] text-xs uppercase text-[var(--color-mute)]"><th className="px-3 py-2">Field</th><th className="px-3 py-2">Change</th><th className="px-3 py-2">Before</th><th className="px-3 py-2">After</th><th className="px-3 py-2">Risk</th><th className="px-3 py-2">Decision</th><th className="px-3 py-2">Actions</th></tr></thead><tbody>{workspace.diffs.map((diff) => <tr className="border-b border-[var(--color-line)] align-top" key={diff.id}><td className="px-3 py-3 font-mono text-xs">{diff.field_path}</td><td className="px-3 py-3"><Badge tone="neutral">{diff.change_kind}</Badge></td><td className="max-w-48 break-words px-3 py-3 font-mono text-xs">{jsonValue(diff.before_value_json)}</td><td className="max-w-48 break-words px-3 py-3 font-mono text-xs">{jsonValue(diff.after_value_json)}</td><td className="px-3 py-3"><Badge tone={diff.risk_level === "high" ? "warning" : "neutral"}>{diff.risk_level}</Badge>{diff.deadline_recalculation_state === "required" ? <div className="mt-2 text-xs text-amber-800">Deadline review required</div> : null}</td><td className="px-3 py-3"><Badge tone={statusTone(diff.resolution_status)}>{diff.resolution_status}</Badge>{diff.emitted_event_id ? <div className="mt-2 text-xs text-[var(--color-mute)]">Event recorded</div> : null}</td><td className="px-3 py-3"><div className="flex flex-wrap gap-1">{canSync && !["accepted", "rejected"].includes(diff.resolution_status) ? <><Button size="sm" disabled={!membershipId || reviewReason.trim().length < 5 || resolveDiff.isPending} onClick={() => resolveDiff.mutate({ diff, decision: "accept" })}>Accept</Button><Button size="sm" variant="outline" disabled={reviewReason.trim().length < 5 || resolveDiff.isPending} onClick={() => resolveDiff.mutate({ diff, decision: "reject" })}>Reject</Button><Button size="sm" variant="outline" disabled={reviewReason.trim().length < 5 || !mappedPath.startsWith("/") || resolveDiff.isPending} onClick={() => resolveDiff.mutate({ diff, decision: "map" })}>Map</Button><Button size="sm" variant="ghost" disabled={reviewReason.trim().length < 5 || resolveDiff.isPending} onClick={() => resolveDiff.mutate({ diff, decision: "defer" })}>Defer</Button></> : null}</div></td></tr>)}</tbody></table></div></>}
        </CardContent>
      </Card>

      {canSync ? (
        <Card>
          <CardHeader><CardTitle as="h3">Record source snapshot</CardTitle><p className="text-sm text-[var(--color-mute)]">Both source and normalized JSON are stored as immutable evidence. Corrections supersede; they never overwrite.</p></CardHeader>
          <CardContent className="grid gap-4 lg:grid-cols-2"><div><Label htmlFor="raw-snapshot">Raw source JSON</Label><Textarea id="raw-snapshot" className="mt-1 min-h-56 font-mono text-xs" value={raw} onChange={(event) => setRaw(event.target.value)} /></div><div><Label htmlFor="normalized-snapshot">Normalized register JSON</Label><Textarea id="normalized-snapshot" className="mt-1 min-h-56 font-mono text-xs" value={normalized} onChange={(event) => setNormalized(event.target.value)} /></div><div className="lg:col-span-2"><Label htmlFor="snapshot-source">Source URL</Label><Input id="snapshot-source" type="url" className="mt-1" value={snapshotSource} onChange={(event) => setSnapshotSource(event.target.value)} /></div><div><Label htmlFor="parser-version">Parser version</Label><Input id="parser-version" className="mt-1" value={parserVersion} onChange={(event) => setParserVersion(event.target.value)} /></div><div><Label htmlFor="supersedes-snapshot">Corrects snapshot</Label><select id="supersedes-snapshot" className="mt-1 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={supersedes} onChange={(event) => setSupersedes(event.target.value)}><option value="">No correction</option>{workspace.snapshots.map((snapshot) => <option value={snapshot.id} key={snapshot.id}>{stamp(snapshot.source_retrieved_at)} · {snapshot.normalized_sha256.slice(0, 10)}</option>)}</select></div>{supersedes ? <div className="lg:col-span-2"><Label htmlFor="correction-reason">Correction reason</Label><Input id="correction-reason" className="mt-1" value={correctionReason} onChange={(event) => setCorrectionReason(event.target.value)} /></div> : null}<div className="lg:col-span-2"><Button disabled={addSnapshot.isPending || link.match_status !== "confirmed" || (Boolean(supersedes) !== Boolean(correctionReason.trim()))} onClick={() => addSnapshot.mutate()}>{addSnapshot.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}Record immutable snapshot</Button>{link.match_status !== "confirmed" ? <p className="mt-2 text-xs text-amber-800">Confirm the registry match before recording source evidence.</p> : null}</div></CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader><CardTitle as="h3">Evidence history</CardTitle></CardHeader>
        <CardContent className="grid gap-4 lg:grid-cols-2"><div><h4 className="text-sm font-semibold">Snapshots</h4><div className="mt-3 divide-y divide-[var(--color-line)] border-y border-[var(--color-line)]">{workspace.snapshots.length ? workspace.snapshots.map((snapshot) => <div className="py-3 text-sm" key={snapshot.id}><div className="flex items-center justify-between gap-2"><strong>{stamp(snapshot.source_retrieved_at)}</strong><a href={snapshot.source_url} target="_blank" rel="noreferrer" className="text-[var(--color-brand-700)]" aria-label="Open snapshot source"><ArrowUpRight className="h-4 w-4" /></a></div><div className="mt-1 break-all font-mono text-xs text-[var(--color-mute)]">{snapshot.normalized_sha256}</div>{snapshot.supersedes_snapshot_id ? <div className="mt-2 text-xs">Correction of {snapshot.supersedes_snapshot_id.slice(0, 8)} · {snapshot.correction_reason}</div> : null}</div>) : <p className="py-3 text-sm text-[var(--color-mute)]">No snapshots recorded.</p>}</div></div><div><h4 className="text-sm font-semibold">Attempts</h4><div className="mt-3 divide-y divide-[var(--color-line)] border-y border-[var(--color-line)]">{workspace.attempts.length ? workspace.attempts.map((attempt) => <div className="py-3 text-sm" key={attempt.id}><div className="flex items-center justify-between gap-2"><span><Badge tone={statusTone(attempt.status)}>{attempt.status}</Badge> <span className="ml-2">{attempt.operation_kind}</span></span><span className="text-xs text-[var(--color-mute)]">{stamp(attempt.started_at)}</span></div><div className="mt-2 text-xs text-[var(--color-mute)]">{attempt.external_call ? "External call" : "No external call"} · {attempt.response_class}</div>{attempt.error_redacted ? <div className="mt-2 text-xs text-amber-800">{attempt.error_redacted}</div> : null}</div>) : <p className="py-3 text-sm text-[var(--color-mute)]">No attempts recorded.</p>}</div></div></CardContent>
      </Card>

      {canSync ? (
        <Card>
          <CardHeader><CardTitle as="h3">Record failed attempt</CardTitle><p className="text-sm text-[var(--color-mute)]">Failure evidence updates freshness and history without changing accepted legal state.</p></CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-[220px_minmax(0,1fr)_auto]"><div><Label htmlFor="failure-class">Failure class</Label><select id="failure-class" className="mt-1 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={failureClass} onChange={(event) => setFailureClass(event.target.value as typeof failureClass)}>{["authentication", "rate_limit", "parse_error", "provider_outage", "configuration", "policy", "unknown"].map((value) => <option value={value} key={value}>{value.replaceAll("_", " ")}</option>)}</select></div><div><Label htmlFor="failure-message">Redactable operator detail</Label><Input id="failure-message" className="mt-1" value={failureMessage} onChange={(event) => setFailureMessage(event.target.value)} /></div><div className="flex items-end"><Button variant="outline" disabled={failureMessage.trim().length < 2 || addFailure.isPending} onClick={() => addFailure.mutate()}><FileClock className="h-4 w-4" />Record failure</Button></div></CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function CourtReferences({ docket, proceedings, references, bookmarks, canSync, onChanged }: { docket: Awaited<ReturnType<typeof fetchIpDockets>>["dockets"][number] | null; proceedings: Awaited<ReturnType<typeof fetchIpCoreRecords>>["proceedings"]; references: Awaited<ReturnType<typeof fetchIpTrackedCaseReferences>>; bookmarks: Awaited<ReturnType<typeof listCaseTrackingBookmarks>>["bookmarks"]; canSync: boolean; onChanged: () => Promise<void> }) {
  const [proceedingId, setProceedingId] = useState("");
  const [trackedCaseId, setTrackedCaseId] = useState("");
  const [purpose, setPurpose] = useState("Opposition or appeal tracking");
  const [evidence, setEvidence] = useState("");
  const [reason, setReason] = useState("");
  const eligible = bookmarks.filter((row) => Boolean(docket?.matter_id) && row.matter_id === docket?.matter_id);
  useEffect(() => { if (!proceedingId && proceedings[0]) setProceedingId(proceedings[0].id); }, [proceedingId, proceedings]);
  useEffect(() => { if (!trackedCaseId && eligible[0]) setTrackedCaseId(eligible[0].tracked_case_id); }, [eligible, trackedCaseId]);
  const create = useMutation({ mutationFn: () => createIpTrackedCaseReference({ docketId: docket?.id ?? "", proceedingId, trackedCaseId, purpose, evidenceReference: evidence }), onSuccess: async () => { toast.success("Canonical court tracking reference added."); setEvidence(""); await onChanged(); }, onError: (error) => toast.error(apiErrorMessage(error, "Could not add the court reference.")) });
  const decide = useMutation({ mutationFn: ({ id, version, decision }: { id: string; version: number; decision: "confirm" | "mismatch" | "retire" }) => decideIpTrackedCaseReference({ linkId: id, expectedVersion: version, decision, reason }), onSuccess: async () => { toast.success("Court reference decision recorded."); setReason(""); await onChanged(); }, onError: (error) => toast.error(apiErrorMessage(error, "Could not update the court reference.")) });
  return <Card><CardHeader><CardTitle as="h2">Court proceeding references</CardTitle><p className="text-sm text-[var(--color-mute)]">References reuse canonical TrackedCase and Matter bookmark data; court updates are never copied into the IP record.</p></CardHeader><CardContent className="flex flex-col gap-5">{references.length ? <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-sm"><thead><tr className="border-b border-[var(--color-line)] text-xs uppercase text-[var(--color-mute)]"><th className="px-3 py-2">Case</th><th className="px-3 py-2">Court</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Updates</th><th className="px-3 py-2">Reference</th></tr></thead><tbody>{references.map((row) => <tr className="border-b border-[var(--color-line)]" key={row.id}><td className="px-3 py-3"><strong>{row.case_title}</strong><div className="mt-1 text-xs text-[var(--color-mute)]">{row.cnr_number ?? row.case_number ?? "No court identifier"}</div></td><td className="px-3 py-3">{row.court_name ?? "Not recorded"}</td><td className="px-3 py-3"><Badge tone={statusTone(row.link_status)}>{row.link_status}</Badge></td><td className="px-3 py-3 tabular-nums">{row.update_count}</td><td className="px-3 py-3">{canSync ? <div className="flex gap-1"><Button size="sm" variant="outline" disabled={reason.trim().length < 5 || decide.isPending} onClick={() => decide.mutate({ id: row.id, version: row.version, decision: "mismatch" })}>Mismatch</Button><Button size="sm" variant="ghost" disabled={reason.trim().length < 5 || decide.isPending} onClick={() => decide.mutate({ id: row.id, version: row.version, decision: "retire" })}>Retire</Button></div> : null}</td></tr>)}</tbody></table></div> : <p className="text-sm text-[var(--color-mute)]">No court tracking references are attached to this IP docket.</p>}{canSync ? <><div><Label htmlFor="court-reference-reason">Decision reason</Label><Input id="court-reference-reason" className="mt-1" value={reason} onChange={(event) => setReason(event.target.value)} /></div>{!docket?.matter_id ? <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">Link this IP docket to a Matter before referencing court tracking.</div> : eligible.length === 0 ? <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">Bookmark a tracked court case to the linked Matter first.</div> : <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5"><div><Label htmlFor="court-proceeding">IP proceeding</Label><select id="court-proceeding" className="mt-1 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={proceedingId} onChange={(event) => setProceedingId(event.target.value)}>{proceedings.map((row) => <option value={row.id} key={row.id}>{row.proceeding_kind} · {row.stage}</option>)}</select></div><div><Label htmlFor="tracked-case">Matter tracked case</Label><select id="tracked-case" className="mt-1 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={trackedCaseId} onChange={(event) => setTrackedCaseId(event.target.value)}>{eligible.map((row) => <option value={row.tracked_case_id} key={row.id}>{row.tracked_case.case_title}</option>)}</select></div><div><Label htmlFor="court-purpose">Purpose</Label><Input id="court-purpose" className="mt-1" value={purpose} onChange={(event) => setPurpose(event.target.value)} /></div><div><Label htmlFor="court-evidence">Evidence reference</Label><Input id="court-evidence" className="mt-1" value={evidence} onChange={(event) => setEvidence(event.target.value)} /></div><div className="flex items-end"><Button className="w-full" disabled={!proceedingId || !trackedCaseId || purpose.trim().length < 3 || evidence.trim().length < 3 || create.isPending} onClick={() => create.mutate()}><Link2 className="h-4 w-4" />Add reference</Button></div></div>}</> : null}</CardContent></Card>;
}
