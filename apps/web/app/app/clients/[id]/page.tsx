"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArchiveRestore,
  ArrowLeft,
  Archive,
  CheckCircle2,
  Link2,
  Loader2,
  ShieldCheck,
  Upload,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { MatterPicker, OPERATIONAL_MATTER_STATUSES } from "@/components/app/MatterPicker";
import { ClientContactEditor } from "@/components/clients/ClientContactEditor";
import { ClientKycPanel } from "@/components/clients/ClientKycPanel";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { apiErrorMessage } from "@/lib/api/config";
import {
  archiveClient,
  assignClientToMatter,
  fetchClient,
  unarchiveClient,
  unassignClientFromMatter,
  type ClientMatterLink,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";


export default function ClientProfilePage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const clientId = params.id;
  const queryClient = useQueryClient();
  const canArchive = useCapability("clients:archive");
  const canSubmitKyc = useCapability("clients:kyc_submit");
  const canReviewKyc = useCapability("clients:kyc_review");

  const query = useQuery({
    queryKey: ["clients", clientId],
    queryFn: () => fetchClient(clientId),
  });

  const archiveMutation = useMutation({
    mutationFn: () => archiveClient(clientId),
    onSuccess: async () => {
      toast.success("Client archived.");
      await queryClient.invalidateQueries({ queryKey: ["clients"] });
      router.push("/app/clients");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not archive."));
    },
  });

  // Phase B / BUG-025: archive is now reversible. The button only
  // renders when the current client is archived AND the caller has
  // the same capability that can archive (clients:archive).
  const unarchiveMutation = useMutation({
    mutationFn: () => unarchiveClient(clientId),
    onSuccess: async () => {
      toast.success("Client restored.");
      await queryClient.invalidateQueries({ queryKey: ["clients"] });
      await queryClient.invalidateQueries({ queryKey: ["clients", clientId] });
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not restore client."));
    },
  });

  if (query.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }
  if (query.isError) {
    return (
      <QueryErrorState
        title="Could not load client"
        error={query.error}
        onRetry={query.refetch}
      />
    );
  }

  const c = query.data;
  const kycTone =
    c.kyc_status === "verified"
      ? "success"
      : c.kyc_status === "rejected" || c.kyc_status === "expired"
        ? "warning"
        : c.kyc_status === "submitted" ||
            c.kyc_status === "under_review" ||
            c.kyc_status === "requested"
          ? "brand"
          : "neutral";

  return (
    <div className="flex min-w-0 flex-col gap-6 break-words">
      <div>
        <Link
          href="/app/clients"
          className="inline-flex items-center gap-1 text-xs text-[var(--color-mute)] hover:text-[var(--color-ink)]"
        >
          <ArrowLeft className="h-3 w-3" aria-hidden /> Clients
        </Link>
      </div>
      <PageHeader
        className="[&>div]:min-w-0"
        eyebrow={c.client_type}
        title={c.name}
        description={
          c.city || c.state || c.country
            ? [c.city, c.state, c.country].filter(Boolean).join(", ")
            : "Client profile"
        }
        actions={
          <>
            <ClientContactEditor key={c.id} client={c} />
            {canArchive ? (
              c.is_active ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={archiveMutation.isPending}
                  onClick={() => archiveMutation.mutate()}
                  data-testid="client-archive"
                >
                  <Archive className="h-4 w-4" aria-hidden /> Archive
                </Button>
              ) : (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={unarchiveMutation.isPending}
                  onClick={() => unarchiveMutation.mutate()}
                  data-testid="client-unarchive"
                >
                  <ArchiveRestore className="h-4 w-4" aria-hidden /> Restore
                </Button>
              )
            ) : null}
          </>
        }
      />

      <section className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="py-4">
            <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
              KYC
            </div>
            <div className="mt-1 flex items-center gap-2">
              <Badge tone={kycTone}>{c.kyc_status.replace("_", " ")}</Badge>
              {c.kyc_status === "verified" ? (
                <ShieldCheck
                  className="h-4 w-4 text-[var(--color-brand-600)]"
                  aria-hidden
                />
              ) : null}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
              Active matters
            </div>
            <div className="mt-1 tabular text-xl font-semibold text-[var(--color-ink)]">
              {c.active_matters_count}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
              Total matters
            </div>
            <div className="mt-1 tabular text-xl font-semibold text-[var(--color-ink)]">
              {c.total_matters_count}
            </div>
          </CardContent>
        </Card>
      </section>

      <Card>
        <CardHeader>
          <CardTitle as="h2" className="text-base">
            Contact
          </CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid min-w-0 gap-3 [overflow-wrap:anywhere] sm:grid-cols-2">
            <div>
              <dt className="text-xs text-[var(--color-mute)]">Primary contact</dt>
              <dd className="text-sm font-medium text-[var(--color-ink-2)]">
                {c.primary_contact_name ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-mute)]">Email</dt>
              <dd className="text-sm font-medium text-[var(--color-ink-2)]">
                {c.primary_contact_email ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-mute)]">Phone</dt>
              <dd className="text-sm font-medium text-[var(--color-ink-2)]">
                {c.primary_contact_phone ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-mute)]">PAN / GSTIN</dt>
              <dd className="text-sm font-medium text-[var(--color-ink-2)]">
                {[c.pan, c.gstin].filter(Boolean).join(" · ") || "—"}
              </dd>
            </div>
            {/* Strict Ledger #4 (BUG-022 follow-up, 2026-04-22):
                full street address renders alongside contact in
                the Contact dl. Each piece on its own row so the
                user can see exactly what's recorded vs missing. */}
            <div className="sm:col-span-2">
              <dt className="text-xs text-[var(--color-mute)]">Address line 1</dt>
              <dd className="text-sm font-medium text-[var(--color-ink-2)]">
                {c.address_line_1 ?? "—"}
              </dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-xs text-[var(--color-mute)]">Address line 2</dt>
              <dd className="text-sm font-medium text-[var(--color-ink-2)]">
                {c.address_line_2 ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-mute)]">City</dt>
              <dd className="text-sm font-medium text-[var(--color-ink-2)]">
                {c.city ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-mute)]">State</dt>
              <dd className="text-sm font-medium text-[var(--color-ink-2)]">
                {c.state ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-mute)]">Postal code</dt>
              <dd className="text-sm font-medium text-[var(--color-ink-2)]">
                {c.postal_code ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--color-mute)]">Country</dt>
              <dd className="text-sm font-medium text-[var(--color-ink-2)]">
                {c.country ?? "—"}
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      <ClientKycPanel client={c} canSubmit={canSubmitKyc} canReview={canReviewKyc} />

      <ClientMattersCard
        clientId={c.id}
        clientName={c.name}
        clientIsActive={c.is_active}
        matters={c.matters}
      />

      {c.internal_notes ? (
        <Card>
          <CardHeader>
            <CardTitle as="h2" className="text-base">
              Internal notes
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="whitespace-pre-wrap text-sm text-[var(--color-ink-2)]">
              {c.internal_notes}
            </p>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

// nova-legal 2026-11-25: a client is linked to Matters from here as well as
// from the Matter overview. The picker lists only Matters the user can open
// (the wall-scoped Matter list) and disables the ones the link API refuses.
function ClientMattersCard({
  clientId,
  clientName,
  clientIsActive,
  matters,
}: {
  clientId: string;
  clientName: string;
  clientIsActive: boolean;
  matters: ClientMatterLink[];
}) {
  const queryClient = useQueryClient();
  const canEdit = useCapability("clients:edit");
  const [linking, setLinking] = useState(false);
  const [matterId, setMatterId] = useState("");
  const [role, setRole] = useState("");
  const [makePrimary, setMakePrimary] = useState(false);
  const [confirmUnlink, setConfirmUnlink] = useState<string | null>(null);
  const linkedIds = new Set(matters.map((m) => m.matter_id));
  const blockedReason = !canEdit
    ? "Your role can view these matters but cannot link or unlink them."
    : !clientIsActive
      ? "This client is archived. Restore it to link it to matters."
      : null;

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["clients"] }),
      queryClient.invalidateQueries({ queryKey: ["matters"] }),
    ]);
  };
  const resetForm = () => {
    setLinking(false);
    setMatterId("");
    setRole("");
    setMakePrimary(false);
  };
  const linkMutation = useMutation({
    mutationFn: () =>
      assignClientToMatter({
        matterId,
        clientId,
        role: role.trim() || null,
        // Always explicit: the link is primary exactly when the box is checked.
        isPrimary: makePrimary,
      }),
    onSuccess: async () => {
      toast.success("Matter linked to this client.");
      resetForm();
      await refresh();
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not link the matter.")),
  });
  const unlinkMutation = useMutation({
    mutationFn: (targetMatterId: string) =>
      unassignClientFromMatter({ matterId: targetMatterId, clientId }),
    onSuccess: async () => {
      toast.success("Matter unlinked from this client.");
      setConfirmUnlink(null);
      await refresh();
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not unlink the matter.")),
  });

  return (
    <Card data-testid="client-matters-card">
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3 space-y-0">
        <CardTitle as="h2" className="text-base">
          Matters linked to this client
        </CardTitle>
        <div className="flex min-w-0 flex-col items-end gap-1">
          <Button
            type="button"
            size="sm"
            variant={linking ? "ghost" : "outline"}
            disabled={Boolean(blockedReason)}
            aria-describedby={blockedReason ? "client-matters-blocked" : undefined}
            onClick={() => (linking ? resetForm() : setLinking(true))}
            data-testid="client-link-matter-open"
          >
            <Link2 className="h-4 w-4" aria-hidden />
            {linking ? "Cancel" : "Link to matter"}
          </Button>
          {blockedReason ? (
            <p id="client-matters-blocked" className="max-w-xs text-right text-xs text-[var(--color-mute)]">
              {blockedReason}
            </p>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {linking && !blockedReason ? (
          <form
            className="grid gap-3 rounded-md border border-[var(--color-line)] p-3 md:grid-cols-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (matterId) linkMutation.mutate();
            }}
            data-testid="client-link-matter-form"
          >
            <MatterPicker
              className="md:col-span-2"
              id="client-link-matter-picker"
              label="Matter to link"
              searchLabel="Search matters"
              value={matterId}
              onChange={(next) => setMatterId(next)}
              disabledReason={(matter) =>
                linkedIds.has(matter.id)
                  ? "already linked to this client"
                  : OPERATIONAL_MATTER_STATUSES.has(matter.status)
                    ? null
                    : "disposed matters take no new client links"
              }
            />
            <div className="flex min-w-0 flex-col gap-1.5">
              <Label htmlFor="client-link-matter-role">Role on the matter (optional)</Label>
              <Input
                id="client-link-matter-role"
                value={role}
                maxLength={60}
                placeholder="Petitioner, respondent, guarantor…"
                onChange={(event) => setRole(event.target.value)}
              />
            </div>
            <div className="flex min-w-0 flex-col gap-1 self-end pb-2">
              <label className="flex items-center gap-2 text-sm text-[var(--color-ink)]">
                <input
                  type="checkbox"
                  checked={makePrimary}
                  onChange={(event) => setMakePrimary(event.target.checked)}
                  aria-describedby="client-link-matter-primary-caption"
                  data-testid="client-link-matter-primary"
                />
                Make {clientName} the matter&apos;s primary client
              </label>
              <p
                id="client-link-matter-primary-caption"
                className="break-words text-xs text-[var(--color-mute)]"
                data-testid="client-link-matter-primary-caption"
              >
                {makePrimary
                  ? `${clientName} becomes the matter's primary client: its name replaces the matter's client name and any current primary client.`
                  : `${clientName} is linked as an additional client; the matter's primary client and client name do not change.`}
              </p>
            </div>
            <div className="flex justify-end gap-2 md:col-span-2">
              <Button type="button" variant="outline" size="sm" onClick={resetForm}>
                Cancel
              </Button>
              <Button
                type="submit"
                size="sm"
                disabled={!matterId || linkMutation.isPending}
                data-testid="client-link-matter-submit"
              >
                {linkMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                Link matter
              </Button>
            </div>
          </form>
        ) : null}

        {matters.length === 0 ? (
          <EmptyState
            icon={Archive}
            title="No matters linked yet"
            description={
              blockedReason
                ? "Matters you can open appear here once this client is linked to them."
                : "Use Link to matter, or link this client from a matter's Clients card. Only matters you can open are listed."
            }
          />
        ) : (
          <ul className="flex flex-col gap-2">
            {matters.map((m) => {
              const operational = OPERATIONAL_MATTER_STATUSES.has(m.status);
              const unlinkBlocked = !canEdit
                ? "Your role cannot unlink matters."
                : operational
                  ? null
                  : "Disposed matters keep their client links.";
              return (
                <li
                  key={m.matter_id}
                  className="flex flex-col gap-2 rounded-md border border-[var(--color-line)] bg-white px-3 py-2"
                  data-testid="client-matter-row"
                >
                  <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                    <Link
                      href={`/app/matters/${m.matter_id}`}
                      className="min-w-0 break-words hover:underline"
                    >
                      <div className="font-mono text-xs text-[var(--color-mute)]">
                        {m.matter_code}
                      </div>
                      <div className="text-sm font-medium text-[var(--color-ink)]">
                        {m.matter_title}
                      </div>
                    </Link>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-mute)]">
                      {m.role ? <Badge tone="neutral">{m.role}</Badge> : null}
                      {m.is_primary ? <Badge tone="brand">primary</Badge> : null}
                      <span className="capitalize">{m.status.replace(/_/g, " ")}</span>
                      {confirmUnlink === m.matter_id ? null : (
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          disabled={Boolean(unlinkBlocked)}
                          title={unlinkBlocked ?? undefined}
                          aria-label={`Unlink ${m.matter_code}`}
                          onClick={() => setConfirmUnlink(m.matter_id)}
                        >
                          Unlink
                        </Button>
                      )}
                    </div>
                  </div>
                  {confirmUnlink === m.matter_id ? (
                    <div
                      role="alert"
                      className="flex flex-col gap-2 rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] p-3 text-sm"
                    >
                      <p className="text-[var(--color-ink)]">
                        Unlink {m.matter_code} from {clientName}?
                        {m.is_primary
                          ? " The matter keeps this client's name as its client name until another primary client is linked or the name is edited."
                          : ""}
                      </p>
                      <div className="flex justify-end gap-2">
                        <Button type="button" size="sm" variant="outline" onClick={() => setConfirmUnlink(null)}>
                          Keep linked
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          disabled={unlinkMutation.isPending}
                          onClick={() => unlinkMutation.mutate(m.matter_id)}
                        >
                          Unlink matter
                        </Button>
                      </div>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
