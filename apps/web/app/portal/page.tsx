"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Briefcase,
  CalendarDays,
  LogOut,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
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
  fetchPortalMatters,
  fetchPortalSession,
  logoutPortal,
  type PortalMatter,
} from "@/lib/api/portal";

export default function PortalLandingPage() {
  const router = useRouter();
  // All hooks declared up-front so an early return below cannot
  // change the hook-call order between renders (React rule of
  // hooks). The early return for the session-error state lives
  // AFTER every useQuery / useMutation call.
  const sessionQuery = useQuery({
    queryKey: ["portal", "session"],
    queryFn: () => fetchPortalSession(),
    retry: 0,
  });
  const logoutMutation = useMutation({
    mutationFn: () => logoutPortal(),
    onSuccess: () => router.replace("/portal/sign-in"),
  });
  const portalUser = sessionQuery.data?.portal_user;
  const mattersQuery = useQuery({
    queryKey: ["portal", "matters"],
    queryFn: () => fetchPortalMatters(),
    enabled: Boolean(portalUser),
  });
  const roleLabel =
    portalUser?.role === "outside_counsel"
      ? "Outside counsel"
      : portalUser?.role === "client"
        ? "Client"
        : "Portal user";
  const matters: PortalMatter[] = mattersQuery.data?.matters ?? [];

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
            ? `Signed in as ${portalUser.email} (${roleLabel}). Tap a matter below to see status, hearings, communications, and KYC.`
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
            <ShieldCheck className="h-4 w-4" /> Your matters
          </CardTitle>
          <CardDescription>
            Every matter your firm has explicitly granted you. You cannot
            see anything outside this list.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {mattersQuery.isError ? (
            <QueryErrorState
              error={mattersQuery.error}
              title="Could not load your matters"
              onRetry={() => mattersQuery.refetch()}
            />
          ) : matters.length === 0 ? (
            <EmptyState
              icon={Briefcase}
              title="No matters yet"
              description="Your workspace has not granted you a matter yet. The firm will let you know when one is ready."
            />
          ) : (
            <ul className="space-y-2">
              {matters.map((m) => (
                <li
                  key={m.id}
                  className="flex items-center justify-between gap-2 rounded-md border border-[var(--color-line)] px-3 py-2"
                  data-testid={`portal-matter-${m.id}`}
                >
                  <Link
                    href={`/portal/matters/${m.id}`}
                    className="flex flex-1 flex-col"
                  >
                    <span className="text-sm font-medium text-[var(--color-ink)]">
                      {m.title}
                    </span>
                    <span className="text-xs text-[var(--color-mute)]">
                      {[
                        m.matter_code,
                        m.court_name,
                        m.next_hearing_on
                          ? `Next hearing ${new Date(m.next_hearing_on).toLocaleDateString()}`
                          : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </Link>
                  <div className="flex items-center gap-2">
                    <Badge tone="brand">{m.status}</Badge>
                    <Link href={`/portal/matters/${m.id}`}>
                      <Button size="sm" variant="outline">
                        Open <ArrowUpRight className="ml-1 h-3.5 w-3.5" />
                      </Button>
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <p className="flex items-center gap-1.5 text-xs text-[var(--color-mute)]">
        <CalendarDays className="h-3.5 w-3.5" />
        Signed in as {portalUser?.email ?? "—"} · {roleLabel}
      </p>

      <p className="text-xs text-[var(--color-mute)]">
        Need help? Contact your firm. CaseOps cannot reset portal access
        — only the firm that invited you can.
      </p>
    </main>
  );
}
