import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  createIpDocketMatterLinkMock,
  fetchIpDocketMatterLinksMock,
  fetchIpDocketMock,
  fetchMatterIpLinksMock,
  listMattersMock,
  retireIpDocketMatterLinkMock,
} = vi.hoisted(() => ({
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

async function openCreate() {
  const onChanged = vi.fn().mockResolvedValue(undefined);
  render(withClient(<IpMatterLinksPanel docket={docket} canWrite onChanged={onChanged} />));
  const panel = await screen.findByTestId("ip-matter-links-panel");
  fireEvent.click(within(panel).getByRole("button", { name: /Link Matter/ }));
  return { panel, onChanged };
}

describe("BUG-007 Matter relationship picker", () => {
  beforeEach(() => {
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
