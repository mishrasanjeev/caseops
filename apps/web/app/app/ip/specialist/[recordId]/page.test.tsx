import { render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { act } from "react";
import { expect, it, vi } from "vitest";

const detail = vi.hoisted(() => vi.fn(({ recordId }: { recordId: string }) => <div>Specialist record: {recordId}</div>));
vi.mock("@/components/ip/SpecialistWorkspace", () => ({ SpecialistDetail: detail }));

import Page from "./page";

it("passes the routed specialist record identity to the detail surface", async () => {
  const params = Promise.resolve({ recordId: "record-123" });
  await act(async () => {
    render(<Suspense fallback={<p>Loading specialist record</p>}><Page params={params} /></Suspense>);
    await params;
  });
  expect(await screen.findByText("Specialist record: record-123")).toBeVisible();
  expect(detail).toHaveBeenCalledWith({ recordId: "record-123" }, undefined);
});
