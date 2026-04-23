"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Banknote, Plus, Users } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { apiErrorMessage } from "@/lib/api/config";
import {
  createOutsideCounselAssignment,
  fetchOutsideCounselWorkspace,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import { useMatterWorkspace } from "@/lib/use-matter-workspace";

/**
 * Per-matter Outside Counsel view (Hari-II-BUG-019 Codex fix
 * 2026-04-21). Disambiguates from the Hari III sheet's BUG-019
 * (drafting 503) — always use the sheet prefix when referencing.
 *
 * Previous versions redirected to the workspace list, which Codex
 * (correctly) demoted to "Partial" — the redirect is a band-aid, not
 * a feature. This page fetches the workspace-wide counsel data and
 * filters to the current matter: shows each counsel assigned to
 * this matter with role / budget / spend, and exposes an Assign-counsel
 * action.
 */
export default function PerMatterOutsideCounselPage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const canManage = useCapability("outside_counsel:manage");
  const { data: matterData } = useMatterWorkspace(matterId);
  const workspaceQuery = useQuery({
    queryKey: ["outside-counsel", "workspace"],
    queryFn: () => fetchOutsideCounselWorkspace(),
  });

  const matterAssignments = useMemo(
    () =>
      (workspaceQuery.data?.assignments ?? []).filter(
        (a) => a.matter_id === matterId,
      ),
    [workspaceQuery.data, matterId],
  );
  const matterSpend = useMemo(
    () =>
      (workspaceQuery.data?.spend_records ?? []).filter(
        (s) => s.matter_id === matterId,
      ),
    [workspaceQuery.data, matterId],
  );
  const currency =
    workspaceQuery.data?.summary.currency ??
    (matterAssignments[0]?.currency ?? "INR");

  const totalBudget = matterAssignments.reduce(
    (acc, a) => acc + (a.budget_amount_minor ?? 0),
    0,
  );
  const totalSpend = matterSpend.reduce((acc, s) => acc + s.amount_minor, 0);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Matter · Outside counsel"
        title={
          matterData?.matter.title
            ? `${matterData.matter.title} — Outside counsel`
            : "Outside counsel on this matter"
        }
        description="Counsel engaged on this matter. Add or remove assignments; budgets and spend track against the matter."
        actions={
          canManage ? (
            <AssignCounselDialog
              matterId={matterId}
              availableCounsel={workspaceQuery.data?.profiles ?? []}
            />
          ) : (
            <Link
              className="text-xs text-[var(--color-brand-700)] underline-offset-4 hover:underline"
              href="/app/outside-counsel"
            >
              Open panel →
            </Link>
          )
        }
      />

      <section className="grid gap-3 md:grid-cols-3">
        <KpiCard
          icon={Users}
          label="Counsel assigned"
          value={String(matterAssignments.length)}
        />
        <KpiCard
          icon={Banknote}
          label="Approved budget"
          value={formatMoney(totalBudget, currency)}
        />
        <KpiCard
          icon={Banknote}
          label="Recorded spend"
          value={formatMoney(totalSpend, currency)}
        />
      </section>

      <Card>
        <CardHeader>
          <CardTitle as="h2" className="text-base">
            Assignments
          </CardTitle>
          <CardDescription>
            Counsel engaged on <span className="font-mono">{matterData?.matter.matter_code ?? "this matter"}</span>.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {workspaceQuery.isPending ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : workspaceQuery.isError ? (
            <QueryErrorState
              title="Could not load outside counsel"
              error={workspaceQuery.error}
              onRetry={workspaceQuery.refetch}
            />
          ) : matterAssignments.length === 0 ? (
            <EmptyState
              icon={Users}
              title="No counsel assigned to this matter yet"
              description={
                canManage
                  ? "Add a counsel from your panel to track engagement + spend against this matter."
                  : "A partner on your team can assign counsel from the panel."
              }
              action={
                canManage ? (
                  <AssignCounselDialog
                    matterId={matterId}
                    availableCounsel={workspaceQuery.data?.profiles ?? []}
                  />
                ) : undefined
              }
            />
          ) : (
            <ul className="flex flex-col gap-2">
              {matterAssignments.map((a) => (
                <li
                  key={a.id}
                  className="flex flex-col gap-1 rounded-lg border border-[var(--color-line)] bg-white px-3 py-2"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-semibold text-[var(--color-ink)]">
                        {a.counsel_name}
                      </div>
                      {a.role_summary ? (
                        <div className="text-xs text-[var(--color-mute)]">
                          {a.role_summary}
                        </div>
                      ) : null}
                    </div>
                    <StatusBadge status={a.status} />
                  </div>
                  <div className="flex items-center justify-between text-xs text-[var(--color-mute)]">
                    <span>
                      Budget:{" "}
                      {a.budget_amount_minor != null
                        ? formatMoney(a.budget_amount_minor, a.currency)
                        : "—"}
                    </span>
                    <span>
                      Assigned by {a.assigned_by_name ?? "—"}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {matterSpend.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle as="h2" className="text-base">
              Spend records
            </CardTitle>
            <CardDescription>
              Line-item costs billed to this matter by outside counsel.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="flex flex-col gap-2">
              {matterSpend.map((s) => (
                <li
                  key={s.id}
                  className="flex items-start justify-between gap-3 rounded-lg border border-[var(--color-line)] bg-white px-3 py-2"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-[var(--color-ink)]">
                      {s.description}
                    </div>
                    <div className="text-xs text-[var(--color-mute)]">
                      {s.counsel_name}
                      {s.stage_label ? ` · ${s.stage_label}` : ""}
                    </div>
                  </div>
                  <div className="text-right text-sm font-semibold tabular text-[var(--color-ink)]">
                    {formatMoney(s.amount_minor, s.currency)}
                  </div>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}


function KpiCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Users;
  label: string;
  value: string;
}): React.JSX.Element {
  return (
    <Card>
      <CardContent className="flex items-start gap-3 py-4">
        <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--color-bg)] text-[var(--color-ink-3)]">
          <Icon className="h-5 w-5" aria-hidden />
        </span>
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
            {label}
          </div>
          <div className="tabular text-xl font-semibold text-[var(--color-ink)]">
            {value}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}


function AssignCounselDialog({
  matterId,
  availableCounsel,
}: {
  matterId: string;
  availableCounsel: { id: string; name: string }[];
}): React.JSX.Element {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [counselId, setCounselId] = useState("");
  const [role, setRole] = useState("");
  const [budget, setBudget] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      createOutsideCounselAssignment({
        matterId,
        counselId,
        roleSummary: role.trim() || null,
        budgetAmountMinor: budget
          ? Math.round(Number(budget) * 100)
          : null,
      }),
    onSuccess: async () => {
      toast.success("Counsel assigned.");
      setOpen(false);
      setCounselId("");
      setRole("");
      setBudget("");
      await queryClient.invalidateQueries({
        queryKey: ["outside-counsel", "workspace"],
      });
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not assign."));
    },
  });

  const canSubmit =
    counselId.trim().length > 0 && !mutation.isPending;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" data-testid="matter-oc-assign-open">
          <Plus className="h-4 w-4" aria-hidden /> Assign counsel
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Assign outside counsel</DialogTitle>
          <DialogDescription>
            Pick a counsel from your panel. You can log spend against this
            assignment later.
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (canSubmit) mutation.mutate();
          }}
        >
          <div>
            <Label htmlFor="oc-counsel">Counsel</Label>
            {availableCounsel.length === 0 ? (
              <p className="text-xs text-[var(--color-mute)]">
                No counsel on your panel yet.{" "}
                <Link
                  className="text-[var(--color-brand-700)] underline-offset-4 hover:underline"
                  href="/app/outside-counsel"
                >
                  Add one
                </Link>{" "}
                first.
              </p>
            ) : (
              <Select value={counselId} onValueChange={setCounselId}>
                <SelectTrigger id="oc-counsel" data-testid="matter-oc-counsel-picker">
                  <SelectValue placeholder="Pick a counsel…" />
                </SelectTrigger>
                <SelectContent>
                  {availableCounsel.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>
          <div>
            <Label htmlFor="oc-role">Role / summary</Label>
            <Input
              id="oc-role"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder="Lead counsel on the bail petition"
              maxLength={255}
            />
          </div>
          <div>
            <Label htmlFor="oc-budget">Budget (INR)</Label>
            <Input
              id="oc-budget"
              type="number"
              min={0}
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
              placeholder="optional"
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!canSubmit || availableCounsel.length === 0}
              data-testid="matter-oc-assign-submit"
            >
              {mutation.isPending ? "Assigning…" : "Assign"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}


function formatMoney(minor: number, currency = "INR"): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
  }).format(minor / 100);
}
