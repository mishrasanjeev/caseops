import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/config";

const { searchProductGuideMock } = vi.hoisted(() => ({
  searchProductGuideMock: vi.fn(),
}));

vi.mock("@/lib/api/product-guide", () => ({
  searchProductGuide: searchProductGuideMock,
}));

import { ProductGuideSearch } from "@/components/guide/ProductGuideSearch";

const CURRENT_VERSION = "2026.08.26.1";

describe("ProductGuideSearch", () => {
  beforeEach(() => {
    searchProductGuideMock.mockReset();
  });

  it("searches the approved corpus and offers direct workflow navigation", async () => {
    const user = userEvent.setup();
    searchProductGuideMock.mockResolvedValue({
      status: "matched",
      version_status: "current",
      content_version: CURRENT_VERSION,
      catalog_fingerprint: "fingerprint",
      query: "deadline control",
      results: [
        {
          kind: "command",
          id: "deadline-control",
          title: "Deadline control",
          summary: "Review legal deadlines and calculation provenance.",
          href: "/app/ip/docket",
          required_capabilities: ["ip:read"],
        },
      ],
      permission: null,
      suggested_queries: [],
    });

    render(<ProductGuideSearch contentVersion={CURRENT_VERSION} />);
    await user.type(screen.getByRole("searchbox", { name: "Search the CaseOps guide" }), "deadline control");
    await user.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() =>
      expect(searchProductGuideMock).toHaveBeenCalledWith(
        "deadline control",
        expect.objectContaining({ clientVersion: CURRENT_VERSION }),
      ),
    );
    expect(screen.getByRole("link", { name: /Deadline control/ })).toHaveAttribute(
      "href",
      "/app/ip/docket",
    );
    expect(screen.getByText("Review legal deadlines and calculation provenance.")).toBeVisible();
  });

  it("reports a stale guide and explains missing capability without leaking a destination", async () => {
    const user = userEvent.setup();
    searchProductGuideMock.mockResolvedValue({
      status: "permission_required",
      version_status: "stale",
      content_version: "2026.08.27.1",
      catalog_fingerprint: "fingerprint",
      query: "platform admin",
      results: [],
      permission: {
        required_capabilities: ["platform:admin"],
        message: "This task needs additional workspace access.",
      },
      suggested_queries: [],
    });

    render(<ProductGuideSearch contentVersion={CURRENT_VERSION} />);
    await user.type(screen.getByRole("searchbox"), "platform admin");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByTestId("product-guide-stale")).toHaveTextContent(
      "search is using the current guide 2026.08.27.1",
    );
    expect(screen.getByTestId("product-guide-permission")).toHaveTextContent(
      "Required access: Platform admin",
    );
    expect(screen.queryByText("/app/platform-admin")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Platform admin/ })).not.toBeInTheDocument();
  });

  it("keeps the permission explanation visible beside safe guide matches", async () => {
    const user = userEvent.setup();
    searchProductGuideMock.mockResolvedValue({
      status: "matched",
      version_status: "current",
      content_version: CURRENT_VERSION,
      catalog_fingerprint: "fingerprint",
      query: "platform admin",
      results: [
        {
          kind: "guide",
          id: "admin",
          title: "Admin, audit and access controls",
          summary: "Review safe administration guidance.",
          href: "/guide#admin",
          required_capabilities: [],
        },
      ],
      permission: {
        required_capabilities: ["platform:admin"],
        message: "This task needs additional workspace access.",
      },
      suggested_queries: [],
    });

    render(<ProductGuideSearch contentVersion={CURRENT_VERSION} />);
    await user.type(screen.getByRole("searchbox"), "platform admin");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByRole("link", { name: /Admin, audit and access controls/ })).toBeVisible();
    expect(screen.getByTestId("product-guide-permission")).toHaveTextContent(
      "Required access: Platform admin",
    );
    expect(screen.queryByRole("link", { name: /^Platform admin/ })).not.toBeInTheDocument();
  });

  it("abstains deterministically and lets a user run an approved suggested search", async () => {
    const user = userEvent.setup();
    searchProductGuideMock
      .mockResolvedValueOnce({
        status: "no_match",
        version_status: "current",
        content_version: CURRENT_VERSION,
        catalog_fingerprint: "fingerprint",
        query: "xylophone nebula",
        results: [],
        permission: null,
        suggested_queries: ["research"],
      })
      .mockResolvedValueOnce({
        status: "matched",
        version_status: "current",
        content_version: CURRENT_VERSION,
        catalog_fingerprint: "fingerprint",
        query: "research",
        results: [
          {
            kind: "guide",
            id: "research",
            title: "Research",
            summary: "Run source-backed legal research.",
            href: "/guide#research",
            required_capabilities: [],
          },
        ],
        permission: null,
        suggested_queries: [],
      });

    render(<ProductGuideSearch contentVersion={CURRENT_VERSION} />);
    await user.type(screen.getByRole("searchbox"), "xylophone nebula");
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByTestId("product-guide-no-match")).toHaveTextContent(
      "does not have approved guidance",
    );

    await user.click(screen.getByRole("button", { name: "research" }));
    await waitFor(() => expect(searchProductGuideMock).toHaveBeenLastCalledWith("research", expect.any(Object)));
    expect(await screen.findByRole("link", { name: /Research/ })).toHaveAttribute(
      "href",
      "/guide#research",
    );
  });

  it("requires a meaningful query and gives signed-out users a sign-in path", async () => {
    const user = userEvent.setup();
    searchProductGuideMock.mockRejectedValue(
      new ApiError(401, "Authentication is required.", null),
    );

    render(<ProductGuideSearch contentVersion={CURRENT_VERSION} />);
    await user.type(screen.getByRole("searchbox"), "a");
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(screen.getByText("Enter at least two characters.")).toBeVisible();
    expect(searchProductGuideMock).not.toHaveBeenCalled();

    await user.clear(screen.getByRole("searchbox"));
    await user.type(screen.getByRole("searchbox"), "research");
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/sign-in",
    );
  });
});
