"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Briefcase, LogOut, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import {
  fetchPortalSession,
  logoutPortal,
  type PortalGrant,
} from "@/lib/api/portal";

export default function PortalLandingPage() {
  const router = useRouter();
  const sessionQuery = useQuery({
    queryKey: ["portal", "session"],
    queryFn: () => fetchPortalSession(),
    retry: 0,
  });

  const logoutMutation = useMutation({
    mutationFn: () => logoutPortal(),
    onSuccess: () => router.replace("/portal/sign-in"),
  });

  if (sessionQuery.isError) {
    return (
      <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 px-6 py-10">
        <QueryErrorState
          error={sessionQuery.error}
          title="Sign in to your portal"
          onRetry={() => router.push("/portal/sign-in")}
        />
      </main>
    );
  }

  const portalUser = sessionQuery.data?.portal_user;
  const grants: PortalGrant[] = sessionQuery.data?.grants ?? [];
  const roleLabel =
    portalUser?.role === "outside_counsel"
      ? "Outside counsel"
      : portalUser?.role === "client"
        ? "Client"
        : "Portal user";

  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col gap-6 px-6 py-10">
      <PageHeader
        eyebrow="Workspace portal"
        title={
          portalUser
            ? `Welcome, ${portalUser.full_name.split(" ")[0]}`
            : "Workspace portal"
        }
        description={
          portalUser
            ? `Signed in as ${portalUser.email} (${roleLabel}). Phase C-2 and C-3 will add the matter, comms, and document surfaces — for now this page confirms your portal session is live.`
            : "Loading your portal session…"
        }
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => logoutMutation.mutate()}
            disabled={logoutMutation.isPending}
            data-testid="portal-logout"
          >
            <LogOut className="mr-1 h-3.5 w-3.5" />
            Sign out
          </Button>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="h-4 w-4" /> Your access
          </CardTitle>
          <CardDescription>
            Below is every matter your firm has explicitly granted you.
            You cannot see anything outside this list.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {grants.length === 0 ? (
            <EmptyState
              icon={Briefcase}
              title="No matters yet"
              description="Your workspace has not granted you a matter yet. The firm will let you know when one is ready."
            />
          ) : (
            <ul className="space-y-2">
              {grants.map((g) => (
                <li
                  key={g.id}
                  className="flex items-center justify-between gap-2 rounded-md border border-[var(--color-line)] px-3 py-2"
                  data-testid={`portal-grant-${g.id}`}
                >
                  <div className="flex flex-col">
                    <span className="text-sm font-medium text-[var(--color-ink)]">
                      Matter {g.matter_id.slice(0, 8)}…
                    </span>
                    <span className="text-xs text-[var(--color-mute)]">
                      Granted {new Date(g.granted_at).toLocaleDateString()}
                    </span>
                  </div>
                  <Badge tone="brand">{roleLabel}</Badge>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <p className="text-xs text-[var(--color-mute)]">
        Need help? Contact your firm. CaseOps cannot reset portal access
        — only the firm that invited you can.
      </p>
    </main>
  );
}
