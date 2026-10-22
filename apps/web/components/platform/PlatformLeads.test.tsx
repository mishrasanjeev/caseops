import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PLATFORM_SESSION_INVALIDATED } from "@/lib/platform/client";
import { PlatformSessionProvider } from "@/lib/platform/session";

import { PlatformLeads } from "./PlatformLeads";

const manager = { id: "lead-test-manager", email: "manager@example.com", full_name: "Synthetic manager", role: "manager" };
const lead = {
  id: "00000000-0000-4000-8000-000000000021", submitted_at: "2026-10-21T20:00:00Z",
  contact_name: "Synthetic enquiry", contact_email: "enquiry@example.com", contact_mobile: "+910000000000",
  company_name: "Synthetic firm", segment: "firm", selected_plan: "firm-trial", source: "pricing_page",
  role: "partner", intent: "pricing", notes: "First line\n<script>not executable</script>", privacy_notice_version: "2026-10-21",
  notification: { status: "accepted", attempts: 1, last_error_code: null, eligible: true },
};
const page = (items: unknown[] = [lead], next_cursor: string | null = null) => ({ items, next_cursor, has_more: next_cursor !== null });
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

describe("platform leads renderer through the real console client", () => {
  let fetcher: ReturnType<typeof vi.fn>;
  let auth: unknown;
  let authStatus: number;
  let serveLeads: (url: URL, init?: RequestInit) => Promise<Response>;
  beforeEach(() => {
    auth = { state: "authenticated", admin: manager, expires_at: "2099-01-01T00:00:00Z" };
    authStatus = 200;
    serveLeads = async () => response(page());
    fetcher = vi.fn(async (input: string, init?: RequestInit) => {
      const url = new URL(input, "http://localhost");
      if (url.pathname.endsWith("/auth/session")) return response(auth, authStatus);
      if (url.pathname.endsWith("/leads")) return serveLeads(url, init);
      throw new Error("Unexpected renderer request");
    });
    vi.stubGlobal("fetch", fetcher);
  });
  afterEach(() => { vi.unstubAllGlobals(); });
  const mount = () => render(<PlatformSessionProvider><PlatformLeads /></PlatformSessionProvider>);
  const leadCalls = () => fetcher.mock.calls.filter(([url]) => new URL(String(url), "http://localhost").pathname.endsWith("/leads"));

  it("shows all allowlisted details, the original instant in IST, and no inbox-delivery claim", async () => {
    mount();
    const table = await screen.findByRole("table");
    const time = table.querySelector("time")!;
    expect(time).toHaveAttribute("dateTime", lead.submitted_at);
    expect(time).toHaveTextContent(new Intl.DateTimeFormat("en-IN", {
      dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata",
    }).format(new Date(lead.submitted_at)));
    expect(within(table).getByText("Provider accepted")).toBeVisible();
    expect(within(table).queryByText(/inbox|delivered/i)).not.toBeInTheDocument();
    fireEvent.click(within(table).getByText("View submission", { exact: true }));
    const details = table.querySelector("details")!;
    for (const [label, value] of [
      ["Reference", lead.id], ["Full name", lead.contact_name], ["Email", lead.contact_email],
      ["Phone", lead.contact_mobile], ["Firm or company", lead.company_name], ["Practice segment", lead.segment],
      ["Role", lead.role], ["Intent", lead.intent], ["Selected plan", lead.selected_plan],
      ["Public entry point", lead.source], ["Privacy notice", lead.privacy_notice_version], ["Notes", lead.notes],
    ]) expect(within(details).getByText(label, { exact: true }).nextElementSibling?.textContent).toBe(value);
    expect(table.querySelector("script")).toBeNull();
    expect(leadCalls()).toHaveLength(1);
    const [url, init] = leadCalls()[0];
    expect(String(url)).toMatch(/\/leads\?limit=25$/);
    expect(init).toMatchObject({ method: "GET", credentials: "include", cache: "no-store", referrerPolicy: "no-referrer" });
    expect((init as RequestInit).headers).not.toHaveProperty("Authorization");
  });

  it.each([
    ["not_requested", "Not requested"], ["pending", "Pending"], ["sending", "In progress"],
    ["accepted", "Provider accepted"], ["retry_pending", "Retry pending"], ["exhausted", "Not sent"],
    ["outcome_unknown", "Outcome unknown"],
  ])("keeps the %s notification state distinct", async (status, label) => {
    serveLeads = async () => response(page([{ ...lead, notification: { ...lead.notification, status, eligible: false } }]));
    mount();
    const table = await screen.findByRole("table");
    expect(within(table).getByText(label, { exact: true })).toBeVisible();
    expect(within(table).getByText("Not eligible for new-submission notifications")).toBeVisible();
    expect(within(table).queryByText("Inspect delivery evidence before any further send.") !== null).toBe(status === "outcome_unknown");
    expect(within(table).queryByRole("button", { name: /send|retry/i })).not.toBeInTheDocument();
  });

  it.each([
    [401, null, "Sign in required"],
    [200, { state: "mfa_enrollment_required", admin: null, expires_at: "2099-01-01T00:00:00Z" }, "Verification required"],
    [200, { state: "mfa_challenge_required", admin: null, expires_at: "2099-01-01T00:00:00Z" }, "Verification required"],
    [200, { state: "authenticated", admin: { ...manager, role: "viewer" }, expires_at: "2099-01-01T00:00:00Z" }, "Access denied"],
  ])("never requests or renders leads outside completed manager MFA %#", async (status, body, heading) => {
    authStatus = status; auth = body;
    mount();
    expect(await screen.findByRole("heading", { name: heading })).toBeVisible();
    expect(leadCalls()).toHaveLength(0);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText(lead.contact_email)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Leads" })).not.toBeInTheDocument();
  });

  it("uses signed continuation unchanged for next, reload and previous without retaining another page's PII", async () => {
    const cursor = "signed+/cursor=with?opaque&value";
    const next = { ...lead, id: "00000000-0000-4000-8000-000000000022", contact_email: "next@example.com" };
    serveLeads = async url => response(url.searchParams.get("cursor") === cursor ? page([next]) : page([lead], cursor));
    mount();
    await screen.findByText(lead.contact_email, { selector: "p" });
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await screen.findByText(next.contact_email, { selector: "p" });
    expect(screen.queryByText(lead.contact_email)).not.toBeInTheDocument();
    expect(screen.getByText("Page 2")).toBeVisible();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Reload leads" }));
    await waitFor(() => expect(leadCalls()).toHaveLength(3));
    await screen.findByText(next.contact_email, { selector: "p" });
    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    await screen.findByText(lead.contact_email, { selector: "p" });
    expect(screen.queryByText(next.contact_email)).not.toBeInTheDocument();
    expect(leadCalls().map(([url]) => new URL(String(url), "http://localhost").searchParams.get("cursor"))).toEqual([null, cursor, cursor, null]);
  });

  it("shows an honest empty result and nullable fields without inventing contact or notification data", async () => {
    serveLeads = async () => response(page([]));
    mount();
    expect(await screen.findByText("No public leads on this page.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    serveLeads = async () => response(page([{ ...lead, contact_name: null, contact_email: null, contact_mobile: null,
      company_name: null, selected_plan: null, role: null, intent: null, notes: null, privacy_notice_version: null }]));
    fireEvent.click(screen.getByRole("button", { name: "Reload leads" }));
    const summary = await screen.findByText("View submission");
    fireEvent.click(summary);
    expect(screen.getAllByText("Not provided")).toHaveLength(9);
    expect(screen.queryByText("No public leads on this page.")).not.toBeInTheDocument();
  });

  it.each([
    { ...lead, password_hash: "private-never-render" },
    { ...lead, submitted_at: "2026-10-21T20:00:00" },
    { ...lead, notification: { ...lead.notification, status: "delivered" } },
    { ...lead, notification: { ...lead.notification, attempts: -1 } },
  ])("rejects malformed or expanded DTOs instead of showing partial PII %#", async row => {
    serveLeads = async () => response(page([row]));
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("The report response could not be verified. No data is shown.");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText(lead.contact_email)).not.toBeInTheDocument();
    expect(screen.queryByText("No public leads on this page.")).not.toBeInTheDocument();
  });

  it("clears existing PII on read failure, shows safe copy, and never automatically retries", async () => {
    mount();
    await screen.findByText(lead.contact_email, { selector: "p" });
    serveLeads = async () => response({ detail: "Private backend diagnostics must not be displayed" }, 503);
    fireEvent.click(screen.getByRole("button", { name: "Reload leads" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The request outcome could not be confirmed. Check the current state before trying again.");
    expect(screen.queryByText(lead.contact_email)).not.toBeInTheDocument();
    expect(screen.queryByText(/Private backend diagnostics/)).not.toBeInTheDocument();
    expect(leadCalls()).toHaveLength(2);
  });

  it("aborts an in-flight lead read on session invalidation and cannot restore PII from a late response", async () => {
    let finish!: (value: Response) => void;
    let signal: AbortSignal | null | undefined;
    serveLeads = async (_url, init) => { signal = init?.signal; return new Promise(resolve => { finish = resolve; }); };
    mount();
    await waitFor(() => expect(leadCalls()).toHaveLength(1));
    act(() => { window.dispatchEvent(new Event(PLATFORM_SESSION_INVALIDATED)); });
    expect(await screen.findByRole("heading", { name: "Sign in required" })).toBeVisible();
    expect(signal?.aborted).toBe(true);
    await act(async () => { finish(response(page())); });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText(lead.contact_email)).not.toBeInTheDocument();
  });
});
