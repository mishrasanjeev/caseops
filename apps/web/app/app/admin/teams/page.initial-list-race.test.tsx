import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Team, TeamListResult } from "@/lib/api/endpoints";

const mocks = vi.hoisted(() => ({
  listTeams: vi.fn(), createTeam: vi.fn(), deleteTeam: vi.fn(), setTeamScoping: vi.fn(),
  listCompanyUsers: vi.fn(), addTeamMember: vi.fn(), removeTeamMember: vi.fn(),
  updateTeamMemberLead: vi.fn(), capability: vi.fn(), success: vi.fn(), error: vi.fn(),
}));
vi.mock("@/lib/api/endpoints", () => mocks);
vi.mock("@/lib/capabilities", () => ({ useCapability: () => mocks.capability() }));
vi.mock("sonner", () => ({ toast: { success: mocks.success, error: mocks.error } }));

import TeamsAdminPage from "@/app/app/admin/teams/page";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((accept, refuse) => { resolve = accept; reject = refuse; });
  return { promise, resolve, reject };
}

const created: Team = {
  id: "a1111111-1111-4111-8111-111111111111", company_id: "b2222222-2222-4222-8222-222222222222",
  name: "New litigation team", slug: "new-litigation-team", kind: "team", description: null,
  is_active: true, members: [], member_count: 0,
  created_at: "2026-11-19T00:00:00Z", updated_at: "2026-11-19T00:00:00Z",
};
const stale: TeamListResult = { team_scoping_enabled: true, teams: [] };
const fresh: TeamListResult = { team_scoping_enabled: true, teams: [created] };

const activeCleanups = new Set<() => Promise<void>>();
afterEach(async () => {
  const errors: unknown[] = [];
  for (const cleanup of [...activeCleanups]) {
    try { await cleanup(); } catch (error) { errors.push(error); }
  }
  if (errors.length === 1) throw errors[0];
  if (errors.length > 1) throw new AggregateError(errors, "Independent fixture cleanup failures");
});

function ownedCleanup(view: ReturnType<typeof render>, client: QueryClient, release: () => void) {
  let completion: Promise<void> | undefined;
  const cleanup = (): Promise<void> => completion ??= (async () => {
    try {
      await act(async () => {
        release();
        await client.cancelQueries({ queryKey: ["teams", "list"] });
      });
      await waitFor(() => expect(client.isMutating()).toBe(0));
    } finally {
      view.unmount();
      client.clear();
      activeCleanups.delete(cleanup);
    }
  })();
  activeCleanups.add(cleanup);
  return cleanup;
}

function mountPage() {
  const client = new QueryClient({ defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false },
  } });
  const view = render(<QueryClientProvider client={client}><TeamsAdminPage /></QueryClientProvider>);
  const page = within(view.container);
  const user = userEvent.setup();
  const dialog = () => {
    expect(view.container.isConnected).toBe(true);
    const element = within(document.body).getByRole("dialog", { name: /^Create a team$/ });
    expect(element.isConnected).toBe(true);
    return within(element);
  };
  const create = async () => {
    expect(view.container.isConnected).toBe(true);
    await user.click(page.getAllByRole("button", { name: /^New team$/ })[0]);
    const name = dialog().getByRole("textbox", { name: /^Name$/ });
    await user.click(name);
    expect(name).toHaveFocus();
    await user.paste(created.name);
    const slug = dialog().getByRole("textbox", { name: /^Slug$/ });
    await user.click(slug);
    expect(slug).toHaveFocus();
    await user.paste(created.slug);
    await user.click(dialog().getByRole("button", { name: /^Create team$/ }));
    await waitFor(() => expect(mocks.createTeam).toHaveBeenCalledTimes(1));
    expect(mocks.createTeam).toHaveBeenCalledWith({
      name: created.name, slug: created.slug, description: null, kind: "team",
    });
  };
  return { client, view, page, user, dialog, create };
}

async function withPage(release: () => void, body: (page: ReturnType<typeof mountPage>) => Promise<void>) {
  const page = mountPage();
  const cleanup = ownedCleanup(page.view, page.client, release);
  const errors: unknown[] = [];
  try { await body(page); } catch (error) { errors.push(error); }
  try { await cleanup(); } catch (error) { errors.push(error); }
  if (errors.length === 1) throw errors[0];
  if (errors.length > 1) throw new AggregateError(errors, "Workflow and cleanup errors are retained separately");
}

describe("Teams creation during the initial list read", () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => { mock.mockReset(); });
    mocks.capability.mockReturnValue(true);
    mocks.createTeam.mockResolvedValue(created);
  });

  it("shows the committed team without reload when the initial read returns its older snapshot", async () => {
    const initial = deferred<TeamListResult>();
    mocks.listTeams.mockReturnValueOnce(initial.promise).mockResolvedValue(fresh);
    const client = new QueryClient({ defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false },
    } });
    const view = render(<QueryClientProvider client={client}><TeamsAdminPage /></QueryClientProvider>);
    const cleanup = ownedCleanup(view, client, () => { initial.resolve(stale); });
    const page = within(view.container);
    const user = userEvent.setup();
    const dialog = () => {
      expect(view.container.isConnected).toBe(true);
      const element = within(document.body).getByRole("dialog", { name: /^Create a team$/ });
      expect(element.isConnected).toBe(true);
      return within(element);
    };
    const errors: unknown[] = [];
    try {
      await waitFor(() => expect(mocks.listTeams).toHaveBeenCalledTimes(1));
      expect(client.getQueryState(["teams", "list"])?.status).toBe("pending");
      await user.click(page.getByRole("button", { name: /^New team$/ }));
      const name = dialog().getByRole("textbox", { name: /^Name$/ });
      await user.click(name);
      expect(name).toHaveFocus();
      await user.paste(created.name);
      const slug = dialog().getByRole("textbox", { name: /^Slug$/ });
      await user.click(slug);
      expect(slug).toHaveFocus();
      await user.paste(created.slug);
      await user.click(dialog().getByRole("button", { name: /^Create team$/ }));
      await waitFor(() => expect(mocks.createTeam).toHaveBeenCalledTimes(1));
      expect(mocks.createTeam).toHaveBeenCalledWith({
        name: created.name, slug: created.slug, description: null, kind: "team",
      });
      await act(async () => {
        initial.resolve(stale);
        await initial.promise;
      });
      await waitFor(() => expect(mocks.success).toHaveBeenCalledWith("Team created."));
      expect(within(document.body).queryByRole("dialog", { name: /^Create a team$/ })).not.toBeInTheDocument();
      expect(await page.findByRole("button", { name: /^Manage members of New litigation team$/ })).toBeVisible();
      expect(page.getByRole("button", { name: /^Scoping: ON$/ })).toBeVisible();
      expect(mocks.createTeam).toHaveBeenCalledTimes(1);
      expect(mocks.listTeams).toHaveBeenCalledTimes(2);
      expect(client.getQueryData(["teams", "list"])).toEqual(fresh);
      expect(mocks.error).not.toHaveBeenCalled();
    } catch (error) { errors.push(error); }
    try { await cleanup(); } catch (error) { errors.push(error); }
    if (errors.length === 1) throw errors[0];
    if (errors.length > 1) throw new AggregateError(errors, "Workflow and cleanup errors are retained separately");
  });

  it("waits for the fresh read when the cancelled initial snapshot arrives first", async () => {
    const initial = deferred<TeamListResult>();
    const recovery = deferred<TeamListResult>();
    mocks.listTeams.mockReturnValueOnce(initial.promise).mockReturnValueOnce(recovery.promise);
    await withPage(() => { initial.resolve(stale); recovery.resolve(fresh); }, async ({ client, create, dialog, page }) => {
      await waitFor(() => expect(mocks.listTeams).toHaveBeenCalledTimes(1));
      expect(client.getQueryState(["teams", "list"])?.status).toBe("pending");
      await create();
      await waitFor(() => expect(mocks.listTeams).toHaveBeenCalledTimes(2));
      await act(async () => { initial.resolve(stale); await initial.promise; });
      expect(client.getQueryState(["teams", "list"])?.status).toBe("pending");
      expect(client.getQueryData(["teams", "list"])).toBeUndefined();
      expect(dialog().getByRole("button", { name: /^Creating…$/ })).toBeDisabled();
      expect(mocks.success).not.toHaveBeenCalled();
      await act(async () => { recovery.resolve(fresh); await recovery.promise; });
      expect(await page.findByRole("button", { name: /^Manage members of New litigation team$/ })).toBeVisible();
      expect(page.getByRole("button", { name: /^Scoping: ON$/ })).toBeVisible();
      await waitFor(() => expect(mocks.success).toHaveBeenCalledExactlyOnceWith("Team created."));
      expect(mocks.createTeam).toHaveBeenCalledTimes(1);
      expect(mocks.listTeams).toHaveBeenCalledTimes(2);
    });
  });

  it("ignores a cancelled initial read failure after the committed team is visible", async () => {
    const initial = deferred<TeamListResult>();
    const refusal = new Error("Old initial read failed");
    mocks.listTeams.mockReturnValueOnce(initial.promise).mockResolvedValue(fresh);
    await withPage(() => { initial.resolve(stale); }, async ({ client, create, page }) => {
      await waitFor(() => expect(mocks.listTeams).toHaveBeenCalledTimes(1));
      await create();
      expect(await page.findByRole("button", { name: /^Manage members of New litigation team$/ })).toBeVisible();
      await act(async () => {
        initial.reject(refusal);
        await expect(initial.promise).rejects.toBe(refusal);
      });
      expect(client.getQueryState(["teams", "list"])?.status).toBe("success");
      expect(client.getQueryData(["teams", "list"])).toEqual(fresh);
      expect(page.getByRole("button", { name: /^Manage members of New litigation team$/ })).toBeVisible();
      expect(page.queryByText("Could not load teams")).not.toBeInTheDocument();
      expect(mocks.error).not.toHaveBeenCalled();
      expect(mocks.createTeam).toHaveBeenCalledTimes(1);
      expect(mocks.listTeams).toHaveBeenCalledTimes(2);
    });
  });

  it("retains the form and original list read after a rejected creation without replay", async () => {
    const initial = deferred<TeamListResult>();
    const refusal = new Error("Team creation was refused");
    mocks.listTeams.mockReturnValueOnce(initial.promise);
    mocks.createTeam.mockRejectedValue(refusal);
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      await withPage(() => { initial.resolve(stale); }, async ({ client, create, dialog }) => {
        await waitFor(() => expect(mocks.listTeams).toHaveBeenCalledTimes(1));
        await create();
        await waitFor(() => expect(mocks.error).toHaveBeenCalledExactlyOnceWith("Team creation was refused"));
        expect(logged).toHaveBeenCalledExactlyOnceWith("[apiErrorMessage]", refusal);
        await act(async () => { initial.resolve(stale); await initial.promise; });
        await waitFor(() => expect(client.getQueryState(["teams", "list"])?.status).toBe("success"));
        expect(dialog().getByRole("textbox", { name: /^Name$/ })).toHaveValue(created.name);
        expect(dialog().getByRole("textbox", { name: /^Slug$/ })).toHaveValue(created.slug);
        expect(dialog().getByRole("button", { name: /^Create team$/ })).toBeEnabled();
        expect(client.getQueryData(["teams", "list"])).toEqual(stale);
        expect(mocks.success).not.toHaveBeenCalled();
        expect(mocks.createTeam).toHaveBeenCalledTimes(1);
        expect(mocks.listTeams).toHaveBeenCalledTimes(1);
      });
    } finally { logged.mockRestore(); }
  });

  it("recovers a failed post-create read with a read-only retry instead of creating twice", async () => {
    const initial = deferred<TeamListResult>();
    mocks.listTeams.mockReturnValueOnce(initial.promise)
      .mockRejectedValueOnce(new Error("Current team list is temporarily unavailable"))
      .mockResolvedValue(fresh);
    await withPage(() => { initial.resolve(stale); }, async ({ client, create, page, user }) => {
      await waitFor(() => expect(mocks.listTeams).toHaveBeenCalledTimes(1));
      await create();
      expect(await page.findByText("Could not load teams")).toBeVisible();
      expect(page.getByText("Current team list is temporarily unavailable")).toBeVisible();
      expect(page.queryByRole("button", { name: /^Manage members of New litigation team$/ })).not.toBeInTheDocument();
      await waitFor(() => expect(mocks.success).toHaveBeenCalledExactlyOnceWith("Team created."));
      await act(async () => { initial.resolve(stale); await initial.promise; });
      expect(client.getQueryState(["teams", "list"])?.status).toBe("error");
      await user.click(page.getByRole("button", { name: /^Try again$/ }));
      expect(await page.findByRole("button", { name: /^Manage members of New litigation team$/ })).toBeVisible();
      expect(client.getQueryData(["teams", "list"])).toEqual(fresh);
      expect(mocks.createTeam).toHaveBeenCalledTimes(1);
      expect(mocks.listTeams).toHaveBeenCalledTimes(3);
      expect(mocks.success).toHaveBeenCalledExactlyOnceWith("Team created.");
    });
  });

  it("preserves list metadata and the created row across an older background read", async () => {
    const background = deferred<TeamListResult>();
    mocks.listTeams.mockResolvedValueOnce(stale).mockReturnValueOnce(background.promise).mockResolvedValue(fresh);
    await withPage(() => { background.resolve(stale); }, async ({ client, create, page }) => {
      expect(await page.findByText("No teams yet")).toBeVisible();
      let refetch!: Promise<void>;
      await act(async () => { refetch = client.refetchQueries({ queryKey: ["teams", "list"] }); });
      expect(client.getQueryState(["teams", "list"])?.fetchStatus).toBe("fetching");
      expect(client.getQueryData(["teams", "list"])).toEqual(stale);
      await create();
      expect(await page.findByRole("button", { name: /^Manage members of New litigation team$/ })).toBeVisible();
      await act(async () => { background.resolve(stale); await background.promise; await refetch; });
      expect(client.getQueryData(["teams", "list"])).toEqual(fresh);
      expect(page.getByRole("button", { name: /^Scoping: ON$/ })).toBeVisible();
      expect(page.getByRole("button", { name: /^Manage members of New litigation team$/ })).toBeVisible();
      expect(mocks.createTeam).toHaveBeenCalledTimes(1);
      expect(mocks.listTeams).toHaveBeenCalledTimes(3);
      expect(mocks.error).not.toHaveBeenCalled();
    });
  });
});
