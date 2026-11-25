import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { capabilityMock } = vi.hoisted(() => ({ capabilityMock: vi.fn() }));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (cap: string) => capabilityMock(cap),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { MatterEthicalWallsCard } from "@/components/app/MatterEthicalWallsCard";

// Tests drive the real endpoint client (zod-parsed) and the real MatterPicker;
// only the network is faked, at fetch.

type Wall = Record<string, unknown> & { id: string; matter_id: string; excluded_membership_id: string };

const USERS = [
  { membership_id: "m-owner", role: "owner", full_name: "Asha Owner", email: "asha@firm.in" },
  { membership_id: "m-admin", role: "admin", full_name: "Bela Admin", email: "bela@firm.in" },
  { membership_id: "m-rao", role: "partner", full_name: "Chetan Rao", email: "chetan@firm.in" },
  { membership_id: "m-iyer", role: "member", full_name: "Divya Iyer", email: "divya@firm.in" },
  { membership_id: "m-gone", role: "member", full_name: "Esha Gone", email: "esha@firm.in", membership_active: false },
].map((user) => ({
  membership_active: true,
  user_active: true,
  user_id: `u-${user.membership_id}`,
  created_at: "2026-11-01T00:00:00Z",
  ...user,
}));

const MATTER = {
  id: "matter-1",
  matter_code: "LIT-101",
  title: "Kapoor v. Meridian",
  client_name: "Kapoor Textiles",
  opposing_party: "Meridian",
  status: "active",
  lifecycle_version: 1,
  practice_area: "Commercial",
  forum_level: "high_court",
  court_name: "Delhi High Court",
  judge_name: null,
  description: null,
  next_hearing_on: null,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};

function wall(overrides: Partial<Wall> & Pick<Wall, "id" | "excluded_membership_id">): Wall {
  const person = USERS.find((user) => user.membership_id === overrides.excluded_membership_id)!;
  return {
    matter_id: "matter-1",
    matter_code: "LIT-101",
    matter_title: "Kapoor v. Meridian",
    excluded_full_name: person.full_name,
    excluded_email: person.email,
    excluded_role: person.role,
    excluded_membership_active: person.membership_active,
    enforced: person.role !== "owner",
    reason: null,
    created_by_membership_id: "m-owner",
    created_by_full_name: "Asha Owner",
    created_at: "2026-11-20T09:30:00Z",
    ...overrides,
  };
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
}

function problem(status: number, detail: string): Response {
  return new Response(JSON.stringify({ type: `https://httpstatuses.com/${status}`, title: "Error", status, detail }), {
    status,
    headers: { "content-type": "application/problem+json" },
  });
}

let walls: Wall[];
let listResponse: (() => Response) | null;
let createResponse: ((body: { excluded_membership_id: string; reason: string | null }) => Response) | null;
let removeResponse: (() => Response) | null;
const fetchMock = vi.fn();
let originalFetch: typeof globalThis.fetch;

function calls(method: string, fragment: string) {
  return fetchMock.mock.calls.filter(
    ([input, init]) => (init?.method ?? "GET") === method && String(input).includes(fragment),
  );
}

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MatterEthicalWallsCard />
    </QueryClientProvider>,
  );
}

async function chooseMatter(user: ReturnType<typeof userEvent.setup>) {
  const select = screen.getByLabelText("Matter");
  await waitFor(() => expect(select).not.toBeDisabled());
  await waitFor(() => expect(within(select).getByRole("option", { name: /LIT-101/ })).toBeInTheDocument());
  await user.selectOptions(select, "matter-1");
}

function personBox(name: RegExp) {
  return within(screen.getByTestId("matter-wall-people")).getByRole("checkbox", { name });
}

beforeEach(() => {
  capabilityMock.mockReset();
  capabilityMock.mockImplementation(() => true);
  walls = [
    wall({ id: "w-1", excluded_membership_id: "m-iyer", reason: "Acted for Meridian in 2024." }),
    wall({
      id: "w-2",
      excluded_membership_id: "m-owner",
      matter_id: "matter-2",
      matter_code: "LIT-202",
      matter_title: "State v. Arora",
    }),
  ];
  listResponse = null;
  createResponse = null;
  removeResponse = null;
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url.includes("/api/matters/ethical-walls")) {
      return listResponse ? listResponse() : json({ walls, truncated: false });
    }
    if (url.includes("/api/companies/current/users")) {
      return json({ company_id: "c-1", company_slug: "firm", users: USERS });
    }
    const wallPath = url.match(/\/api\/matters\/([^/]+)\/access\/walls(?:\/([^/?]+))?/);
    if (wallPath && method === "POST") {
      const body = JSON.parse(String(init?.body));
      if (createResponse) return createResponse(body);
      const created = wall({ id: `w-${body.excluded_membership_id}`, excluded_membership_id: body.excluded_membership_id, reason: body.reason });
      walls = [created, ...walls];
      return json({
        id: created.id,
        matter_id: wallPath[1],
        excluded_membership_id: body.excluded_membership_id,
        reason: body.reason,
        created_by_membership_id: "m-owner",
        created_at: "2026-11-22T10:00:00Z",
      });
    }
    if (wallPath && method === "DELETE") {
      if (removeResponse) return removeResponse();
      walls = walls.filter((row) => row.id !== wallPath[2]);
      return new Response(null, { status: 204 });
    }
    if (url.includes("/api/matters/")) {
      return json({ matters: [MATTER], next_cursor: null });
    }
    return json({});
  });
  originalFetch = globalThis.fetch;
  globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe("MatterEthicalWallsCard", () => {
  it("lists active walls per Matter with the walled person, reason and who set the wall up", async () => {
    renderCard();

    const lit101 = await screen.findByTestId("matter-walls-LIT-101");
    expect(within(lit101).getByRole("link", { name: /LIT-101 · Kapoor v\. Meridian/ })).toHaveAttribute(
      "href",
      "/app/matters/matter-1",
    );
    const row = within(lit101).getByTestId("matter-wall-row-w-1");
    expect(row).toHaveTextContent("Divya Iyer");
    expect(row).toHaveTextContent("divya@firm.in");
    expect(row).toHaveTextContent("Member");
    expect(row).toHaveTextContent("Acted for Meridian in 2024.");
    expect(row).toHaveTextContent("Asha Owner");
    expect(within(lit101).getByText("1 person walled")).toBeInTheDocument();

    // A wall naming an owner is stored but never enforced; say so.
    const ownerRow = within(screen.getByTestId("matter-walls-LIT-202")).getByTestId("matter-wall-row-w-2");
    expect(ownerRow).toHaveTextContent("Not enforced: owners bypass walls");
    expect(ownerRow).toHaveTextContent("No reason recorded");
  });

  it("shows an explanatory empty state", async () => {
    walls = [];
    renderCard();
    expect(await screen.findByTestId("matter-walls-empty")).toHaveTextContent(
      "No active ethical walls on Matters you can open.",
    );
  });

  it("sets up walls for several people after an explicit confirmation", async () => {
    const user = userEvent.setup();
    renderCard();
    await screen.findByTestId("matter-wall-row-w-1");
    await chooseMatter(user);

    // Owners cannot be walled, already-walled and inactive people are not offered.
    expect(personBox(/Asha Owner/)).toBeDisabled();
    expect(within(screen.getByTestId("matter-wall-people")).getByText(/Owner: walls do not apply to owners/)).toBeInTheDocument();
    expect(personBox(/Divya Iyer/)).toBeDisabled();
    expect(within(screen.getByTestId("matter-wall-people")).queryByText(/Esha Gone/)).toBeNull();

    await user.click(personBox(/Bela Admin/));
    await user.click(personBox(/Chetan Rao/));
    await user.type(screen.getByLabelText("Reason (optional)"), "Conflict found at intake.");
    await user.click(screen.getByTestId("matter-wall-review"));

    const confirm = screen.getByTestId("matter-wall-confirm");
    expect(confirm).toHaveTextContent("Wall off Bela Admin, Chetan Rao from LIT-101 · Kapoor v. Meridian · Kapoor Textiles?");
    expect(calls("POST", "/access/walls")).toHaveLength(0);

    await user.click(within(confirm).getByRole("button", { name: "Confirm 2 walls" }));

    await waitFor(() => expect(calls("POST", "/api/matters/matter-1/access/walls")).toHaveLength(2));
    const bodies = calls("POST", "/access/walls").map(([, init]) => JSON.parse(String(init?.body)));
    expect(bodies).toEqual([
      { excluded_membership_id: "m-admin", reason: "Conflict found at intake." },
      { excluded_membership_id: "m-rao", reason: "Conflict found at intake." },
    ]);
    expect(await screen.findByTestId("matter-wall-result")).toHaveTextContent(
      "Wall set up: Bela Admin, Chetan Rao can no longer open LIT-101.",
    );
    const lit101 = screen.getByTestId("matter-walls-LIT-101");
    await waitFor(() => expect(within(lit101).getByText("3 people walled")).toBeInTheDocument());
    expect(screen.getByLabelText("Reason (optional)")).toHaveValue("");
    // The newly walled people are no longer offered for this Matter.
    expect(personBox(/Bela Admin/)).toBeDisabled();
  });

  it("anchors missing-field errors to their fields and sends nothing", async () => {
    const user = userEvent.setup();
    renderCard();
    await screen.findByTestId("matter-wall-row-w-1");
    await user.click(screen.getByTestId("matter-wall-review"));

    const matter = screen.getByLabelText("Matter");
    expect(matter).toHaveAttribute("aria-invalid", "true");
    expect(matter).toHaveAccessibleDescription(/Choose the Matter to wall\./);
    const people = screen.getByTestId("matter-wall-people");
    expect(people).toHaveAttribute("aria-invalid", "true");
    expect(people).toHaveAccessibleDescription("Choose at least one person to wall off.");
    expect(screen.queryByTestId("matter-wall-confirm")).toBeNull();
    expect(calls("POST", "/access/walls")).toHaveLength(0);
  });

  it("anchors a refused Matter to the Matter field when it disappears before confirmation", async () => {
    createResponse = () => problem(404, "Matter not found.");
    const user = userEvent.setup();
    renderCard();
    await screen.findByTestId("matter-wall-row-w-1");
    await chooseMatter(user);
    await user.click(personBox(/Chetan Rao/));
    await user.click(screen.getByTestId("matter-wall-review"));
    await user.click(screen.getByRole("button", { name: "Confirm wall" }));

    const matter = screen.getByLabelText("Matter");
    await waitFor(() => expect(matter).toHaveAttribute("aria-invalid", "true"));
    expect(matter).toHaveAccessibleDescription(/This Matter is no longer available to you/);
    expect(screen.getByTestId("matter-wall-result")).toHaveTextContent("");
  });

  it("anchors a server conflict to the people field and names who was not walled", async () => {
    createResponse = () =>
      problem(409, "Reassign live linked-IP responsibility before revoking Matter access.");
    const user = userEvent.setup();
    renderCard();
    await screen.findByTestId("matter-wall-row-w-1");
    await chooseMatter(user);
    await user.click(personBox(/Chetan Rao/));
    await user.click(screen.getByTestId("matter-wall-review"));
    await user.click(screen.getByRole("button", { name: "Confirm wall" }));

    const people = screen.getByTestId("matter-wall-people");
    await waitFor(() => expect(people).toHaveAttribute("aria-invalid", "true"));
    expect(people).toHaveAccessibleDescription(
      "Chetan Rao was not walled: Reassign live linked-IP responsibility before revoking Matter access.",
    );
    // The failed person stays selected so the admin can retry after the handoff.
    expect(personBox(/Chetan Rao/)).toBeChecked();
  });

  it("anchors an over-long reason to the reason field before sending", async () => {
    const user = userEvent.setup();
    renderCard();
    await screen.findByTestId("matter-wall-row-w-1");
    await chooseMatter(user);
    await user.click(personBox(/Chetan Rao/));
    const reason = screen.getByLabelText("Reason (optional)");
    await user.click(reason);
    await user.paste("x".repeat(2001));
    await user.click(screen.getByTestId("matter-wall-review"));

    expect(reason).toHaveAttribute("aria-invalid", "true");
    expect(reason).toHaveAccessibleDescription("Keep the reason to 2000 characters or fewer.");
    expect(calls("POST", "/access/walls")).toHaveLength(0);
  });

  it("lifts a wall only after confirmation", async () => {
    const user = userEvent.setup();
    renderCard();
    const row = await screen.findByTestId("matter-wall-row-w-1");

    await user.click(within(row).getByRole("button", { name: "Lift wall for Divya Iyer on LIT-101" }));
    expect(within(row).getByText("Divya Iyer regains normal access to LIT-101.")).toBeInTheDocument();
    await user.click(within(row).getByRole("button", { name: "Keep wall" }));
    expect(calls("DELETE", "/access/walls")).toHaveLength(0);

    await user.click(within(row).getByRole("button", { name: "Lift wall for Divya Iyer on LIT-101" }));
    await user.click(within(row).getByRole("button", { name: "Confirm lift" }));

    await waitFor(() => expect(calls("DELETE", "/api/matters/matter-1/access/walls/w-1")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByTestId("matter-wall-row-w-1")).toBeNull());
    expect(screen.queryByTestId("matter-walls-LIT-101")).toBeNull();
  });

  it("keeps the wall and shows the refusal in its row when lifting fails", async () => {
    removeResponse = () =>
      problem(409, "Reassign live linked-IP responsibility before revoking Matter access.");
    const user = userEvent.setup();
    renderCard();
    const row = await screen.findByTestId("matter-wall-row-w-1");
    await user.click(within(row).getByRole("button", { name: "Lift wall for Divya Iyer on LIT-101" }));
    await user.click(within(row).getByRole("button", { name: "Confirm lift" }));

    expect(await within(row).findByRole("alert")).toHaveTextContent(
      "Reassign live linked-IP responsibility before revoking Matter access.",
    );
    expect(screen.getByTestId("matter-wall-row-w-1")).toBeInTheDocument();
  });

  it("does not load or offer walls without matter_access:manage", async () => {
    capabilityMock.mockImplementation((cap: string) => cap !== "matter_access:manage");
    renderCard();

    expect(screen.getByTestId("matter-ethical-walls-denied")).toHaveTextContent(
      "Your role does not include matter_access:manage.",
    );
    expect(screen.queryByTestId("matter-wall-review")).toBeNull();
    expect(calls("GET", "/api/matters/ethical-walls")).toHaveLength(0);
  });

  it("explains a server permission denial without offering a retry", async () => {
    listResponse = () => problem(403, "Managing matter access requires admin or owner role.");
    renderCard();

    expect(await screen.findByText("Your role cannot view ethical walls. Ask a workspace owner or admin.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("shows a load failure with a retry", async () => {
    let failures = 1;
    listResponse = () => (failures-- > 0 ? problem(500, "The wall directory is unavailable.") : json({ walls, truncated: false }));
    const user = userEvent.setup();
    renderCard();

    expect(await screen.findByText("The wall directory is unavailable.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("matter-wall-row-w-1")).toBeInTheDocument();
  });
});

// Nov 24 workbook adjacent path: the directory stops at the 500 most recent
// walls, and the filter and the "already walled" check only saw those rows.
describe("truncated wall directory", () => {
  function truncatedDirectory() {
    const recent = Array.from({ length: 9 }, (_, index) =>
      wall({
        id: `w-recent-${index}`,
        excluded_membership_id: "m-rao",
        matter_id: `matter-r${index}`,
        matter_code: `LIT-R${index}`,
        matter_title: `Recent matter ${index}`,
      }),
    );
    const older = wall({
      id: "w-older",
      excluded_membership_id: "m-iyer",
      matter_id: "matter-1",
      matter_code: "LIT-101",
      matter_title: "Kapoor v. Meridian",
    });
    listResponse = null;
    const base = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/matters/ethical-walls?")) {
        const params = new URL(url, "http://local").searchParams;
        if (params.get("q") === "Divya" || params.get("matter_id") === "matter-1") {
          return json({ walls: [older], truncated: false });
        }
        return json({ walls: [], truncated: false });
      }
      if (url.includes("/api/matters/ethical-walls")) {
        return json({ walls: recent, truncated: true });
      }
      return base(input, init);
    });
  }

  it("searches every wall on the server when the local filter cannot see it", async () => {
    truncatedDirectory();
    const user = userEvent.setup();
    renderCard();
    await screen.findByTestId("matter-walls-LIT-R0");
    await user.type(screen.getByLabelText("Filter walls by Matter or person"), "Divya");
    expect(screen.getByText("No wall in the 500 most recent matches this filter.")).toBeInTheDocument();
    await user.click(screen.getByTestId("matter-walls-search-all"));
    await screen.findByTestId("matter-walls-LIT-101");
    expect(calls("GET", "/api/matters/ethical-walls?q=Divya")).toHaveLength(1);
  });

  it("marks a person already walled by an older wall as unavailable", async () => {
    truncatedDirectory();
    const user = userEvent.setup();
    renderCard();
    await screen.findByTestId("matter-walls-LIT-R0");
    await chooseMatter(user);
    await waitFor(() => expect(calls("GET", "/api/matters/ethical-walls?matter_id=matter-1")).toHaveLength(1));
    await waitFor(() => expect(personBox(/Divya Iyer/)).toBeDisabled());
    expect(screen.getByText(/divya@firm\.in · Member · Already walled from this Matter/)).toBeInTheDocument();
  });
});
