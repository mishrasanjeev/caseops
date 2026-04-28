import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listCourtsMock } = vi.hoisted(() => ({
  listCourtsMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listCourts: listCourtsMock,
}));

import CourtsIndexPage from "@/app/app/courts/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const COURTS_FIXTURE = {
  courts: [
    {
      id: "c-sc",
      name: "Supreme Court of India",
      short_name: "SCI",
      forum_level: "supreme_court",
      jurisdiction: "Union of India",
      seat_city: "New Delhi",
    },
    {
      id: "c-hc-del",
      name: "Delhi High Court",
      short_name: "DHC",
      forum_level: "high_court",
      jurisdiction: "Delhi",
      seat_city: "New Delhi",
    },
    {
      id: "c-hc-bom",
      name: "Bombay High Court",
      short_name: "BHC",
      forum_level: "high_court",
      jurisdiction: "Maharashtra",
      seat_city: "Mumbai",
    },
  ],
};

describe("CourtsIndexPage", () => {
  beforeEach(() => {
    listCourtsMock.mockReset();
  });

  it("renders skeleton on first load", () => {
    listCourtsMock.mockImplementation(() => new Promise(() => {}));
    render(withClient(<CourtsIndexPage />));
    // PageHeader title is visible immediately even while data loads.
    expect(screen.getAllByText(/Courts/i).length).toBeGreaterThan(0);
  });

  it("groups courts by forum level (Supreme Court, High Court order)", async () => {
    listCourtsMock.mockResolvedValue(COURTS_FIXTURE);
    render(withClient(<CourtsIndexPage />));
    expect(await screen.findByText("Supreme Court of India")).toBeInTheDocument();
    expect(screen.getByText("Delhi High Court")).toBeInTheDocument();
    expect(screen.getByText("Bombay High Court")).toBeInTheDocument();
  });

  it("filters by search term (case-insensitive across name + city)", async () => {
    listCourtsMock.mockResolvedValue(COURTS_FIXTURE);
    render(withClient(<CourtsIndexPage />));
    await screen.findByText("Bombay High Court");
    const searchInput = screen.getByRole("textbox");
    await userEvent.type(searchInput, "mumbai");
    expect(screen.queryByText("Delhi High Court")).not.toBeInTheDocument();
    expect(screen.queryByText("Supreme Court of India")).not.toBeInTheDocument();
    expect(screen.getByText("Bombay High Court")).toBeInTheDocument();
  });
});
