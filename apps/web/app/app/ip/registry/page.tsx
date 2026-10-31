"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowUpRight,
  Check,
  FileClock,
  Link2,
  LoaderCircle,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Unlink,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { toast } from "sonner";

import { IpDocketPicker } from "@/components/ip/IpDocketPicker";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { RecordSelect } from "@/components/ui/RecordSelect";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { API_FORM_ERROR_KEY, apiErrorMessage, apiFieldErrors } from "@/lib/api/config";
import {
  createIpRegistryLink,
  createIpTrackedCaseReference,
  decideIpRegistryMatch,
  decideIpTrackedCaseReference,
  fetchIpCoreRecords,
  fetchIpDocket,
  fetchIpRegistryDiffs,
  fetchIpRegistryWorkspaces,
  fetchIpTrackedCaseReferences,
  fetchIpWorkspaceReadiness,
  listCaseTrackingBookmarks,
  recordIpRegistryFailure,
  recordIpRegistryManualSnapshot,
  resolveIpRegistryDiff,
  type IpCoreRecords,
  type IpDocket,
  type IpRegistryDiff,
  type IpRegistrySnapshotSummary,
  type IpRegistryWorkspace,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import {
  IDENTIFIER_KIND_LABELS,
  OPTIONAL_REGISTER_FIELDS,
  REGISTRY_DOCKET_RECORD_TYPES,
  flattenRegisterState,
  isMadridRecordType,
  normalizedRegisterRecord,
  registerFieldLabel,
  registerFormFromState,
  registrySyncSentence,
  registryTargets,
  type RegisterParty,
  type RegistryIdentifierKind,
  type RegistryTarget,
} from "@/lib/ip/registry-evidence";
import { useSession } from "@/lib/use-session";

const STAMP = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const STAMP_SECONDS = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

const FIELD_CLASS =
  "mt-1 h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm disabled:cursor-not-allowed disabled:opacity-60 aria-[invalid=true]:border-[var(--color-danger-500)]";

function stamp(value: string | null) {
  return value ? STAMP.format(new Date(value)) : "Never";
}

function jsonValue(value: unknown) {
  return JSON.stringify(value, null, 2);
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

function sourceHost(url: string) {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/** A `datetime-local` value for the browser's own time zone. */
function localDateTimeValue(date: Date) {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Error text for one control, wired through aria-describedby. */
function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return <p id={id} className="mt-1 break-words text-sm text-[var(--color-danger-500)]">{message}</p>;
}

function fieldProps(id: string, errors: Record<string, string>, extra?: string) {
  const describedBy = [errors[id] ? `${id}-error` : null, extra ?? null].filter(Boolean).join(" ");
  return {
    id,
    "aria-invalid": errors[id] ? true : undefined,
    "aria-describedby": describedBy || undefined,
  } as const;
}

export default function IpRegistryPage() {
  const canRead = useCapability("ip:read");
  const canSync = useCapability("ip:registry_sync");
  const session = useSession();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  // A `?docket=` deep link is the only default: the page never picks a docket itself.
  const [selectedDocketId, setSelectedDocketId] = useState(() => searchParams.get("docket") ?? "");
  const [selectedLinkId, setSelectedLinkId] = useState("");
  const [workspaceOffset, setWorkspaceOffset] = useState(0);

  const docket = useQuery({
    queryKey: ["ip", "dockets", selectedDocketId],
    queryFn: () => fetchIpDocket(selectedDocketId),
    enabled: canRead && Boolean(selectedDocketId),
  });
  const madrid = isMadridRecordType(docket.data?.record_type);
  const nationalDocket = docket.data && !madrid ? docket.data : null;
  const workspaces = useQuery({
    queryKey: ["ip", "registry", "workspaces", selectedDocketId, workspaceOffset],
    queryFn: () => fetchIpRegistryWorkspaces(selectedDocketId, 25, workspaceOffset),
    enabled: canRead,
  });
  const core = useQuery({
    queryKey: ["ip", "core-records", selectedDocketId],
    queryFn: () => fetchIpCoreRecords(selectedDocketId),
    enabled: canRead && Boolean(nationalDocket),
  });
  const references = useQuery({
    queryKey: ["ip", "tracked-case-references", selectedDocketId],
    queryFn: () => fetchIpTrackedCaseReferences(selectedDocketId),
    enabled: canRead && Boolean(nationalDocket),
  });
  const bookmarks = useQuery({
    queryKey: ["case-tracking", "bookmarks"],
    queryFn: listCaseTrackingBookmarks,
    enabled: canRead && Boolean(nationalDocket),
  });
  const readiness = useQuery({
    queryKey: ["ip", "readiness"],
    queryFn: fetchIpWorkspaceReadiness,
    enabled: canRead && canSync,
  });
  const syncSentence = registrySyncSentence(
    readiness.data?.features.find((feature) => feature.feature_id === "registry_sync"),
  );

  const visibleWorkspaces = useMemo(() => workspaces.data?.items ?? [], [workspaces.data]);

  useEffect(() => {
    setWorkspaceOffset(0);
  }, [selectedDocketId]);

  useEffect(() => {
    if (!visibleWorkspaces.some((row) => row.link.id === selectedLinkId)) {
      setSelectedLinkId(visibleWorkspaces[0]?.link.id ?? "");
    }
  }, [selectedLinkId, visibleWorkspaces]);

  const selectedWorkspace =
    visibleWorkspaces.find((row) => row.link.id === selectedLinkId) ?? null;

  function chooseDocket(docketId: string) {
    setSelectedDocketId(docketId);
    setSelectedLinkId("");
    const url = new URL(window.location.href);
    if (docketId) url.searchParams.set("docket", docketId);
    else url.searchParams.delete("docket");
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }

  async function refreshAll() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["ip", "registry"] }),
      queryClient.invalidateQueries({ queryKey: ["ip", "core-records", selectedDocketId] }),
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

      <Card>
        <CardHeader>
          <CardTitle as="h2">Docket scope</CardTitle>
          <p className="mt-1 text-sm text-[var(--color-mute)]">
            Registry observations remain separate from accepted CaseOps legal state.
          </p>
        </CardHeader>
        <CardContent className="flex min-w-0 flex-col gap-4">
          <IpDocketPicker
            id="registry-docket"
            label="IP docket"
            searchLabel="Find a docket by mark or number"
            value={selectedDocketId}
            onChange={(docketId) => chooseDocket(docketId)}
            recordTypes={REGISTRY_DOCKET_RECORD_TYPES}
            className="w-full sm:max-w-xl"
          />
          <p className="text-sm text-[var(--color-mute)]">
            Lists national trademark dockets. International registrations and designations are
            reconciled in the{" "}
            <Link className="font-semibold text-[var(--color-brand-700)] hover:underline" href="/app/ip/madrid">
              Madrid portfolio
            </Link>
            .
          </p>
          {docket.data ? (
            <div className="grid gap-4 text-sm sm:grid-cols-3">
              <div className="min-w-0"><span className="text-[var(--color-mute)]">Record</span><strong className="mt-1 block break-words">{docket.data.title}</strong></div>
              <div><span className="text-[var(--color-mute)]">Matter</span><strong className="mt-1 block">{docket.data.matter_id ? "Linked" : "Not linked"}</strong></div>
              <div><span className="text-[var(--color-mute)]">Registry identities</span><strong className="mt-1 block tabular-nums">{workspaces.data?.total ?? 0}</strong></div>
            </div>
          ) : !selectedDocketId ? (
            <p className="text-sm text-[var(--color-mute)]">
              Select a docket to begin. Registry identities already recorded across your dockets are listed below.
            </p>
          ) : null}
        </CardContent>
      </Card>

      {madrid && docket.data ? <MadridDocketNotice docket={docket.data} /> : null}

      {nationalDocket ? (
        canSync ? (
          <CreateRegistryLink
            key={`create-${nationalDocket.id}`}
            docketId={nationalDocket.id}
            core={core}
            syncSentence={syncSentence}
            onCreated={async (linkId) => {
              await refreshAll();
              setSelectedLinkId(linkId);
            }}
          />
        ) : (
          <Card>
            <CardContent className="py-5 text-sm text-[var(--color-mute)]">
              Your role cannot add registry identities or record register evidence. Ask an IP
              workspace admin for registry access.
            </CardContent>
          </Card>
        )
      ) : null}

      {workspaces.isPending ? (
        <div className="grid gap-4 lg:grid-cols-3">
          <Skeleton className="h-48" />
          <Skeleton className="h-48 lg:col-span-2" />
        </div>
      ) : workspaces.isError ? (
        <QueryErrorState
          error={workspaces.error}
          title="Could not load registry identities"
          onRetry={() => workspaces.refetch()}
        />
      ) : (
        <div className="grid min-w-0 gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
          <Card className="min-w-0">
            <CardHeader>
              <CardTitle as="h2">Registry identities</CardTitle>
              <p className="text-sm text-[var(--color-mute)]">
                {selectedDocketId ? "This docket only." : "Across every docket you can see."}
              </p>
            </CardHeader>
            <CardContent className="p-0">
              {visibleWorkspaces.length === 0 ? (
                <div className="p-6 text-sm text-[var(--color-mute)]">
                  {selectedDocketId
                    ? "No registry identity is linked to this docket yet."
                    : "No registry identity has been recorded yet. Choose a docket above to add one."}
                </div>
              ) : (
                <div className="divide-y divide-[var(--color-line)]">
                  {visibleWorkspaces.map((workspace) => (
                    <button
                      key={workspace.link.id}
                      type="button"
                      aria-pressed={workspace.link.id === selectedLinkId}
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
              {(workspaces.data?.total ?? 0) > 25 ? (
                <div className="flex items-center justify-between border-t border-[var(--color-line)] p-3">
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={workspaceOffset === 0 || workspaces.isFetching}
                    onClick={() => setWorkspaceOffset(Math.max(0, workspaceOffset - 25))}
                  >
                    Previous
                  </Button>
                  <span className="text-xs tabular-nums text-[var(--color-mute)]">
                    {workspaceOffset + 1}-{Math.min(workspaceOffset + 25, workspaces.data?.total ?? 0)} of {workspaces.data?.total ?? 0}
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={workspaceOffset + 25 >= (workspaces.data?.total ?? 0) || workspaces.isFetching}
                    onClick={() => setWorkspaceOffset(workspaceOffset + 25)}
                  >
                    Next
                  </Button>
                </div>
              ) : null}
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
      )}

      {nationalDocket ? (
        <CourtReferences
          key={`court-${nationalDocket.id}`}
          docket={nationalDocket}
          core={core}
          references={references.data ?? []}
          bookmarks={bookmarks.data?.bookmarks ?? []}
          canSync={canSync}
          onChanged={refreshAll}
        />
      ) : null}
    </div>
  );
}

function MadridDocketNotice({ docket }: { docket: IpDocket }) {
  return (
    <Card>
      <CardContent className="flex min-w-0 flex-col gap-2 py-5 text-sm" role="status">
        <strong className="break-words">{docket.title} is a Madrid international record.</strong>
        <span className="text-[var(--color-mute)]">
          Registry identities attach to a national application or proceeding, and an international
          registration or designation has neither. Track its WIPO and national status in the Madrid
          portfolio.
        </span>
        <Link
          className="inline-flex items-center gap-1 font-semibold text-[var(--color-brand-700)] hover:underline"
          href="/app/ip/madrid"
        >
          Open the Madrid portfolio <ArrowUpRight className="h-4 w-4" aria-hidden />
        </Link>
      </CardContent>
    </Card>
  );
}

const LINK_FIELD_MAP = {
  application_id: "registry-target",
  proceeding_id: "registry-target",
  identifier_kind: "registry-kind",
  raw_identifier: "registry-identifier",
  office: "registry-office",
  jurisdiction: "registry-jurisdiction",
  source_url: "registry-source",
  match_confidence: "registry-confidence",
} as const;

function CreateRegistryLink({
  docketId,
  core,
  syncSentence,
  onCreated,
}: {
  docketId: string;
  core: UseQueryResult<IpCoreRecords>;
  syncSentence: string | null;
  onCreated: (linkId: string) => Promise<void>;
}) {
  const targets = useMemo(() => (core.data ? registryTargets(core.data) : []), [core.data]);
  const [targetValue, setTargetValue] = useState("");
  const [kind, setKind] = useState<RegistryIdentifierKind>("application");
  const [identifier, setIdentifier] = useState("");
  const [office, setOffice] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [confidence, setConfidence] = useState("0.95");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const target = targets.find((row) => row.value === targetValue) ?? null;

  function prefill(next: RegistryTarget) {
    setTargetValue(next.value);
    setKind(next.identifierKind);
    setIdentifier(next.identifier);
    setOffice(next.office);
    setJurisdiction(next.jurisdiction);
  }

  // A docket with exactly one legal record has nothing to choose between.
  useEffect(() => {
    if (targetValue || targets.length !== 1) return;
    const only = targets[0];
    setTargetValue(only.value);
    setKind(only.identifierKind);
    setIdentifier(only.identifier);
    setOffice(only.office);
    setJurisdiction(only.jurisdiction);
  }, [targets, targetValue]);

  const create = useMutation({
    mutationFn: (chosen: RegistryTarget) =>
      createIpRegistryLink({
        docketId,
        applicationId: chosen.kind === "application" ? chosen.id : null,
        proceedingId: chosen.kind === "proceeding" ? chosen.id : null,
        office: office.trim(),
        jurisdiction: jurisdiction.trim(),
        identifierKind: kind,
        rawIdentifier: identifier.trim(),
        sourceUrl: sourceUrl.trim(),
        matchConfidence: Number(confidence),
        matchEvidence: { capture: "manual", identifier: identifier.trim(), office: office.trim(), jurisdiction: jurisdiction.trim() },
      }),
    onSuccess: async (link) => {
      toast.success("Registry identity added for match review.");
      setErrors({});
      setIdentifier("");
      setSourceUrl("");
      await onCreated(link.id);
    },
    onError: (error) => {
      const fields = apiFieldErrors(error, LINK_FIELD_MAP);
      const message = apiErrorMessage(error, "Could not add the registry identity.");
      setErrors(Object.keys(fields).length > 0 ? fields : { [API_FORM_ERROR_KEY]: message });
      toast.error(message);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    // Fail closed: only a record of this docket, as listed right now, is sent.
    const chosen = targets.find((row) => row.value === targetValue);
    const next: Record<string, string> = {};
    if (!chosen) next["registry-target"] = "Choose the legal record this identity belongs to.";
    if (!identifier.trim()) next["registry-identifier"] = "Enter the identifier exactly as the register shows it.";
    if (office.trim().length < 2) next["registry-office"] = "Enter the office, for example IP India.";
    if (jurisdiction.trim().length < 2) next["registry-jurisdiction"] = "Enter the jurisdiction code, for example IN.";
    if (!/^https?:\/\/\S{4,}$/i.test(sourceUrl.trim())) next["registry-source"] = "Enter the official register page address, starting with https://.";
    const share = Number(confidence);
    if (confidence.trim() === "" || !(share >= 0 && share <= 1)) next["registry-confidence"] = "Enter a confidence between 0 and 1, for example 0.95.";
    setErrors(next);
    if (!chosen || Object.keys(next).length > 0) return;
    create.mutate(chosen);
  }

  const noRecords = core.isSuccess && targets.length === 0;
  const recordsUnavailable = core.isPending || core.isError || noRecords;
  const blockedReason = core.isPending
    ? "Loading this docket's applications and proceedings."
    : core.isError
      ? "The docket's legal records could not be loaded."
      : noRecords
        ? "This docket has no application or proceeding to attach an identity to."
        : !target
          ? "Choose the legal record this identity belongs to."
          : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2">Add registry identity</CardTitle>
        <p className="text-sm text-[var(--color-mute)]">
          Manual path: record the identity exactly as the official register shows it. CaseOps makes
          no call to the registry. {syncSentence}
        </p>
      </CardHeader>
      <CardContent>
        <form className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-6" onSubmit={submit} noValidate>
          <div className="min-w-0 md:col-span-2 xl:col-span-3">
            <RecordSelect
              id="registry-target"
              label="Legal record"
              className={FIELD_CLASS}
              value={targetValue}
              disabled={recordsUnavailable || create.isPending}
              required
              aria-invalid={errors["registry-target"] ? true : undefined}
              aria-describedby={[errors["registry-target"] ? "registry-target-error" : null, "registry-target-status"].filter(Boolean).join(" ")}
              onChange={(event) => {
                const next = targets.find((row) => row.value === event.target.value);
                if (next) prefill(next);
                setErrors(({ "registry-target": _cleared, ...rest }) => rest);
              }}
              options={[
                { value: "", label: core.isPending ? "Loading legal records…" : "Choose the application or proceeding", disabled: true },
                ...targets.map((row) => ({ value: row.value, label: row.label })),
              ]}
            />
            <FieldError id="registry-target-error" message={errors["registry-target"]} />
            <LegalRecordStatus docketId={docketId} core={core} empty={noRecords} />
          </div>
          <div className="min-w-0">
            <Label htmlFor="registry-kind">Identifier type</Label>
            <select
              {...fieldProps("registry-kind", errors)}
              className={FIELD_CLASS}
              value={target ? kind : ""}
              disabled={!target || create.isPending}
              required
              onChange={(event) => setKind(event.target.value as RegistryIdentifierKind)}
            >
              {target ? null : <option value="">Choose a legal record first</option>}
              {(target?.identifierKinds ?? []).map((value) => (
                <option key={value} value={value}>{IDENTIFIER_KIND_LABELS[value]}</option>
              ))}
            </select>
            <FieldError id="registry-kind-error" message={errors["registry-kind"]} />
          </div>
          <div className="min-w-0 xl:col-span-2">
            <Label htmlFor="registry-identifier">Identifier</Label>
            <Input {...fieldProps("registry-identifier", errors)} className="mt-1" value={identifier} disabled={!target || create.isPending} onChange={(event) => setIdentifier(event.target.value)} required />
            <FieldError id="registry-identifier-error" message={errors["registry-identifier"]} />
          </div>
          <div className="min-w-0">
            <Label htmlFor="registry-office">Office</Label>
            <Input {...fieldProps("registry-office", errors)} className="mt-1" value={office} disabled={!target || create.isPending} onChange={(event) => setOffice(event.target.value)} required />
            <FieldError id="registry-office-error" message={errors["registry-office"]} />
          </div>
          <div className="min-w-0">
            <Label htmlFor="registry-jurisdiction">Jurisdiction</Label>
            <Input {...fieldProps("registry-jurisdiction", errors)} className="mt-1" value={jurisdiction} disabled={!target || create.isPending} onChange={(event) => setJurisdiction(event.target.value)} required />
            <FieldError id="registry-jurisdiction-error" message={errors["registry-jurisdiction"]} />
          </div>
          <div className="min-w-0 md:col-span-2 xl:col-span-3">
            <Label htmlFor="registry-source">Official source URL</Label>
            <Input {...fieldProps("registry-source", errors)} type="url" className="mt-1" value={sourceUrl} disabled={!target || create.isPending} onChange={(event) => setSourceUrl(event.target.value)} placeholder="https://tmrsearch.ipindia.gov.in/…" required />
            <FieldError id="registry-source-error" message={errors["registry-source"]} />
          </div>
          <div className="min-w-0">
            <Label htmlFor="registry-confidence">Match confidence</Label>
            <Input {...fieldProps("registry-confidence", errors)} type="number" min="0" max="1" step="0.01" className="mt-1" value={confidence} disabled={!target || create.isPending} onChange={(event) => setConfidence(event.target.value)} required />
            <FieldError id="registry-confidence-error" message={errors["registry-confidence"]} />
          </div>
          <div className="flex min-w-0 flex-col justify-end gap-1 md:col-span-2 xl:col-span-2">
            <Button
              type="submit"
              className="w-full"
              disabled={!target || create.isPending}
              aria-describedby={blockedReason ? "registry-submit-reason" : undefined}
            >
              {create.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />}
              Add identity
            </Button>
            {blockedReason ? <p id="registry-submit-reason" className="text-xs text-[var(--color-mute)]">{blockedReason}</p> : null}
          </div>
          {errors[API_FORM_ERROR_KEY] ? (
            <p role="alert" className="break-words text-sm text-[var(--color-danger-500)] md:col-span-2 xl:col-span-6">{errors[API_FORM_ERROR_KEY]}</p>
          ) : null}
        </form>
      </CardContent>
    </Card>
  );
}

function LegalRecordStatus({ docketId, core, empty }: { docketId: string; core: UseQueryResult<IpCoreRecords>; empty: boolean }) {
  if (core.isPending) {
    return <p id="registry-target-status" role="status" className="mt-1 text-sm text-[var(--color-mute)]">Loading this docket&apos;s applications and proceedings…</p>;
  }
  if (core.isError) {
    return (
      <div id="registry-target-status" role="alert" className="mt-1 flex min-w-0 flex-wrap items-center gap-2 text-sm text-[var(--color-danger-500)]">
        <span className="min-w-0 break-words">Legal records could not be loaded: {apiErrorMessage(core.error, "Request failed.")}</span>
        <Button type="button" size="sm" variant="outline" onClick={() => core.refetch()}>Retry</Button>
      </div>
    );
  }
  if (empty) {
    return (
      <div id="registry-target-status" role="status" className="mt-1 flex min-w-0 flex-col gap-1 text-sm text-[var(--color-mute)]">
        <span className="break-words">
          This docket has no trademark application or proceeding yet, so a registry identity has
          nothing to attach to. Applications are recorded with New trademark application or by
          portfolio import; proceedings are opened from the docket.
        </span>
        <Link className="font-semibold text-[var(--color-brand-700)] hover:underline" href={`/app/ip?docket=${encodeURIComponent(docketId)}`}>
          Open this docket
        </Link>
      </div>
    );
  }
  return <p id="registry-target-status" className="mt-1 text-sm text-[var(--color-mute)]">Applications and proceedings of this docket, with their numbers.</p>;
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
  const [diffOffset, setDiffOffset] = useState(0);
  const [matchReason, setMatchReason] = useState("");
  const [failureClass, setFailureClass] = useState<"authentication" | "rate_limit" | "parse_error" | "provider_outage" | "configuration" | "policy" | "unknown">("parse_error");
  const [failureMessage, setFailureMessage] = useState("");
  const [reviewReason, setReviewReason] = useState("");
  const [mappedPath, setMappedPath] = useState("");
  const mappableFields = useMemo(() => {
    const paths = new Set(flattenRegisterState(link.accepted_state_json ?? {}).keys());
    for (const field of OPTIONAL_REGISTER_FIELDS) paths.add(field.path);
    paths.delete("/");
    return [...paths].sort().map((path) => ({ value: path, label: registerFieldLabel(path) }));
  }, [link.accepted_state_json]);
  const diffs = useQuery({
    queryKey: ["ip", "registry", "diffs", link.id, diffOffset],
    queryFn: () => fetchIpRegistryDiffs(link.id, 50, diffOffset),
  });

  useEffect(() => {
    setDiffOffset(0);
  }, [link.id]);

  useEffect(() => {
    if (diffOffset > 0 && diffs.data && diffs.data.items.length === 0) {
      setDiffOffset(Math.max(0, diffOffset - 50));
    }
  }, [diffOffset, diffs.data]);

  const decideMatch = useMutation({
    mutationFn: (decision: "confirm" | "mismatch" | "retire") =>
      decideIpRegistryMatch({ linkId: link.id, expectedVersion: link.version, decision, reason: matchReason }),
    onSuccess: async () => { toast.success("Registry match decision recorded."); setMatchReason(""); await onChanged(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not record the match decision.")),
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
          {diffs.isPending ? <Skeleton className="h-32" /> : diffs.isError ? <QueryErrorState error={diffs.error} title="Could not load unresolved registry changes" onRetry={() => diffs.refetch()} /> : (diffs.data?.items.length ?? 0) === 0 ? <p className="text-sm text-[var(--color-mute)]">No field changes are awaiting a decision.</p> : <><div className="grid gap-3 sm:grid-cols-2"><div><Label htmlFor="review-reason">Decision reason</Label><Input id="review-reason" className="mt-1" value={reviewReason} onChange={(event) => setReviewReason(event.target.value)} /></div><RecordSelect id="mapped-path" label="Map to CaseOps field" className={FIELD_CLASS} value={mappedPath} onChange={(event) => setMappedPath(event.target.value)} options={[{ value: "", label: "Only needed for Map", disabled: false }, ...mappableFields]} /></div><div className="overflow-x-auto"><table className="w-full min-w-[920px] border-collapse text-left text-sm"><thead><tr className="border-b border-[var(--color-line)] text-xs uppercase text-[var(--color-mute)]"><th className="px-3 py-2">Field</th><th className="px-3 py-2">Change</th><th className="px-3 py-2">Before</th><th className="px-3 py-2">After</th><th className="px-3 py-2">Risk</th><th className="px-3 py-2">Decision</th><th className="px-3 py-2">Actions</th></tr></thead><tbody>{diffs.data?.items.map((diff) => <tr className="border-b border-[var(--color-line)] align-top" key={diff.id}><td className="px-3 py-3"><span className="block font-mono text-xs">{diff.mapped_field_path ?? diff.field_path}</span><span className="mt-1 block text-xs text-[var(--color-mute)]">{registerFieldLabel(diff.mapped_field_path ?? diff.field_path)}</span></td><td className="px-3 py-3"><Badge tone="neutral">{diff.change_kind}</Badge></td><td className="max-w-48 break-words px-3 py-3 font-mono text-xs">{jsonValue(diff.before_value_json)}</td><td className="max-w-48 break-words px-3 py-3 font-mono text-xs">{jsonValue(diff.after_value_json)}</td><td className="px-3 py-3"><Badge tone={diff.risk_level === "high" ? "warning" : "neutral"}>{diff.risk_level}</Badge>{diff.deadline_recalculation_state === "required" ? <div className="mt-2 text-xs text-amber-800">Deadline review required</div> : null}</td><td className="px-3 py-3"><Badge tone={statusTone(diff.resolution_status)}>{diff.resolution_status}</Badge></td><td className="px-3 py-3"><div className="flex flex-wrap gap-1">{canSync ? <><Button size="sm" disabled={!membershipId || reviewReason.trim().length < 5 || resolveDiff.isPending} onClick={() => resolveDiff.mutate({ diff, decision: "accept" })}>Accept</Button><Button size="sm" variant="outline" disabled={reviewReason.trim().length < 5 || resolveDiff.isPending} onClick={() => resolveDiff.mutate({ diff, decision: "reject" })}>Reject</Button><Button size="sm" variant="outline" disabled={reviewReason.trim().length < 5 || !mappedPath || resolveDiff.isPending} onClick={() => resolveDiff.mutate({ diff, decision: "map" })}>Map</Button><Button size="sm" variant="ghost" disabled={reviewReason.trim().length < 5 || resolveDiff.isPending} onClick={() => resolveDiff.mutate({ diff, decision: "defer" })}>Defer</Button></> : null}</div></td></tr>)}</tbody></table></div>{(diffs.data?.total ?? 0) > 50 ? <div className="flex items-center justify-end gap-3"><Button size="sm" variant="ghost" disabled={diffOffset === 0} onClick={() => setDiffOffset(Math.max(0, diffOffset - 50))}>Previous</Button><span className="text-xs tabular-nums text-[var(--color-mute)]">{diffOffset + 1}-{Math.min(diffOffset + 50, diffs.data?.total ?? 0)} of {diffs.data?.total ?? 0}</span><Button size="sm" variant="ghost" disabled={diffOffset + 50 >= (diffs.data?.total ?? 0)} onClick={() => setDiffOffset(diffOffset + 50)}>Next</Button></div> : null}</>}
        </CardContent>
      </Card>

      {canSync ? (
        <RegisterEvidenceForm key={`${link.id}:${link.version}`} workspace={workspace} onChanged={onChanged} />
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

const SNAPSHOT_FIELD_MAP = {
  source_url: "snapshot-source",
  source_retrieved_at: "snapshot-viewed-at",
  supersedes_snapshot_id: "supersedes-snapshot",
  correction_reason: "correction-reason",
} as const;

function snapshotLabel(snapshot: IpRegistrySnapshotSummary) {
  return `Recorded ${STAMP_SECONDS.format(new Date(snapshot.source_retrieved_at))} from ${sourceHost(snapshot.source_url)}${snapshot.supersedes_snapshot_id ? " (a correction)" : ""}`;
}

function registerFieldId(path: string) {
  return `register${path.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`;
}

/**
 * Manual register evidence, entered field by field. The normalized record
 * keeps the accepted state's shape, so only what the lawyer changed becomes a
 * change to review; the text they copied from the register page is kept with
 * it as the source evidence.
 */
function RegisterEvidenceForm({ workspace, onChanged }: { workspace: IpRegistryWorkspace; onChanged: () => Promise<void> }) {
  const { link } = workspace;
  const form = useMemo(() => registerFormFromState(link.accepted_state_json ?? {}), [link.accepted_state_json]);
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(form.fields.map((field) => [field.path, field.value])),
  );
  const [parties, setParties] = useState<RegisterParty[] | null>(() => form.parties?.map((row) => ({ ...row })) ?? null);
  const [sourceText, setSourceText] = useState("");
  const [sourceUrl, setSourceUrl] = useState(link.source_url);
  const [viewedAt, setViewedAt] = useState(() => localDateTimeValue(new Date()));
  const [supersedes, setSupersedes] = useState("");
  const [correctionReason, setCorrectionReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const confirmed = link.match_status === "confirmed";
  // The API refuses a second correction of the same snapshot.
  const correctable = workspace.snapshots.filter(
    (snapshot) => !workspace.snapshots.some((other) => other.supersedes_snapshot_id === snapshot.id),
  );

  const addSnapshot = useMutation({
    mutationFn: (input: { normalized: Record<string, unknown>; retrievedAt: string }) => recordIpRegistryManualSnapshot({
      linkId: link.id,
      expectedLinkVersion: link.version,
      idempotencyKey: randomKey("manual-snapshot"),
      sourceUrl: sourceUrl.trim(),
      sourceRetrievedAt: input.retrievedAt,
      parserVersion: "manual-register-form-v1",
      attribution: { publisher: link.office, capture_method: "manual_register_form" },
      rawSnapshot: {
        capture_method: "manual_register_form",
        register_record: input.normalized,
        ...(sourceText.trim() ? { source_text: sourceText.trim() } : {}),
      },
      normalizedSnapshot: input.normalized,
      supersedesSnapshotId: supersedes || null,
      correctionReason: supersedes ? correctionReason.trim() : null,
    }),
    onSuccess: async (result) => {
      toast.success(result.no_change ? "No-change observation recorded." : `${result.diffs.length} registry change${result.diffs.length === 1 ? "" : "s"} queued for review.`);
      await onChanged();
    },
    onError: (error) => {
      const fields = apiFieldErrors(error, SNAPSHOT_FIELD_MAP);
      const message = apiErrorMessage(error, "Could not record the register evidence.");
      setErrors(Object.keys(fields).length > 0 ? fields : { [API_FORM_ERROR_KEY]: message });
      toast.error(message);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const next: Record<string, string> = {};
    const normalized = normalizedRegisterRecord(form, values, parties);
    if (Object.keys(normalized).length === 0) next[API_FORM_ERROR_KEY] = "Enter at least one detail shown on the register.";
    if (!/^https?:\/\/\S+$/i.test(sourceUrl.trim())) next["snapshot-source"] = "Enter the register page address, starting with https://.";
    const viewed = new Date(viewedAt);
    if (Number.isNaN(viewed.getTime())) next["snapshot-viewed-at"] = "Enter when you viewed the register.";
    else if (viewed.getTime() > Date.now() + 60_000) next["snapshot-viewed-at"] = "The viewing time cannot be in the future.";
    if (supersedes && correctionReason.trim().length < 3) next["correction-reason"] = "Say why the earlier snapshot is being corrected.";
    setErrors(next);
    if (Object.keys(next).length > 0) return;
    addSnapshot.mutate({ normalized, retrievedAt: viewed.toISOString() });
  }

  const disabled = !confirmed || addSnapshot.isPending;
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h3">Record register evidence</CardTitle>
        <p className="text-sm text-[var(--color-mute)]">
          Manual path: enter what the official register shows for this identity. Each entry is kept
          as immutable evidence; a correction supersedes an earlier entry, it never overwrites it.
        </p>
      </CardHeader>
      <CardContent>
        <form className="flex min-w-0 flex-col gap-5" onSubmit={submit} noValidate>
          {!confirmed ? (
            <p id="register-evidence-blocked" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              Confirm the registry match above before recording register evidence.
            </p>
          ) : null}
          <fieldset className="grid min-w-0 gap-4 sm:grid-cols-2 xl:grid-cols-3" disabled={disabled} aria-describedby={!confirmed ? "register-evidence-blocked" : undefined}>
            <legend className="mb-2 text-sm font-semibold">As shown on the register</legend>
            {form.fields.map((field) => {
              const id = registerFieldId(field.path);
              return (
                <div className="min-w-0" key={field.path}>
                  <Label htmlFor={id}>{field.label}</Label>
                  <Input
                    id={id}
                    type={field.input}
                    className="mt-1"
                    value={values[field.path] ?? ""}
                    onChange={(event) => setValues((current) => ({ ...current, [field.path]: event.target.value }))}
                  />
                </div>
              );
            })}
          </fieldset>
          {parties ? (
            <fieldset className="flex min-w-0 flex-col gap-3" disabled={disabled}>
              <legend className="mb-1 text-sm font-semibold">Parties on the register</legend>
              {parties.length === 0 ? <p className="text-sm text-[var(--color-mute)]">No party is recorded for this identity.</p> : null}
              {parties.map((party, index) => (
                <div className="grid min-w-0 gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto]" key={index}>
                  <div className="min-w-0">
                    <Label htmlFor={`register-party-${index}-name`}>Party {index + 1} name</Label>
                    <Input id={`register-party-${index}-name`} className="mt-1" value={party.name} onChange={(event) => setParties((rows) => (rows ?? []).map((row, at) => (at === index ? { ...row, name: event.target.value } : row)))} />
                  </div>
                  <div className="min-w-0">
                    <Label htmlFor={`register-party-${index}-role`}>Party {index + 1} role</Label>
                    <Input id={`register-party-${index}-role`} className="mt-1" value={party.role} onChange={(event) => setParties((rows) => (rows ?? []).map((row, at) => (at === index ? { ...row, role: event.target.value } : row)))} />
                  </div>
                  <div className="flex items-end">
                    <Button type="button" variant="ghost" size="sm" onClick={() => setParties((rows) => (rows ?? []).filter((_, at) => at !== index))}>
                      <Trash2 className="h-4 w-4" aria-hidden />Remove party {index + 1}
                    </Button>
                  </div>
                </div>
              ))}
              <div>
                <Button type="button" variant="outline" size="sm" onClick={() => setParties((rows) => [...(rows ?? []), { name: "", role: "proprietor" }])}>
                  <Plus className="h-4 w-4" aria-hidden />Add party
                </Button>
              </div>
            </fieldset>
          ) : null}
          <fieldset className="grid min-w-0 gap-4 lg:grid-cols-2" disabled={disabled}>
            <legend className="mb-2 text-sm font-semibold">Source</legend>
            <div className="min-w-0 lg:col-span-2">
              <Label htmlFor="snapshot-text">Text shown on the register page (optional)</Label>
              <Textarea id="snapshot-text" className="mt-1 min-h-24 text-sm" value={sourceText} onChange={(event) => setSourceText(event.target.value)} placeholder="Copy the status, dates and proprietor lines from the register page." />
            </div>
            <div className="min-w-0">
              <Label htmlFor="snapshot-source">Register page URL</Label>
              <Input {...fieldProps("snapshot-source", errors)} type="url" className="mt-1" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} required />
              <FieldError id="snapshot-source-error" message={errors["snapshot-source"]} />
            </div>
            <div className="min-w-0">
              <Label htmlFor="snapshot-viewed-at">Viewed on the register at</Label>
              <Input {...fieldProps("snapshot-viewed-at", errors)} type="datetime-local" className="mt-1" value={viewedAt} onChange={(event) => setViewedAt(event.target.value)} required />
              <FieldError id="snapshot-viewed-at-error" message={errors["snapshot-viewed-at"]} />
            </div>
            {correctable.length > 0 ? (
              <div className="min-w-0">
                <RecordSelect
                  id="supersedes-snapshot"
                  label="Corrects an earlier entry"
                  className={FIELD_CLASS}
                  value={supersedes}
                  onChange={(event) => setSupersedes(event.target.value)}
                  options={[
                    { value: "", label: "No, this is a new observation" },
                    ...correctable.map((snapshot) => ({ value: snapshot.id, label: snapshotLabel(snapshot) })),
                  ]}
                />
                <FieldError id="supersedes-snapshot-error" message={errors["supersedes-snapshot"]} />
              </div>
            ) : (
              <div className="min-w-0 text-sm">
                <span className="font-medium">Corrects an earlier entry</span>
                <p className="mt-1 text-[var(--color-mute)]">
                  {workspace.snapshots.length === 0
                    ? "Nothing to correct yet: this will be the first entry for this identity."
                    : "Every earlier entry already has a correction; record a new observation instead."}
                </p>
              </div>
            )}
            {supersedes ? (
              <div className="min-w-0">
                <Label htmlFor="correction-reason">Correction reason</Label>
                <Input {...fieldProps("correction-reason", errors)} className="mt-1" value={correctionReason} onChange={(event) => setCorrectionReason(event.target.value)} required />
                <FieldError id="correction-reason-error" message={errors["correction-reason"]} />
              </div>
            ) : null}
          </fieldset>
          {errors[API_FORM_ERROR_KEY] ? <p role="alert" className="break-words text-sm text-[var(--color-danger-500)]">{errors[API_FORM_ERROR_KEY]}</p> : null}
          <div>
            <Button type="submit" disabled={disabled} aria-describedby={!confirmed ? "register-evidence-blocked" : undefined}>
              {addSnapshot.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
              Record register evidence
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function CourtReferences({ docket, core, references, bookmarks, canSync, onChanged }: { docket: IpDocket; core: UseQueryResult<IpCoreRecords>; references: Awaited<ReturnType<typeof fetchIpTrackedCaseReferences>>; bookmarks: Awaited<ReturnType<typeof listCaseTrackingBookmarks>>["bookmarks"]; canSync: boolean; onChanged: () => Promise<void> }) {
  const proceedings = useMemo(
    () => (core.data ? registryTargets(core.data).filter((row) => row.kind === "proceeding") : []),
    [core.data],
  );
  const [proceedingId, setProceedingId] = useState("");
  const [trackedCaseId, setTrackedCaseId] = useState("");
  const [purpose, setPurpose] = useState("Opposition or appeal tracking");
  const [evidence, setEvidence] = useState("");
  const [reason, setReason] = useState("");
  const eligible = bookmarks.filter((row) => Boolean(docket.matter_id) && row.matter_id === docket.matter_id);
  // Remounted per docket (keyed by the parent), so a choice never outlives its docket.
  useEffect(() => { if (!proceedingId && proceedings[0]) setProceedingId(proceedings[0].id); }, [proceedingId, proceedings]);
  useEffect(() => { if (!trackedCaseId && eligible[0]) setTrackedCaseId(eligible[0].tracked_case_id); }, [eligible, trackedCaseId]);
  const create = useMutation({ mutationFn: () => createIpTrackedCaseReference({ docketId: docket.id, proceedingId, trackedCaseId, purpose, evidenceReference: evidence }), onSuccess: async () => { toast.success("Canonical court tracking reference added."); setEvidence(""); await onChanged(); }, onError: (error) => toast.error(apiErrorMessage(error, "Could not add the court reference.")) });
  const decide = useMutation({ mutationFn: ({ id, version, decision }: { id: string; version: number; decision: "confirm" | "mismatch" | "retire" }) => decideIpTrackedCaseReference({ linkId: id, expectedVersion: version, decision, reason }), onSuccess: async () => { toast.success("Court reference decision recorded."); setReason(""); await onChanged(); }, onError: (error) => toast.error(apiErrorMessage(error, "Could not update the court reference.")) });
  const notice = (text: string) => <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{text}</div>;
  let addForm;
  if (!docket.matter_id) addForm = notice("Link this IP docket to a Matter before referencing court tracking.");
  else if (core.isPending) addForm = <p role="status" className="text-sm text-[var(--color-mute)]">Loading this docket&apos;s proceedings…</p>;
  else if (core.isError) addForm = <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-[var(--color-danger-500)]"><span className="min-w-0 break-words">Proceedings could not be loaded: {apiErrorMessage(core.error, "Request failed.")}</span><Button type="button" size="sm" variant="outline" onClick={() => core.refetch()}>Retry</Button></div>;
  else if (proceedings.length === 0) addForm = notice("This docket has no IP proceeding yet. Open an opposition or post-registration proceeding on the docket before referencing court tracking.");
  else if (eligible.length === 0) addForm = notice("Bookmark a tracked court case to the linked Matter first.");
  else addForm = <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5"><RecordSelect id="court-proceeding" label="IP proceeding" className={FIELD_CLASS} value={proceedingId} onChange={(event) => setProceedingId(event.target.value)} options={proceedings.map((row) => ({ value: row.id, label: row.label }))} /><div><Label htmlFor="tracked-case">Matter tracked case</Label><select id="tracked-case" className="mt-1 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={trackedCaseId} onChange={(event) => setTrackedCaseId(event.target.value)}>{eligible.map((row) => <option value={row.tracked_case_id} key={row.id}>{row.tracked_case.case_title}</option>)}</select></div><div><Label htmlFor="court-purpose">Purpose</Label><Input id="court-purpose" className="mt-1" value={purpose} onChange={(event) => setPurpose(event.target.value)} /></div><div><Label htmlFor="court-evidence">Evidence reference</Label><Input id="court-evidence" className="mt-1" value={evidence} onChange={(event) => setEvidence(event.target.value)} /></div><div className="flex items-end"><Button className="w-full" disabled={!proceedingId || !trackedCaseId || purpose.trim().length < 3 || evidence.trim().length < 3 || create.isPending} onClick={() => create.mutate()}><Link2 className="h-4 w-4" />Add reference</Button></div></div>;
  return <Card><CardHeader><CardTitle as="h2">Court proceeding references</CardTitle><p className="text-sm text-[var(--color-mute)]">References reuse canonical TrackedCase and Matter bookmark data; court updates are never copied into the IP record.</p></CardHeader><CardContent className="flex flex-col gap-5">{references.length ? <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-sm"><thead><tr className="border-b border-[var(--color-line)] text-xs uppercase text-[var(--color-mute)]"><th className="px-3 py-2">Case</th><th className="px-3 py-2">Court</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Updates</th><th className="px-3 py-2">Reference</th></tr></thead><tbody>{references.map((row) => <tr className="border-b border-[var(--color-line)]" key={row.id}><td className="px-3 py-3"><strong>{row.case_title}</strong><div className="mt-1 text-xs text-[var(--color-mute)]">{row.cnr_number ?? row.case_number ?? "No court identifier"}</div></td><td className="px-3 py-3">{row.court_name ?? "Not recorded"}</td><td className="px-3 py-3"><Badge tone={statusTone(row.link_status)}>{row.link_status}</Badge></td><td className="px-3 py-3 tabular-nums">{row.update_count}</td><td className="px-3 py-3">{canSync ? <div className="flex gap-1"><Button size="sm" variant="outline" disabled={reason.trim().length < 5 || decide.isPending} onClick={() => decide.mutate({ id: row.id, version: row.version, decision: "mismatch" })}>Mismatch</Button><Button size="sm" variant="ghost" disabled={reason.trim().length < 5 || decide.isPending} onClick={() => decide.mutate({ id: row.id, version: row.version, decision: "retire" })}>Retire</Button></div> : null}</td></tr>)}</tbody></table></div> : <p className="text-sm text-[var(--color-mute)]">No court tracking references are attached to this IP docket.</p>}{canSync ? <>{references.length ? <div><Label htmlFor="court-reference-reason">Decision reason</Label><Input id="court-reference-reason" className="mt-1" value={reason} onChange={(event) => setReason(event.target.value)} /></div> : null}{addForm}</> : null}</CardContent></Card>;
}
