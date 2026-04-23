"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Archive, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { apiErrorMessage } from "@/lib/api/config";
import { archiveClient, fetchClient } from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";


export default function ClientProfilePage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const clientId = params.id;
  const queryClient = useQueryClient();
  const canArchive = useCapability("clients:archive");

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
          canArchive && c.is_active ? (
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
