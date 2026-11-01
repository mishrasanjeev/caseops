"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  UserPlus,
  X,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { toast } from "sonner";

import { IpDocketPicker } from "@/components/ip/IpDocketPicker";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { PersonName, PersonPicker } from "@/components/ui/PersonPicker";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { RecordSelect } from "@/components/ui/RecordSelect";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import {
  API_FORM_ERROR_KEY,
  apiErrorMessage,
  apiFieldErrors,
  humanizeApiFieldPath,
  isApiErrorShape,
} from "@/lib/api/config";
import {
  createIpWatchHandoff,
  createIpWatchProfile,
  decideIpWatchHit,
  fetchIpCoreRecords,
  fetchIpWatchWorkspace,
  fetchIpWorkspaceReadiness,
  ingestIpJournal,
  listCompanyUsers,
  searchIpJournalPublications,
  updateIpWatchProfileStatus,
  type IpCoreRecords,
  type IpFeatureReadiness,
  type IpJournalIngestionRun,
  type IpJournalIngestResult,
  type IpJournalPublication,
  type IpWatchDisposition,
  type IpWatchHandoff,
  type IpWatchHit,
  type IpWatchProfile,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import {
  CAPTURE_FIELDS,
  CAPTURE_LABELS,
  EMPTY_JOURNAL_CAPTURE,
  buildJournalCapture,
  captureFieldMap,
  goodsFieldId,
  type JournalCaptureForm,
} from "@/lib/ip/journal-capture";
import { parseJurisdictions } from "@/lib/ip/jurisdictions";
import { parseNiceClasses } from "@/lib/ip/nice-classes";
import { mergeWatchPages, nextWatchOffset, watchCountText } from "@/lib/ip/watch-pages";
import { useSession } from "@/lib/use-session";

const DATE = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" });
const STAMP = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const SELECT_CLASS =
  "mt-1 h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm aria-[invalid=true]:border-[var(--color-danger-500)]";

type View = "profiles" | "ingest" | "hits" | "runs";
type FieldErrors = Record<string, string>;
type BlockedReason = NonNullable<IpFeatureReadiness["blocked_reasons"]>[number];

function splitTerms(value: string) {
  return Array.from(new Set(value.split(/[,;\n]/).map((item) => item.trim()).filter(Boolean)));
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

function errorIdFor(fieldId: string) {
  return `${fieldId}-error`;
}

/** Split an API failure into field messages and one form-level message. */
function formErrorsFrom(
  error: unknown,
  fieldMap: Readonly<Record<string, string>>,
  fallback: string,
): { fields: FieldErrors; form: string | null } {
  const mapped = apiFieldErrors(error, fieldMap);
  if (Object.keys(mapped).length === 0) return { fields: {}, form: apiErrorMessage(error, fallback) };
  const known = new Set(Object.values(fieldMap));
  const fields: FieldErrors = {};
  const leftovers: string[] = [];
  for (const [key, message] of Object.entries(mapped)) {
    if (known.has(key)) fields[key] = message;
    else if (key === API_FORM_ERROR_KEY) leftovers.push(message);
    else leftovers.push(`${humanizeApiFieldPath(key.split("."))}: ${message}`);
  }
  return {
    fields,
    form: leftovers.length ? leftovers.join("; ") : "Correct the highlighted fields and try again.",
  };
}

function focusFirst(errors: FieldErrors, order: readonly string[]) {
  const first = order.find((id) => errors[id]) ?? Object.keys(errors)[0];
  if (first) document.getElementById(first)?.focus();
}

function applicationLabel(
  application: IpCoreRecords["applications"][number],
  core: IpCoreRecords | undefined,
) {
  const asset = core?.assets.find((item) => item.id === application.asset_id);
  const number = core?.identifiers.find(
    (row) =>
      row.application_id === application.id &&
      row.identifier_kind === "application" &&
      row.effective_until === null,
  )?.raw_value;
  return [
    asset?.title ?? "Trademark application",
    number ? `Application ${number}` : "No application number recorded",
    `${application.office} · ${application.filing_phase.replaceAll("_", " ")}`,
  ].join(" · ");
}

function publicationLabel(item: IpJournalPublication) {
  return [
    `Journal ${item.journal_number}`,
    DATE.format(new Date(item.journal_date)),
    `Application ${item.application_number}`,
    item.mark_text || "Device mark",
  ].join(" · ");
}

export default function IpJournalWatchPage() {
  const canRead = useCapability("ip:read");
  const canManage = useCapability("ip:watch_manage");
  const session = useSession();
  const queryClient = useQueryClient();
  const [view, setView] = useState<View>("hits");
  // "" is the explicit "All accessible dockets" scope; the picker never picks one itself.
  const [docketId, setDocketId] = useState("");
  const [selectedHitId, setSelectedHitId] = useState("");

  // Every list is paged with its server total; "Load more" reads the next
  // offset of all of them (B4-ADJ-05: the lists stopped at 250 silently).
  const workspace = useInfiniteQuery({
    queryKey: ["ip", "watch", docketId],
    queryFn: ({ pageParam }) => fetchIpWatchWorkspace(docketId || null, { offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (_last, pages) => nextWatchOffset(pages),
    enabled: canRead,
  });
  const data = useMemo(() => mergeWatchPages(workspace.data?.pages ?? []), [workspace.data]);
  const more: MoreRows = {
    hasMore: Boolean(workspace.hasNextPage),
    loading: workspace.isFetchingNextPage,
    error: workspace.isFetchNextPageError ? workspace.error : null,
    onLoadMore: () => void workspace.fetchNextPage(),
    onRefresh: () => void refresh(),
  };
  const core = useQuery({
    queryKey: ["ip", "core-records", docketId],
    queryFn: () => fetchIpCoreRecords(docketId),
    enabled: canRead && Boolean(docketId),
  });
  const readiness = useQuery({
    queryKey: ["ip", "readiness"],
    queryFn: fetchIpWorkspaceReadiness,
    enabled: canRead,
  });

  useEffect(() => {
    const hits = data?.hits ?? [];
    if (!hits.some((hit) => hit.id === selectedHitId)) setSelectedHitId(hits[0]?.id ?? "");
  }, [selectedHitId, data]);

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

  const profiles = data?.profiles ?? [];
  const hits = data?.hits ?? [];
  const selectedHit = hits.find((hit) => hit.id === selectedHitId) ?? null;
  const publication = selectedHit
    ? data?.publications.find((item) => item.id === selectedHit.publication_id) ?? null
    : null;
  const selectedProfile = selectedHit
    ? [...profiles, ...(data?.hit_profiles ?? [])].find((item) => item.id === selectedHit.profile_id) ?? null
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

      <WatchReadiness
        feature={readiness.data?.features.find((item) => item.feature_id === "watch_operations") ?? null}
        loading={readiness.isPending}
        error={readiness.isError ? readiness.error : null}
        onRetry={() => readiness.refetch()}
        canManage={canManage}
      />

      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-[var(--color-line)] pb-4">
        <IpDocketPicker
          id="watch-docket"
          label="Docket scope"
          emptyOptionLabel="All accessible dockets"
          value={docketId}
          onChange={(next) => setDocketId(next)}
          className="w-full sm:max-w-lg"
        />
        <div
          role="group"
          aria-label="Watch views"
          className="grid w-full min-w-0 grid-cols-2 overflow-hidden rounded-md border border-[var(--color-line)] bg-white sm:w-auto sm:grid-cols-4"
        >
          {(["hits", "profiles", "ingest", "runs"] as View[]).map((item) => (
            <button
              key={item}
              type="button"
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

      {workspace.isPending ? (
        <div className="grid gap-4 lg:grid-cols-3"><Skeleton className="h-56" /><Skeleton className="h-56 lg:col-span-2" /></div>
      ) : workspace.isError ? (
        <QueryErrorState error={workspace.error} title="Could not load journal watch" onRetry={refresh} />
      ) : view === "profiles" ? (
        <ProfilesView
          profiles={profiles}
          profileTotal={data?.profile_total ?? 0}
          more={more}
          scopeDocketId={docketId}
          membershipId={session.context?.membership.id ?? ""}
          canManage={canManage}
          onChanged={refresh}
        />
      ) : view === "ingest" ? (
        <JournalIntake
          docketId={docketId}
          publications={data?.publications ?? []}
          publicationTotal={data?.publication_total ?? 0}
          more={more}
          core={core.data}
          intakeProfileCount={data?.intake_profile_count ?? 0}
          canManage={canManage}
          onCreateProfile={() => setView("profiles")}
          onRecorded={refresh}
          onReviewHits={(hitId) => {
            setSelectedHitId(hitId);
            setView("hits");
          }}
        />
      ) : view === "runs" ? (
        <RunsView
          profiles={profiles}
          pausedTotal={data?.paused_profile_total ?? 0}
          runs={data?.ingestion_runs ?? []}
          runTotal={data?.ingestion_run_total ?? 0}
        />
      ) : (
        <HitsView
          hits={hits}
          hitTotal={data?.hit_total ?? 0}
          more={more}
          profiles={profiles}
          publication={publication}
          selectedHit={selectedHit}
          selectedProfile={selectedProfile}
          selectedHitId={selectedHitId}
          setSelectedHitId={setSelectedHitId}
          handoffs={data?.handoffs ?? []}
          core={core.data}
          membershipId={session.context?.membership.id ?? ""}
          canManage={canManage}
          onChanged={refresh}
        />
      )}
    </div>
  );
}

const BLOCKED_REASON_TEXT: Record<BlockedReason, string> = {
  incident_kill_switch: "A risk incident has stopped automated journal polling.",
  rollout_disabled: "CaseOps has not switched automated journal polling on yet.",
  rollout_expired: "The approved pilot window for automated journal polling has ended.",
  missing_entitlement: "Automated journal polling is not part of this workspace's plan.",
  workspace_not_configured: "IP workspace setup has not been saved.",
  tenant_disabled: "IP workspace enablement has not passed.",
  readiness_test_failed: "The latest IP readiness test has not passed.",
  missing_capability: "Your role does not include journal-watch management.",
  unknown_feature: "Automated journal polling is not in the approved catalogue.",
};

const BLOCKED_CATEGORY: Record<BlockedReason, string> = {
  incident_kill_switch: "Paused by CaseOps",
  rollout_disabled: "Paused by CaseOps",
  rollout_expired: "Paused by CaseOps",
  missing_entitlement: "Not in your plan",
  workspace_not_configured: "Needs setup",
  tenant_disabled: "Needs setup",
  readiness_test_failed: "Needs setup",
  missing_capability: "Your role cannot",
  unknown_feature: "Unavailable",
};

/** What the reader can do about each gate (who to ask, or that nothing is needed). */
const BLOCKED_CATEGORY_PATH: Record<string, string> = {
  "Paused by CaseOps": "CaseOps controls this switch; nothing needs to change in your workspace.",
  "Not in your plan": "A workspace owner can ask CaseOps to add journal watch to the plan.",
  "Your role cannot": "Ask a workspace owner or admin for journal-watch management access.",
  Unavailable: "Contact CaseOps support if you expected automated polling here.",
};

/**
 * Manual intake and automated polling are different promises. Manual intake
 * (the operator records each journal entry) needs only journal-watch
 * management. No automated journal source is connected to CaseOps: the
 * scheduler never contacts a journal (services/ip_watch.py
 * run_journal_watch_scheduler), so "Available" is never claimed for it even
 * when every readiness gate passes. Each gate that is closed is still named.
 */
function WatchReadiness({
  feature,
  loading,
  error,
  onRetry,
  canManage,
}: {
  feature: IpFeatureReadiness | null;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  canManage: boolean;
}) {
  const reasons: BlockedReason[] = feature
    ? feature.blocked_reasons?.length
      ? feature.blocked_reasons
      : feature.reason === "available"
        ? []
        : [feature.reason]
    : [];
  const categories = Array.from(new Set(reasons.map((reason) => BLOCKED_CATEGORY[reason])));
  const needsSetup = categories.includes("Needs setup");
  return (
    <section
      aria-labelledby="watch-readiness-title"
      data-testid="watch-readiness"
      className="grid min-w-0 gap-3 rounded-md border border-[var(--color-line)] bg-white p-4 text-sm md:grid-cols-2"
    >
      <h2 id="watch-readiness-title" className="sr-only">Journal watch availability</h2>
      <div className="min-w-0" data-testid="watch-readiness-manual">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold">Manual journal intake</span>
          <Badge tone={canManage ? "success" : "neutral"}>{canManage ? "Available" : "Your role cannot"}</Badge>
        </div>
        <p className="mt-1 break-words text-[var(--color-mute)]">
          {canManage
            ? "This is the manual path: you record each official journal entry with its evidence, and it is compared with every active watch profile you can see."
            : "Your role does not include journal-watch management, so you can review hits but not record journal entries."}
        </p>
      </div>
      <div className="min-w-0" data-testid="watch-readiness-automated">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold">Automated journal polling</span>
          {loading ? (
            <span className="text-[var(--color-mute)]" role="status">Checking availability…</span>
          ) : error ? null : (
            <>
              <Badge tone="neutral">No journal source connected</Badge>
              {categories.map((category) => <Badge key={category} tone="warning">{category}</Badge>)}
            </>
          )}
        </div>
        {error ? (
          <div role="alert" className="mt-1 flex flex-wrap items-center gap-2 text-[var(--color-danger-500)]">
            <span className="min-w-0 break-words">Could not load automation availability: {apiErrorMessage(error, "Request failed.")}</span>
            <Button type="button" size="sm" variant="outline" onClick={onRetry}>Try again</Button>
          </div>
        ) : loading ? null : (
          <>
            <p className="mt-1 break-words text-[var(--color-mute)]">
              No automated journal source is connected to CaseOps, so scheduled checks never contact a journal. Record each official journal entry through manual intake.
            </p>
            {reasons.length ? (
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-[var(--color-mute)]" aria-label="Closed automation gates">
                {reasons.map((reason) => (
                  <li key={reason} className="break-words">
                    <span className="font-medium text-[var(--color-ink)]">{BLOCKED_CATEGORY[reason]}:</span> {BLOCKED_REASON_TEXT[reason]}{" "}
                    {BLOCKED_CATEGORY[reason] === "Needs setup" ? null : BLOCKED_CATEGORY_PATH[BLOCKED_CATEGORY[reason]]}
                  </li>
                ))}
              </ul>
            ) : null}
            {needsSetup ? <p className="mt-1"><Link className="font-semibold text-[var(--color-brand-700)]" href="/app/ip">Open IP workspace setup</Link></p> : null}
          </>
        )}
      </div>
    </section>
  );
}

const PROFILE_FIELDS = [
  "profile-docket",
  "profile-name",
  "profile-words",
  "profile-phonetic",
  "profile-devices",
  "profile-classes",
  "profile-jurisdictions",
  "profile-proprietors",
  "profile-recipients-picker",
  "profile-frequency",
  "profile-cost",
] as const;

const PROFILE_FIELD_MAP: Record<string, string> = {
  docket_id: "profile-docket",
  name: "profile-name",
  word_terms: "profile-words",
  phonetic_terms: "profile-phonetic",
  device_references: "profile-devices",
  class_numbers: "profile-classes",
  proprietor_terms: "profile-proprietors",
  jurisdictions: "profile-jurisdictions",
  recipient_membership_ids: "profile-recipients-picker",
  frequency: "profile-frequency",
  max_cost_minor_per_period: "profile-cost",
  cost_currency: "profile-cost",
};

type MoreRows = {
  hasMore: boolean;
  loading: boolean;
  error: unknown;
  onLoadMore: () => void;
  onRefresh: () => void;
};

/** "Showing N of M …" with the way to the rest, or the complete count. */
function ListCount({ loaded, total, noun, more }: {
  loaded: number;
  total: number;
  noun: [string, string];
  more: MoreRows;
}) {
  const short = loaded < total;
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm text-[var(--color-mute)]" data-testid={`watch-count-${noun[1].replaceAll(" ", "-")}`}>
      <span role="status" className="min-w-0 break-words">
        {watchCountText(loaded, total, noun)}
        {short && !more.hasMore ? " The list changed while it was loading." : ""}
      </span>
      {short && more.hasMore ? (
        <Button type="button" size="sm" variant="outline" disabled={more.loading} onClick={more.onLoadMore}>
          {more.loading ? "Loading…" : `Load more ${noun[1]}`}
        </Button>
      ) : short ? (
        <Button type="button" size="sm" variant="outline" onClick={more.onRefresh}>Refresh</Button>
      ) : null}
      {more.error ? (
        <span role="alert" className="flex min-w-0 flex-wrap items-center gap-2 text-[var(--color-danger-500)]">
          <span className="min-w-0 break-words">More could not be loaded: {apiErrorMessage(more.error, "Request failed.")}</span>
          <Button type="button" size="sm" variant="outline" onClick={more.onLoadMore}>Retry</Button>
        </span>
      ) : null}
    </div>
  );
}

function ProfilesView({
  profiles,
  profileTotal,
  more,
  scopeDocketId,
  membershipId,
  canManage,
  onChanged,
}: {
  profiles: IpWatchProfile[];
  profileTotal: number;
  more: MoreRows;
  scopeDocketId: string;
  membershipId: string;
  canManage: boolean;
  onChanged: () => Promise<void>;
}) {
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: createIpWatchProfile,
    onSuccess: async () => {
      toast.success("Watch profile created.");
      setErrors({});
      setFormError(null);
      await onChanged();
    },
    onError: (error) => {
      const result = formErrorsFrom(error, PROFILE_FIELD_MAP, "Could not create watch profile.");
      setErrors(result.fields);
      setFormError(result.form);
      focusFirst(result.fields, PROFILE_FIELDS);
    },
  });
  const status = useMutation({
    mutationFn: updateIpWatchProfileStatus,
    onSuccess: async () => { toast.success("Watch profile status updated."); await onChanged(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not update watch profile.")),
  });
  const [profileDocketId, setProfileDocketId] = useState(scopeDocketId);
  const [name, setName] = useState("");
  const [words, setWords] = useState("");
  const [phonetic, setPhonetic] = useState("");
  const [devices, setDevices] = useState("");
  const [classNumbers, setClassNumbers] = useState("");
  const [proprietors, setProprietors] = useState("");
  const [jurisdictions, setJurisdictions] = useState("IN");
  const [frequency, setFrequency] = useState<IpWatchProfile["frequency"]>("publication");
  const [recipients, setRecipients] = useState<string[]>(membershipId ? [membershipId] : []);
  const [candidate, setCandidate] = useState("");
  const [maxCost, setMaxCost] = useState("0");

  useEffect(() => {
    if (membershipId) setRecipients((current) => (current.length ? current : [membershipId]));
  }, [membershipId]);

  function clearError(id: string) {
    setErrors((current) => {
      if (!(id in current)) return current;
      const next = { ...current };
      delete next[id];
      return next;
    });
  }

  const typedJurisdictions = parseJurisdictions(jurisdictions);
  const outsideIntake = typedJurisdictions.codes.length > 0 && !typedJurisdictions.codes.includes("IN");

  function submit(event: FormEvent) {
    event.preventDefault();
    const parsed = parseNiceClasses(classNumbers);
    const deviceList = splitTerms(devices);
    const next: FieldErrors = {};
    if (!profileDocketId) next["profile-docket"] = "Choose the docket this watch belongs to.";
    if (name.trim().length < 2) next["profile-name"] = "Enter a profile name of at least 2 characters.";
    if (parsed.errors.length) next["profile-classes"] = parsed.errors.map((item) => item.message).join(" ");
    const jurisdictionList = parseJurisdictions(jurisdictions);
    if (jurisdictionList.error) next["profile-jurisdictions"] = jurisdictionList.error;
    if (deviceList.some((item) => !/^https?:\/\/\S+$/i.test(item))) {
      next["profile-devices"] = "Device evidence must be web links that start with https:// or http://.";
    }
    const hasCriterion =
      splitTerms(words).length > 0 ||
      splitTerms(phonetic).length > 0 ||
      deviceList.length > 0 ||
      parsed.classes.length > 0 ||
      splitTerms(proprietors).length > 0;
    if (!hasCriterion && !next["profile-classes"]) {
      next["profile-words"] =
        "Add at least one criterion: a word, phonetic term, device link, Nice class or proprietor.";
    }
    if (recipients.length === 0) next["profile-recipients-picker"] = "Choose at least one colleague to notify.";
    const cost = Number(maxCost.trim() || "0");
    if (!Number.isInteger(cost) || cost < 0) next["profile-cost"] = "Enter the limit in paise as a whole number (0 for no limit).";
    setFormError(null);
    setErrors(next);
    if (Object.keys(next).length) {
      focusFirst(next, PROFILE_FIELDS);
      return;
    }
    mutation.mutate({
      docketId: profileDocketId,
      name: name.trim(),
      providerKey: "manual-journal",
      wordTerms: splitTerms(words),
      phoneticTerms: splitTerms(phonetic),
      deviceReferences: deviceList,
      classNumbers: parsed.classes,
      proprietorTerms: splitTerms(proprietors),
      jurisdictions: jurisdictionList.codes,
      frequency,
      recipientMembershipIds: recipients,
      maxCostMinorPerPeriod: cost,
      costCurrency: "INR",
    });
  }

  return (
    <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
      <section className="flex min-w-0 flex-col gap-3" aria-label="Watch profiles">
        {profileTotal > 0 ? <ListCount loaded={profiles.length} total={profileTotal} noun={["watch profile", "watch profiles"]} more={more} /> : null}
        {profiles.length === 0 ? (
          <EmptyState title="No watch profiles" description="Create docket-specific criteria and recipients. Journal entries are compared with active profiles only." />
        ) : profiles.map((profile) => (
          <Card key={profile.id} data-testid={`watch-profile-${profile.id}`}>
            <CardHeader className="gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0"><CardTitle as="h2" className="break-words">{profile.name}</CardTitle><p className="mt-1 text-sm text-[var(--color-mute)]">{profile.provider_key === "manual-journal" ? "Manual journal intake" : profile.provider_key} · {profile.frequency}</p></div>
              <Badge tone={tone(profile.poll_status)}>{profile.poll_status.replaceAll("_", " ")}</Badge>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              {profile.pause_reason ? <div className="flex gap-2 border-l-2 border-amber-400 pl-3 text-amber-900"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{profile.pause_reason}</div> : null}
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Words / phonetics" value={[...profile.word_terms_json, ...profile.phonetic_terms_json].join(", ") || "None"} />
                <Field label="Classes / jurisdictions" value={[...profile.class_numbers_json.map((item) => `Class ${item}`), ...profile.jurisdictions_json].join(", ") || "None"} />
                <div className="min-w-0"><span className="text-[var(--color-mute)]">Recipients</span><ul className="mt-1 space-y-0.5 font-medium text-[var(--color-ink)]">{profile.recipient_membership_ids_json.map((id) => <li key={id} className="break-words"><PersonName membershipId={id} /></li>)}</ul></div>
                <Field label="Cost policy" value={`${profile.spent_cost_minor_in_period} / ${profile.max_cost_minor_per_period || "unlimited"} ${profile.cost_currency} paise`} />
                {profile.provider_key === "manual-journal" ? (
                  <>
                    <Field label="Last journal entry compared" value={profile.last_polled_at ? localDate(profile.last_polled_at) : "None yet"} />
                    <Field label="Scheduled check" value="None: manual intake only" />
                  </>
                ) : (
                  <>
                    <Field label="Last checked" value={localDate(profile.last_polled_at)} />
                    <Field label="Next check" value={localDate(profile.next_poll_at)} />
                  </>
                )}
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
      <Card className="min-w-0">
        <CardHeader><CardTitle as="h2">New watch profile</CardTitle></CardHeader>
        <CardContent>
          {!canManage ? <p className="text-sm text-[var(--color-mute)]">Your role cannot create watch profiles; journal-watch management access is required.</p> : (
            <form className="min-w-0 space-y-4" onSubmit={submit} noValidate aria-label="New watch profile">
              <IpDocketPicker
                id="profile-docket"
                label="Docket"
                value={profileDocketId}
                onChange={(next) => { setProfileDocketId(next); clearError("profile-docket"); }}
                error={errors["profile-docket"] ?? null}
                required
              />
              <TextField id="profile-name" label="Profile name" value={name} setValue={(value) => { setName(value); clearError("profile-name"); }} error={errors["profile-name"]} required />
              <TextField id="profile-words" label="Word terms" hint="Comma separated" value={words} setValue={(value) => { setWords(value); clearError("profile-words"); }} error={errors["profile-words"]} />
              <TextField id="profile-phonetic" label="Phonetic terms" hint="Comma separated" value={phonetic} setValue={(value) => { setPhonetic(value); clearError("profile-phonetic"); }} error={errors["profile-phonetic"]} />
              <TextField id="profile-devices" label="Device evidence URLs" hint="Comma separated web links" value={devices} setValue={(value) => { setDevices(value); clearError("profile-devices"); }} error={errors["profile-devices"]} />
              <div className="grid gap-3 sm:grid-cols-2">
                <TextField id="profile-classes" label="Nice classes" hint="For example: Class 30, 43" value={classNumbers} setValue={(value) => { setClassNumbers(value); clearError("profile-classes"); }} error={errors["profile-classes"]} />
                <div className="min-w-0">
                  <TextField id="profile-jurisdictions" label="Jurisdictions" hint="Codes or names, for example IN" value={jurisdictions} setValue={(value) => { setJurisdictions(value); clearError("profile-jurisdictions"); }} error={errors["profile-jurisdictions"]} />
                  {outsideIntake ? <p className="mt-1 break-words text-xs text-amber-900" data-testid="profile-jurisdiction-note">Journal intake records the IP India Trade Marks Journal (IN). A profile limited to {typedJurisdictions.codes.join(", ")} will not match those entries.</p> : null}
                </div>
              </div>
              <TextField id="profile-proprietors" label="Proprietor terms" hint="Comma separated" value={proprietors} setValue={(value) => { setProprietors(value); clearError("profile-proprietors"); }} error={errors["profile-proprietors"]} />
              <RecipientsField
                recipients={recipients}
                candidate={candidate}
                setCandidate={setCandidate}
                error={errors["profile-recipients-picker"]}
                onAdd={() => {
                  if (!candidate) return;
                  setRecipients((current) => (current.includes(candidate) ? current : [...current, candidate]));
                  setCandidate("");
                  clearError("profile-recipients-picker");
                }}
                onRemove={(id) => setRecipients((current) => current.filter((item) => item !== id))}
              />
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="min-w-0"><Label htmlFor="profile-frequency">Frequency</Label><select id="profile-frequency" className={SELECT_CLASS} value={frequency} onChange={(event) => setFrequency(event.target.value as IpWatchProfile["frequency"])}><option value="publication">Each publication</option><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select></div>
                <TextField id="profile-cost" label="Max cost per period (paise)" hint="0 means no limit" type="number" value={maxCost} setValue={(value) => { setMaxCost(value); clearError("profile-cost"); }} error={errors["profile-cost"]} />
              </div>
              {formError ? <p role="alert" className="break-words text-sm text-[var(--color-danger-500)]">{formError}</p> : null}
              <Button type="submit" className="w-full" disabled={mutation.isPending}>{mutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Radar className="h-4 w-4" />}Create profile</Button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/** Recipients are colleagues chosen by name; nobody types a membership id. */
function RecipientsField({
  recipients,
  candidate,
  setCandidate,
  error,
  onAdd,
  onRemove,
}: {
  recipients: string[];
  candidate: string;
  setCandidate: (value: string) => void;
  error?: string;
  onAdd: () => void;
  onRemove: (membershipId: string) => void;
}) {
  // Same directory and predicate the picker uses: when every active colleague
  // is already a recipient there is nothing to add, so the picker is disabled.
  const colleagues = useQuery({ queryKey: ["company-users"], queryFn: () => listCompanyUsers() });
  const nobodyToAdd = colleagues.isSuccess && !colleagues.data.users.some(
    (user) => user.membership_active && user.user_active && !recipients.includes(user.membership_id),
  );
  return (
    <fieldset className="min-w-0 space-y-2" aria-describedby={error ? errorIdFor("profile-recipients-picker") : undefined}>
      <legend className="text-sm font-medium text-[var(--color-ink)]">Recipients</legend>
      {recipients.length ? (
        <ul className="space-y-1" aria-label="Chosen recipients">
          {recipients.map((id) => (
            <li key={id} className="flex min-w-0 items-center justify-between gap-2 rounded-md border border-[var(--color-line)] px-3 py-1.5 text-sm">
              <span id={`recipient-${id}`} className="min-w-0 break-words"><PersonName membershipId={id} /></span>
              <Button type="button" size="sm" variant="ghost" aria-label="Remove recipient" aria-describedby={`recipient-${id}`} onClick={() => onRemove(id)}><X className="h-4 w-4" /></Button>
            </li>
          ))}
        </ul>
      ) : <p className="text-sm text-[var(--color-mute)]">No recipient chosen yet.</p>}
      <Label htmlFor="profile-recipients-picker">Add a recipient</Label>
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start">
        <PersonPicker
          id="profile-recipients-picker"
          value={candidate}
          onChange={setCandidate}
          excludeMembershipIds={recipients}
          disabled={nobodyToAdd}
          className="min-w-0 flex-1"
        />
        <Button type="button" variant="outline" size="sm" className="sm:mt-1" disabled={!candidate || nobodyToAdd} onClick={onAdd}><UserPlus className="h-4 w-4" />Add recipient</Button>
      </div>
      {error ? <p id={errorIdFor("profile-recipients-picker")} className="break-words text-sm text-[var(--color-danger-500)]">{error}</p> : null}
    </fieldset>
  );
}

const CAPTURE_ORDER = [
  CAPTURE_FIELDS.application,
  CAPTURE_FIELDS.journalNumber,
  CAPTURE_FIELDS.journalDate,
  CAPTURE_FIELDS.kind,
  CAPTURE_FIELDS.supersedes,
  CAPTURE_FIELDS.correctionReason,
  CAPTURE_FIELDS.applicationNumber,
  CAPTURE_FIELDS.markText,
  CAPTURE_FIELDS.deviceReference,
  CAPTURE_FIELDS.proprietor,
  CAPTURE_FIELDS.classes,
  CAPTURE_FIELDS.goods,
  CAPTURE_FIELDS.scope,
  CAPTURE_FIELDS.sourceUrl,
  CAPTURE_FIELDS.sourcePage,
  CAPTURE_FIELDS.sourceStatus,
  CAPTURE_FIELDS.retrievedAt,
  CAPTURE_FIELDS.evidence,
  CAPTURE_FIELDS.cost,
] as const;

function JournalIntake({
  docketId,
  publications,
  publicationTotal,
  more,
  core,
  intakeProfileCount,
  canManage,
  onCreateProfile,
  onRecorded,
  onReviewHits,
}: {
  docketId: string;
  publications: IpJournalPublication[];
  publicationTotal: number;
  more: MoreRows;
  core: IpCoreRecords | undefined;
  intakeProfileCount: number;
  canManage: boolean;
  onCreateProfile: () => void;
  onRecorded: () => Promise<void>;
  onReviewHits: (hitId: string) => void;
}) {
  const [form, setForm] = useState<JournalCaptureForm>(EMPTY_JOURNAL_CAPTURE);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [recorded, setRecorded] = useState<IpJournalIngestResult | null>(null);
  const [conflict, setConflict] = useState<{ publicationId: string | null; applicationNumber: string } | null>(null);
  const [predecessorFilter, setPredecessorFilter] = useState("");
  const [predecessorQuery, setPredecessorQuery] = useState("");
  const [predecessor, setPredecessor] = useState<IpJournalPublication | null>(null);
  const parsedClasses = useMemo(() => parseNiceClasses(form.classNumbers).classes, [form.classNumbers]);
  const applications = core?.applications ?? [];
  const correcting = form.kind !== "advertisement";
  const canCapture = canManage && intakeProfileCount > 0;
  useEffect(() => {
    const timer = setTimeout(() => setPredecessorQuery(predecessorFilter.trim()), 250);
    return () => clearTimeout(timer);
  }, [predecessorFilter]);
  // Server-side search over every entry the viewer may see (the predicate the
  // API uses to accept a correction), not the recent page held by the workspace.
  const predecessorSearch = useQuery({
    queryKey: ["ip", "watch", "publications", predecessorQuery],
    queryFn: () => searchIpJournalPublications(predecessorQuery),
    enabled: canCapture && correcting,
  });
  const found = predecessorSearch.data?.publications ?? [];
  const predecessorOptions = predecessor && !found.some((item) => item.id === predecessor.id)
    ? [predecessor, ...found]
    : found;
  const nothingToCorrect =
    predecessorSearch.isSuccess && !predecessorQuery && predecessorOptions.length === 0;
  const mutation = useMutation({
    mutationFn: ingestIpJournal,
    onSuccess: async (result) => {
      setRecorded(result);
      setConflict(null);
      setErrors({});
      setFormError(null);
      if (result.run.status !== "paused_cost_quota") {
        setForm(EMPTY_JOURNAL_CAPTURE);
        setPredecessor(null);
      }
      await onRecorded();
    },
    onError: (error) => {
      if (isApiErrorShape(error) && error.status === 409 && error.problemType === "journal_entry_already_recorded") {
        const data = (error.data ?? {}) as { publication_id?: string | null };
        setErrors({});
        setFormError(error.detail);
        setConflict({ publicationId: data.publication_id ?? null, applicationNumber: form.applicationNumber.trim() });
        return;
      }
      const result = formErrorsFrom(error, captureFieldMap(parsedClasses), "Could not record the journal entry.");
      setErrors(result.fields);
      setFormError(result.form);
      focusFirst(result.fields, CAPTURE_ORDER);
    },
  });

  function update<K extends keyof JournalCaptureForm>(key: K, fieldId?: string) {
    return (value: JournalCaptureForm[K]) => {
      setForm((current) => ({ ...current, [key]: value }));
      if (fieldId) {
        setErrors((current) => {
          if (!(fieldId in current)) return current;
          const next = { ...current };
          delete next[fieldId];
          return next;
        });
      }
    };
  }

  function choosePredecessor(id: string) {
    const chosen = predecessorOptions.find((item) => item.id === id) ?? null;
    setPredecessor(chosen);
    // A correction keeps the corrected entry's application number (the API refuses
    // any other), so it is filled in and locked rather than typed.
    setForm((current) => ({
      ...current,
      supersedes: id,
      applicationNumber: chosen ? chosen.application_number : current.applicationNumber,
    }));
    setErrors((current) => {
      const next = { ...current };
      delete next[CAPTURE_FIELDS.supersedes];
      delete next[CAPTURE_FIELDS.applicationNumber];
      return next;
    });
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    setRecorded(null);
    setConflict(null);
    const outcome = buildJournalCapture(form);
    if (!outcome.ok) {
      setErrors(outcome.errors);
      setFormError("Correct the highlighted fields before recording the entry.");
      focusFirst(outcome.errors, CAPTURE_ORDER);
      return;
    }
    setErrors({});
    setFormError(null);
    mutation.mutate({
      idempotencyKey: randomKey(),
      providerKey: "ipindia-journal-manual",
      costMinor: outcome.costMinor,
      publication: outcome.publication,
    });
  }

  const errorCount = Object.keys(errors).length;
  const applicationNumberLocked = correcting && predecessor !== null && form.supersedes === predecessor.id;

  // Only the capture form is gated: recorded entries and the last result stay
  // visible to read-only users and when no profile is active.
  const gate = !canManage ? (
    <EmptyState title="Your role cannot record journal entries" description="Journal-watch management access is required to capture official journal evidence. Ask a workspace owner or admin for it. You can still review hits and recorded entries." />
  ) : intakeProfileCount === 0 ? (
    <EmptyState
      title="No active watch profile to compare with"
      description="Each journal entry is compared with the active watch profiles you can see. Create a watch profile, or resume a paused one, before recording an entry."
      action={<Button type="button" onClick={onCreateProfile}><Radar className="h-4 w-4" />Create a watch profile</Button>}
    />
  ) : null;

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {recorded ? <RecordedSummary result={recorded} onReviewHits={onReviewHits} onDismiss={() => setRecorded(null)} /> : null}
      {gate ?? <Card className="min-w-0">
        <CardHeader>
          <CardTitle as="h2">Manual official-journal intake</CardTitle>
          <p className="text-sm text-[var(--color-mute)]">This is the manual path. Record one entry exactly as the official journal publishes it; it is compared with {intakeProfileCount} active watch {intakeProfileCount === 1 ? "profile" : "profiles"} across every docket you can see.</p>
        </CardHeader>
        <CardContent>
          <form className="grid min-w-0 gap-4 lg:grid-cols-2" onSubmit={submit} noValidate aria-label="Manual official-journal intake">
            <div className="min-w-0 space-y-4">
              {!docketId ? (
                <p className="text-sm text-[var(--color-mute)]" id="watch-application-note"><span className="font-medium text-[var(--color-ink)]">Linked trademark application:</span> to link one of the firm&apos;s applications, choose its docket in Docket scope above. The entry can be recorded without a link.</p>
              ) : applications.length === 0 ? (
                <p className="text-sm text-[var(--color-mute)]" id="watch-application-note"><span className="font-medium text-[var(--color-ink)]">Linked trademark application:</span> this docket has no trademark application record, so the entry is recorded without a link.</p>
              ) : (
                <RecordSelect id={CAPTURE_FIELDS.application} label="Linked trademark application"
                  className={SELECT_CLASS}
                  value={form.applicationId} onChange={(event) => update("applicationId")(event.target.value)} options={[
                    { value: "", label: "No internal application link" },
                    ...applications.map((item) => ({ value: item.id, label: applicationLabel(item, core) })),
                  ]} />
              )}
              <div className="grid gap-3 sm:grid-cols-2">
                <TextField id={CAPTURE_FIELDS.journalNumber} label="Journal number" value={form.journalNumber} setValue={update("journalNumber", CAPTURE_FIELDS.journalNumber)} error={errors[CAPTURE_FIELDS.journalNumber]} required />
                <TextField id={CAPTURE_FIELDS.journalDate} label="Journal date" type="date" value={form.journalDate} setValue={update("journalDate", CAPTURE_FIELDS.journalDate)} error={errors[CAPTURE_FIELDS.journalDate]} required />
              </div>
              <div className="min-w-0"><Label htmlFor={CAPTURE_FIELDS.kind}>Publication kind</Label><select id={CAPTURE_FIELDS.kind} className={SELECT_CLASS} value={form.kind} onChange={(event) => update("kind")(event.target.value as JournalCaptureForm["kind"])}><option value="advertisement">Advertisement</option><option value="correction">Correction</option><option value="readvertisement">Re-advertisement</option></select></div>
              {correcting ? (
                <div className="min-w-0 space-y-2">
                  <div className="min-w-0"><Label htmlFor="supersedes-filter">Find the entry being corrected</Label><Input id="supersedes-filter" type="search" className="mt-1" value={predecessorFilter} onChange={(event) => setPredecessorFilter(event.target.value)} placeholder="Journal, application number or mark" aria-controls={CAPTURE_FIELDS.supersedes} /></div>
                  {predecessorSearch.isError ? (
                    <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-[var(--color-danger-500)]">
                      <span className="min-w-0 break-words">Could not search recorded entries: {apiErrorMessage(predecessorSearch.error, "Request failed.")}</span>
                      <Button type="button" size="sm" variant="outline" onClick={() => predecessorSearch.refetch()}>Try again</Button>
                    </div>
                  ) : (
                    <RecordSelect id={CAPTURE_FIELDS.supersedes} label="Journal entry being corrected" className={SELECT_CLASS}
                      value={form.supersedes} onChange={(event) => choosePredecessor(event.target.value)}
                      aria-invalid={errors[CAPTURE_FIELDS.supersedes] ? true : undefined}
                      aria-describedby={errors[CAPTURE_FIELDS.supersedes] ? errorIdFor(CAPTURE_FIELDS.supersedes) : undefined}
                      disabled={predecessorSearch.isPending || predecessorOptions.length === 0}
                      options={[
                        {
                          value: "",
                          label: predecessorSearch.isPending
                            ? "Searching recorded entries…"
                            : predecessorOptions.length
                              ? "Choose the recorded entry"
                              : predecessorQuery ? "No recorded entry matches" : "No recorded entry yet",
                          disabled: true,
                        },
                        ...predecessorOptions.map((item) => ({ value: item.id, label: publicationLabel(item) })),
                      ]} />
                  )}
                  {nothingToCorrect ? (
                    <p role="status" className="border-l-2 border-amber-400 pl-3 text-sm text-amber-900">No journal entry you can see is recorded yet, so there is nothing to correct. Record the original advertisement first.</p>
                  ) : predecessorSearch.isSuccess && predecessorOptions.length === 0 ? (
                    <p role="status" className="text-sm text-[var(--color-mute)]">No recorded entry you can see matches this search. Search by journal number, application number or mark.</p>
                  ) : (
                    <p className="text-xs text-[var(--color-mute)]">Searches every recorded entry you can see; the 25 most recent matches are listed.</p>
                  )}
                  <FieldError fieldId={CAPTURE_FIELDS.supersedes} message={errors[CAPTURE_FIELDS.supersedes]} />
                  <div className="min-w-0"><Label htmlFor={CAPTURE_FIELDS.correctionReason}>Correction reason</Label><Textarea id={CAPTURE_FIELDS.correctionReason} className="mt-1" value={form.correctionReason} onChange={(event) => update("correctionReason", CAPTURE_FIELDS.correctionReason)(event.target.value)} aria-invalid={errors[CAPTURE_FIELDS.correctionReason] ? true : undefined} aria-describedby={errors[CAPTURE_FIELDS.correctionReason] ? errorIdFor(CAPTURE_FIELDS.correctionReason) : undefined} /><FieldError fieldId={CAPTURE_FIELDS.correctionReason} message={errors[CAPTURE_FIELDS.correctionReason]} /></div>
                </div>
              ) : null}
              <TextField id={CAPTURE_FIELDS.applicationNumber} label="Registry application number" hint={applicationNumberLocked ? "Kept from the entry being corrected" : undefined} readOnly={applicationNumberLocked} value={form.applicationNumber} setValue={update("applicationNumber", CAPTURE_FIELDS.applicationNumber)} error={errors[CAPTURE_FIELDS.applicationNumber]} required />
              <TextField id={CAPTURE_FIELDS.markText} label="Published word mark" value={form.markText} setValue={update("markText", CAPTURE_FIELDS.markText)} error={errors[CAPTURE_FIELDS.markText]} />
              <TextField id={CAPTURE_FIELDS.deviceReference} label="Published device image link" hint="Needed when the mark is a device" value={form.deviceReference} setValue={update("deviceReference", CAPTURE_FIELDS.deviceReference)} error={errors[CAPTURE_FIELDS.deviceReference]} />
              <TextField id={CAPTURE_FIELDS.proprietor} label="Published proprietor" value={form.proprietor} setValue={update("proprietor")} />
              <TextField id={CAPTURE_FIELDS.classes} label="Published Nice classes" hint="For example: Class 45, or 30, 43" value={form.classNumbers} setValue={update("classNumbers", CAPTURE_FIELDS.classes)} error={errors[CAPTURE_FIELDS.classes]} required />
              <fieldset id={CAPTURE_FIELDS.goods} tabIndex={-1} className="min-w-0 space-y-3" aria-describedby={errors[CAPTURE_FIELDS.goods] ? errorIdFor(CAPTURE_FIELDS.goods) : undefined}>
                <legend className="text-sm font-medium text-[var(--color-ink)]">Goods and services as published</legend>
                {parsedClasses.length === 0 ? (
                  <p className="text-sm text-[var(--color-mute)]">Enter the published classes above to list the goods and services for each one.</p>
                ) : parsedClasses.map((number) => (
                  <div key={number} className="min-w-0">
                    <Label htmlFor={goodsFieldId(number)}>Class {number} goods/services as published</Label>
                    <Textarea id={goodsFieldId(number)} className="mt-1" rows={2} value={form.goods[String(number)] ?? ""}
                      onChange={(event) => update("goods", goodsFieldId(number))({ ...form.goods, [String(number)]: event.target.value })}
                      aria-invalid={errors[goodsFieldId(number)] ? true : undefined}
                      aria-describedby={[`${goodsFieldId(number)}-hint`, errors[goodsFieldId(number)] ? errorIdFor(goodsFieldId(number)) : null].filter(Boolean).join(" ")} />
                    <p id={`${goodsFieldId(number)}-hint`} className="mt-0.5 text-xs text-[var(--color-mute)]">One item per line or separated by semicolons. Optional.</p>
                    <FieldError fieldId={goodsFieldId(number)} message={errors[goodsFieldId(number)]} />
                  </div>
                ))}
                <FieldError fieldId={CAPTURE_FIELDS.goods} message={errors[CAPTURE_FIELDS.goods]} />
              </fieldset>
              <fieldset id={CAPTURE_FIELDS.scope} tabIndex={-1} className="min-w-0 space-y-2" aria-describedby={errors[CAPTURE_FIELDS.scope] ? errorIdFor(CAPTURE_FIELDS.scope) : undefined}>
                <legend className="text-sm font-medium text-[var(--color-ink)]">Publication scope</legend>
                <div className="flex flex-wrap gap-4 text-sm">
                  <label className="flex items-center gap-2"><input type="radio" name="publication-scope" value="full" checked={form.scopeKind === "full"} onChange={() => update("scopeKind", CAPTURE_FIELDS.scope)("full")} />Every published class</label>
                  <label className="flex items-center gap-2"><input type="radio" name="publication-scope" value="partial" checked={form.scopeKind === "partial"} onChange={() => update("scopeKind", CAPTURE_FIELDS.scope)("partial")} />Only some classes</label>
                </div>
                {form.scopeKind === "partial" ? (
                  parsedClasses.length === 0 ? <p className="text-sm text-[var(--color-mute)]">Enter the published classes above, then choose the ones this publication covers.</p> : (
                    <div className="flex flex-wrap gap-3 text-sm">
                      {parsedClasses.map((number) => (
                        <label key={number} className="flex items-center gap-2"><input type="checkbox" checked={form.scopeClasses.includes(number)} onChange={(event) => update("scopeClasses", CAPTURE_FIELDS.scope)(event.target.checked ? [...form.scopeClasses, number] : form.scopeClasses.filter((item) => item !== number))} />Class {number}</label>
                      ))}
                    </div>
                  )
                ) : null}
                <FieldError fieldId={CAPTURE_FIELDS.scope} message={errors[CAPTURE_FIELDS.scope]} />
              </fieldset>
            </div>
            <div className="min-w-0 space-y-4">
              <TextField id={CAPTURE_FIELDS.sourceUrl} label="Official source URL" value={form.sourceUrl} setValue={update("sourceUrl", CAPTURE_FIELDS.sourceUrl)} error={errors[CAPTURE_FIELDS.sourceUrl]} required />
              <div className="grid gap-3 sm:grid-cols-2">
                <TextField id={CAPTURE_FIELDS.sourcePage} label="Source page" value={form.sourcePage} setValue={update("sourcePage", CAPTURE_FIELDS.sourcePage)} error={errors[CAPTURE_FIELDS.sourcePage]} />
                <div className="min-w-0"><Label htmlFor={CAPTURE_FIELDS.sourceStatus}>Source status</Label><select id={CAPTURE_FIELDS.sourceStatus} className={SELECT_CLASS} value={form.sourceStatus} onChange={(event) => update("sourceStatus")(event.target.value as JournalCaptureForm["sourceStatus"])}><option value="available">Available</option><option value="unavailable">Unavailable</option><option value="stale">Stale</option></select></div>
              </div>
              <TextField id={CAPTURE_FIELDS.retrievedAt} label="Retrieved at" type="datetime-local" value={form.retrievedAt} setValue={update("retrievedAt", CAPTURE_FIELDS.retrievedAt)} error={errors[CAPTURE_FIELDS.retrievedAt]} />
              <fieldset className="min-w-0 space-y-3 rounded-md border border-[var(--color-line)] p-3">
                <legend className="px-1 text-sm font-semibold text-[var(--color-ink)]">Captured source evidence</legend>
                <p id="evidence-hint" className="text-xs text-[var(--color-mute)]">Required: paste the entry as the journal publishes it, or give a reference to the saved journal page (or both).</p>
                <div className="min-w-0">
                  <Label htmlFor={CAPTURE_FIELDS.evidence}>Journal entry as published</Label>
                  <Textarea id={CAPTURE_FIELDS.evidence} className="mt-1" rows={4} maxLength={20000} value={form.extract} onChange={(event) => update("extract", CAPTURE_FIELDS.evidence)(event.target.value)}
                    aria-invalid={errors[CAPTURE_FIELDS.evidence] ? true : undefined}
                    aria-describedby={["evidence-hint", errors[CAPTURE_FIELDS.evidence] ? errorIdFor(CAPTURE_FIELDS.evidence) : null].filter(Boolean).join(" ")} />
                </div>
                <div className="min-w-0">
                  <Label htmlFor="evidence-reference">Saved page reference</Label>
                  <Input id="evidence-reference" className="mt-1" maxLength={20000} value={form.reference} onChange={(event) => update("reference", CAPTURE_FIELDS.evidence)(event.target.value)}
                    placeholder="Link or file location of the saved journal page"
                    aria-invalid={errors[CAPTURE_FIELDS.evidence] ? true : undefined}
                    aria-describedby={["evidence-hint", errors[CAPTURE_FIELDS.evidence] ? errorIdFor(CAPTURE_FIELDS.evidence) : null].filter(Boolean).join(" ")} />
                </div>
                <FieldError fieldId={CAPTURE_FIELDS.evidence} message={errors[CAPTURE_FIELDS.evidence]} />
                <div className="min-w-0">
                  <Label htmlFor="evidence-notes">Capture notes</Label>
                  <Textarea id="evidence-notes" className="mt-1" rows={2} maxLength={20000} value={form.notes} onChange={(event) => update("notes")(event.target.value)} />
                </div>
              </fieldset>
              <TextField id={CAPTURE_FIELDS.cost} label="Acquisition cost (paise)" hint="0 if the journal was free" type="number" value={form.cost} setValue={update("cost", CAPTURE_FIELDS.cost)} error={errors[CAPTURE_FIELDS.cost]} />
              <div className="border-l-2 border-[var(--color-brand-500)] pl-4 text-sm text-[var(--color-ink-2)]">The source record is append-only. Corrections and re-advertisements create a linked successor and never rewrite prior evidence.</div>
              {formError ? (
                <div role="alert" className="break-words text-sm text-[var(--color-danger-500)]" data-testid="journal-intake-error">
                  <p>{formError}</p>
                  {errorCount ? <p className="mt-1">Fields to correct: {Object.keys(errors).map((id) => CAPTURE_LABELS[id] ?? (id.startsWith("goods-") ? `Class ${id.slice(6)} goods/services` : id)).join(", ")}.</p> : null}
                </div>
              ) : null}
              {conflict?.publicationId ? <AlreadyRecordedEntry publicationId={conflict.publicationId} applicationNumber={conflict.applicationNumber} /> : null}
              <Button type="submit" disabled={mutation.isPending || (correcting && nothingToCorrect)}>{mutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <FileInput className="h-4 w-4" />}Record and compare</Button>
            </div>
          </form>
        </CardContent>
      </Card>}
      <RecordedEntries publications={publications} total={publicationTotal} more={more} />
    </div>
  );
}

/** The entry a re-capture collided with, so the operator reviews it instead of guessing. */
function AlreadyRecordedEntry({ publicationId, applicationNumber }: { publicationId: string; applicationNumber: string }) {
  const lookup = useQuery({
    queryKey: ["ip", "watch", "publications", "recorded", applicationNumber],
    queryFn: () => searchIpJournalPublications(applicationNumber),
  });
  const entry = lookup.data?.publications.find((item) => item.id === publicationId) ?? null;
  return (
    <div className="rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] p-3 text-sm" data-testid="journal-already-recorded">
      <p className="font-semibold text-[var(--color-ink)]">The recorded entry</p>
      {lookup.isPending ? (
        <p className="mt-1 text-[var(--color-mute)]" role="status">Loading the recorded entry…</p>
      ) : lookup.isError ? (
        <div role="alert" className="mt-1 flex flex-wrap items-center gap-2 text-[var(--color-danger-500)]">
          <span className="min-w-0 break-words">Could not load it: {apiErrorMessage(lookup.error, "Request failed.")}</span>
          <Button type="button" size="sm" variant="outline" onClick={() => lookup.refetch()}>Try again</Button>
        </div>
      ) : entry ? (
        <>
          <p className="mt-1 break-words">{publicationLabel(entry)}</p>
          <p className="mt-1 break-words text-[var(--color-mute)]">Classes {entry.class_numbers_json.join(", ")} · {evidenceSummary(entry.raw_evidence_json ?? {})} · recorded {localDate(entry.created_at)}</p>
        </>
      ) : (
        <p className="mt-1 text-[var(--color-mute)]">It is listed under Recorded journal entries.</p>
      )}
    </div>
  );
}

function RecordedSummary({ result, onReviewHits, onDismiss }: { result: IpJournalIngestResult; onReviewHits: (hitId: string) => void; onDismiss: () => void }) {
  const entry = result.publications[0] ?? null;
  const paused = result.run.status === "paused_cost_quota";
  const ref = useRef<HTMLElement>(null);
  // The form is submitted from its foot; bring the outcome to where the user is looking.
  useEffect(() => {
    ref.current?.scrollIntoView({ block: "center" });
    ref.current?.focus({ preventScroll: true });
  }, [result]);
  return (
    <section ref={ref} tabIndex={-1} role="status" aria-label="Journal intake result" data-testid="journal-intake-result" className={paused ? "border-l-2 border-amber-400 bg-amber-50 p-4 text-sm text-amber-950" : "border-l-2 border-[var(--color-brand-500)] bg-white p-4 text-sm"}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {paused ? (
            <p className="font-semibold">Not recorded: every watch profile it would be compared with has reached its cost limit. Raise the limit or wait for the next period, then record it again.</p>
          ) : entry ? (
            <>
              <p className="font-semibold">{result.idempotent_replay ? "Already recorded" : "Recorded"}: Journal {entry.journal_number} · Application {entry.application_number} · {entry.mark_text || "Device mark"}</p>
              <p className="mt-1 text-[var(--color-mute)]">Classes {entry.class_numbers_json.join(", ")} · {evidenceSummary(entry.raw_evidence_json)} · {result.hits.length} new watch {result.hits.length === 1 ? "hit" : "hits"}{result.run.duplicate_hits ? ` · ${result.run.duplicate_hits} already reviewed` : ""}</p>
            </>
          ) : (
            <p className="font-semibold">Run {result.run.status.replaceAll("_", " ")}; no journal entry was recorded.</p>
          )}
        </div>
        <Button type="button" size="sm" variant="ghost" aria-label="Dismiss intake result" onClick={onDismiss}><X className="h-4 w-4" /></Button>
      </div>
      {result.hits.length ? <Button type="button" size="sm" className="mt-3" onClick={() => onReviewHits(result.hits[0].id)}>Review {result.hits.length === 1 ? "the hit" : `${result.hits.length} hits`}</Button> : null}
    </section>
  );
}

function evidenceSummary(evidence: Record<string, unknown>) {
  const parts: string[] = [];
  if (typeof evidence.extract_text === "string" && evidence.extract_text.trim()) parts.push("journal extract captured");
  if (typeof evidence.evidence_reference === "string" && evidence.evidence_reference.trim()) parts.push("saved page referenced");
  return parts.length ? parts.join(", ") : "evidence captured";
}

function RecordedEntries({ publications, total, more }: { publications: IpJournalPublication[]; total: number; more: MoreRows }) {
  return (
    <Card className="min-w-0">
      <CardHeader className="gap-2">
        <CardTitle as="h2">Recorded journal entries</CardTitle>
        {total > 0 ? <ListCount loaded={publications.length} total={total} noun={["recorded entry", "recorded entries"]} more={more} /> : null}
      </CardHeader>
      <CardContent className="p-0">
        {publications.length === 0 ? (
          <p className="px-5 pb-5 text-sm text-[var(--color-mute)]">No journal entry is recorded yet. Entries you record appear here, with or without watch hits.</p>
        ) : (
          <ul className="divide-y divide-[var(--color-line)]" aria-label="Recorded journal entries">
            {publications.map((item) => (
              <li key={item.id} className="min-w-0 px-5 py-3 text-sm" data-testid={`journal-entry-${item.id}`}>
                <div className="flex flex-wrap items-center gap-2"><strong className="break-words">{item.mark_text || "Device mark"}</strong><Badge tone={tone(item.source_status)}>{item.source_status}</Badge>{item.publication_kind !== "advertisement" ? <Badge tone="warning">{item.publication_kind}</Badge> : null}</div>
                <p className="mt-1 break-words text-[var(--color-mute)]">Journal {item.journal_number} · {DATE.format(new Date(item.journal_date))} · Application {item.application_number} · Classes {item.class_numbers_json.join(", ")} · {evidenceSummary(item.raw_evidence_json ?? {})}</p>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function CapturedEvidence({ publication }: { publication: IpJournalPublication }) {
  const evidence = publication.raw_evidence_json ?? {};
  const extract = typeof evidence.extract_text === "string" ? evidence.extract_text : null;
  const reference = typeof evidence.evidence_reference === "string" ? evidence.evidence_reference : null;
  const notes = typeof evidence.notes === "string" ? evidence.notes : null;
  const other = Object.entries(evidence).filter(
    ([key, value]) => !["extract_text", "evidence_reference", "notes", "capture_method"].includes(key) && typeof value === "string",
  ) as Array<[string, string]>;
  const goods = Object.entries(publication.goods_services_json);
  return (
    <dl className="grid min-w-0 gap-3 rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] p-4 text-sm">
      <div className="min-w-0"><dt className="text-[var(--color-mute)]">Journal entry as published</dt><dd className="mt-1 whitespace-pre-wrap break-words">{extract ?? "Not captured"}</dd></div>
      <div className="min-w-0"><dt className="text-[var(--color-mute)]">Saved page reference</dt><dd className="mt-1 break-words">{reference ? (/^https?:\/\//i.test(reference) ? <a className="font-medium text-[var(--color-brand-700)] underline" href={reference} target="_blank" rel="noreferrer">{reference}</a> : reference) : "Not recorded"}</dd></div>
      {notes ? <div className="min-w-0"><dt className="text-[var(--color-mute)]">Capture notes</dt><dd className="mt-1 whitespace-pre-wrap break-words">{notes}</dd></div> : null}
      {other.map(([key, value]) => <div key={key} className="min-w-0"><dt className="text-[var(--color-mute)]">{humanizeApiFieldPath([key])}</dt><dd className="mt-1 whitespace-pre-wrap break-words">{value}</dd></div>)}
      <div className="min-w-0"><dt className="text-[var(--color-mute)]">Goods and services</dt><dd className="mt-1 break-words">{goods.length ? goods.map(([number, items]) => `Class ${number}: ${items.join("; ")}`).join(" · ") : "Not recorded"}</dd></div>
      <div className="min-w-0"><dt className="text-[var(--color-mute)]">Source page · retrieved</dt><dd className="mt-1 break-words">{publication.source_page ?? "No page"} · {publication.source_retrieved_at ? localDate(publication.source_retrieved_at) : "Retrieval time not recorded"}</dd></div>
    </dl>
  );
}

function HitsView({ hits, hitTotal, more, profiles, publication, selectedHit, selectedProfile, selectedHitId, setSelectedHitId, handoffs, core, membershipId, canManage, onChanged }: {
  hits: IpWatchHit[];
  hitTotal: number;
  more: MoreRows;
  profiles: IpWatchProfile[];
  publication: IpJournalPublication | null;
  selectedHit: IpWatchHit | null;
  selectedProfile: IpWatchProfile | null;
  selectedHitId: string;
  setSelectedHitId: (value: string) => void;
  handoffs: IpWatchHandoff[];
  core: IpCoreRecords | undefined;
  membershipId: string;
  canManage: boolean;
  onChanged: () => Promise<void>;
}) {
  if (hits.length === 0) return <EmptyState title="No watch hits" description={profiles.length ? "No journal evidence matches the selected docket profiles. Recorded journal entries are listed under Journal intake." : "Create a watch profile, then record official journal evidence."} />;
  return (
    <div className="grid min-w-0 gap-4 xl:grid-cols-[330px_minmax(0,1fr)]">
      <Card className="min-w-0">
        <CardHeader className="gap-2"><CardTitle as="h2">Review queue</CardTitle><ListCount loaded={hits.length} total={hitTotal} noun={["hit", "hits"]} more={more} /></CardHeader>
        <CardContent className="p-0"><div className="divide-y divide-[var(--color-line)]">{hits.map((hit) => {
          const mark = String(hit.candidate_mark_json.mark_text ?? "Device mark");
          return <button type="button" key={hit.id} data-testid={`watch-hit-${hit.id}`} className={hit.id === selectedHitId ? "w-full bg-[var(--color-brand-50)] px-5 py-4 text-left" : "w-full px-5 py-4 text-left hover:bg-[var(--color-bg-2)]"} onClick={() => setSelectedHitId(hit.id)}><strong className="block break-words text-sm">{mark}</strong><span className="mt-2 flex flex-wrap gap-2"><Badge tone={tone(hit.disposition)}>{hit.disposition.replaceAll("_", " ")}</Badge><Badge tone={tone(hit.source_status)}>{hit.source_status}</Badge>{hit.stale_source_alert ? <Badge tone="warning">stale alert</Badge> : null}</span><span className="mt-2 block text-xs text-[var(--color-mute)]">{DATE.format(new Date(hit.hit_date))}</span></button>;
        })}</div></CardContent>
      </Card>
      {selectedHit && publication ? <div className="flex min-w-0 flex-col gap-4">
        <Card>
          <CardHeader className="gap-3 sm:flex-row sm:items-start sm:justify-between"><div className="min-w-0"><CardTitle as="h2" className="break-words">{publication.mark_text || "Device mark"}</CardTitle><p className="mt-1 break-words text-sm text-[var(--color-mute)]">Application {publication.application_number} · Journal {publication.journal_number}</p></div><div className="flex flex-wrap gap-2"><Badge tone={tone(selectedHit.source_status)}>{selectedHit.source_status}</Badge><Badge tone={tone(selectedHit.deadline_confirmation_state)}>{selectedHit.deadline_confirmation_state}</Badge></div></CardHeader>
          <CardContent className="space-y-5">
            {selectedHit.source_status !== "available" ? <div className="flex gap-2 border-l-2 border-amber-400 pl-3 text-sm text-amber-900"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />Final source-dependent dispositions are blocked until an attorney can open and confirm the official source.</div> : null}
            {selectedHit.duplicate_of_hit_id ? <PriorHit priorId={selectedHit.duplicate_of_hit_id} hits={hits} onOpen={setSelectedHitId} /> : null}
            <div className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4"><Field label="Compared profile" value={selectedProfile?.name ?? "Profile not visible to you"} /><Field label="Classes" value={publication.class_numbers_json.join(", ")} /><Field label="Proprietor" value={publication.proprietor_name ?? "Not published"} /><Field label="Publication scope" value={scopeLabel(publication.publication_scope_json)} /></div>
            <div><div className="mb-2 flex items-center justify-between gap-3"><h3 className="text-sm font-semibold">Official source evidence</h3><Button href={selectedHit.source_url} target="_blank" rel="noreferrer" size="sm" variant="outline">Open source<ArrowUpRight className="h-4 w-4" /></Button></div><CapturedEvidence publication={publication} /></div>
            <div><h3 className="mb-2 text-sm font-semibold">Similarity evidence</h3><SimilarityEvidence evidence={selectedHit.similarity_evidence_json} /></div>
            <div className="flex gap-3 border-l-2 border-[var(--color-brand-500)] pl-4 text-sm"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /><div><strong>AI assistance is advisory.</strong><p className="mt-1 text-[var(--color-mute)]">{selectedHit.advisory_notice}</p></div></div>
          </CardContent>
        </Card>
        {canManage ? <ReviewPanel hit={selectedHit} onChanged={onChanged} /> : null}
        {canManage && ["relevant", "client_instruction", "enforcement_opened"].includes(selectedHit.disposition) ? <HandoffPanel hit={selectedHit} publication={publication} core={core} membershipId={membershipId} handoffs={handoffs.filter((item) => item.hit_id === selectedHit.id)} onChanged={onChanged} /> : null}
      </div> : <EmptyState title="Select a hit" description="Choose a journal candidate to inspect source and similarity evidence." />}
    </div>
  );
}

function PriorHit({ priorId, hits, onOpen }: { priorId: string; hits: IpWatchHit[]; onOpen: (hitId: string) => void }) {
  const prior = hits.find((item) => item.id === priorId) ?? null;
  const mark = prior ? String(prior.candidate_mark_json.mark_text ?? "Device mark") : null;
  const application = prior ? prior.candidate_mark_json.application_number : null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <Badge tone="warning">Linked successor / duplicate</Badge>
      {prior ? (
        <>
          <span className="min-w-0 break-words text-[var(--color-mute)]">Earlier hit: {mark}{application ? ` · Application ${String(application)}` : ""} · {DATE.format(new Date(prior.hit_date))}</span>
          <Button type="button" size="sm" variant="outline" onClick={() => onOpen(prior.id)}>Open the earlier hit</Button>
        </>
      ) : (
        <span className="text-[var(--color-mute)]">An earlier hit on this application is outside the current docket scope.</span>
      )}
    </div>
  );
}

type WordRow = { term?: unknown; score?: unknown; contains?: unknown };
type PhoneticRow = { term?: unknown; matched?: unknown };

/** The comparison as labelled fields; a lawyer never reads the stored JSON. */
function SimilarityEvidence({ evidence }: { evidence: Record<string, unknown> }) {
  const words = Array.isArray(evidence.word) ? (evidence.word as WordRow[]) : [];
  const phonetics = Array.isArray(evidence.phonetic) ? (evidence.phonetic as PhoneticRow[]) : [];
  const device = (evidence.device ?? {}) as { matched?: unknown; profile_references?: unknown };
  const classes = Array.isArray(evidence.class_overlap) ? evidence.class_overlap.map(String) : [];
  const proprietors = Array.isArray(evidence.proprietor_matches) ? evidence.proprietor_matches.map(String) : [];
  const watchedDevices = Array.isArray(device.profile_references) && device.profile_references.length > 0;
  const rows: Array<[string, string]> = [
    [
      "Word matches",
      words.length
        ? words.map((row) => `${String(row.term ?? "")}: ${Math.round(Number(row.score ?? 0) * 100)}% similar${row.contains ? ", contained in the mark" : ""}`).join("; ")
        : "No word terms in this profile",
    ],
    [
      "Phonetic matches",
      phonetics.length
        ? phonetics.map((row) => `${String(row.term ?? "")}: ${row.matched ? "sounds alike" : "does not sound alike"}`).join("; ")
        : "No phonetic terms in this profile",
    ],
    ["Device", device.matched ? "Matches a watched device image" : watchedDevices ? "No match with the watched device images" : "No device image watched"],
    ["Class overlap", classes.length ? `Class ${classes.join(", ")}` : "No shared Nice class"],
    ["Proprietor matches", proprietors.length ? proprietors.join(", ") : "None"],
    ["Jurisdiction", evidence.jurisdiction_match ? "Within the profile's jurisdictions" : "Outside the profile's jurisdictions"],
    ["AI assistance", evidence.ai_advisory ? "Device similarity was suggested by AI (advisory only)" : "None used"],
  ];
  return (
    <dl className="grid min-w-0 gap-3 rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] p-4 text-sm sm:grid-cols-2" data-testid="similarity-evidence">
      {rows.map(([label, value]) => (
        <div key={label} className="min-w-0"><dt className="text-[var(--color-mute)]">{label}</dt><dd className="mt-1 break-words">{value}</dd></div>
      ))}
    </dl>
  );
}

function scopeLabel(scope: Record<string, unknown>) {
  if (scope.scope_kind === "full") return "Every published class";
  if (scope.scope_kind === "partial") {
    const covered = Array.isArray(scope.published_classes) ? scope.published_classes.join(", ") : "";
    return covered ? `Only classes ${covered}` : "Only some classes";
  }
  return "Not supplied";
}

function ReviewPanel({ hit, onChanged }: { hit: IpWatchHit; onChanged: () => Promise<void> }) {
  const [disposition, setDisposition] = useState<IpWatchDisposition>(hit.disposition);
  const [reason, setReason] = useState(hit.disposition_reason ?? "");
  const [sourceConfirmed, setSourceConfirmed] = useState(false);
  const mutation = useMutation({ mutationFn: decideIpWatchHit, onSuccess: async () => { toast.success("Attorney review recorded."); await onChanged(); }, onError: (error) => toast.error(apiErrorMessage(error, "Could not record the review.")) });
  return <Card><CardHeader><CardTitle as="h2">Attorney disposition</CardTitle></CardHeader><CardContent><form className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)_auto] lg:items-end" onSubmit={(event) => { event.preventDefault(); mutation.mutate({ hitId: hit.id, expectedVersion: hit.version, disposition, reason, sourceConfirmed }); }}><div><Label htmlFor="hit-disposition">Disposition</Label><select id="hit-disposition" className={SELECT_CLASS} value={disposition} onChange={(event) => setDisposition(event.target.value as IpWatchDisposition)}>{["new", "reviewing", "relevant", "not_relevant", "monitor", "client_instruction", "enforcement_opened", "closed"].map((item) => <option key={item} value={item}>{item.replaceAll("_", " ")}</option>)}</select></div><div><Label htmlFor="disposition-reason">Reason</Label><Input id="disposition-reason" value={reason} onChange={(event) => setReason(event.target.value)} required /></div><Button type="submit" disabled={mutation.isPending}>{mutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}Record review</Button><label className="flex items-center gap-2 text-sm lg:col-span-3"><input type="checkbox" checked={sourceConfirmed} onChange={(event) => setSourceConfirmed(event.target.checked)} />I opened and confirmed the official journal source for this decision.</label></form></CardContent></Card>;
}

function HandoffPanel({ hit, publication, core, membershipId, handoffs, onChanged }: { hit: IpWatchHit; publication: IpJournalPublication; core: IpCoreRecords | undefined; membershipId: string; handoffs: IpWatchHandoff[]; onChanged: () => Promise<void> }) {
  const applications = core?.applications ?? [];
  const [kind, setKind] = useState<IpWatchHandoff["handoff_kind"]>("opposition");
  // The journal entry's own application, or none: never the docket's first application.
  const [applicationId, setApplicationId] = useState(publication.application_id ?? "");
  const [title, setTitle] = useState(`Review ${publication.mark_text || publication.application_number}`);
  const [matterCode, setMatterCode] = useState("");
  const [dueOn, setDueOn] = useState("");
  const [assignee, setAssignee] = useState(membershipId);
  const [notes, setNotes] = useState("");
  const mutation = useMutation({ mutationFn: createIpWatchHandoff, onSuccess: async (row) => { toast.success(`${row.handoff_kind.replaceAll("_", " ")} created without re-entry.`); await onChanged(); }, onError: (error) => toast.error(apiErrorMessage(error, "Could not create the canonical handoff.")) });
  const existingKinds = new Set(handoffs.map((item) => item.handoff_kind));
  const applicationOptions = [
    { value: "", label: "No linked application" },
    ...applications.map((item) => ({ value: item.id, label: applicationLabel(item, core) })),
    ...(applicationId && !applications.some((item) => item.id === applicationId)
      ? [{ value: applicationId, label: "Application linked by the journal entry" }]
      : []),
  ];
  return <Card><CardHeader><CardTitle as="h2">Canonical handoff</CardTitle></CardHeader><CardContent className="space-y-4"><div className="flex flex-wrap gap-2">{(["opposition", "enforcement_matter", "task", "deadline", "client_report_item"] as const).map((item) => <button type="button" key={item} className={kind === item ? "rounded-md bg-[var(--color-ink)] px-3 py-2 text-sm font-medium text-white" : "rounded-md border border-[var(--color-line)] px-3 py-2 text-sm font-medium"} onClick={() => setKind(item)}>{item.replaceAll("_", " ")}{existingKinds.has(item) ? " · created" : ""}</button>)}</div><form className="grid gap-4 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); mutation.mutate({ hitId: hit.id, handoffKind: kind, applicationId: applicationId || null, title: title || null, matterCode: matterCode || null, dueOn: dueOn || null, assigneeMembershipId: assignee || null, notes: notes || null }); }}>{kind === "opposition" ? (
    applicationOptions.length > 1 ? (
      <RecordSelect id="handoff-application" label="Application"
        className={SELECT_CLASS}
        value={applicationId} onChange={(event) => setApplicationId(event.target.value)} options={applicationOptions} />
    ) : <p className="text-sm text-[var(--color-mute)] sm:col-span-2">No trademark application is linked; choose the docket in Docket scope to link one of its applications.</p>
  ) : null}{["enforcement_matter", "task", "deadline"].includes(kind) ? <TextField id="handoff-title" label="Title" value={title} setValue={setTitle} required /> : null}{kind === "enforcement_matter" ? <TextField id="handoff-code" label="Matter code" value={matterCode} setValue={setMatterCode} required /> : null}{kind === "deadline" ? <TextField id="handoff-due" label="Due date" type="date" value={dueOn} setValue={setDueOn} required /> : null}{["task", "deadline", "client_report_item"].includes(kind) ? <div className="min-w-0"><Label htmlFor="handoff-assignee">Assignee</Label><PersonPicker id="handoff-assignee" value={assignee} onChange={setAssignee} placeholder="No assignee" className="mt-1" /></div> : null}<div className="sm:col-span-2"><Label htmlFor="handoff-notes">Notes</Label><Textarea id="handoff-notes" value={notes} onChange={(event) => setNotes(event.target.value)} /></div><div className="sm:col-span-2"><Button type="submit" disabled={mutation.isPending || existingKinds.has(kind)}>{mutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}Create {kind.replaceAll("_", " ")}</Button></div></form>{handoffs.length ? <div className="border-t border-[var(--color-line)] pt-4"><h3 className="mb-2 text-sm font-semibold">Completed handoffs</h3><div className="flex flex-wrap gap-2">{handoffs.map((item) => <Badge key={item.id} tone={tone(item.status)}>{item.handoff_kind.replaceAll("_", " ")} → {item.target_type}</Badge>)}</div></div> : null}</CardContent></Card>;
}

function runSource(run: IpJournalIngestionRun) {
  // Manual-only profiles are never polled, so the API returns no scheduler run for them.
  if (run.idempotency_key.startsWith("scheduler:")) return `${run.provider_key} · scheduled check`;
  return run.provider_key === "ipindia-journal-manual" ? "Manual journal intake" : run.provider_key;
}

function RunsView({ profiles, pausedTotal, runs, runTotal }: { profiles: IpWatchProfile[]; pausedTotal: number; runs: IpJournalIngestionRun[]; runTotal: number }) {
  // The server counts every paused profile; only the loaded ones can be named.
  const paused = profiles.filter((item) => item.poll_status !== "active");
  const unnamed = Math.max(0, pausedTotal - paused.length);
  return <div className="flex flex-col gap-4">{pausedTotal ? <div className="border-l-2 border-amber-400 bg-amber-50 p-4 text-sm text-amber-950"><div className="flex items-center gap-2 font-semibold"><Pause className="h-4 w-4" />{pausedTotal} {pausedTotal === 1 ? "profile" : "profiles"} paused</div><p className="mt-1 break-words">{paused.map((item) => `${item.name}: ${item.pause_reason ?? item.poll_status}`).join(" · ")}{unnamed ? `${paused.length ? " · " : ""}${unnamed} more listed under Profiles` : ""}</p></div> : null}{runTotal > runs.length ? <p role="status" className="text-sm text-[var(--color-mute)]" data-testid="watch-runs-cap">The {runs.length} most recent of {runTotal.toLocaleString("en-IN")} runs are shown.</p> : null}{runs.length === 0 ? <EmptyState title="No ingestion runs" description="Manual intake and scheduler checks will appear here." /> : <div className="overflow-x-auto border-y border-[var(--color-line)]"><table className="w-full min-w-[850px] text-left text-sm"><thead className="bg-[var(--color-bg-2)] text-xs text-[var(--color-mute)]"><tr><th className="px-4 py-3">Started</th><th className="px-4 py-3">Source</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Entries recorded</th><th className="px-4 py-3">Hits</th><th className="px-4 py-3">Cost</th><th className="px-4 py-3">Exception</th></tr></thead><tbody className="divide-y divide-[var(--color-line)]">{runs.map((run) => <tr key={run.id}><td className="px-4 py-3">{localDate(run.started_at)}</td><td className="px-4 py-3">{runSource(run)}</td><td className="px-4 py-3"><Badge tone={tone(run.status)}>{run.status.replaceAll("_", " ")}</Badge></td><td className="px-4 py-3 tabular-nums">{run.publications_created}/{run.publications_seen}{run.duplicate_hits ? ` · ${run.duplicate_hits} duplicate` : ""}</td><td className="px-4 py-3 tabular-nums">{run.hits_created}{run.stale_source_alert ? " · stale" : ""}</td><td className="px-4 py-3 tabular-nums">{run.cost_minor} {run.currency}</td><td className="px-4 py-3 text-[var(--color-mute)]">{run.error_redacted ?? "None"}</td></tr>)}</tbody></table></div>}</div>;
}

function Field({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><span className="text-[var(--color-mute)]">{label}</span><strong className="mt-1 block break-words font-medium text-[var(--color-ink)]">{value}</strong></div>;
}

function FieldError({ fieldId, message }: { fieldId: string; message?: string }) {
  return message ? <p id={errorIdFor(fieldId)} className="mt-1 break-words text-sm text-[var(--color-danger-500)]">{message}</p> : null;
}

function TextField({ id, label, hint, value, setValue, type = "text", required = false, readOnly = false, error }: { id: string; label: string; hint?: ReactNode; value: string; setValue: (value: string) => void; type?: string; required?: boolean; readOnly?: boolean; error?: string }) {
  const hintId = hint ? `${id}-hint` : null;
  const describedBy = [hintId, error ? errorIdFor(id) : null].filter(Boolean).join(" ");
  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-2"><Label htmlFor={id}>{label}</Label>{hint ? <span id={hintId ?? undefined} className="text-xs text-[var(--color-mute)]">{hint}</span> : null}</div>
      <Input id={id} type={type} className="mt-1" value={value} onChange={(event) => setValue(event.target.value)} required={required} readOnly={readOnly} aria-invalid={error ? true : undefined} aria-describedby={describedBy || undefined} />
      <FieldError fieldId={id} message={error} />
    </div>
  );
}
