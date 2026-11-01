import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchIpNiceClassesMock } = vi.hoisted(() => ({ fetchIpNiceClassesMock: vi.fn() }));

vi.mock("@/lib/api/endpoints", () => ({ fetchIpNiceClasses: fetchIpNiceClassesMock }));

import { IpDocketClassScope } from "@/components/ip/IpDocketClassScope";

// Class 9's heading is one of the two rows NCL 13-2027 revised.
const HEADING_9 = {
  "NCL 13-2026": "Scientific, research, navigation apparatus; recorded and downloadable computer software.",
  "NCL 13-2027": "Scientific, research, navigation apparatus; computers and computer peripheral devices.",
} as const;

function catalogue(edition: keyof typeof HEADING_9) {
  return {
    edition,
    in_force_from: edition === "NCL 13-2026" ? "2026-01-01" : "2027-01-01",
    source_url: "https://nclpub.wipo.int/enfr/",
    source_data_url: "https://www.wipo.int/classifications/data/nice/",
    retrieved_on: "2026-10-31",
    headings_sha256: "a".repeat(64),
    attribution: `Nice Classification (${edition}). Copyright World Intellectual Property Organization (WIPO).`,
    classes: Array.from({ length: 45 }, (_, index) => ({
      number: index + 1,
      kind: index + 1 <= 34 ? "goods" : "services",
      heading: index + 1 === 9 ? HEADING_9[edition] : `Class ${index + 1} heading.`,
      note: null,
    })),
  };
}

function renderScope(classes: Parameters<typeof IpDocketClassScope>[0]["classes"]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IpDocketClassScope classes={classes} />
    </QueryClientProvider>,
  );
}

describe("IpDocketClassScope", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // The server serves NCL 13-2027 by default from 2027-01-01.
    fetchIpNiceClassesMock.mockImplementation(async (edition?: string) =>
      catalogue(edition === "NCL 13-2026" ? "NCL 13-2026" : "NCL 13-2027"),
    );
  });

  it("BUG-002 keeps a 2026 row's own heading after NCL 13-2027 is in force", async () => {
    renderScope([
      { class_number: 9, specification: "Downloadable software", nice_edition: "NCL 13-2026" },
      { class_number: 35, specification: "Advertising services", nice_edition: "NCL 13-2027" },
    ]);

    const row9 = screen.getByTestId("ip-docket-class-9");
    await waitFor(() => expect(row9).toHaveTextContent(HEADING_9["NCL 13-2026"]));
    expect(row9).not.toHaveTextContent(HEADING_9["NCL 13-2027"]);
    expect(row9).toHaveTextContent("Nice edition NCL 13-2026");
    await waitFor(() => expect(screen.getByTestId("ip-docket-class-35")).toHaveTextContent("Class 35 heading."));
    expect(fetchIpNiceClassesMock).toHaveBeenCalledWith("NCL 13-2026");
    expect(fetchIpNiceClassesMock).toHaveBeenCalledWith("NCL 13-2027");
  });

  it("BUG-002 never borrows a heading for a row recorded without an edition", async () => {
    renderScope([{ class_number: 9, specification: "Legacy software row" }]);

    const row = screen.getByTestId("ip-docket-class-9");
    expect(row).toHaveTextContent("Nice edition not recorded");
    expect(row).not.toHaveTextContent("Scientific");
    expect(fetchIpNiceClassesMock).not.toHaveBeenCalled();
  });

  it("BUG-002 says when a recorded edition's heading could not load", async () => {
    fetchIpNiceClassesMock.mockRejectedValue(new Error("offline"));
    renderScope([{ class_number: 9, specification: "Downloadable software", nice_edition: "NCL 13-2026" }]);

    await waitFor(() =>
      expect(screen.getByTestId("ip-docket-class-9")).toHaveTextContent(
        "Nice edition NCL 13-2026 · the class heading could not load",
      ),
    );
  });
});
