import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchIpDocketMatterLinksMock,
  fetchIpDocketMock,
  fetchMatterIpLinksMock,
  listMattersMock,
  retireIpDocketMatterLinkMock,
} = vi.hoisted(() => ({
  fetchIpDocketMatterLinksMock: vi.fn(),
  fetchIpDocketMock: vi.fn(),
  fetchMatterIpLinksMock: vi.fn(),
  listMattersMock: vi.fn(),
  retireIpDocketMatterLinkMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/endpoints")>()),
  fetchIpDocketMatterLinks: fetchIpDocketMatterLinksMock,
  fetchIpDocket: fetchIpDocketMock,
  fetchMatterIpLinks: fetchMatterIpLinksMock,
  listMatters: listMattersMock,
  retireIpDocketMatterLink: retireIpDocketMatterLinkMock,
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { IpMatterLinksPanel, MatterIpLinksPanel } from "./IpMatterLinksPanel";
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
