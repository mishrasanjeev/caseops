import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PricingPage from "@/app/pricing/page";
import { mockBillingFetch, planCatalog } from "@/test/billing-fixtures";

describe("PricingPage", () => {
  const fetchMock = vi.fn();
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    fetchMock.mockReset();
    mockBillingFetch(fetchMock);
    const catalogFetch = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input, init) => String(input) === "/api/demo-request"
      ? Promise.resolve(Response.json({ accepted: true, id: JSON.parse(String(init?.body)).idempotency_key, status: "demo_requested" }, { status: 202 }))
      : String(input).includes("/api/billing/plans")
        // Served out of price order: the page must sort cheapest first.
        ? Promise.resolve(Response.json({ ...planCatalog, plans: [...planCatalog.plans].reverse() }))
        : catalogFetch(input, init));
    originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("shows the 2026.11.v1 catalog with per-user and annual prices and sends a demo request", async () => {
    const user = userEvent.setup();
    render(<PricingPage />);

    expect((await screen.findAllByText("Solo Pro")).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("heading", { level: 2 }).slice(0, 2).map((h) => h.textContent)).toEqual([
      "Solo Core",
      "Solo Pro",
    ]);
    const soloPro = within(screen.getByTestId("plan-solo_pro"));
    expect(soloPro.getByText("4 users")).toBeInTheDocument();
    expect(soloPro.getByText("250 active matters")).toBeInTheDocument();
    expect(soloPro.getByText("40 tracked court cases")).toBeInTheDocument();
    expect(soloPro.getByText("250 AI credits per month")).toBeInTheDocument();
    expect(soloPro.getByText("per month, GST included")).toBeInTheDocument();
    // Rs 1,999 / 4 users, GST included; annual is ten months.
    expect(soloPro.getByText(/^₹500 per user per month$/)).toBeInTheDocument();
    expect(soloPro.getByText("Annual ₹19,990, saves ₹3,998")).toBeInTheDocument();
    // Refresh cadence is not enforced by the product, so it is not advertised.
    expect(screen.queryByText(/Refresh:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/founder/i)).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Included in every plan" })).toBeInTheDocument();
    expect(screen.getByText("AI credits", { selector: "dt" })).toBeInTheDocument();
    for (const link of screen.getAllByRole("link", { name: "Start 14-day trial" })) {
      expect(link).toHaveAttribute("href", "/sign-in?tab=new");
    }

    await user.click(screen.getByRole("button", { name: /law firms/i }));
    expect((await screen.findAllByText("Firm Growth")).length).toBeGreaterThan(0);
    const firmGrowth = within(screen.getByTestId("plan-firm_growth"));
    expect(firmGrowth.getByText("15 users + 10 viewers")).toBeInTheDocument();
    expect(firmGrowth.getByText("400 tracked court cases")).toBeInTheDocument();
    expect(firmGrowth.getByText("₹1,200 per user per month + GST")).toBeInTheDocument();
    expect(firmGrowth.getByText("Annual ₹1,79,990, saves ₹35,998")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /general counsel/i }));
    expect((await screen.findAllByText("GC Professional")).length).toBeGreaterThan(0);
    const gcProfessional = within(screen.getByTestId("plan-gc_professional"));
    expect(gcProfessional.getByText(/per year \+ GST/i)).toBeInTheDocument();
    expect(gcProfessional.getByText("4,000 tracked court cases")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Full name"), "Founder One");
    await user.type(screen.getByLabelText("Work email"), "founder@example.com");
    await user.type(screen.getByLabelText("Firm / company (optional)"), "Acme Law");
    await user.selectOptions(screen.getByLabelText("Role"), "general_counsel");
    await user.click(screen.getByRole("button", { name: "Request a conversation" }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input) === "/api/demo-request",
        ),
      ).toBe(true),
    );
    const [, init] = fetchMock.mock.calls.find(([input]) =>
      String(input) === "/api/demo-request",
    )!;
    expect(JSON.parse(String(init.body))).toMatchObject({
      contact_email: "founder@example.com",
      company_name: "Acme Law",
      selected_plan: null,
      segment: "gc",
    });
    expect(screen.getByRole("status")).toHaveTextContent(/request saved/i);
  });
});
