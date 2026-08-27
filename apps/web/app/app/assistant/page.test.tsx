import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/assistant/WorkspaceAssistant", () => ({
  WorkspaceAssistant: () => (
    <div data-testid="workspace-assistant">Workspace assistant workflow</div>
  ),
}));

import WorkspaceAssistantPage, { metadata } from "@/app/app/assistant/page";

describe("WorkspaceAssistantPage", () => {
  it("mounts the assistant workflow with accurate page metadata", () => {
    render(<WorkspaceAssistantPage />);

    expect(screen.getByTestId("workspace-assistant")).toBeInTheDocument();
    expect(metadata.title).toBe("Ask this Workspace");
    expect(metadata.description).toMatch(/permission-scoped/i);
  });
});
