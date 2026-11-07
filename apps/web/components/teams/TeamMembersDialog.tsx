"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Trash2, UserPlus, Users } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/Dialog";
import { Label } from "@/components/ui/Label";
import { PersonPicker } from "@/components/ui/PersonPicker";
import { apiErrorMessage, isApiErrorShape } from "@/lib/api/config";
import {
  addTeamMember,
  listCompanyUsers,
  removeTeamMember,
  updateTeamMemberLead,
  type Team,
  type TeamListResult,
} from "@/lib/api/endpoints";

type MembershipChange =
  | { action: "add"; membershipId: string; isLead: boolean }
  | { action: "lead"; teamMembershipId: string; isLead: boolean }
  | { action: "remove"; membershipId: string; teamMembershipId: string };

export function TeamMembersDialog({ team }: { team: Team }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [membershipId, setMembershipId] = useState("");
  const [isLead, setIsLead] = useState(false);
  const [removeId, setRemoveId] = useState<string | null>(null);
  const [leadIntent, setLeadIntent] = useState<{ teamMembershipId: string; isLead: boolean } | null>(null);
  const fieldId = `team-member-${team.id}`;
  const directory = useQuery({
    queryKey: ["company-users"],
    queryFn: () => listCompanyUsers(),
    enabled: open,
  });
  const selectedIsValid = !directory.isError && directory.data?.users.some((user) =>
    user.membership_id === membershipId && user.membership_active && user.user_active &&
    !team.members.some((member) => member.membership_id === user.membership_id),
  );
  const change = useMutation({
    retry: false,
    mutationFn: (input: MembershipChange) => {
      switch (input.action) {
        case "remove":
          return removeTeamMember({
            teamId: team.id,
            membershipId: input.membershipId,
            expectedTeamMembershipId: input.teamMembershipId,
          });
        case "lead":
          return updateTeamMemberLead({
            teamId: team.id,
            teamMembershipId: input.teamMembershipId,
            isLead: input.isLead,
          });
        case "add":
          return addTeamMember({ teamId: team.id, membershipId: input.membershipId, isLead: input.isLead });
      }
    },
    onSuccess: async (updated, input) => {
      queryClient.setQueryData<TeamListResult>(["teams", "list"], (current) =>
        current
          ? { ...current, teams: current.teams.map((row) => row.id === updated.id ? updated : row) }
          : current,
      );
      if (input.action === "add") {
        setMembershipId("");
        setIsLead(false);
      }
      setRemoveId(null);
      await queryClient.invalidateQueries({ queryKey: ["teams", "list"] });
    },
    onError: async (error, input) => {
      setLeadIntent(null);
      if (
        input.action !== "add" && isApiErrorShape(error) &&
        (error.status === 409 || error.status === 404)
      ) {
        setRemoveId(null);
        await queryClient.invalidateQueries({ queryKey: ["teams", "list"] });
      }
    },
    onSettled: () => setLeadIntent(null),
  });
  const busy = change.isPending || leadIntent !== null;
  const writesDisabled = busy || !team.is_active;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (busy) return;
        setOpen(next);
        if (!next) {
          setMembershipId("");
          setIsLead(false);
          setRemoveId(null);
          change.reset();
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" disabled={!team.is_active} aria-label={`Manage members of ${team.name}`}>
          <Users className="h-4 w-4" aria-hidden />
          Members
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Members of {team.name}</DialogTitle>
          <DialogDescription>Membership changes can affect access to team matters.</DialogDescription>
        </DialogHeader>
        <div className="flex min-w-0 flex-col gap-5" aria-busy={busy}>
          {change.isError ? (
            <p role="alert" className="break-words text-sm text-red-700">
              {apiErrorMessage(change.error, "The membership change could not be saved.")}
            </p>
          ) : null}
          <form
            className="flex min-w-0 flex-col gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (!selectedIsValid || writesDisabled) return;
              change.mutate({ action: "add", membershipId, isLead });
            }}
          >
            <div className="flex min-w-0 flex-col gap-2">
              <Label htmlFor={fieldId}>Colleague</Label>
              <PersonPicker
                id={fieldId}
                value={membershipId}
                onChange={setMembershipId}
                excludeMembershipIds={team.members.map((member) => member.membership_id)}
                emptyText="All active colleagues are already members."
                disabled={writesDisabled}
              />
            </div>
            <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
              <label className="inline-flex items-center gap-2 text-sm">
                <input type="checkbox" checked={isLead} disabled={writesDisabled} onChange={(event) => setIsLead(event.target.checked)} />
                Team lead
              </label>
              <Button type="submit" className="w-full sm:w-auto" disabled={!selectedIsValid || writesDisabled}>
                {busy && change.variables?.action === "add" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <UserPlus className="h-4 w-4" aria-hidden />}
                Add member
              </Button>
            </div>
          </form>
          {team.members.length === 0 ? <p className="text-sm text-[var(--color-mute)]">No members yet.</p> : (
            <ul className="flex min-w-0 flex-col divide-y divide-[var(--color-line)]" aria-label="Team members">
              {team.members.map((member) => (
                <li key={member.id} className="flex min-w-0 flex-col gap-3 py-3" data-testid={`team-member-${member.membership_id}`}>
                  <div className="min-w-0">
                    <p className="break-words text-sm font-medium">{member.member_name}</p>
                    <p className="break-all text-xs text-[var(--color-mute)]">{member.member_email}</p>
                  </div>
                  <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
                    <label className="inline-flex min-w-0 items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={leadIntent?.teamMembershipId === member.id ? leadIntent.isLead : member.is_lead}
                        disabled={writesDisabled}
                        aria-label={`Team lead for ${member.member_name}`}
                        onChange={(event) => {
                          if (writesDisabled) return;
                          const isLead = event.target.checked;
                          setLeadIntent({ teamMembershipId: member.id, isLead });
                          change.mutate({ action: "lead", teamMembershipId: member.id, isLead });
                        }}
                      />
                      Team lead
                    </label>
                    <Button type="button" variant="ghost" size="sm" disabled={writesDisabled} onClick={() => setRemoveId(member.id)} aria-label={`Remove ${member.member_name} from team`}>
                      <Trash2 className="h-4 w-4" aria-hidden />
                      Remove
                    </Button>
                  </div>
                  {removeId === member.id ? (
                    <div role="group" aria-label={`Confirm removal of ${member.member_name}`} className="flex min-w-0 flex-col gap-2">
                      <p className="text-sm">Remove {member.member_name} from {team.name}?</p>
                      <div className="flex flex-wrap gap-2">
                        <Button type="button" size="sm" disabled={writesDisabled} onClick={() => change.mutate({ action: "remove", membershipId: member.membership_id, teamMembershipId: member.id })}>Remove member</Button>
                        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => setRemoveId(null)}>Cancel</Button>
                      </div>
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
