import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  capabilityMock,
  createIpDocketMatterLinkMock,
  fetchIpDocketMatterLinksMock,
  fetchIpDocketMock,
  fetchMatterIpLinksMock,
  listMattersMock,
  retireIpDocketMatterLinkMock,
} = vi.hoisted(() => ({
  capabilityMock: vi.fn(),
  createIpDocketMatterLinkMock: vi.fn(),
  fetchIpDocketMatterLinksMock: vi.fn(),
  fetchIpDocketMock: vi.fn(),
  fetchMatterIpLinksMock: vi.fn(),
  listMattersMock: vi.fn(),
  retireIpDocketMatterLinkMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/endpoints")>()),
  createIpDocketMatterLink: createIpDocketMatterLinkMock,
  fetchIpDocketMatterLinks: fetchIpDocketMatterLinksMock,
  fetchIpDocket: fetchIpDocketMock,
  fetchMatterIpLinks: fetchMatterIpLinksMock,
  listMatters: listMattersMock,
  retireIpDocketMatterLink: retireIpDocketMatterLinkMock,
}));

vi.mock("@/lib/capabilities", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/capabilities")>()),
  useCapability: (capability: string) => capabilityMock(capability),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { IpMatterLinksPanel, MatterIpLinksPanel } from "./IpMatterLinksPanel";
import { ApiError } from "@/lib/api/config";
import type { IpDocket, IpMatterLink } from "@/lib/api/endpoints";

const docket = {
  id: "docket-1",
  title: "CASEOPS",
  status: "ready",
  updated_at: "2026-08-23T10:00:00Z",
} as IpDocket;

const link: IpMatterLink = {
  id: "link-1",
  company_id: "company-1",
  docket_id: "docket-1",
  matter_id: "matter-1",
  relation_role: "litigation",
  effective_from: "2026-08-23T09:00:00Z",
  retired_at: null,
  source: "manual",
  source_reference: null,
  reason: "Registry opposition litigation.",
  retirement_reason: null,
  created_by_membership_id: "membership-1",
  retired_by_membership_id: null,
  access_mismatch_warning: true,
  lifecycle: {
    matter_id: "matter-1",
    matter_code: "TM-OPP-1",
    matter_title: "Opposition litigation",
    matter_status: "active",
    matter_is_active: true,
    docket_id: "docket-1",
    docket_title: "CASEOPS",
    docket_status: "ready",
    docket_is_active: true,
  },
  created_at: "2026-08-23T09:00:00Z",
  updated_at: "2026-08-23T09:00:00Z",
};

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("IP Matter relationship panels", () => {
  beforeEach(() => {
    fetchIpDocketMatterLinksMock.mockReset().mockResolvedValue({
      docket_id: docket.id,
      links: [link],
      count: 1,
      active_count: 1,
    });
    fetchMatterIpLinksMock.mockReset().mockResolvedValue({
      matter_id: link.matter_id,
      links: [link],
      count: 1,
      active_count: 1,
    });
    fetchIpDocketMock.mockReset().mockResolvedValue(docket);
    listMattersMock.mockReset().mockResolvedValue({ matters: [], next_cursor: null });
    retireIpDocketMatterLinkMock.mockReset().mockResolvedValue({
      link: {
        ...link,
        retired_at: "2026-08-23T11:00:00Z",
        retirement_reason: "Litigation engagement concluded.",
      },
      operational_pointer_cleared: false,
    });
  });

  it("shows independent states and retires an effective relationship on mobile", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 360 });
    const onChanged = vi.fn().mockResolvedValue(undefined);
    render(withClient(<IpMatterLinksPanel docket={docket} canWrite onChanged={onChanged} />));

    const panel = await screen.findByTestId("ip-matter-links-panel");
    expect(await within(panel).findByText("Matter lifecycle")).toBeVisible();
    expect(within(panel).getByText("IP lifecycle")).toBeVisible();
    expect(within(panel).getByText("Matter and IP access policies differ.")).toBeVisible();
    expect(within(panel).getByRole("link", { name: /TM-OPP-1/ })).toHaveAttribute(
      "href",
      "/app/matters/matter-1",
    );

    fireEvent.click(within(panel).getByRole("button", { name: "Retire" }));
    fireEvent.change(within(panel).getByLabelText("Retirement reason"), {
      target: { value: "Litigation engagement concluded." },
    });
    fireEvent.click(within(panel).getAllByRole("button", { name: "Retire" })[1]);

    await waitFor(() =>
      expect(retireIpDocketMatterLinkMock).toHaveBeenCalledWith({
        docketId: docket.id,
        linkId: link.id,
        reason: "Litigation engagement concluded.",
        expectedLinkUpdatedAt: link.updated_at,
        expectedDocketUpdatedAt: docket.updated_at,
      }),
    );
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("opens the linked IP record from the Matter view", async () => {
    render(withClient(<MatterIpLinksPanel matterId="matter-1" />));
    expect(await screen.findByText("CASEOPS")).toBeVisible();
    expect(screen.getByRole("link", { name: "Open IP" })).toHaveAttribute(
      "href",
      "/app/ip?docket=docket-1",
    );
  });
});

const LONG_CODE = "CALDIAG-100DC57D-D4DA-48C3-9398-568E8A67F784-3";
const LONG_TITLE = "Isolated Calendar diagnostic CALDIAG-100dc57d-d4da-48c3-9398-568e8a67f784 3";

function matter(index: number, overrides: Record<string, unknown> = {}) {
  return {
    id: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
    company_id: "company-1",
    matter_code: `M-${index}`,
    title: `Matter number ${index}`,
    client_name: null,
    status: "active",
    lifecycle_version: 0,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    ...overrides,
  };
}

async function openCreate(forDocket: IpDocket = docket) {
  const onChanged = vi.fn().mockResolvedValue(undefined);
  render(withClient(<IpMatterLinksPanel docket={forDocket} canWrite onChanged={onChanged} />));
  const panel = await screen.findByTestId("ip-matter-links-panel");
  fireEvent.click(within(panel).getByRole("button", { name: /Link Matter/ }));
  return { panel, onChanged };
}

async function chooseRole(name: string) {
  const user = userEvent.setup();
  await user.click(screen.getByRole("combobox", { name: "Role" }));
  await user.click(await screen.findByRole("option", { name }));
}

describe("BUG-007 Matter relationship picker", () => {
  beforeEach(() => {
    capabilityMock.mockReset().mockReturnValue(true);
    createIpDocketMatterLinkMock.mockReset();
    fetchIpDocketMock.mockReset().mockResolvedValue(docket);
    fetchIpDocketMatterLinksMock.mockReset().mockResolvedValue({
      docket_id: docket.id, links: [link], count: 1, active_count: 1,
    });
    listMattersMock.mockReset();
  });

  it("lists long code-like captions in a native select, pages by cursor and shows the full caption", async () => {
    const first = Array.from({ length: 49 }, (_, i) => matter(i + 2));
    first.push(matter(99, { matter_code: LONG_CODE, title: LONG_TITLE }));
    listMattersMock.mockImplementation(async (params: { cursor?: string }) =>
      params.cursor === "page-2"
        ? { matters: Array.from({ length: 20 }, (_, i) => matter(200 + i)), next_cursor: null }
        : { matters: first, next_cursor: "page-2" });
    const { panel } = await openCreate();

    const select = await within(panel).findByRole("combobox", { name: "Matter" });
    expect(select.tagName).toBe("SELECT");
    await waitFor(() => expect(select).toBeEnabled());
    expect(within(panel).getByText(/Showing the 50 most recently updated Matters/)).toBeVisible();
    fireEvent.click(within(panel).getByRole("button", { name: "Load more Matters" }));
    await waitFor(() => expect(listMattersMock).toHaveBeenCalledWith(expect.objectContaining({ cursor: "page-2" })));
    // 70 Matters plus the disabled placeholder.
    await waitFor(() => expect(within(select).getAllByRole("option").length).toBe(71));

    fireEvent.change(select, { target: { value: matter(99).id } });
    const caption = `${LONG_CODE} · ${LONG_TITLE}`;
    const description = within(panel).getByText(caption, { selector: "p" });
    expect(select.getAttribute("aria-describedby")).toContain(description.id);
  });

  it("searches on the server and names the query when nothing matches", async () => {
    listMattersMock.mockImplementation(async (params: { q?: string }) =>
      params.q ? { matters: [], next_cursor: null } : { matters: [matter(1)], next_cursor: null });
    const { panel } = await openCreate();
    fireEvent.change(await within(panel).findByLabelText("Search Matters"), { target: { value: "zzzz-no-such" } });
    expect(await within(panel).findByText(/No Matter you can see matches “zzzz-no-such”/)).toBeVisible();
    expect(listMattersMock).toHaveBeenCalledWith(expect.objectContaining({ q: "zzzz-no-such" }));
    expect(within(panel).getByRole("combobox", { name: "Matter" })).toBeDisabled();
  });

  it("shows a load failure with retry instead of an empty result", async () => {
    listMattersMock.mockRejectedValueOnce(new ApiError(503, "Service unavailable.", null));
    listMattersMock.mockResolvedValue({ matters: [matter(1)], next_cursor: null });
    const { panel } = await openCreate();
    expect(await within(panel).findByText(/Matters could not be loaded/)).toBeVisible();
    expect(within(panel).queryByText(/No Matter/)).toBeNull();
    fireEvent.click(within(panel).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(within(panel).getByRole("combobox", { name: "Matter" })).toBeEnabled());
  });

  it("offers the in-product path to create a Matter when none exist", async () => {
    listMattersMock.mockResolvedValue({ matters: [], next_cursor: null });
    const { panel } = await openCreate();
    expect(await within(panel).findByRole("link", { name: "Create a Matter" })).toHaveAttribute("href", "/app/matters");
    expect(within(panel).getByRole("combobox", { name: "Matter" })).toBeDisabled();
  });

  it("tells a role without matters:create who can create a Matter instead of linking to a dead end", async () => {
    capabilityMock.mockImplementation((capability: string) => capability !== "matters:create");
    listMattersMock.mockResolvedValue({ matters: [], next_cursor: null });
    const { panel } = await openCreate();
    expect(await within(panel).findByText(/Your role cannot create Matters; ask someone who can\./)).toBeVisible();
    expect(within(panel).queryByRole("link", { name: "Create a Matter" })).toBeNull();
  });

  it("never submits the form when Enter is pressed in the Matter search", async () => {
    const user = userEvent.setup();
    listMattersMock.mockImplementation(async (params: { q?: string }) =>
      ({ matters: params.q ? [matter(4)] : [matter(3)], next_cursor: null }));
    const { panel } = await openCreate();
    const select = await within(panel).findByRole("combobox", { name: "Matter" });
    await waitFor(() => expect(select).toBeEnabled());
    await user.selectOptions(select, matter(3).id);
    await user.type(within(panel).getByLabelText("Reason"), "Advisory counsel for the mark");
    expect(within(panel).getByRole("button", { name: /Add relationship/ })).toBeEnabled();

    await user.type(within(panel).getByLabelText("Search Matters"), "M-4{Enter}");
    await waitFor(() => expect(listMattersMock).toHaveBeenCalledWith(expect.objectContaining({ q: "M-4" })));
    expect(fetchIpDocketMock).not.toHaveBeenCalled();
    expect(createIpDocketMatterLinkMock).not.toHaveBeenCalled();
    // The earlier choice is still the one on screen; nothing was sent for it.
    expect(select).toHaveValue(matter(3).id);
  });

  it("keeps the chosen Matter when the role changes and anchors the reason when the new role refuses it", async () => {
    listMattersMock.mockResolvedValue({
      matters: [matter(2, { matter_code: "M-2", status: "closed" }), matter(3)],
      next_cursor: null,
    });
    const { panel } = await openCreate();
    const select = await within(panel).findByRole("combobox", { name: "Matter" });
    await waitFor(() => expect(select).toBeEnabled());
    fireEvent.change(select, { target: { value: matter(2).id } });
    fireEvent.change(within(panel).getByLabelText("Reason"), { target: { value: "Advisory counsel for the mark" } });

    await chooseRole("Advisory");
    expect(select).toHaveValue(matter(2).id);
    expect(within(panel).getByText("M-2 · Matter number 2", { selector: "p" })).toBeVisible();
    expect(within(panel).getByRole("button", { name: /Add relationship/ })).toBeEnabled();

    await chooseRole("Operational");
    expect(select).toHaveValue(matter(2).id);
    const message = within(panel).getByText("M-2: Closed Matters cannot be operational. Choose another Matter or role.");
    expect(select).toHaveAttribute("aria-invalid", "true");
    expect(select.getAttribute("aria-describedby")).toContain(message.id);
    expect(within(panel).getByRole("button", { name: /Add relationship/ })).toBeDisabled();
    expect(within(panel).getByText("Choose a Matter that can take this role to add the relationship.")).toBeVisible();

    await chooseRole("Litigation");
    expect(select).toHaveValue(matter(2).id);
    expect(select).not.toHaveAttribute("aria-invalid");
    expect(within(panel).getByRole("button", { name: /Add relationship/ })).toBeEnabled();
  });

  it("names every reason on screen when no search result can be chosen", async () => {
    listMattersMock.mockImplementation(async (params: { q?: string }) => ({
      matters: params.q
        ? [matter(1, { id: "matter-1", matter_code: "TM-OPP-1" })]
        : [matter(1, { id: "matter-1", matter_code: "TM-OPP-1" }), matter(3)],
      next_cursor: null,
    }));
    const { panel } = await openCreate();
    fireEvent.change(await within(panel).findByLabelText("Search Matters"), { target: { value: "TM-OPP" } });
    expect(
      await within(panel).findByText("None of these Matters can be chosen. Already linked as Litigation: TM-OPP-1."),
    ).toBeVisible();
    expect(within(panel).getByRole("combobox", { name: "Matter" })).toBeDisabled();
  });

  it("refuses each Operational branch the API refuses, with its reason", async () => {
    fetchIpDocketMatterLinksMock.mockResolvedValue({ docket_id: docket.id, links: [], count: 0, active_count: 0 });
    listMattersMock.mockResolvedValue({
      matters: [
        matter(5, { matter_code: "M-5", status: "disposed" }),
        matter(6, { id: "matter-pointer", matter_code: "M-6" }),
        matter(7, { matter_code: "M-7", status: "on_hold" }),
      ],
      next_cursor: null,
    });
    // The docket's operational pointer is M-6, with no active link (legacy pointer).
    await openCreate({ ...docket, matter_id: "matter-pointer" } as IpDocket);
    const panel = screen.getByTestId("ip-matter-links-panel");
    const select = await within(panel).findByRole("combobox", { name: "Matter" });
    await waitFor(() => expect(select).toBeEnabled());
    await chooseRole("Operational");
    const option = (code: string) => within(select).getByRole("option", { name: new RegExp(code) }) as HTMLOptionElement;
    expect(option("M-5").disabled).toBe(true);
    expect(option("M-5").textContent).toMatch(/Disposed Matters cannot be operational/);
    expect(option("M-7").disabled).toBe(true);
    expect(option("M-7").textContent).toMatch(/another Matter is this record's operational Matter/);
    expect(option("M-6").disabled).toBe(false);
  });

  it("disables the Operational role while an operational link is active", async () => {
    fetchIpDocketMatterLinksMock.mockResolvedValue({
      docket_id: docket.id,
      links: [{ ...link, id: "link-op", relation_role: "operational" }],
      count: 1,
      active_count: 1,
    });
    listMattersMock.mockResolvedValue({ matters: [matter(3)], next_cursor: null });
    await openCreate();
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Role" })).toBeEnabled());
    await user.click(screen.getByRole("combobox", { name: "Role" }));
    const operational = await screen.findByRole("option", { name: /Operational \(retire the current operational link first\)/ });
    expect(operational).toHaveAttribute("aria-disabled", "true");
  });

  it("waits for the existing relationships before offering a Matter, and shows why", async () => {
    fetchIpDocketMatterLinksMock.mockRejectedValue(new ApiError(503, "Service unavailable.", null));
    listMattersMock.mockResolvedValue({ matters: [matter(3)], next_cursor: null });
    const { panel } = await openCreate();
    expect(await within(panel).findByText(/a duplicate link cannot be ruled out/)).toBeVisible();
    expect(within(panel).getByText("Matter relationships could not be loaded: Service unavailable.")).toBeVisible();
    expect(within(panel).getByRole("button", { name: "Retry relationships" })).toBeVisible();
    expect(within(panel).getByRole("combobox", { name: "Matter" })).toBeDisabled();
    expect(within(panel).getByRole("button", { name: /Add relationship/ })).toBeDisabled();
  });

  it("anchors a rejected retirement reason to the Retirement reason field", async () => {
    retireIpDocketMatterLinkMock.mockReset().mockRejectedValue(new ApiError(422, "Reason: too short", {
      errors: [{ loc: ["body", "reason"], msg: "String should have at least 8 characters", type: "string_too_short" }],
    }));
    render(withClient(<IpMatterLinksPanel docket={docket} canWrite onChanged={vi.fn()} />));
    const panel = await screen.findByTestId("ip-matter-links-panel");
    fireEvent.click(await within(panel).findByRole("button", { name: "Retire" }));
    expect(within(panel).getByText("At least 8 characters. Recorded in the audit trail.")).toBeVisible();
    expect(within(panel).getByText("Give a reason of at least 8 characters to retire the relationship.")).toBeVisible();
    const field = within(panel).getByLabelText("Retirement reason");
    fireEvent.change(field, { target: { value: "Engagement concluded." } });
    fireEvent.click(within(panel).getAllByRole("button", { name: "Retire" })[1]);
    await waitFor(() => expect(field).toHaveAttribute("aria-invalid", "true"));
    const message = within(panel).getByText("String should have at least 8 characters");
    expect(field.getAttribute("aria-describedby")).toContain(message.id);
  });

  it("disables the values the link validator would reject, with the reason", async () => {
    listMattersMock.mockResolvedValue({
      matters: [matter(1, { id: "matter-1", matter_code: "TM-OPP-1" }), matter(2, { status: "closed" }), matter(3)],
      next_cursor: null,
    });
    const { panel } = await openCreate();
    const select = await within(panel).findByRole("combobox", { name: "Matter" });
    await waitFor(() => expect(select).toBeEnabled());
    const already = within(select).getByRole("option", { name: /TM-OPP-1/ }) as HTMLOptionElement;
    expect(already.disabled).toBe(true);
    expect(already.textContent).toMatch(/already linked as Litigation/);
    // A closed Matter can still take a non-operational role.
    expect((within(select).getByRole("option", { name: /M-2/ }) as HTMLOptionElement).disabled).toBe(false);
  });

  it("anchors a rejected reason to the Reason field", async () => {
    listMattersMock.mockResolvedValue({ matters: [matter(3)], next_cursor: null });
    createIpDocketMatterLinkMock.mockRejectedValue(new ApiError(422, "Reason: too short", {
      errors: [{ loc: ["body", "reason"], msg: "String should have at least 8 characters", type: "string_too_short" }],
    }));
    const { panel } = await openCreate();
    const select = await within(panel).findByRole("combobox", { name: "Matter" });
    await waitFor(() => expect(select).toBeEnabled());
    fireEvent.change(select, { target: { value: matter(3).id } });
    fireEvent.change(within(panel).getByLabelText("Reason"), { target: { value: "Opposition counsel" } });
    fireEvent.click(within(panel).getByRole("button", { name: /Add relationship/ }));
    const reason = within(panel).getByLabelText("Reason");
    await waitFor(() => expect(reason).toHaveAttribute("aria-invalid", "true"));
    const message = within(panel).getByText("String should have at least 8 characters");
    expect(reason.getAttribute("aria-describedby")).toContain(message.id);
    expect(createIpDocketMatterLinkMock).toHaveBeenCalledWith(expect.objectContaining({ matterId: matter(3).id }));
  });
});
