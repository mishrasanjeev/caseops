import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
vi.mock("next/navigation", () => ({ useParams: () => ({ applicationId: "application-123" }) }));
vi.mock("@/components/ip/PatentApplicationWorkspace", () => ({
  PatentApplicationDetail: ({ applicationId }: { applicationId: string }) => <div>{applicationId}</div>,
}));
import Page from "./page";
it("opens the route's independent application rather than a family or trademark", () => {
  render(<Page />);
  expect(screen.getByText("application-123")).toBeVisible();
});
