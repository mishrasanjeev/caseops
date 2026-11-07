import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/config";
import type { Team, TeamListResult } from "@/lib/api/endpoints";

const mocks = vi.hoisted(() => ({
  listTeams: vi.fn(), listCompanyUsers: vi.fn(), addTeamMember: vi.fn(),
  updateTeamMemberLead: vi.fn(), removeTeamMember: vi.fn(), capability: vi.fn(),
}));
vi.mock("@/lib/api/endpoints", () => ({
  ...mocks, createTeam: vi.fn(), deleteTeam: vi.fn(), setTeamScoping: vi.fn(),
}));
vi.mock("@/lib/capabilities", () => ({ useCapability: () => mocks.capability() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import TeamsAdminPage from "@/app/app/admin/teams/page";

const alice = {
  id: "tm-alice", team_id: "team-1", membership_id: "alice", member_name: "Alice Counsel",
  member_email: "alice@example.com", is_lead: false, created_at: "2026-11-07T00:00:00Z",
};
const bob = { ...alice, id: "tm-bob", membership_id: "bob", member_name: "Bob Counsel", member_email: "bob@example.com" };
const team: Team = {
  id: "team-1", company_id: "company-1", name: "Litigation", slug: "litigation", kind: "team",
  description: null, is_active: true, members: [alice], member_count: 1,
  created_at: "2026-11-07T00:00:00Z", updated_at: "2026-11-07T00:00:00Z",
};
const directory = {
  company_id: "company-1", company_slug: "firm",
  users: [alice, bob].map((member) => ({
    membership_id: member.membership_id, role: "member", membership_active: true,
    user_id: `user-${member.membership_id}`, email: member.member_email, full_name: member.member_name,
    user_active: true, created_at: member.created_at,
  })).concat([{ membership_id: "inactive", role: "member", membership_active: false,
    user_id: "user-inactive", email: "inactive@example.com", full_name: "Inactive Colleague",
    user_active: true, created_at: alice.created_at }]),
};

function setup() {
  const client = new QueryClient({ defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false },
  } });
  render(<QueryClientProvider client={client}><TeamsAdminPage /></QueryClientProvider>);
  return { user: userEvent.setup(), client };
}
async function open(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "Manage members of Litigation" }));
  return screen.findByRole("dialog", { name: "Members of Litigation" });
}

describe("Team membership administration", () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset());
    mocks.capability.mockReturnValue(true);
    mocks.listTeams.mockResolvedValue({ teams: [structuredClone(team)], team_scoping_enabled: false });
    mocks.listCompanyUsers.mockResolvedValue(structuredClone(directory));
  });

  it("loads the tenant directory only on open and excludes existing/inactive colleagues", async () => {
    const { user } = setup();
    await screen.findByRole("button", { name: "Manage members of Litigation" });
    expect(mocks.listCompanyUsers).not.toHaveBeenCalled();
    const dialog = await open(user);
    expect(await within(dialog).findByRole("option", { name: /Bob Counsel/ })).toBeInTheDocument();
    expect(within(dialog).queryByRole("option", { name: /Alice Counsel|Inactive Colleague/ })).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Add member" })).toBeDisabled();
    expect(mocks.listCompanyUsers).toHaveBeenCalledTimes(1);
  });

  it("adds an active colleague with the selected lead flag and refreshes the visible membership", async () => {
    const { user } = setup();
    const dialog = await open(user);
    await within(dialog).findByRole("option", { name: /Bob Counsel/ });
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Colleague" }), "bob");
    await user.click(within(dialog).getByRole("checkbox", { name: /^Team lead$/ }));
    const updated = { ...team, members: [alice, { ...bob, is_lead: true }], member_count: 2 };
    mocks.addTeamMember.mockResolvedValue(updated);
    mocks.listTeams.mockResolvedValue({ teams: [updated], team_scoping_enabled: false });
    await user.click(within(dialog).getByRole("button", { name: "Add member" }));
    await waitFor(() => expect(mocks.addTeamMember).toHaveBeenCalledExactlyOnceWith({ teamId: "team-1", membershipId: "bob", isLead: true }));
    expect(await within(dialog).findByRole("checkbox", { name: "Team lead for Bob Counsel" })).toBeChecked();
    expect(within(dialog).getByRole("combobox", { name: "Colleague" })).toHaveValue("");
  });

  it("updates the exact team membership row without calling add", async () => {
    const { user } = setup();
    const dialog = await open(user);
    const updated = { ...team, members: [{ ...alice, is_lead: true }] };
    mocks.updateTeamMemberLead.mockResolvedValue(updated);
    mocks.listTeams.mockResolvedValue({ teams: [updated], team_scoping_enabled: false });
    await user.click(within(dialog).getByRole("checkbox", { name: "Team lead for Alice Counsel" }));
    await waitFor(() => expect(mocks.updateTeamMemberLead).toHaveBeenCalledExactlyOnceWith({ teamId: "team-1", teamMembershipId: alice.id, isLead: true }));
    expect(mocks.addTeamMember).not.toHaveBeenCalled();
    await waitFor(() => expect(within(dialog).getByRole("checkbox", { name: "Team lead for Alice Counsel" })).toBeChecked());
  });

  it("requires explicit removal confirmation and preserves a cancelled member", async () => {
    const { user } = setup();
    const dialog = await open(user);
    await user.click(within(dialog).getByRole("button", { name: "Remove Alice Counsel from team" }));
    expect(mocks.removeTeamMember).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: /^Cancel$/ }));
    expect(within(dialog).getByRole("checkbox", { name: "Team lead for Alice Counsel" })).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Remove Alice Counsel from team" }));
    const updated = { ...team, members: [], member_count: 0 };
    mocks.removeTeamMember.mockResolvedValue(updated);
    mocks.listTeams.mockResolvedValue({ teams: [updated], team_scoping_enabled: false });
    await user.click(within(dialog).getByRole("button", { name: /^Remove member$/ }));
    await waitFor(() => expect(mocks.removeTeamMember).toHaveBeenCalledExactlyOnceWith({
      teamId: "team-1", membershipId: "alice", expectedTeamMembershipId: alice.id,
    }));
    await waitFor(() => expect(within(dialog).queryByRole("checkbox", { name: "Team lead for Alice Counsel" })).not.toBeInTheDocument());
  });

  it("preserves selected input on a rejected add and never retries a mutation", async () => {
    const { user } = setup();
    const dialog = await open(user);
    await within(dialog).findByRole("option", { name: /Bob Counsel/ });
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Colleague" }), "bob");
    mocks.addTeamMember.mockRejectedValue(new Error("refused"));
    await user.click(within(dialog).getByRole("button", { name: "Add member" }));
    expect(await within(dialog).findByRole("alert")).toBeVisible();
    expect(within(dialog).getByRole("combobox", { name: "Colleague" })).toHaveValue("bob");
    expect(mocks.addTeamMember).toHaveBeenCalledTimes(1);
  });

  it("disables adding a retained selection after the current directory becomes unavailable", async () => {
    const { user, client } = setup();
    const dialog = await open(user);
    await within(dialog).findByRole("option", { name: /Bob Counsel/ });
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Colleague" }), "bob");
    mocks.listCompanyUsers.mockRejectedValue(new Error("directory denied"));
    await act(async () => { await client.invalidateQueries({ queryKey: ["company-users"] }); });
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Add member" })).toBeDisabled());
    expect(mocks.addTeamMember).not.toHaveBeenCalled();
  });

  it("does not expose management controls or load the directory without capability", async () => {
    mocks.capability.mockReturnValue(false);
    setup();
    expect(await screen.findByText("You don't have access to manage teams")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Manage members/ })).not.toBeInTheDocument();
    expect(mocks.listCompanyUsers).not.toHaveBeenCalled();
  });

  it("blocks sibling membership commands while a lead change is pending", async () => {
    let finish!: (value: Team) => void;
    mocks.updateTeamMemberLead.mockReturnValue(new Promise<Team>((resolve) => { finish = resolve; }));
    const { user, client } = setup();
    const dialog = await open(user);
    await user.click(within(dialog).getByRole("checkbox", { name: "Team lead for Alice Counsel" }));
    expect(within(dialog).getByRole("checkbox", { name: "Team lead for Alice Counsel" })).toBeChecked();
    expect(within(dialog).getByRole("button", { name: "Remove Alice Counsel from team" })).toBeDisabled();
    expect(within(dialog).getByRole("checkbox", { name: /^Team lead$/ })).toBeDisabled();
    const updated = { ...team, members: [{ ...alice, is_lead: true }] };
    mocks.listTeams.mockResolvedValue({ teams: [updated], team_scoping_enabled: false });
    await act(async () => { finish(updated); });
    await waitFor(() => expect(client.getQueryData<TeamListResult>(["teams", "list"])?.teams[0].members[0].is_lead).toBe(true));
  });

  it("restores the persisted lead state when the single pending change is rejected", async () => {
    let reject!: (error: Error) => void;
    mocks.updateTeamMemberLead.mockReturnValue(new Promise<Team>((_resolve, refuse) => { reject = refuse; }));
    const { user } = setup();
    const dialog = await open(user);
    const checkbox = within(dialog).getByRole("checkbox", { name: "Team lead for Alice Counsel" });
    await user.click(checkbox);
    expect(checkbox).toBeChecked();
    expect(checkbox).toBeDisabled();
    await act(async () => { reject(new Error("refused")); });
    expect(await within(dialog).findByRole("alert")).toBeVisible();
    await waitFor(() => expect(checkbox).not.toBeChecked());
    expect(checkbox).toBeEnabled();
    expect(mocks.updateTeamMemberLead).toHaveBeenCalledExactlyOnceWith({ teamId: "team-1", teamMembershipId: alice.id, isLead: true });
    expect(mocks.addTeamMember).not.toHaveBeenCalled();
  });

  it.each(["removed", "replaced"] as const)("refreshes a %s row on conflict without replay", async (kind) => {
    const { user } = setup();
    const dialog = await open(user);
    const checkbox = within(dialog).getByRole("checkbox", { name: "Team lead for Alice Counsel" });
    const replacement = { ...alice, id: "tm-alice-new" };
    const members = kind === "removed" ? [] : [replacement];
    const current = { ...team, members, member_count: members.length };
    let finish!: (value: TeamListResult) => void;
    mocks.listTeams.mockReturnValueOnce(new Promise<TeamListResult>((resolve) => { finish = resolve; }));
    const detail = "This team membership changed. Review the current team before editing.";
    mocks.updateTeamMemberLead.mockRejectedValueOnce(new ApiError(409, detail, { code: "team_membership_changed" }));
    await user.click(checkbox);
    await waitFor(() => expect(mocks.listTeams).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(checkbox).not.toBeChecked());
    expect(checkbox).toBeDisabled();
    await act(async () => { finish({ teams: [current], team_scoping_enabled: false }); });
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(detail);
    expect(checkbox).not.toBeInTheDocument();
    expect(mocks.updateTeamMemberLead).toHaveBeenCalledExactlyOnceWith({
      teamId: "team-1", teamMembershipId: alice.id, isLead: true,
    });
    expect(mocks.addTeamMember).not.toHaveBeenCalled();
    if (kind === "removed") {
      expect(within(dialog).getByText("No members yet.")).toBeVisible();
    } else {
      const next = within(dialog).getByRole("checkbox", { name: "Team lead for Alice Counsel" });
      expect(next).not.toBeChecked();
      expect(next).toBeEnabled();
      const updated = { ...current, members: [{ ...replacement, is_lead: true }] };
      mocks.updateTeamMemberLead.mockResolvedValueOnce(updated);
      mocks.listTeams.mockResolvedValueOnce({ teams: [updated], team_scoping_enabled: false });
      await user.click(next);
      await waitFor(() => expect(mocks.updateTeamMemberLead).toHaveBeenLastCalledWith({
        teamId: "team-1", teamMembershipId: replacement.id, isLead: true,
      }));
    }
  });

  it("discards a stale removal confirmation when the replacement is loaded", async () => {
    const { user } = setup();
    const dialog = await open(user);
    const remove = within(dialog).getByRole("button", { name: "Remove Alice Counsel from team" });
    await user.click(remove);
    const replacement = { ...team, members: [{ ...alice, id: "tm-alice-new", is_lead: true }] };
    mocks.removeTeamMember.mockRejectedValueOnce(new ApiError(409, "This team membership changed.", {}));
    mocks.listTeams.mockResolvedValueOnce({ teams: [replacement], team_scoping_enabled: false });
    await user.click(within(dialog).getByRole("button", { name: /^Remove member$/ }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("This team membership changed.");
    expect(within(dialog).getByRole("checkbox", { name: "Team lead for Alice Counsel" })).toBeChecked();
    expect(within(dialog).queryByRole("button", { name: /^Remove member$/ })).not.toBeInTheDocument();
    expect(mocks.removeTeamMember).toHaveBeenCalledExactlyOnceWith({
      teamId: "team-1", membershipId: "alice", expectedTeamMembershipId: alice.id,
    });
  });
});
