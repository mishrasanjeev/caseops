"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArchiveRestore,
  ArrowLeft,
  Archive,
  CheckCircle2,
  ShieldCheck,
  Upload,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { apiErrorMessage } from "@/lib/api/config";
import {
  archiveClient,
  fetchClient,
  rejectClientKyc,
  submitClientKyc,
  unarchiveClient,
  verifyClientKyc,
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

  // Phase B M11 slice 3 — KYC lifecycle mutations.
  const kycInvalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["clients"] });
    await queryClient.invalidateQueries({ queryKey: ["clients", clientId] });
  };
  const kycSubmitMutation = useMutation({
    mutationFn: (documents: { name: string }[]) =>
      submitClientKyc({ clientId, documents }),
    onSuccess: async () => {
      toast.success("KYC submitted for review.");
      await kycInvalidate();
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not submit KYC.")),
  });
  const kycVerifyMutation = useMutation({
    mutationFn: () => verifyClientKyc(clientId),
    onSuccess: async () => {
      toast.success("KYC verified.");
      await kycInvalidate();
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not verify KYC.")),
  });
  const kycRejectMutation = useMutation({
    mutationFn: (reason: string) =>
      rejectClientKyc({ clientId, reason }),
    onSuccess: async () => {
      toast.success("KYC rejected.");
      await kycInvalidate();
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not reject KYC.")),
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
      : c.kyc_status === "rejected"
        ? "warning"
        : "neutral";

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link
          href="/app/clients"
          className="inline-flex items-center gap-1 text-xs text-[var(--color-mute)] hover:text-[var(--color-ink)]"
        >
          <ArrowLeft className="h-3 w-3" aria-hidden /> Clients
        </Link>
      </div>
      <PageHeader
        eyebrow={c.client_type}
        title={c.name}
        description={
          c.city || c.state || c.country
            ? [c.city, c.state, c.country].filter(Boolean).join(", ")
            : "Client profile"
        }
        actions={
          canArchive ? (
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
          ) : undefined
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
          <dl className="grid gap-3 sm:grid-cols-2">
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

      <KycPanel
        client={c}
        canSubmit={canSubmitKyc}
        canReview={canReviewKyc}
        submitting={kycSubmitMutation.isPending}
        verifying={kycVerifyMutation.isPending}
        rejecting={kycRejectMutation.isPending}
        onSubmit={(docs) => kycSubmitMutation.mutate(docs)}
        onVerify={() => kycVerifyMutation.mutate()}
        onReject={(reason) => kycRejectMutation.mutate(reason)}
      />

      <Card>
        <CardHeader>
          <CardTitle as="h2" className="text-base">
            Matters linked to this client
          </CardTitle>
        </CardHeader>
        <CardContent>
          {c.matters.length === 0 ? (
            <EmptyState
              icon={Archive}
              title="No matters yet"
              description="Open a matter and link this client from its overview page to populate this list."
            />
          ) : (
            <ul className="flex flex-col gap-2">
              {c.matters.map((m) => (
                <li key={m.matter_id}>
                  <Link
                    href={`/app/matters/${m.matter_id}`}
                    className="flex items-center justify-between rounded-md border border-[var(--color-line)] bg-white px-3 py-2 hover:border-[var(--color-ink-3)]"
                  >
                    <div>
                      <div className="font-mono text-xs text-[var(--color-mute)]">
                        {m.matter_code}
                      </div>
                      <div className="text-sm font-medium text-[var(--color-ink)]">
                        {m.matter_title}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-[var(--color-mute)]">
                      {m.role ? <Badge tone="neutral">{m.role}</Badge> : null}
                      {m.is_primary ? <Badge tone="brand">primary</Badge> : null}
                      <span className="capitalize">{m.status}</span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

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

// Phase B M11 slice 3 — KYC card with submit / verify / reject
// actions. The state machine is enforced server-side; the UI just
// hides actions that don't make sense for the current status.
type KycPanelClient = {
  kyc_status: "not_started" | "pending" | "verified" | "rejected";
  kyc_submitted_at: string | null;
  kyc_verified_at: string | null;
  kyc_rejection_reason: string | null;
  kyc_documents: { name: string; status: string; note: string | null }[];
};

function KycPanel({
  client,
  canSubmit,
  canReview,
  submitting,
  verifying,
  rejecting,
  onSubmit,
  onVerify,
  onReject,
}: {
  client: KycPanelClient;
  canSubmit: boolean;
  canReview: boolean;
  submitting: boolean;
  verifying: boolean;
  rejecting: boolean;
  onSubmit: (documents: { name: string }[]) => void;
  onVerify: () => void;
  onReject: (reason: string) => void;
}) {
  const [docsInput, setDocsInput] = useState(
    "PAN\nAadhaar / address proof\nBoard resolution / authorisation",
  );
  const [showSubmit, setShowSubmit] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [showReject, setShowReject] = useState(false);

  const formatLocal = (iso: string | null): string =>
    iso
      ? new Date(iso).toLocaleString(undefined, {
          day: "2-digit",
          month: "short",
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        })
      : "—";

  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2" className="text-base">
          KYC verification
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Badge
              tone={
                client.kyc_status === "verified"
                  ? "success"
                  : client.kyc_status === "rejected"
                    ? "warning"
                    : client.kyc_status === "pending"
                      ? "brand"
                      : "neutral"
              }
            >
              {client.kyc_status.replace("_", " ")}
            </Badge>
            {client.kyc_status === "verified" ? (
              <ShieldCheck
                className="h-4 w-4 text-[var(--color-brand-600)]"
                aria-hidden
              />
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {canSubmit &&
            (client.kyc_status === "not_started" ||
              client.kyc_status === "rejected") ? (
              <Button
                type="button"
                size="sm"
                onClick={() => setShowSubmit((s) => !s)}
                data-testid="kyc-submit-toggle"
              >
                <Upload className="h-4 w-4" aria-hidden />
                {client.kyc_status === "rejected"
                  ? "Re-submit KYC"
                  : "Submit KYC"}
              </Button>
            ) : null}
            {canReview && client.kyc_status === "pending" ? (
              <>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setShowReject((s) => !s)}
                  data-testid="kyc-reject-toggle"
                >
                  <XCircle className="h-4 w-4" aria-hidden /> Reject
                </Button>
                <Button
                  type="button"
                  size="sm"
                  disabled={verifying}
                  onClick={() => onVerify()}
                  data-testid="kyc-verify"
                >
                  <CheckCircle2 className="h-4 w-4" aria-hidden /> Verify
                </Button>
              </>
            ) : null}
          </div>
        </div>

        {client.kyc_submitted_at ? (
          <div className="mt-3 grid gap-2 text-xs text-[var(--color-mute)] sm:grid-cols-2">
            <div>
              <span className="font-medium text-[var(--color-ink)]">
                Submitted
              </span>
              {" — "}
              {formatLocal(client.kyc_submitted_at)}
            </div>
            {client.kyc_verified_at ? (
              <div>
                <span className="font-medium text-[var(--color-ink)]">
                  Verified
                </span>
                {" — "}
                {formatLocal(client.kyc_verified_at)}
              </div>
            ) : null}
          </div>
        ) : null}

        {client.kyc_status === "rejected" && client.kyc_rejection_reason ? (
          <div className="mt-3 rounded-md border border-[var(--color-warning-500)]/40 bg-[var(--color-warning-500)]/10 p-3 text-xs">
            <div className="font-medium text-[var(--color-ink)]">
              Rejection reason
            </div>
            <p className="mt-1 whitespace-pre-wrap text-[var(--color-ink-2)]">
              {client.kyc_rejection_reason}
            </p>
          </div>
        ) : null}

        {client.kyc_documents.length > 0 ? (
          <div className="mt-3">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-mute)]">
              Documents on file
            </div>
            <ul className="mt-1 list-disc pl-5 text-xs text-[var(--color-ink-2)]">
              {client.kyc_documents.map((d, i) => (
                <li key={`${d.name}-${i}`}>
                  {d.name}
                  {d.status && d.status !== "received" ? (
                    <span className="ml-1 text-[var(--color-mute)]">
                      ({d.status})
                    </span>
                  ) : null}
                  {d.note ? (
                    <span className="ml-1 text-[var(--color-mute)]">
                      — {d.note}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {showSubmit ? (
          <form
            className="mt-4 flex flex-col gap-2 rounded-md border border-[var(--color-line)] bg-[var(--color-line-1)]/40 p-3"
            onSubmit={(e) => {
              e.preventDefault();
              const docs = docsInput
                .split(/\r?\n/)
                .map((s) => s.trim())
                .filter(Boolean)
                .map((name) => ({ name }));
              onSubmit(docs);
              setShowSubmit(false);
            }}
          >
            <label className="flex flex-col gap-1 text-xs font-medium text-[var(--color-ink)]">
              Documents collected (one per line)
              <textarea
                value={docsInput}
                onChange={(e) => setDocsInput(e.target.value)}
                rows={4}
                className="rounded-md border border-[var(--color-line)] px-2 py-1 text-sm font-mono"
                data-testid="kyc-submit-docs"
              />
            </label>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setShowSubmit(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                size="sm"
                disabled={submitting}
                data-testid="kyc-submit"
              >
                Submit for review
              </Button>
            </div>
          </form>
        ) : null}

        {showReject ? (
          <form
            className="mt-4 flex flex-col gap-2 rounded-md border border-[var(--color-line)] bg-[var(--color-line-1)]/40 p-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (rejectReason.trim().length < 4) return;
              onReject(rejectReason.trim());
              setShowReject(false);
              setRejectReason("");
            }}
          >
            <label className="flex flex-col gap-1 text-xs font-medium text-[var(--color-ink)]">
              Rejection reason (visible to the lawyer who submitted)
              <textarea
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                rows={3}
                required
                placeholder="e.g. Address proof missing — please attach a recent utility bill."
                className="rounded-md border border-[var(--color-line)] px-2 py-1 text-sm"
                data-testid="kyc-reject-reason"
              />
            </label>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setShowReject(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                size="sm"
                disabled={rejecting || rejectReason.trim().length < 4}
                data-testid="kyc-reject"
              >
                Send rejection
              </Button>
            </div>
          </form>
        ) : null}
      </CardContent>
    </Card>
  );
}
