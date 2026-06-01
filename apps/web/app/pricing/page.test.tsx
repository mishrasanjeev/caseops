import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PricingPage from "@/app/pricing/page";
import { mockBillingFetch } from "@/test/billing-fixtures";

describe("PricingPage", () => {
  const fetchMock = vi.fn();
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    fetchMock.mockReset();
    mockBillingFetch(fetchMock);
    originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("loads the PRD plan catalog by segment and sends a demo request", async () => {
    const user = userEvent.setup();
    render(<PricingPage />);

    expect((await screen.findAllByText("Solo Pro")).length).toBeGreaterThan(0);
    expect(screen.getByText("4 internal users")).toBeInTheDocument();
    expect(screen.getByText("250 active matters")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /law firms/i }));
    expect((await screen.findAllByText("Firm Growth")).length).toBeGreaterThan(0);
    expect(screen.getByText("1,000 tracked cases")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /general counsel/i }));
    expect((await screen.findAllByText("GC Professional")).length).toBeGreaterThan(0);
    expect(screen.getByText(/per year \+ GST/i)).toBeInTheDocument();

    await user.type(screen.getByLabelText("Name"), "Founder One");
    await user.type(screen.getByLabelText("Email"), "founder@example.com");
    await user.type(screen.getByLabelText("Company"), "Acme Law");
    await user.selectOptions(screen.getByLabelText("Plan"), "firm_growth");
    await user.click(screen.getByRole("button", { name: "Request pricing" }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).includes("/api/billing/enrollments/demo-request"),
        ),
      ).toBe(true),
    );
    const [, init] = fetchMock.mock.calls.find(([input]) =>
      String(input).includes("/api/billing/enrollments/demo-request"),
    )!;
    expect(JSON.parse(String(init.body))).toMatchObject({
      contact_email: "founder@example.com",
      company_name: "Acme Law",
      selected_plan: "firm_growth",
      segment: "gc",
    });
    expect(screen.getByRole("status")).toHaveTextContent(/request received/i);
  });
});
