"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Loader2,
  Plus,
  ShieldCheck,
  Trash2,
  Users,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
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
import { Textarea } from "@/components/ui/Textarea";
import { ApiError } from "@/lib/api/config";
import {
  createTeam,
  deleteTeam,
  listTeams,
  setTeamScoping,
  type Team,
  type TeamKind,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

const KIND_LABEL: Record<TeamKind, string> = {
  team: "Team",
  department: "Department",
  practice_area: "Practice area",
};

export default function TeamsAdminPage() {
  const canManage = useCapability("teams:manage");
  const queryClient = useQueryClient();

  const teamsQuery = useQuery({
    queryKey: ["teams", "list"],
    queryFn: () => listTeams(),
  });

  const scopingMutation = useMutation({
    mutationFn: (enabled: boolean) => setTeamScoping(enabled),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["teams", "list"] });
      toast.success(
        result.enabled
          ? "Team scoping is on — non-owners see only their team's matters."
          : "Team scoping is off — teams are metadata only.",
      );
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Could not update scoping."),
  });

  const deleteMutation = useMutation({
    mutationFn: (teamId: string) => deleteTeam(teamId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["teams", "list"] });
      toast.success("Team deleted.");
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Could not delete team."),
  });

  return (
    <div className="flex flex-col gap-6">
      <Link
        href="/app/admin"
        className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-mute)] hover:text-[var(--color-ink)]"
      >
        ← Back to admin
      </Link>
      <PageHeader
        eyebrow="Admin"
        title="Teams"
        description="Group your firm into teams, departments, or practice areas. Optionally scope matter visibility to team membership."
        actions={canManage ? <NewTeamDialog /> : null}
      />

      {!canManage ? (
        <EmptyState
          icon={Users}
          title="You don't have access to manage teams"
          description="Ask a workspace owner to grant the teams:manage capability."
        />
      ) : teamsQuery.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : teamsQuery.isError ? (
        <QueryErrorState
          title="Could not load teams"
          error={teamsQuery.error}
          onRetry={teamsQuery.refetch}
        />
      ) : (
        <>
          <Card>
            <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
              <div>
                <CardTitle as="h2" className="text-base">
                  Team-scoped matter visibility
                </CardTitle>
                <CardDescription>
                  When on, non-owners see only matters where they're on the
                  team (firm-wide matters with no team stay visible). Owners
                  always see everything.
                </CardDescription>
              </div>
              <Button
                variant={teamsQuery.data?.team_scoping_enabled ? "secondary" : "outline"}
                size="sm"
                onClick={() =>
                  scopingMutation.mutate(!teamsQuery.data?.team_scoping_enabled)
                }
                disabled={scopingMutation.isPending}
                data-testid="team-scoping-toggle"
              >
                {scopingMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <ShieldCheck className="h-4 w-4" aria-hidden />
                )}
                {teamsQuery.data?.team_scoping_enabled ? "Scoping: ON" : "Scoping: off"}
              </Button>
            </CardHeader>
          </Card>

          {teamsQuery.data?.teams.length === 0 ? (
            <EmptyState
              icon={Users}
              title="No teams yet"
              description="Create a team to start grouping members. Teams are metadata by default; flip scoping on to enforce visibility."
              action={canManage ? <NewTeamDialog /> : undefined}
            />
          ) : (
            <ul className="flex flex-col gap-3" data-testid="teams-list">
              {teamsQuery.data?.teams.map((team) => (
                <TeamRow
                  key={team.id}
                  team={team}
                  onDelete={() => deleteMutation.mutate(team.id)}
                  deleting={
                    deleteMutation.isPending &&
                    deleteMutation.variables === team.id
                  }
                />
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function TeamRow({
  team,
  onDelete,
  deleting,
}: {
  team: Team;
  onDelete: () => void;
  deleting: boolean;
}) {
  return (
    <li className="rounded-xl border border-[var(--color-line)] bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-xs text-[var(--color-mute)]">
            <span className="rounded-full border border-[var(--color-line)] bg-[var(--color-bg-2)] px-2 py-0.5 font-medium capitalize text-[var(--color-ink-2)]">
              {KIND_LABEL[team.kind]}
            </span>
            {!team.is_active ? <StatusBadge status="archived" /> : null}
            <span className="font-mono">{team.slug}</span>
          </div>
          <h3 className="mt-1 text-sm font-semibold text-[var(--color-ink)]">
            {team.name}
          </h3>
          {team.description ? (
            <p className="mt-0.5 text-xs text-[var(--color-mute)]">
              {team.description}
            </p>
          ) : null}
          <p className="mt-2 text-xs text-[var(--color-mute)]">
            {team.member_count === 0
              ? "No members yet."
              : `${team.member_count} member${team.member_count === 1 ? "" : "s"}: `}
            {team.members.map((m, i) => (
              <span key={m.id}>
                {i > 0 ? ", " : ""}
                <span className="text-[var(--color-ink-2)]">{m.member_name}</span>
                {m.is_lead ? " (lead)" : ""}
              </span>
            ))}
          </p>
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={onDelete}
          disabled={deleting}
          data-testid={`team-delete-${team.slug}`}
        >
          {deleting ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <Trash2 className="h-4 w-4" aria-hidden />
          )}
          Delete
        </Button>
      </div>
    </li>
  );
}

const newTeamSchema = z.object({
  name: z.string().min(2).max(120),
  slug: z.string().min(2).max(80).regex(/^[a-z0-9-]+$/),
  description: z.string().max(2000).optional().or(z.literal("")),
  kind: z.enum(["team", "department", "practice_area"]),
});
type NewTeamValues = z.infer<typeof newTeamSchema>;

function NewTeamDialog() {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const form = useForm<NewTeamValues>({
    resolver: zodResolver(newTeamSchema),
    defaultValues: { name: "", slug: "", description: "", kind: "team" },
  });

  const mutation = useMutation({
    mutationFn: (values: NewTeamValues) =>
      createTeam({
        name: values.name.trim(),
        slug: values.slug.trim(),
        description: values.description?.trim() || null,
        kind: values.kind,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["teams", "list"] });
      toast.success("Team created.");
      form.reset();
      setOpen(false);
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Could not create team."),
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" data-testid="new-team-trigger">
          <Plus className="h-4 w-4" aria-hidden /> New team
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Create a team</DialogTitle>
          <DialogDescription>
            Teams are metadata by default. Flip team-scoping on to enforce
            visibility based on membership.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-4"
          onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
          noValidate
          aria-label="New team"
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="team-name">Name</Label>
            <Input id="team-name" placeholder="Litigation" {...form.register("name")} />
            {form.formState.errors.name ? (
              <p className="text-xs text-[var(--color-danger-500,#c53030)]" role="alert">
                {form.formState.errors.name.message}
              </p>
            ) : null}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="team-slug">Slug</Label>
            <Input
              id="team-slug"
              placeholder="litigation"
              {...form.register("slug")}
            />
            {form.formState.errors.slug ? (
              <p className="text-xs text-[var(--color-danger-500,#c53030)]" role="alert">
                Lowercase letters, digits, hyphens only.
              </p>
            ) : null}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="team-kind">Kind</Label>
            <Select
              value={form.watch("kind")}
              onValueChange={(value) => form.setValue("kind", value as TeamKind)}
            >
              <SelectTrigger id="team-kind">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="team">Team</SelectItem>
                <SelectItem value="department">Department</SelectItem>
                <SelectItem value="practice_area">Practice area</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="team-description">Description (optional)</Label>
            <Textarea
              id="team-description"
              rows={2}
              {...form.register("description")}
            />
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setOpen(false)}
              disabled={mutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={mutation.isPending}
              data-testid="new-team-submit"
            >
              {mutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Creating…
                </>
              ) : (
                "Create team"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
