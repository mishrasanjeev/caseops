import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  canCurate: false,
  listJudgeAliases: vi.fn(),
  listJudgeMappingReviews: vi.fn(),
  listCuratorJudges: vi.fn(),
  listCuratorBenches: vi.fn(),
  resolveJudgeMappingReview: vi.fn(),
  createJudgeAlias: vi.fn(),
  createBenchAlias: vi.fn(),
  mergeJudgeIdentities: vi.fn(),
  reprocessJudgeAuthority: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listJudgeAliases: mocks.listJudgeAliases,
  listJudgeMappingReviews: mocks.listJudgeMappingReviews,
  listCuratorJudges: mocks.listCuratorJudges,
  listCuratorBenches: mocks.listCuratorBenches,
  resolveJudgeMappingReview: mocks.resolveJudgeMappingReview,
  createJudgeAlias: mocks.createJudgeAlias,
  createBenchAlias: mocks.createBenchAlias,
  mergeJudgeIdentities: mocks.mergeJudgeIdentities,
  reprocessJudgeAuthority: mocks.reprocessJudgeAuthority,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: () => mocks.canCurate,
}));

import JudgeAliasesAdminPage from "@/app/app/admin/judge-aliases/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("JudgeAliasesAdminPage", () => {
  beforeEach(() => {
    mocks.canCurate = false;
    for (const mock of Object.values(mocks)) {
      if (typeof mock === "function" && "mockReset" in mock) mock.mockReset();
    }
    mocks.listJudgeMappingReviews.mockResolvedValue({
      reviews: [],
      returned_count: 0,
      limit: 100,
      has_more: false,
    });
    mocks.listCuratorJudges.mockResolvedValue({
      judges: [],
      returned_count: 0,
      limit: 200,
      has_more: false,
    });
    mocks.listCuratorBenches.mockResolvedValue({
      benches: [],
      returned_count: 0,
      limit: 200,
      has_more: false,
    });
  });

  it("renders the header + a card per judge with all aliases", async () => {
    mocks.listJudgeAliases.mockResolvedValue({
      aliases: [
        {
          id: "a1",
          judge_id: "j1",
          judge_full_name: "Atul Sharachchandra Chandurkar",
          court_id: "supreme-court-india",
          court_short_name: "SC",
          alias_text: "Justice A.S. Chandurkar",
          source: "auto_extract",
          created_at: "2026-04-25T12:00:00Z",
        },
        {
          id: "a2",
          judge_id: "j1",
          judge_full_name: "Atul Sharachchandra Chandurkar",
          court_id: "supreme-court-india",
          court_short_name: "SC",
          alias_text: "Justice Atul Sharachchandra Chandurkar",
          source: "auto_extract",
          created_at: "2026-04-25T12:00:00Z",
        },
      ],
      judge_count: 1,
      alias_count: 2,
    });
    render(withClient(<JudgeAliasesAdminPage />));
    // Wait for the link to the judge profile (only visible after the
    // query resolves). The judge name appears multiple times in the
    // rendered DOM (link + label + alias chip) so anchor on the
    // /app/courts/judges/{id} href specifically.
    const profileLinks = await screen.findAllByRole("link", {
      name: /Atul Sharachchandra Chandurkar/i,
    });
    expect(
      screen.getByRole("heading", { name: "Judge aliases" }),
    ).toBeInTheDocument();
    expect(profileLinks[0]).toHaveAttribute(
      "href",
      "/app/courts/judges/j1",
    );
    expect(screen.getByText(/Justice A\.S\. Chandurkar/i)).toBeInTheDocument();
    expect(mocks.listJudgeAliases).toHaveBeenCalled();
  });

  it("shows the empty state when no aliases are recorded yet", async () => {
    mocks.listJudgeAliases.mockResolvedValue({
      aliases: [],
      judge_count: 0,
      alias_count: 0,
    });
    render(withClient(<JudgeAliasesAdminPage />));
    expect(
      await screen.findByText(/No aliases recorded yet/i),
    ).toBeInTheDocument();
  });

  it("surfaces an error state when the endpoint throws", async () => {
    mocks.listJudgeAliases.mockRejectedValue(new Error("network"));
    render(withClient(<JudgeAliasesAdminPage />));
    expect(
      await screen.findByText(/Could not load judge aliases/i),
    ).toBeInTheDocument();
  });

  it("resolves one collision evidence slot with the server record version", async () => {
    const user = userEvent.setup();
    mocks.canCurate = true;
    mocks.listJudgeAliases.mockResolvedValue({ aliases: [], judge_count: 0, alias_count: 0 });
    mocks.listJudgeMappingReviews.mockResolvedValue({
      reviews: [
        {
          id: "review-1",
          authority_document_id: "authority-1",
          authority_title: "Acme v Zenith",
          court_id: "court-1",
          court_name: "Delhi High Court",
          raw_judge_name: "Justice A Rao",
          source_ordinal: 1,
          reason: "collision",
          status: "open",
          resolver_version: "judge-alias-v2",
          candidates: [{ id: "judge-1", full_name: "Justice A. Rao", court_id: "court-1" }],
          resolved_judge_id: null,
          resolution_note: null,
          record_version: 3,
          created_at: "2026-08-26T00:00:00Z",
          updated_at: "2026-08-26T00:00:00Z",
        },
      ],
      returned_count: 1,
      limit: 100,
      has_more: false,
    });
    mocks.resolveJudgeMappingReview.mockResolvedValue({});

    render(withClient(<JudgeAliasesAdminPage />));

    await screen.findByText("Acme v Zenith");
    await user.selectOptions(screen.getByLabelText("Canonical judge"), "judge-1");
    await user.type(
      screen.getByLabelText("Resolution note"),
      "Official roster confirms this identity.",
    );
    await user.click(screen.getByRole("button", { name: /resolve evidence/i }));

    await waitFor(() =>
      expect(mocks.resolveJudgeMappingReview).toHaveBeenCalledWith("review-1", {
        judge_id: "judge-1",
        expected_record_version: 3,
        note: "Official roster confirms this identity.",
      }),
    );
  });

  it("searches the server-owned court catalog when a review has no candidates", async () => {
    const user = userEvent.setup();
    mocks.canCurate = true;
    mocks.listJudgeAliases.mockResolvedValue({ aliases: [], judge_count: 0, alias_count: 0 });
    mocks.listJudgeMappingReviews.mockResolvedValue({
      reviews: [
        {
          id: "review-unresolved",
          authority_document_id: "authority-2",
          authority_title: "Unresolved bench record",
          court_id: "court-1",
          court_name: "Delhi High Court",
          raw_judge_name: "A Rao",
          source_ordinal: 0,
          reason: "unresolved",
          status: "open",
          resolver_version: "judge-alias-v2",
          candidates: [],
          resolved_judge_id: null,
          resolution_note: null,
          record_version: 1,
          created_at: "2026-08-26T00:00:00Z",
          updated_at: "2026-08-26T00:00:00Z",
        },
      ],
      returned_count: 1,
      limit: 100,
      has_more: false,
    });
    mocks.listCuratorJudges.mockImplementation(
      async (params: { courtId?: string; q?: string }) => ({
        judges:
          params.q === "Rao"
            ? [
                {
                  id: "judge-1",
                  court_id: "court-1",
                  full_name: "Justice A. Rao",
                  source_name: "official_court",
                  source_url: "https://delhihighcourt.nic.in/web/Judges",
                  source_reference: null,
                  identity_version: 1,
                  record_version: 2,
                  merged_into_judge_id: null,
                  is_active: true,
                },
              ]
            : [],
        returned_count: params.q === "Rao" ? 1 : 0,
        limit: 100,
        has_more: false,
      }),
    );

    render(withClient(<JudgeAliasesAdminPage />));

    await screen.findByText("Unresolved bench record");
    await user.type(screen.getByLabelText("Search canonical judges"), "Rao");
    await waitFor(() =>
      expect(mocks.listCuratorJudges).toHaveBeenCalledWith({
        courtId: "court-1",
        q: "Rao",
        limit: 100,
      }),
    );
    await user.selectOptions(screen.getByLabelText("Canonical judge"), "judge-1");
    expect(screen.getByLabelText("Canonical judge")).toHaveValue("judge-1");
  });

  describe("Nov 27 row 1: Canonical bench picker while adding a bench alias", () => {
    const BOMBAY_BENCHES = [
      "Bench at Aurangabad",
      "Bench at Kolhapur",
      "Bench at Nagpur",
      "High Court of Bombay at Goa",
      "Principal Seat at Bombay",
    ].map((name, index) => ({
      id: `bench-${index}`,
      court_id: "bombay-hc",
      court_name: "Bombay High Court",
      court_short_name: "Bombay HC",
      name,
      seat_city: null,
      source_name: "High Court of Bombay official website",
      source_url: "https://bombayhighcourt.gov.in/bhc/",
      source_reference: "retrieved 2026-11-27",
      record_version: 0,
    }));

    async function openAliasesTab(user: ReturnType<typeof userEvent.setup>) {
      mocks.canCurate = true;
      mocks.listJudgeAliases.mockResolvedValue({ aliases: [], judge_count: 0, alias_count: 0 });
      render(withClient(<JudgeAliasesAdminPage />));
      await user.click(await screen.findByRole("tab", { name: "Aliases" }));
      return screen.getByRole("heading", { name: "Bench alias" }).closest("form")!;
    }

    it("offers the benches of the court the curator searches and creates the alias", async () => {
      const user = userEvent.setup();
      mocks.listCuratorBenches.mockImplementation(async (params: { q?: string }) => {
        const rows = params.q === "Bombay" ? BOMBAY_BENCHES : [];
        return { benches: rows, returned_count: rows.length, total_count: rows.length, limit: 200, has_more: false };
      });
      mocks.createBenchAlias.mockResolvedValue({});
      const form = await openAliasesTab(user);

      await user.type(within(form).getByLabelText("Search benches"), "Bombay");
      const select = within(form).getByLabelText("Canonical bench");
      await waitFor(() =>
        expect(within(select).getAllByRole("option").map((option) => option.textContent)).toEqual([
          "Select",
          "Bench at Aurangabad · Bombay HC",
          "Bench at Kolhapur · Bombay HC",
          "Bench at Nagpur · Bombay HC",
          "High Court of Bombay at Goa · Bombay HC",
          "Principal Seat at Bombay · Bombay HC",
        ]),
      );
      expect(mocks.listCuratorBenches).toHaveBeenLastCalledWith({ q: "Bombay", limit: 200 });
      expect(within(form).getByTestId("bench-alias-catalog-status")).toHaveTextContent(
        "5 of 5 canonical benches shown.",
      );
      expect(select).toHaveAccessibleDescription(/5 of 5 canonical benches shown/);

      await user.selectOptions(select, "bench-2");
      await user.type(within(form).getByLabelText("Alias"), "Nagpur Bench");
      await user.type(
        within(form).getByLabelText("Official source URL"),
        "https://bombayhighcourt.gov.in/bhc/",
      );
      await user.click(within(form).getByRole("button", { name: /add bench alias/i }));
      await waitFor(() =>
        expect(mocks.createBenchAlias).toHaveBeenCalledWith("bench-2", {
          alias_text: "Nagpur Bench",
          source: "manual_curator",
          source_url: "https://bombayhighcourt.gov.in/bhc/",
        }),
      );
    });

    it("explains an empty catalogue and a search with no match instead of a blank dropdown", async () => {
      const user = userEvent.setup();
      const form = await openAliasesTab(user);
      const status = within(form).getByTestId("bench-alias-catalog-status");
      await waitFor(() =>
        expect(status).toHaveTextContent("No canonical benches are catalogued yet."),
      );
      expect(status).toHaveTextContent("ask your platform administrator");
      expect(within(form).getByLabelText("Canonical bench")).toHaveDisplayValue(
        "No matching canonical benches",
      );

      await user.type(within(form).getByLabelText("Search benches"), "Nowhere");
      await waitFor(() =>
        expect(status).toHaveTextContent(
          "No canonical bench matches “Nowhere”. Search by court (Delhi), seat city (Nagpur) or bench name.",
        ),
      );
      expect(within(form).getByRole("button", { name: /add bench alias/i })).toBeDisabled();
    });

    const DELHI_PRINCIPAL_SEAT = {
      id: "bench-delhi",
      court_id: "delhi-hc",
      court_name: "Delhi High Court",
      court_short_name: "Delhi HC",
      name: "Principal Seat at Delhi",
      seat_city: "Delhi",
      source_name: "eCourts High Court Services, Government of India",
      source_url: "https://hcservices.ecourts.gov.in/hcservices/main.php",
      source_reference: "retrieved 2026-11-28",
      record_version: 0,
    };
    const ALLAHABAD = { id: "allahabad-hc", name: "Allahabad High Court", short_name: "Allahabad HC" };

    function byCourt(params: { q?: string }) {
      const q = params.q ?? "";
      const benches = q === "Delhi" ? [DELHI_PRINCIPAL_SEAT] : [];
      const bare = q === "Allahabad" || q === "High Court" ? [ALLAHABAD] : [];
      const rows = q === "High Court" ? [...BOMBAY_BENCHES, DELHI_PRINCIPAL_SEAT] : benches;
      return {
        benches: rows,
        returned_count: rows.length,
        total_count: rows.length,
        limit: 200,
        has_more: false,
        courts_without_benches: bare,
        courts_without_benches_total: bare.length,
      };
    }

    it("offers a single-seat court's principal seat and creates the alias against it", async () => {
      const user = userEvent.setup();
      mocks.listCuratorBenches.mockImplementation(async (params: { q?: string }) => byCourt(params));
      mocks.createBenchAlias.mockResolvedValue({});
      const form = await openAliasesTab(user);

      await user.type(within(form).getByLabelText("Search benches"), "Delhi");
      const select = within(form).getByLabelText("Canonical bench");
      await waitFor(() =>
        expect(within(select).getAllByRole("option").map((option) => option.textContent)).toEqual([
          "Select",
          "Principal Seat at Delhi · Delhi HC",
        ]),
      );
      expect(within(form).getByTestId("bench-alias-catalog-status")).toHaveTextContent(
        "1 of 1 canonical benches shown.",
      );
      await user.selectOptions(select, "bench-delhi");
      await user.type(within(form).getByLabelText("Alias"), "High Court of Delhi at New Delhi");
      await user.type(
        within(form).getByLabelText("Official source URL"),
        "https://delhihighcourt.nic.in/",
      );
      await user.click(within(form).getByRole("button", { name: /add bench alias/i }));
      await waitFor(() =>
        expect(mocks.createBenchAlias).toHaveBeenCalledWith("bench-delhi", {
          alias_text: "High Court of Delhi at New Delhi",
          source: "manual_curator",
          source_url: "https://delhihighcourt.nic.in/",
        }),
      );
    });

    it("names a searched court whose benches are not catalogued and gives the next step", async () => {
      const user = userEvent.setup();
      mocks.listCuratorBenches.mockImplementation(async (params: { q?: string }) => byCourt(params));
      const form = await openAliasesTab(user);
      const status = within(form).getByTestId("bench-alias-catalog-status");

      await user.type(within(form).getByLabelText("Search benches"), "Allahabad");
      await waitFor(() =>
        expect(status).toHaveTextContent(
          "No canonical benches are catalogued for Allahabad High Court yet.",
        ),
      );
      expect(status).toHaveTextContent(
        "Ask your platform administrator to have its benches catalogued",
      );
      expect(status).not.toHaveTextContent("No canonical bench matches");
      const select = within(form).getByLabelText("Canonical bench");
      expect(select).toHaveAccessibleDescription(/catalogued for Allahabad High Court yet/);
      expect(within(select).getAllByRole("option")).toHaveLength(1);
      expect(within(form).getByRole("button", { name: /add bench alias/i })).toBeDisabled();

      // A broad search that also matches catalogued benches still names the gap.
      await user.clear(within(form).getByLabelText("Search benches"));
      await user.type(within(form).getByLabelText("Search benches"), "High Court");
      await waitFor(() =>
        expect(within(form).getByTestId("bench-alias-catalog-uncatalogued")).toHaveTextContent(
          "No canonical benches are catalogued yet for Allahabad High Court.",
        ),
      );
      expect(status).toHaveTextContent("6 of 6 canonical benches shown.");
    });

    it("states the server total when the result is capped", async () => {
      const user = userEvent.setup();
      mocks.listCuratorBenches.mockResolvedValue({
        benches: BOMBAY_BENCHES,
        returned_count: 5,
        total_count: 340,
        limit: 200,
        has_more: true,
      });
      const form = await openAliasesTab(user);
      await waitFor(() =>
        expect(within(form).getByTestId("bench-alias-catalog-status")).toHaveTextContent(
          "Showing 5 of 340 canonical benches. Refine the search to reach the rest.",
        ),
      );
    });

    it("shows a failed catalogue read with a working retry", async () => {
      const user = userEvent.setup();
      mocks.listCuratorBenches.mockRejectedValueOnce(new Error("network"));
      mocks.listCuratorBenches.mockResolvedValue({
        benches: BOMBAY_BENCHES,
        returned_count: 5,
        total_count: 5,
        limit: 200,
        has_more: false,
      });
      const form = await openAliasesTab(user);
      const status = within(form).getByTestId("bench-alias-catalog-status");
      await waitFor(() =>
        expect(status).toHaveTextContent("The canonical benches could not be loaded."),
      );
      await user.click(within(form).getByRole("button", { name: "Retry" }));
      await waitFor(() => expect(status).toHaveTextContent("5 of 5 canonical benches shown."));
    });
  });
});
