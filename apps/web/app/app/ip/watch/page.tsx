"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  FileInput,
  LoaderCircle,
  Pause,
  Play,
  Radar,
  RefreshCw,
  Send,
} from "lucide-react";
import { useEffect, useState } from "react";
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
  createIpWatchHandoff,
  createIpWatchProfile,
  decideIpWatchHit,
  fetchIpCoreRecords,
  fetchIpDockets,
  fetchIpWatchWorkspace,
  ingestIpJournal,
  updateIpWatchProfileStatus,
  type IpJournalPublication,
  type IpWatchDisposition,
  type IpWatchHandoff,
  type IpWatchHit,
  type IpWatchProfile,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import { useSession } from "@/lib/use-session";

const DATE = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" });
const STAMP = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

type View = "profiles" | "ingest" | "hits" | "runs";

function csv(value: string) {
  return Array.from(new Set(value.split(",").map((item) => item.trim()).filter(Boolean)));
}

function classes(value: string) {
  return Array.from(new Set(csv(value).map(Number))).filter((item) => Number.isInteger(item));
}

function jsonObject(value: string, label: string): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(value);
    if (parsed && !Array.isArray(parsed) && typeof parsed === "object") {
      return parsed as Record<string, unknown>;
    }
  } catch {
    // The field-specific message below is more useful than JSON.parse output.
  }
  throw new Error(`${label} must be a JSON object.`);
}

function tone(value: string) {
  if (["active", "available", "succeeded", "relevant", "confirmed", "completed"].includes(value)) {
    return "success" as const;
  }
  if (
    ["paused", "paused_cost_quota", "unavailable", "stale", "reviewing", "pending"].includes(value)
  ) {
    return "warning" as const;
  }
  return "neutral" as const;
}

function localDate(value: string | null) {
  return value ? STAMP.format(new Date(value)) : "Not scheduled";
}

function randomKey() {
  return `journal-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function IpJournalWatchPage() {
  const canRead = useCapability("ip:read");
  const canManage = useCapability("ip:watch_manage");
  const session = useSession();
  const queryClient = useQueryClient();
  const [view, setView] = useState<View>("hits");
  const [docketId, setDocketId] = useState("");
  const [selectedHitId, setSelectedHitId] = useState("");

  const dockets = useQuery({ queryKey: ["ip", "dockets"], queryFn: fetchIpDockets, enabled: canRead });
  const workspace = useQuery({
    queryKey: ["ip", "watch", docketId],
    queryFn: () => fetchIpWatchWorkspace(docketId || null),
    enabled: canRead,
  });
  const core = useQuery({
    queryKey: ["ip", "core-records", docketId],
    queryFn: () => fetchIpCoreRecords(docketId),
    enabled: canRead && Boolean(docketId),
  });

  useEffect(() => {
    if (!docketId && dockets.data?.dockets[0]) setDocketId(dockets.data.dockets[0].id);
  }, [docketId, dockets.data]);

  useEffect(() => {
    const hits = workspace.data?.hits ?? [];
    if (!hits.some((hit) => hit.id === selectedHitId)) setSelectedHitId(hits[0]?.id ?? "");
  }, [selectedHitId, workspace.data]);

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["ip", "watch"] });
  }

  if (!canRead) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title="Trademark journal watch" />
        <EmptyState title="IP access required" description="Ask an owner or admin for IP read access." />
      </div>
    );
  }

  const profiles = workspace.data?.profiles ?? [];
  const hits = workspace.data?.hits ?? [];
  const selectedHit = hits.find((hit) => hit.id === selectedHitId) ?? null;
  const publication = selectedHit
    ? workspace.data?.publications.find((item) => item.id === selectedHit.publication_id) ?? null
    : null;
  const selectedProfile = selectedHit
    ? profiles.find((item) => item.id === selectedHit.profile_id) ?? null
    : null;

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        eyebrow="IP operations"
        title="Trademark journal watch"
        description="Docket watch criteria, official journal evidence, attorney review, notifications, and canonical follow-on work."
        actions={
          <Button variant="outline" size="sm" onClick={() => refresh()} disabled={workspace.isFetching}>
            <RefreshCw className={workspace.isFetching ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
            Refresh
          </Button>
        }
      />

      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-[var(--color-line)] pb-4">
        <div className="w-full sm:max-w-lg">
          <Label htmlFor="watch-docket">Docket scope</Label>
          <select
            id="watch-docket"
            className="mt-1 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
            value={docketId}
            onChange={(event) => setDocketId(event.target.value)}
          >
            <option value="">All accessible dockets</option>
            {(dockets.data?.dockets ?? []).map((docket) => (
              <option key={docket.id} value={docket.id}>{docket.title}</option>
            ))}
          </select>
        </div>
        <div
          role="group"
          aria-label="Watch views"
          className="grid w-full min-w-0 grid-cols-2 overflow-hidden rounded-md border border-[var(--color-line)] bg-white sm:w-auto sm:grid-cols-4"
        >
          {(["hits", "profiles", "ingest", "runs"] as View[]).map((item) => (
            <button
              key={item}
              aria-pressed={view === item}
              className={
                view === item
                  ? "min-h-10 min-w-0 px-2 text-sm font-medium text-white bg-[var(--color-ink)] sm:px-4"
                  : "min-h-10 min-w-0 px-2 text-sm font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)] sm:px-4"
              }
              onClick={() => setView(item)}
            >
              {item === "ingest" ? "Journal intake" : item[0].toUpperCase() + item.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {workspace.isPending || dockets.isPending ? (
        <div className="grid gap-4 lg:grid-cols-3"><Skeleton className="h-56" /><Skeleton className="h-56 lg:col-span-2" /></div>
      ) : workspace.isError || dockets.isError ? (
        <QueryErrorState error={workspace.error ?? dockets.error} title="Could not load journal watch" onRetry={refresh} />
      ) : view === "profiles" ? (
        <ProfilesView
          profiles={profiles}
          docketId={docketId}
          membershipId={session.context?.membership.id ?? ""}
          canManage={canManage}
          onChanged={refresh}
        />
      ) : view === "ingest" ? (
        <JournalIntake
          docketId={docketId}
          publications={workspace.data?.publications ?? []}
          applications={core.data?.applications ?? []}
          canManage={canManage}
          onCreated={async (hitId) => {
            await refresh();
            setSelectedHitId(hitId);
            setView("hits");
          }}
        />
      ) : view === "runs" ? (
        <RunsView profiles={profiles} runs={workspace.data?.ingestion_runs ?? []} />
      ) : (
        <HitsView
          hits={hits}
          profiles={profiles}
          publication={publication}
          selectedHit={selectedHit}
          selectedProfile={selectedProfile}
          selectedHitId={selectedHitId}
          setSelectedHitId={setSelectedHitId}
          handoffs={workspace.data?.handoffs ?? []}
          applications={core.data?.applications ?? []}
          membershipId={session.context?.membership.id ?? ""}
          canManage={canManage}
          onChanged={refresh}
        />
      )}
    </div>
  );
}

function ProfilesView({
  profiles,
  docketId,
  membershipId,
  canManage,
  onChanged,
}: {
  profiles: IpWatchProfile[];
  docketId: string;
  membershipId: string;
  canManage: boolean;
  onChanged: () => Promise<void>;
}) {
  const mutation = useMutation({
    mutationFn: createIpWatchProfile,
    onSuccess: async () => { toast.success("Watch profile created."); await onChanged(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not create watch profile.")),
  });
  const status = useMutation({
    mutationFn: updateIpWatchProfileStatus,
    onSuccess: async () => { toast.success("Watch profile status updated."); await onChanged(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not update watch profile.")),
  });
  const [name, setName] = useState("");
  const [words, setWords] = useState("");
  const [phonetic, setPhonetic] = useState("");
  const [devices, setDevices] = useState("");
  const [classNumbers, setClassNumbers] = useState("");
  const [proprietors, setProprietors] = useState("");
  const [jurisdictions, setJurisdictions] = useState("IN");
  const [frequency, setFrequency] = useState<IpWatchProfile["frequency"]>("publication");
  const [recipients, setRecipients] = useState(membershipId);
  const [maxCost, setMaxCost] = useState("0");

  useEffect(() => { if (membershipId) setRecipients((current) => current || membershipId); }, [membershipId]);

  function submit(event: FormEvent) {
    event.preventDefault();
    mutation.mutate({
      docketId,
      name,
      providerKey: "manual-journal",
      wordTerms: csv(words),
      phoneticTerms: csv(phonetic),
      deviceReferences: csv(devices),
      classNumbers: classes(classNumbers),
      proprietorTerms: csv(proprietors),
      jurisdictions: csv(jurisdictions).map((item) => item.toUpperCase()),
      frequency,
      recipientMembershipIds: csv(recipients),
      maxCostMinorPerPeriod: Number(maxCost),
      costCurrency: "INR",
    });
  }

  return (
    <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
      <section className="flex min-w-0 flex-col gap-3" aria-label="Watch profiles">
        {profiles.length === 0 ? (
          <EmptyState title="No watch profiles" description="Create docket-specific criteria and recipients." />
        ) : profiles.map((profile) => (
          <Card key={profile.id}>
            <CardHeader className="gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div><CardTitle as="h2">{profile.name}</CardTitle><p className="mt-1 text-sm text-[var(--color-mute)]">{profile.provider_key} · {profile.frequency}</p></div>
              <Badge tone={tone(profile.poll_status)}>{profile.poll_status.replaceAll("_", " ")}</Badge>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              {profile.pause_reason ? <div className="flex gap-2 border-l-2 border-amber-400 pl-3 text-amber-900"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{profile.pause_reason}</div> : null}
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Words / phonetics" value={[...profile.word_terms_json, ...profile.phonetic_terms_json].join(", ") || "None"} />
                <Field label="Classes / jurisdictions" value={[...profile.class_numbers_json.map(String), ...profile.jurisdictions_json].join(", ") || "None"} />
                <Field label="Recipients" value={`${profile.recipient_membership_ids_json.length} configured`} />
                <Field label="Cost policy" value={`${profile.spent_cost_minor_in_period} / ${profile.max_cost_minor_per_period || "unlimited"} ${profile.cost_currency} minor units`} />
                <Field label="Last checked" value={localDate(profile.last_polled_at)} />
                <Field label="Next check" value={localDate(profile.next_poll_at)} />
              </div>
              {canManage ? (
                <div className="flex gap-2">
                  {profile.poll_status === "active" ? (
                    <Button size="sm" variant="outline" disabled={status.isPending} onClick={() => status.mutate({ profileId: profile.id, expectedVersion: profile.version, pollStatus: "paused", reason: "Paused by an authorized journal-watch operator." })}><Pause className="h-4 w-4" />Pause</Button>
                  ) : (
                    <Button size="sm" variant="outline" disabled={status.isPending} onClick={() => status.mutate({ profileId: profile.id, expectedVersion: profile.version, pollStatus: "active", reason: "Resumed by an authorized journal-watch operator." })}><Play className="h-4 w-4" />Resume</Button>
                  )}
                </div>
              ) : null}
            </CardContent>
          </Card>
        ))}
      </section>
      <Card>
        <CardHeader><CardTitle as="h2">New watch profile</CardTitle></CardHeader>
        <CardContent>
          {!canManage ? <p className="text-sm text-[var(--color-mute)]">Journal-watch management access is required.</p> : !docketId ? <p className="text-sm text-[var(--color-mute)]">Select a docket first.</p> : (
            <form className="space-y-4" onSubmit={submit}>
              <TextField id="profile-name" label="Profile name" value={name} setValue={setName} required />
              <TextField id="profile-words" label="Word terms" hint="Comma separated" value={words} setValue={setWords} />
              <TextField id="profile-phonetic" label="Phonetic terms" hint="Comma separated" value={phonetic} setValue={setPhonetic} />
              <TextField id="profile-devices" label="Device evidence URLs" hint="Comma separated" value={devices} setValue={setDevices} />
              <div className="grid gap-3 sm:grid-cols-2">
                <TextField id="profile-classes" label="Nice classes" value={classNumbers} setValue={setClassNumbers} />
                <TextField id="profile-jurisdictions" label="Jurisdictions" value={jurisdictions} setValue={setJurisdictions} />
              </div>
              <TextField id="profile-proprietors" label="Proprietor terms" value={proprietors} setValue={setProprietors} />
              <TextField id="profile-recipients" label="Recipient membership IDs" hint="Comma separated" value={recipients} setValue={setRecipients} required />
              <div className="grid gap-3 sm:grid-cols-2">
                <div><Label htmlFor="profile-frequency">Frequency</Label><select id="profile-frequency" className="mt-1 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={frequency} onChange={(event) => setFrequency(event.target.value as IpWatchProfile["frequency"])}><option value="publication">Each publication</option><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select></div>
                <TextField id="profile-cost" label="Max cost (minor units)" type="number" value={maxCost} setValue={setMaxCost} />
              </div>
              <Button type="submit" className="w-full" disabled={mutation.isPending}>{mutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Radar className="h-4 w-4" />}Create profile</Button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function JournalIntake({ docketId, publications, applications, canManage, onCreated }: {
  docketId: string;
  publications: IpJournalPublication[];
  applications: Array<{ id: string }>;
  canManage: boolean;
  onCreated: (hitId: string) => Promise<void>;
}) {
  const [applicationId, setApplicationId] = useState("");
  const [journalNumber, setJournalNumber] = useState("");
  const [journalDate, setJournalDate] = useState("");
  const [kind, setKind] = useState<"advertisement" | "correction" | "readvertisement">("advertisement");
  const [applicationNumber, setApplicationNumber] = useState("");
  const [markText, setMarkText] = useState("");
  const [deviceReference, setDeviceReference] = useState("");
  const [proprietor, setProprietor] = useState("");
  const [classNumbers, setClassNumbers] = useState("");
  const [goods, setGoods] = useState("{}");
  const [scope, setScope] = useState('{"scope_kind":"full"}');
  const [sourceUrl, setSourceUrl] = useState("");
  const [sourcePage, setSourcePage] = useState("");
  const [sourceStatus, setSourceStatus] = useState<"available" | "unavailable" | "stale">("available");
  const [retrievedAt, setRetrievedAt] = useState("");
  const [evidence, setEvidence] = useState("{}");
  const [supersedes, setSupersedes] = useState("");
  const [correctionReason, setCorrectionReason] = useState("");
  const [cost, setCost] = useState("0");
  const mutation = useMutation({
    mutationFn: ingestIpJournal,
    onSuccess: async (result) => {
      toast.success(result.idempotent_replay ? "Existing ingestion replayed." : `Journal ingested; ${result.hits.length} watch hit(s) created.`);
      await onCreated(result.hits[0]?.id ?? "");
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not ingest journal evidence.")),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    try {
      const goodsObject = jsonObject(goods, "Goods/services") as Record<string, string[]>;
      mutation.mutate({
        idempotencyKey: randomKey(),
        providerKey: "ipindia-journal-manual",
        costMinor: Number(cost),
        publication: {
          application_id: applicationId || null,
          journal_number: journalNumber,
          journal_date: journalDate,
          publication_kind: kind,
          application_number: applicationNumber,
          mark_text: markText || null,
          device_reference: deviceReference || null,
          proprietor_name: proprietor || null,
          office: "IP India",
          jurisdiction: "IN",
          class_numbers: classes(classNumbers),
          goods_services: goodsObject,
          publication_scope: jsonObject(scope, "Publication scope"),
          source_url: sourceUrl,
          source_page: sourcePage || null,
          source_status: sourceStatus,
          source_retrieved_at: retrievedAt ? new Date(retrievedAt).toISOString() : null,
          parser_version: "manual-journal-v1",
          attribution: { publisher: "IP India", capture_method: "manual" },
          raw_evidence: jsonObject(evidence, "Raw evidence"),
          supersedes_publication_id: supersedes || null,
          correction_reason: correctionReason || null,
        },
      });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Review the journal evidence fields.");
    }
  }

  if (!canManage) return <EmptyState title="Journal-watch management access required" description="An authorized operator must ingest official journal evidence." />;
  if (!docketId) return <EmptyState title="Select a docket" description="Journal intake is evaluated against docket-scoped profiles." />;
  return (
    <Card>
      <CardHeader><CardTitle as="h2">Manual official-journal intake</CardTitle></CardHeader>
      <CardContent>
        <form className="grid gap-4 lg:grid-cols-2" onSubmit={submit}>
          <div className="space-y-4">
            <div><Label htmlFor="watch-application">Linked trademark application</Label><select id="watch-application" className="mt-1 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={applicationId} onChange={(event) => setApplicationId(event.target.value)}><option value="">No internal application link</option>{applications.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}</select></div>
            <div className="grid gap-3 sm:grid-cols-2"><TextField id="journal-number" label="Journal number" value={journalNumber} setValue={setJournalNumber} required /><TextField id="journal-date" label="Journal date" type="date" value={journalDate} setValue={setJournalDate} required /></div>
            <div><Label htmlFor="publication-kind">Publication kind</Label><select id="publication-kind" className="mt-1 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}><option value="advertisement">Advertisement</option><option value="correction">Correction</option><option value="readvertisement">Re-advertisement</option></select></div>
            <TextField id="application-number" label="Registry application number" value={applicationNumber} setValue={setApplicationNumber} required />
            <TextField id="mark-text" label="Published word mark" value={markText} setValue={setMarkText} />
            <TextField id="device-reference" label="Published device URL" value={deviceReference} setValue={setDeviceReference} />
            <TextField id="proprietor" label="Published proprietor" value={proprietor} setValue={setProprietor} />
            <TextField id="publication-classes" label="Published Nice classes" hint="Comma separated, 1-45" value={classNumbers} setValue={setClassNumbers} required />
            <JsonField id="goods-services" label="Goods/services by class" value={goods} setValue={setGoods} />
            <JsonField id="publication-scope" label="Publication scope" value={scope} setValue={setScope} />
          </div>
          <div className="space-y-4">
            <TextField id="journal-source" label="Official source URL" value={sourceUrl} setValue={setSourceUrl} required />
            <div className="grid gap-3 sm:grid-cols-2"><TextField id="source-page" label="Source page" value={sourcePage} setValue={setSourcePage} /><div><Label htmlFor="source-status">Source status</Label><select id="source-status" className="mt-1 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={sourceStatus} onChange={(event) => setSourceStatus(event.target.value as typeof sourceStatus)}><option value="available">Available</option><option value="unavailable">Unavailable</option><option value="stale">Stale</option></select></div></div>
            <TextField id="retrieved-at" label="Retrieved at" type="datetime-local" value={retrievedAt} setValue={setRetrievedAt} />
            <JsonField id="raw-evidence" label="Captured source evidence" value={evidence} setValue={setEvidence} />
            {kind !== "advertisement" ? <><div><Label htmlFor="supersedes">Superseded publication</Label><select id="supersedes" className="mt-1 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={supersedes} onChange={(event) => setSupersedes(event.target.value)} required><option value="">Select predecessor</option>{publications.map((item) => <option key={item.id} value={item.id}>{item.journal_number} · {item.application_number}</option>)}</select></div><div><Label htmlFor="correction-reason">Correction reason</Label><Textarea id="correction-reason" value={correctionReason} onChange={(event) => setCorrectionReason(event.target.value)} required /></div></> : null}
            <TextField id="journal-cost" label="Acquisition cost (minor INR units)" type="number" value={cost} setValue={setCost} />
            <div className="border-l-2 border-[var(--color-brand-500)] pl-4 text-sm text-[var(--color-ink-2)]">The source record is append-only. Corrections and re-advertisements create a linked successor and never rewrite prior evidence.</div>
            <Button type="submit" disabled={mutation.isPending}>{mutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <FileInput className="h-4 w-4" />}Ingest and evaluate</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function HitsView({ hits, profiles, publication, selectedHit, selectedProfile, selectedHitId, setSelectedHitId, handoffs, applications, membershipId, canManage, onChanged }: {
  hits: IpWatchHit[];
  profiles: IpWatchProfile[];
  publication: IpJournalPublication | null;
  selectedHit: IpWatchHit | null;
  selectedProfile: IpWatchProfile | null;
  selectedHitId: string;
  setSelectedHitId: (value: string) => void;
  handoffs: IpWatchHandoff[];
  applications: Array<{ id: string }>;
  membershipId: string;
  canManage: boolean;
  onChanged: () => Promise<void>;
}) {
  if (hits.length === 0) return <EmptyState title="No watch hits" description={profiles.length ? "No journal evidence matches the selected docket profiles." : "Create a watch profile, then ingest official journal evidence."} />;
  return (
    <div className="grid min-w-0 gap-4 xl:grid-cols-[330px_minmax(0,1fr)]">
      <Card className="min-w-0">
        <CardHeader><CardTitle as="h2">Review queue</CardTitle></CardHeader>
        <CardContent className="p-0"><div className="divide-y divide-[var(--color-line)]">{hits.map((hit) => {
          const mark = String(hit.candidate_mark_json.mark_text ?? "Device mark");
          return <button key={hit.id} className={hit.id === selectedHitId ? "w-full bg-[var(--color-brand-50)] px-5 py-4 text-left" : "w-full px-5 py-4 text-left hover:bg-[var(--color-bg-2)]"} onClick={() => setSelectedHitId(hit.id)}><strong className="block break-words text-sm">{mark}</strong><span className="mt-2 flex flex-wrap gap-2"><Badge tone={tone(hit.disposition)}>{hit.disposition.replaceAll("_", " ")}</Badge><Badge tone={tone(hit.source_status)}>{hit.source_status}</Badge>{hit.stale_source_alert ? <Badge tone="warning">stale alert</Badge> : null}</span><span className="mt-2 block text-xs text-[var(--color-mute)]">{DATE.format(new Date(hit.hit_date))}</span></button>;
        })}</div></CardContent>
      </Card>
      {selectedHit && publication ? <div className="flex min-w-0 flex-col gap-4">
        <Card>
          <CardHeader className="gap-3 sm:flex-row sm:items-start sm:justify-between"><div><CardTitle as="h2">{publication.mark_text || "Device mark"}</CardTitle><p className="mt-1 text-sm text-[var(--color-mute)]">Application {publication.application_number} · Journal {publication.journal_number}</p></div><div className="flex flex-wrap gap-2"><Badge tone={tone(selectedHit.source_status)}>{selectedHit.source_status}</Badge><Badge tone={tone(selectedHit.deadline_confirmation_state)}>{selectedHit.deadline_confirmation_state}</Badge></div></CardHeader>
          <CardContent className="space-y-5">
            {selectedHit.source_status !== "available" ? <div className="flex gap-2 border-l-2 border-amber-400 pl-3 text-sm text-amber-900"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />Final source-dependent dispositions are blocked until an attorney can open and confirm the official source.</div> : null}
            {selectedHit.duplicate_of_hit_id ? <div className="text-sm"><Badge tone="warning">Linked successor / duplicate</Badge><span className="ml-2 text-[var(--color-mute)]">Prior hit {selectedHit.duplicate_of_hit_id}</span></div> : null}
            <div className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4"><Field label="Compared profile" value={selectedProfile?.name ?? selectedHit.profile_id} /><Field label="Classes" value={publication.class_numbers_json.join(", ")} /><Field label="Proprietor" value={publication.proprietor_name ?? "Not published"} /><Field label="Publication scope" value={String(selectedHit.classes_goods_json.scope ? JSON.stringify(selectedHit.classes_goods_json.scope) : "Not supplied")} /></div>
            <div><div className="mb-2 flex items-center justify-between gap-3"><h3 className="text-sm font-semibold">Official source evidence</h3><Button href={selectedHit.source_url} target="_blank" rel="noreferrer" size="sm" variant="outline">Open source<ArrowUpRight className="h-4 w-4" /></Button></div><pre className="max-h-64 overflow-auto rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] p-4 text-xs whitespace-pre-wrap">{JSON.stringify({ attribution: publication.attribution_json, goods_services: publication.goods_services_json, source_page: publication.source_page, retrieved_at: publication.source_retrieved_at }, null, 2)}</pre></div>
            <div><h3 className="mb-2 text-sm font-semibold">Similarity evidence</h3><pre className="max-h-72 overflow-auto rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] p-4 text-xs whitespace-pre-wrap">{JSON.stringify(selectedHit.similarity_evidence_json, null, 2)}</pre></div>
            <div className="flex gap-3 border-l-2 border-[var(--color-brand-500)] pl-4 text-sm"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /><div><strong>AI assistance is advisory.</strong><p className="mt-1 text-[var(--color-mute)]">{selectedHit.advisory_notice}</p></div></div>
          </CardContent>
        </Card>
        {canManage ? <ReviewPanel hit={selectedHit} onChanged={onChanged} /> : null}
        {canManage && ["relevant", "client_instruction", "enforcement_opened"].includes(selectedHit.disposition) ? <HandoffPanel hit={selectedHit} publication={publication} applications={applications} membershipId={membershipId} handoffs={handoffs.filter((item) => item.hit_id === selectedHit.id)} onChanged={onChanged} /> : null}
      </div> : <EmptyState title="Select a hit" description="Choose a journal candidate to inspect source and similarity evidence." />}
    </div>
  );
}

function ReviewPanel({ hit, onChanged }: { hit: IpWatchHit; onChanged: () => Promise<void> }) {
  const [disposition, setDisposition] = useState<IpWatchDisposition>(hit.disposition);
  const [reason, setReason] = useState(hit.disposition_reason ?? "");
  const [sourceConfirmed, setSourceConfirmed] = useState(false);
  const mutation = useMutation({ mutationFn: decideIpWatchHit, onSuccess: async () => { toast.success("Attorney review recorded."); await onChanged(); }, onError: (error) => toast.error(apiErrorMessage(error, "Could not record the review.")) });
  return <Card><CardHeader><CardTitle as="h2">Attorney disposition</CardTitle></CardHeader><CardContent><form className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)_auto] lg:items-end" onSubmit={(event) => { event.preventDefault(); mutation.mutate({ hitId: hit.id, expectedVersion: hit.version, disposition, reason, sourceConfirmed }); }}><div><Label htmlFor="hit-disposition">Disposition</Label><select id="hit-disposition" className="mt-1 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={disposition} onChange={(event) => setDisposition(event.target.value as IpWatchDisposition)}>{["new", "reviewing", "relevant", "not_relevant", "monitor", "client_instruction", "enforcement_opened", "closed"].map((item) => <option key={item} value={item}>{item.replaceAll("_", " ")}</option>)}</select></div><div><Label htmlFor="disposition-reason">Reason</Label><Input id="disposition-reason" value={reason} onChange={(event) => setReason(event.target.value)} required /></div><Button type="submit" disabled={mutation.isPending}>{mutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}Record review</Button><label className="flex items-center gap-2 text-sm lg:col-span-3"><input type="checkbox" checked={sourceConfirmed} onChange={(event) => setSourceConfirmed(event.target.checked)} />I opened and confirmed the official journal source for this decision.</label></form></CardContent></Card>;
}

function HandoffPanel({ hit, publication, applications, membershipId, handoffs, onChanged }: { hit: IpWatchHit; publication: IpJournalPublication; applications: Array<{ id: string }>; membershipId: string; handoffs: IpWatchHandoff[]; onChanged: () => Promise<void> }) {
  const [kind, setKind] = useState<IpWatchHandoff["handoff_kind"]>("opposition");
  const [applicationId, setApplicationId] = useState(publication.application_id ?? applications[0]?.id ?? "");
  const [title, setTitle] = useState(`Review ${publication.mark_text || publication.application_number}`);
  const [matterCode, setMatterCode] = useState("");
  const [dueOn, setDueOn] = useState("");
  const [assignee, setAssignee] = useState(membershipId);
  const [notes, setNotes] = useState("");
  const mutation = useMutation({ mutationFn: createIpWatchHandoff, onSuccess: async (row) => { toast.success(`${row.handoff_kind.replaceAll("_", " ")} created without re-entry.`); await onChanged(); }, onError: (error) => toast.error(apiErrorMessage(error, "Could not create the canonical handoff.")) });
  const existingKinds = new Set(handoffs.map((item) => item.handoff_kind));
  return <Card><CardHeader><CardTitle as="h2">Canonical handoff</CardTitle></CardHeader><CardContent className="space-y-4"><div className="flex flex-wrap gap-2">{(["opposition", "enforcement_matter", "task", "deadline", "client_report_item"] as const).map((item) => <button key={item} className={kind === item ? "rounded-md bg-[var(--color-ink)] px-3 py-2 text-sm font-medium text-white" : "rounded-md border border-[var(--color-line)] px-3 py-2 text-sm font-medium"} onClick={() => setKind(item)}>{item.replaceAll("_", " ")}{existingKinds.has(item) ? " · created" : ""}</button>)}</div><form className="grid gap-4 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); mutation.mutate({ hitId: hit.id, handoffKind: kind, applicationId: applicationId || null, title: title || null, matterCode: matterCode || null, dueOn: dueOn || null, assigneeMembershipId: assignee || null, notes: notes || null }); }}>{kind === "opposition" ? <div><Label htmlFor="handoff-application">Application</Label><select id="handoff-application" className="mt-1 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={applicationId} onChange={(event) => setApplicationId(event.target.value)}><option value="">No linked application</option>{applications.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}</select></div> : null}{["enforcement_matter", "task", "deadline"].includes(kind) ? <TextField id="handoff-title" label="Title" value={title} setValue={setTitle} required /> : null}{kind === "enforcement_matter" ? <TextField id="handoff-code" label="Matter code" value={matterCode} setValue={setMatterCode} required /> : null}{kind === "deadline" ? <TextField id="handoff-due" label="Due date" type="date" value={dueOn} setValue={setDueOn} required /> : null}{["task", "deadline", "client_report_item"].includes(kind) ? <TextField id="handoff-assignee" label="Assignee membership ID" value={assignee} setValue={setAssignee} /> : null}<div className="sm:col-span-2"><Label htmlFor="handoff-notes">Notes</Label><Textarea id="handoff-notes" value={notes} onChange={(event) => setNotes(event.target.value)} /></div><div className="sm:col-span-2"><Button type="submit" disabled={mutation.isPending || existingKinds.has(kind)}>{mutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}Create {kind.replaceAll("_", " ")}</Button></div></form>{handoffs.length ? <div className="border-t border-[var(--color-line)] pt-4"><h3 className="mb-2 text-sm font-semibold">Completed handoffs</h3><div className="flex flex-wrap gap-2">{handoffs.map((item) => <Badge key={item.id} tone={tone(item.status)}>{item.handoff_kind.replaceAll("_", " ")} → {item.target_type}</Badge>)}</div></div> : null}</CardContent></Card>;
}

function RunsView({ profiles, runs }: { profiles: IpWatchProfile[]; runs: Array<{ id: string; provider_key: string; status: string; publications_seen: number; publications_created: number; hits_created: number; duplicate_hits: number; stale_source_alert: boolean; error_redacted: string | null; started_at: string; cost_minor: number; currency: string }> }) {
  const paused = profiles.filter((item) => item.poll_status !== "active");
  return <div className="flex flex-col gap-4">{paused.length ? <div className="border-l-2 border-amber-400 bg-amber-50 p-4 text-sm text-amber-950"><div className="flex items-center gap-2 font-semibold"><Pause className="h-4 w-4" />{paused.length} profile(s) paused</div><p className="mt-1">{paused.map((item) => `${item.name}: ${item.pause_reason ?? item.poll_status}`).join(" · ")}</p></div> : null}{runs.length === 0 ? <EmptyState title="No ingestion runs" description="Manual intake and scheduler checks will appear here." /> : <div className="overflow-x-auto border-y border-[var(--color-line)]"><table className="w-full min-w-[850px] text-left text-sm"><thead className="bg-[var(--color-bg-2)] text-xs text-[var(--color-mute)]"><tr><th className="px-4 py-3">Started</th><th className="px-4 py-3">Provider</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Evidence</th><th className="px-4 py-3">Hits</th><th className="px-4 py-3">Cost</th><th className="px-4 py-3">Exception</th></tr></thead><tbody className="divide-y divide-[var(--color-line)]">{runs.map((run) => <tr key={run.id}><td className="px-4 py-3">{localDate(run.started_at)}</td><td className="px-4 py-3">{run.provider_key}</td><td className="px-4 py-3"><Badge tone={tone(run.status)}>{run.status.replaceAll("_", " ")}</Badge></td><td className="px-4 py-3 tabular-nums">{run.publications_created}/{run.publications_seen}{run.duplicate_hits ? ` · ${run.duplicate_hits} duplicate` : ""}</td><td className="px-4 py-3 tabular-nums">{run.hits_created}{run.stale_source_alert ? " · stale" : ""}</td><td className="px-4 py-3 tabular-nums">{run.cost_minor} {run.currency}</td><td className="px-4 py-3 text-[var(--color-mute)]">{run.error_redacted ?? "None"}</td></tr>)}</tbody></table></div>}</div>;
}

function Field({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><span className="text-[var(--color-mute)]">{label}</span><strong className="mt-1 block break-words font-medium text-[var(--color-ink)]">{value}</strong></div>;
}

function TextField({ id, label, hint, value, setValue, type = "text", required = false }: { id: string; label: string; hint?: string; value: string; setValue: (value: string) => void; type?: string; required?: boolean }) {
  return <div><div className="flex items-center justify-between gap-2"><Label htmlFor={id}>{label}</Label>{hint ? <span className="text-xs text-[var(--color-mute)]">{hint}</span> : null}</div><Input id={id} type={type} value={value} onChange={(event) => setValue(event.target.value)} required={required} /></div>;
}

function JsonField({ id, label, value, setValue }: { id: string; label: string; value: string; setValue: (value: string) => void }) {
  return <div><Label htmlFor={id}>{label}</Label><Textarea id={id} className="font-mono text-xs" value={value} onChange={(event) => setValue(event.target.value)} /></div>;
}
