import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { canMock, resolvedMock, roleMock } = vi.hoisted(() => ({
  canMock: vi.fn(),
  resolvedMock: vi.fn(),
  roleMock: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({
  can: (role: string | null, capability: string) => canMock(role, capability),
  useResolvedCapabilities: () => resolvedMock(),
  useRole: () => roleMock(),
}));

import { SidebarBody } from "@/components/app/Sidebar";

describe("SidebarBody resolved capability navigation", () => {
  beforeEach(() => {
    canMock.mockReset();
    resolvedMock.mockReset();
    roleMock.mockReset();
  });

  it("hides admin navigation when server-resolved capabilities restrict a fixed owner", () => {
    roleMock.mockReturnValue("owner");
    resolvedMock.mockReturnValue([]);
    canMock.mockReturnValue(true);

    render(<SidebarBody pathname="/app" />);

    expect(screen.queryByRole("link", { name: "Admin" })).not.toBeInTheDocument();
  });

  it("shows admin navigation when server-resolved capabilities allow a custom-role viewer", () => {
    roleMock.mockReturnValue("viewer");
    resolvedMock.mockReturnValue(["workspace:admin"]);
    canMock.mockReturnValue(false);

    render(<SidebarBody pathname="/app" />);

    expect(screen.getByRole("link", { name: "Admin" })).toHaveAttribute(
      "href",
      "/app/admin",
    );
    expect(screen.getByRole("link", { name: "Billing" })).toHaveAttribute(
      "href",
      "/app/admin/billing",
    );
    expect(screen.queryByRole("link", { name: "Platform admin" })).not.toBeInTheDocument();
  });

  it("shows platform admin navigation only when the server returns platform capability", () => {
    roleMock.mockReturnValue("owner");
    resolvedMock.mockReturnValue(["workspace:admin", "platform:admin"]);
    canMock.mockReturnValue(true);

    render(<SidebarBody pathname="/app/platform-admin" />);

    expect(screen.getByRole("link", { name: "Platform admin" })).toHaveAttribute(
      "href",
      "/app/platform-admin",
    );
  });

  it("shows case tracking when authority search is available", () => {
    roleMock.mockReturnValue("viewer");
    resolvedMock.mockReturnValue(["authorities:search"]);
    canMock.mockReturnValue(false);

    render(<SidebarBody pathname="/app/case-tracking" />);

    expect(screen.getByRole("link", { name: "Case tracking" })).toHaveAttribute(
      "href",
      "/app/case-tracking",
    );
  });
});
