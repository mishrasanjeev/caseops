"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldOff } from "lucide-react";
import Link from "next/link";
import { useId, useMemo, useState } from "react";
import { toast } from "sonner";

import { MatterPicker, matterCaption } from "@/components/app/MatterPicker";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage, apiFieldErrors, isApiErrorShape } from "@/lib/api/config";
import { listCompanyUsers, type CompanyUserRecord } from "@/lib/api/endpoints";
import {
  MATTER_WALL_REASON_MAX,
  createMatterEthicalWall,
  listMatterEthicalWalls,
  removeMatterEthicalWall,
  type MatterEthicalWallDirectoryRow,
} from "@/lib/api/matter-ethical-walls";
import type { Matter } from "@/lib/api/schemas";
import { useCapability } from "@/lib/capabilities";
import { formatLegalDate } from "@/lib/dates";

const WALLS_QUERY_KEY = ["admin", "matter-ethical-walls"] as const;

type FieldErrors = { matter?: string; people?: string; reason?: string; form?: string };

/** Owners bypass every wall (record_access_policy._is_owner); inactive people cannot sign in. */
function wallUnavailableReason(user: CompanyUserRecord, walledIds: ReadonlySet<string>): string | null {
  if (user.role === "owner") return "Owner: walls do not apply to owners";
  if (walledIds.has(user.membership_id)) return "Already walled from this Matter";
  return null;
}

function roleLabel(role: string): string {
  return role.charAt(0).toUpperCase() + role.slice(1);
}

function createErrorFor(err: unknown): { field: keyof FieldErrors; message: string; stop: boolean } {
  if (isApiErrorShape(err)) {
    if (err.status === 404) {
      // Unknown and hidden Matters answer the same; the admin may have been walled meanwhile.
      return {
        field: "matter",
        message: "This Matter is no longer available to you. Choose another Matter, or ask a workspace owner to set up this wall.",
        stop: true,
      };
    }
    if (err.status === 403) {
      return { field: "form", message: "Your role can no longer manage ethical walls. Ask a workspace owner or admin.", stop: true };
    }
    if (err.status === 422) {
      const fields = apiFieldErrors(err, { reason: "reason", excluded_membership_id: "people" });
      if (fields.reason) return { field: "reason", message: fields.reason, stop: true };
    }
    return { field: "people", message: apiErrorMessage(err, "The wall could not be set up."), stop: false };
  }
  return { field: "form", message: apiErrorMessage(err, "The wall could not be set up."), stop: true };
}

export function MatterEthicalWallsCard() {
  const canManage = useCapability("matter_access:manage");
  return (
    <Card data-testid="matter-ethical-walls">
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div className="min-w-0">
          <CardTitle as="h2">Ethical walls</CardTitle>
          <CardDescription>
            Screen people from a litigation Matter. A wall overrides every role
            and explicit grant: the person can no longer find or open the
            Matter, its documents or its drafts. Owners are never walled. Each
            change is recorded in the audit trail.
          </CardDescription>
        </div>
        <ShieldOff className="h-5 w-5 shrink-0 text-[var(--color-brand-700)]" aria-hidden />
      </CardHeader>
      <CardContent>
        {canManage ? (
          <MatterEthicalWallsWorkspace />
        ) : (
          <p className="text-sm text-[var(--color-mute)]" data-testid="matter-ethical-walls-denied">
            Your role does not include <code>matter_access:manage</code>. Ask a
            workspace owner or admin to set up or lift ethical walls.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function MatterEthicalWallsWorkspace() {
  const queryClient = useQueryClient();
  const walls = useQuery({
    queryKey: WALLS_QUERY_KEY,
    queryFn: ({ signal }) => listMatterEthicalWalls(signal),
  });
  const people = useQuery({ queryKey: ["company-users"], queryFn: () => listCompanyUsers() });
  const refreshWalls = () => queryClient.invalidateQueries({ queryKey: WALLS_QUERY_KEY });

  return (
    <div className="flex min-w-0 flex-col gap-8">
      <CreateWallForm
        walls={walls.data?.walls ?? []}
        wallsTruncated={walls.data?.truncated ?? false}
        people={people.data?.users ?? []}
        peopleLoading={people.isPending}
        peopleError={people.isError ? people.error : null}
        onRetryPeople={() => people.refetch()}
        onChanged={refreshWalls}
      />
      <section aria-labelledby="matter-walls-active-heading" className="flex min-w-0 flex-col gap-3">
        <h3 id="matter-walls-active-heading" className="text-sm font-semibold text-[var(--color-ink)]">
          Active walls
        </h3>
        {walls.isPending ? (
          <div className="flex flex-col gap-2" aria-label="Loading ethical walls">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : walls.isError ? (
          <WallsLoadError error={walls.error} onRetry={() => walls.refetch()} />
        ) : (
          <ActiveWalls rows={walls.data.walls} truncated={walls.data.truncated} onChanged={refreshWalls} />
        )}
      </section>
    </div>
  );
}

function WallsLoadError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const forbidden = isApiErrorShape(error) && error.status === 403;
  return (
    <div role="alert" className="flex min-w-0 flex-col gap-2 rounded-md border border-[var(--color-line)] p-3 text-sm sm:flex-row sm:items-center">
      <p className="min-w-0 flex-1 break-words text-[var(--color-danger-500)]">
        {forbidden
          ? "Your role cannot view ethical walls. Ask a workspace owner or admin."
          : apiErrorMessage(error, "Ethical walls could not be loaded.")}
      </p>
      {forbidden ? null : (
        <Button type="button" variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

function CreateWallForm({
  walls,
  wallsTruncated,
  people,
  peopleLoading,
  peopleError,
  onRetryPeople,
  onChanged,
}: {
  walls: MatterEthicalWallDirectoryRow[];
  wallsTruncated: boolean;
  people: CompanyUserRecord[];
  peopleLoading: boolean;
  peopleError: unknown;
  onRetryPeople: () => void;
  onChanged: () => Promise<unknown>;
}) {
  const ids = useId();
  const peopleErrorId = `${ids}-people-error`;
  const reasonErrorId = `${ids}-reason-error`;
  const formErrorId = `${ids}-form-error`;
  const [matterId, setMatterId] = useState("");
  const [matter, setMatter] = useState<Matter | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [filter, setFilter] = useState("");
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [reviewing, setReviewing] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);

  // The directory holds only the 500 most recent walls. When it is cut short,
  // read this Matter's own walls so a person already walled from it is never
  // offered as selectable.
  const matterWalls = useQuery({
    queryKey: [...WALLS_QUERY_KEY, { matterId }],
    queryFn: ({ signal }) => listMatterEthicalWalls(signal, { matterId }),
    enabled: wallsTruncated && Boolean(matterId),
  });
  const walledIds = useMemo(
    () =>
      new Set(
        [...walls, ...(matterWalls.data?.walls ?? [])]
          .filter((row) => row.matter_id === matterId)
          .map((row) => row.excluded_membership_id),
      ),
    [walls, matterWalls.data, matterId],
  );
  const candidates = useMemo(
    () =>
      people
        .filter((user) => user.membership_active && user.user_active)
        .sort((a, b) => a.full_name.localeCompare(b.full_name) || a.email.localeCompare(b.email)),
    [people],
  );
  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return candidates;
    return candidates.filter((user) =>
      [user.full_name, user.email, user.role].some((field) => field.toLowerCase().includes(needle)),
    );
  }, [candidates, filter]);
  const chosen = candidates.filter((user) => selected.includes(user.membership_id));
  const trimmedReason = reason.trim();

  const create = useMutation({
    mutationFn: async () => {
      const done: CompanyUserRecord[] = [];
      for (const person of chosen) {
        try {
          await createMatterEthicalWall({
            matterId,
            excludedMembershipId: person.membership_id,
            reason: trimmedReason || null,
          });
          done.push(person);
        } catch (err) {
          return { done, failed: person, err };
        }
      }
      return { done, failed: null, err: null };
    },
    onSuccess: async ({ done, failed, err }) => {
      setReviewing(false);
      if (done.length > 0) {
        const names = done.map((person) => person.full_name).join(", ");
        const message = `Wall set up: ${names} can no longer open ${matter?.matter_code ?? "the Matter"}.`;
        setLastResult(message);
        toast.success(message);
        setSelected((current) => current.filter((id) => !done.some((person) => person.membership_id === id)));
      }
      if (failed) {
        const anchored = createErrorFor(err);
        const prefix = anchored.field === "people" ? `${failed.full_name} was not walled: ` : "";
        setErrors({ [anchored.field]: `${prefix}${anchored.message}` });
      } else {
        setReason("");
        setErrors({});
      }
      await onChanged();
    },
  });

  function review() {
    const next: FieldErrors = {};
    if (!matterId) next.matter = "Choose the Matter to wall.";
    if (chosen.length === 0) next.people = "Choose at least one person to wall off.";
    if (reason.length > MATTER_WALL_REASON_MAX) {
      next.reason = `Keep the reason to ${MATTER_WALL_REASON_MAX} characters or fewer.`;
    }
    setErrors(next);
    setLastResult(null);
    if (Object.keys(next).length === 0) setReviewing(true);
  }

  return (
    <section aria-labelledby={`${ids}-heading`} className="flex min-w-0 flex-col gap-4">
      <h3 id={`${ids}-heading`} className="text-sm font-semibold text-[var(--color-ink)]">
        Set up a wall
      </h3>
      <form
        className="grid min-w-0 gap-4 md:grid-cols-2"
        aria-describedby={errors.form ? formErrorId : undefined}
        onSubmit={(event) => {
          event.preventDefault();
          review();
        }}
      >
        <MatterPicker
          id="matter-wall-matter"
          className="md:col-span-2"
          label="Matter"
          searchLabel="Search Matters to wall"
          value={matterId}
          error={errors.matter ?? null}
          disabled={reviewing || create.isPending}
          onChange={(id, picked) => {
            setMatterId(id);
            setMatter(picked);
            setReviewing(false);
            setErrors((current) => ({ ...current, matter: undefined }));
          }}
        />

        <fieldset
          className="flex min-w-0 flex-col gap-2 md:col-span-2"
          aria-describedby={errors.people ? peopleErrorId : undefined}
          aria-invalid={errors.people ? true : undefined}
          disabled={reviewing || create.isPending}
          data-testid="matter-wall-people"
        >
          <legend className="text-sm font-medium text-[var(--color-ink)]">People to wall off</legend>
          {peopleError ? (
            <div role="alert" className="flex min-w-0 flex-wrap items-center gap-2 text-sm text-[var(--color-mute)]">
              <span className="min-w-0 break-words">
                The staff list could not be loaded: {apiErrorMessage(peopleError, "try again")}
              </span>
              <Button type="button" size="sm" variant="outline" onClick={onRetryPeople}>
                Try again
              </Button>
            </div>
          ) : null}
          {candidates.length > 8 ? (
            <Input
              aria-label="Filter people by name, email or role"
              placeholder="Filter by name, email or role…"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            />
          ) : null}
          <div className="max-h-72 min-w-0 overflow-y-auto rounded-md border border-[var(--color-line)]">
            {peopleLoading ? (
              <p className="px-3 py-2 text-sm text-[var(--color-mute)]">Loading colleagues…</p>
            ) : shown.length === 0 ? (
              <p className="px-3 py-2 text-sm text-[var(--color-mute)]">
                {candidates.length === 0 ? "No active colleagues to wall off." : "No colleague matches this filter."}
              </p>
            ) : (
              shown.map((user) => {
                const unavailable = wallUnavailableReason(user, walledIds);
                const checked = selected.includes(user.membership_id) && !unavailable;
                return (
                  <label
                    key={user.membership_id}
                    className="flex min-w-0 cursor-pointer items-start gap-3 border-b border-[var(--color-line-2)] px-3 py-2 text-sm last:border-0 has-[:disabled]:cursor-not-allowed"
                  >
                    <input
                      type="checkbox"
                      className="mt-0.5 h-4 w-4 shrink-0"
                      checked={checked}
                      disabled={Boolean(unavailable)}
                      onChange={(event) => {
                        const id = user.membership_id;
                        setSelected((current) =>
                          event.target.checked ? [...current, id] : current.filter((value) => value !== id),
                        );
                        setErrors((current) => ({ ...current, people: undefined }));
                      }}
                    />
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="break-words font-medium text-[var(--color-ink)]">{user.full_name}</span>
                      <span className="break-words text-xs text-[var(--color-mute)]">
                        {user.email} · {roleLabel(user.role)}
                        {unavailable ? ` · ${unavailable}` : ""}
                      </span>
                    </span>
                  </label>
                );
              })
            )}
          </div>
          {errors.people ? (
            <p id={peopleErrorId} className="break-words text-sm text-[var(--color-danger-500)]">
              {errors.people}
            </p>
          ) : null}
        </fieldset>

        <div className="flex min-w-0 flex-col gap-1.5 md:col-span-2">
          <Label htmlFor="matter-wall-reason">Reason (optional)</Label>
          <Textarea
            id="matter-wall-reason"
            value={reason}
            disabled={reviewing || create.isPending}
            aria-invalid={errors.reason ? true : undefined}
            aria-describedby={errors.reason ? reasonErrorId : undefined}
            placeholder="Conflict found at intake: acted for the respondent in 2024."
            onChange={(event) => {
              setReason(event.target.value);
              setErrors((current) => ({ ...current, reason: undefined }));
            }}
          />
          {errors.reason ? (
            <p id={reasonErrorId} className="break-words text-sm text-[var(--color-danger-500)]">
              {errors.reason}
            </p>
          ) : null}
        </div>

        {errors.form ? (
          <p id={formErrorId} role="alert" className="break-words text-sm text-[var(--color-danger-500)] md:col-span-2">
            {errors.form}
          </p>
        ) : null}

        {reviewing ? (
          <div
            className="flex min-w-0 flex-col gap-3 rounded-md border border-[var(--color-brand-300)] bg-[var(--color-brand-50)] p-3 text-sm md:col-span-2"
            role="group"
            aria-label="Confirm ethical wall"
            data-testid="matter-wall-confirm"
          >
            <p className="break-words text-[var(--color-ink)]">
              Wall off {chosen.map((person) => person.full_name).join(", ")} from{" "}
              <strong>{matter ? matterCaption(matter) : "this Matter"}</strong>? They lose access at
              once, including any explicit grant.
            </p>
            <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
              <Button
                type="button"
                className="w-full sm:w-auto"
                disabled={create.isPending}
                onClick={() => create.mutate()}
              >
                {create.isPending ? "Setting up wall…" : chosen.length > 1 ? `Confirm ${chosen.length} walls` : "Confirm wall"}
              </Button>
              <Button
                type="button"
                variant="outline"
                className="w-full sm:w-auto"
                disabled={create.isPending}
                onClick={() => setReviewing(false)}
              >
                Back
              </Button>
            </div>
          </div>
        ) : (
          <div className="md:col-span-2">
            <Button type="submit" className="w-full sm:w-auto" data-testid="matter-wall-review">
              Review wall
            </Button>
          </div>
        )}
        <p role="status" data-testid="matter-wall-result" className="break-words text-sm text-[var(--color-success-700)] md:col-span-2">
          {lastResult}
        </p>
      </form>
    </section>
  );
}

function ActiveWalls({
  rows,
  truncated,
  onChanged,
}: {
  rows: MatterEthicalWallDirectoryRow[];
  truncated: boolean;
  onChanged: () => Promise<unknown>;
}) {
  const [filter, setFilter] = useState("");
  // When the directory is truncated a local filter cannot see older walls, so
  // the user can search every wall on the server (one audited read per search).
  const [serverNeedle, setServerNeedle] = useState("");
  const trimmedFilter = filter.trim();
  const serverSearch = useQuery({
    queryKey: [...WALLS_QUERY_KEY, { q: serverNeedle }],
    queryFn: ({ signal }) => listMatterEthicalWalls(signal, { q: serverNeedle }),
    enabled: truncated && Boolean(serverNeedle),
  });
  const usingServer = truncated && Boolean(serverNeedle) && serverNeedle === trimmedFilter;
  const source = usingServer ? (serverSearch.data?.walls ?? []) : rows;
  const groups = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const byMatter = new Map<string, MatterEthicalWallDirectoryRow[]>();
    for (const row of source) {
      const haystack = [row.matter_code, row.matter_title, row.excluded_full_name, row.excluded_email];
      if (needle && !haystack.some((value) => value.toLowerCase().includes(needle))) continue;
      byMatter.set(row.matter_id, [...(byMatter.get(row.matter_id) ?? []), row]);
    }
    return [...byMatter.values()].sort((a, b) => a[0].matter_code.localeCompare(b[0].matter_code));
  }, [source, filter]);

  if (rows.length === 0) {
    return (
      <p className="text-sm text-[var(--color-mute)]" data-testid="matter-walls-empty">
        No active ethical walls on Matters you can open. When a conflict means
        someone must be screened from a Matter, set up a wall above.
      </p>
    );
  }
  return (
    <div className="flex min-w-0 flex-col gap-4">
      {rows.length > 8 ? (
        <Input
          aria-label="Filter walls by Matter or person"
          placeholder="Filter by Matter or person…"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />
      ) : null}
      {truncated ? (
        <p className="text-sm text-[var(--color-warning-700)]">
          Showing the 500 most recent walls. Older walls stay enforced; open the
          Matter&apos;s access panel to review them.
        </p>
      ) : null}
      {truncated && trimmedFilter && !usingServer ? (
        <div className="flex flex-wrap items-center gap-2 text-sm text-[var(--color-mute)]">
          <span>This filter covers the 500 most recent walls only.</span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setServerNeedle(trimmedFilter)}
            data-testid="matter-walls-search-all"
          >
            Search all walls
          </Button>
        </div>
      ) : null}
      {usingServer && serverSearch.data?.truncated ? (
        <p className="text-sm text-[var(--color-warning-700)]">
          Showing the 500 most recent walls that match. Narrow the search to see older ones.
        </p>
      ) : null}
      {usingServer && serverSearch.isPending ? (
        <p className="text-sm text-[var(--color-mute)]">Searching all walls…</p>
      ) : usingServer && serverSearch.isError ? (
        <p role="alert" className="text-sm text-[var(--color-danger-500)]">
          {apiErrorMessage(serverSearch.error, "Walls could not be searched.")}
        </p>
      ) : groups.length === 0 ? (
        <p className="text-sm text-[var(--color-mute)]">
          {truncated && !usingServer
            ? "No wall in the 500 most recent matches this filter."
            : "No wall matches this filter."}
        </p>
      ) : null}
      {groups.map((group) => {
        const head = group[0];
        return (
          <section
            key={head.matter_id}
            aria-label={`Walls on ${head.matter_code}`}
            className="min-w-0 overflow-hidden rounded-md border border-[var(--color-line)]"
            data-testid={`matter-walls-${head.matter_code}`}
          >
            <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-2 bg-[var(--color-bg-2)] px-3 py-2">
              <Link
                href={`/app/matters/${encodeURIComponent(head.matter_id)}`}
                className="min-w-0 break-words text-sm font-semibold text-[var(--color-ink)] hover:underline"
              >
                <span className="font-mono tabular-nums">{head.matter_code}</span> · {head.matter_title}
              </Link>
              <span className="text-xs text-[var(--color-mute)]">
                {group.length} {group.length === 1 ? "person walled" : "people walled"}
              </span>
            </div>
            <div className="hidden grid-cols-[minmax(0,1.3fr)_minmax(0,1.4fr)_minmax(0,1fr)_10rem] gap-3 border-b border-[var(--color-line-2)] px-3 py-1.5 text-xs font-medium text-[var(--color-mute)] md:grid">
              <span>Walled off</span>
              <span>Reason</span>
              <span>Set up by</span>
              <span className="sr-only">Action</span>
            </div>
            <ul className="min-w-0">
              {group.map((row) => (
                <WallRow key={row.id} row={row} onChanged={onChanged} />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function WallRow({ row, onChanged }: { row: MatterEthicalWallDirectoryRow; onChanged: () => Promise<unknown> }) {
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const errorId = useId();
  const lift = useMutation({
    mutationFn: () => removeMatterEthicalWall({ matterId: row.matter_id, wallId: row.id }),
    onSuccess: async () => {
      toast.success(`Wall lifted: ${row.excluded_full_name} has normal access to ${row.matter_code} again.`);
      await onChanged();
    },
    onError: async (err) => {
      if (isApiErrorShape(err) && err.status === 404) {
        setError("This wall was already lifted, or the Matter is no longer available to you. The list has been refreshed.");
        await onChanged();
        return;
      }
      setError(apiErrorMessage(err, "The wall could not be lifted."));
    },
  });

  return (
    <li
      className="grid min-w-0 gap-2 border-b border-[var(--color-line-2)] px-3 py-3 text-sm last:border-0 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1.4fr)_minmax(0,1fr)_10rem] md:items-start md:gap-3"
      data-testid={`matter-wall-row-${row.id}`}
    >
      <div className="flex min-w-0 flex-col gap-1">
        <span className="break-words font-medium text-[var(--color-ink)]">{row.excluded_full_name}</span>
        <span className="break-words text-xs text-[var(--color-mute)]">{row.excluded_email}</span>
        <span className="flex flex-wrap gap-1.5">
          <Badge>{roleLabel(row.excluded_role)}</Badge>
          {row.excluded_membership_active ? null : <Badge>Inactive</Badge>}
          {row.enforced ? null : <Badge tone="warning">Not enforced: owners bypass walls</Badge>}
        </span>
      </div>
      <div className="min-w-0 break-words text-[var(--color-ink-2)]">
        <span className="text-xs font-medium text-[var(--color-mute)] md:sr-only">Reason: </span>
        {row.reason ?? <span className="text-[var(--color-mute)]">No reason recorded</span>}
      </div>
      <div className="min-w-0 break-words text-xs text-[var(--color-mute)]">
        <span className="font-medium md:sr-only">Set up by: </span>
        {row.created_by_full_name ?? "Former member"} · {formatLegalDate(row.created_at)}
      </div>
      <div className="flex min-w-0 flex-col gap-2 md:items-end">
        {confirming ? (
          <div
            role="group"
            aria-label={`Confirm lifting the wall for ${row.excluded_full_name}`}
            className="flex min-w-0 flex-col gap-2 md:items-end"
          >
            <p className="break-words text-xs text-[var(--color-ink-2)] md:text-right">
              {row.excluded_full_name} regains normal access to {row.matter_code}.
            </p>
            <div className="flex flex-col gap-2 sm:flex-row md:flex-col md:items-end">
              <Button
                type="button"
                size="sm"
                variant="primary"
                disabled={lift.isPending}
                aria-describedby={error ? errorId : undefined}
                onClick={() => {
                  setError(null);
                  lift.mutate();
                }}
              >
                {lift.isPending ? "Lifting…" : "Confirm lift"}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={lift.isPending}
                onClick={() => {
                  setConfirming(false);
                  setError(null);
                }}
              >
                Keep wall
              </Button>
            </div>
          </div>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="outline"
            aria-label={`Lift wall for ${row.excluded_full_name} on ${row.matter_code}`}
            onClick={() => setConfirming(true)}
          >
            Lift wall
          </Button>
        )}
        {error ? (
          <p id={errorId} role="alert" className="break-words text-xs text-[var(--color-danger-500)] md:text-right">
            {error}
          </p>
        ) : null}
      </div>
    </li>
  );
}
