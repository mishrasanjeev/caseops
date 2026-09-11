import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

const index = vi.hoisted(() => vi.fn(() => <div>Specialist index surface</div>));
vi.mock("@/components/ip/SpecialistWorkspace", () => ({ SpecialistIndex: index }));

import Page from "./page";

it("routes the specialist workspace index to its canonical surface", () => {
  render(<Page />);
  expect(screen.getByText("Specialist index surface")).toBeVisible();
  expect(index).toHaveBeenCalledOnce();
});
