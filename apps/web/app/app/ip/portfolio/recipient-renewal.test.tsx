import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { IpPortfolioResponse } from "@/lib/api/endpoints";

vi.mock("@/lib/capabilities", () => ({ useCapability: () => true }));

import IpPortfolioPage from "./page";

const DOCKET = "11111111-1111-4111-8111-111111111111";
const BODY = "Current mark; application CURRENT/2028; classes 42, 45; " +
  "applicant Current Applicant, Current Joint Applicant. " +
  "Source renewal date 2028-03-30 (not a verified legal deadline). " +
  "10 days remaining on the alert date. /app/ip?docket=" + DOCKET;

function response(body: string | null = BODY, status = "delivered"): IpPortfolioResponse {
  return {
    rows: [{
      application_id: "22222222-2222-4222-8222-222222222222", docket_id: DOCKET,
      current_version: 1, source_application_on: null, source_application_state: "missing",
      source_renewal_state: "imported_unverified",
      matter_id: null, asset_id: null, asset_kind: "trademark", asset_title: "Current mark",
      asset_jurisdiction: "IN", docket_title: "Current mark", docket_status: "draft",
      primary_identifier: "CURRENT/2028", application_numbers: ["CURRENT/2028"],
      opposition_numbers: [], nice_classes: [42, 45], goods_services: [],
      representation_kinds: ["word"], proprietors: ["Current Applicant", "Current Joint Applicant"],
      agents: [], client_name: null, responsible_lawyer: null, responsible_membership_id: null,
      team_name: null, team_id: null, office: "IP India", jurisdiction: "IN",
      filing_phase: "draft", is_active: true, lifecycle_version: 0,
      pending_identifier_allocation: false, record_complete: false, incomplete_reasons: ["asset"],
      open_deadline_count: 0, unconfirmed_deadline_count: 0, overdue_deadline_count: 0,
      registry_sync_state: "unavailable", registry_last_success_at: null, provenance: [],
      application_created_at: "2028-03-20T00:00:00Z", updated_at: "2028-03-20T00:00:00Z",
      source_renewal_due_on: "2028-03-30", source_renewal_alert_at: "2028-03-20T00:00:00Z",
      source_renewal_alert_status: status, source_renewal_alert_body: body,
    }],
    counts: { total: 1, complete_records: 0, incomplete_records: 1,
      unconfirmed_deadline_records: 0, overdue_records: 0, stale_sync_records: 0,
      sync_failure_records: null, registry_sync_state: "unavailable" },
    filters: {}, limit: 50, next_cursor: null,
  };
}

let current: IpPortfolioResponse;

beforeEach(() => {
  current = response();
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => {
    const path = new URL(String(url)).pathname;
    const payload = path === "/api/ip/portfolio" ? current :
      path === "/api/ip/portfolio/views" ? { views: [] } :
        path === "/api/ip/portfolio/exports" ? { jobs: [] } : null;
    if (payload === null) throw new Error("Unexpected request: " + path);
    return new Response(JSON.stringify(payload), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  }));
});

afterEach(() => { vi.unstubAllGlobals(); });

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return { client, ...render(
    <QueryClientProvider client={client}><IpPortfolioPage /></QueryClientProvider>,
  ) };
}

describe("Recipient renewal content through the existing Portfolio HTTP client", () => {
  it("renders the exact body in existing table and mobile card cells, without a new request", async () => {
    mount();
    const bodies = await screen.findAllByTestId("ip-source-renewal-alert-" + DOCKET);
    expect(bodies).toHaveLength(2);
    for (const element of bodies) {
      expect(element.textContent).toBe(BODY);
      expect(element.closest("details")).not.toHaveAttribute("open");
      const summary = element.closest("details")!.querySelector("summary")!;
      expect(summary.textContent).toBe("Renewal alert");
      fireEvent.click(summary);
      expect(element.closest("details")).toHaveAttribute("open");
      expect(element.closest("td, article")).not.toBeNull();
      expect(element).toHaveClass("whitespace-pre-wrap", "[overflow-wrap:anywhere]");
      expect(element).not.toHaveTextContent("FAKE_INTERNAL_REMARK_DO_NOT_NOTIFY");
    }
    const portfolioCalls = vi.mocked(fetch).mock.calls.filter(([url]) =>
      new URL(String(url)).pathname === "/api/ip/portfolio");
    expect(portfolioCalls).toHaveLength(1);
    expect(portfolioCalls[0][1]).toMatchObject({ method: "GET", credentials: "include" });
    expect(vi.mocked(fetch).mock.calls.every(([url]) =>
      new URL(String(url)).pathname.startsWith("/api/ip/portfolio"))).toBe(true);
  });

  it("renders the same readable body in the existing grid view", async () => {
    mount();
    await screen.findAllByTestId("ip-source-renewal-alert-" + DOCKET);
    fireEvent.click(screen.getByRole("button", { name: "Grid view" }));
    const bodies = screen.getAllByTestId("ip-source-renewal-alert-" + DOCKET);
    expect(bodies).toHaveLength(1);
    expect(bodies[0].closest("article")).not.toBeNull();
    expect(bodies[0].textContent).toBe(BODY);
  });

  it.each(["queued", "cancelled", "blocked", "delivered"])(
    "shows no alert body when the server denies content with status %s", async status => {
      current = response(null, status);
      mount();
      await screen.findAllByText("Alert: " + status);
      expect(screen.queryByTestId("ip-source-renewal-alert-" + DOCKET)).not.toBeInTheDocument();
      expect(screen.queryByText(BODY)).not.toBeInTheDocument();
    },
  );

  it("clears content after refetch and remount when the source date is removed", async () => {
    const view = mount();
    await screen.findAllByTestId("ip-source-renewal-alert-" + DOCKET);
    current = response(null);
    current.rows[0].source_renewal_due_on = null;
    await view.client.invalidateQueries({ queryKey: ["ip", "portfolio"] });
    await waitFor(() => expect(screen.queryByTestId("ip-source-renewal-alert-" + DOCKET))
      .not.toBeInTheDocument());
    view.unmount();
    mount();
    await screen.findAllByText("Current mark");
    expect(screen.queryByText(BODY)).not.toBeInTheDocument();
  });

  it("renders stored text literally, never as HTML", async () => {
    current = response(BODY + " <b>Literal stored text</b>");
    mount();
    const bodies = await screen.findAllByTestId("ip-source-renewal-alert-" + DOCKET);
    for (const element of bodies) {
      expect(element.textContent).toBe(BODY + " <b>Literal stored text</b>");
      expect(element.querySelector("b")).toBeNull();
    }
  });
});
