import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NextHearingCell } from "./NextHearingCell";

describe("Next Hearing missing identity", () => {
  for (const case_number of ["OA/672/2025", "FA/753/2024", "FA/660/2024"]) {
    it(`shows the missing court for ${case_number} without inventing a date`, () => {
      render(<NextHearingCell matter={{ id: "reported", case_number, status: "active" }} date="No date" />);
      expect(screen.getByText("No date")).toBeVisible();
      expect(screen.getByRole("link", { name: "Add court details for hearing sync" })).toHaveAttribute("href", "/app/matters/reported");
    });
  }
  it("retains an existing date while explaining missing identity", () => {
    render(<NextHearingCell matter={{ id: "matter", status: "active" }} date="21 Sep 2026" />);
    expect(screen.getByText("21 Sep 2026")).toBeVisible();
  });
  it("does not ask a terminal Matter to restart synchronization", () => {
    render(<NextHearingCell matter={{ id: "matter", status: "disposed" }} date="No date" />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
  it("treats a CNR as the primary identity", () => {
    render(<NextHearingCell matter={{ id: "matter", cnr_number: "DLHC010091232026", status: "active" }} date="21 Sep 2026" />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
  it("requires a malformed CNR to be corrected", () => {
    render(<NextHearingCell matter={{ id: "matter", cnr_number: "UNKNOWN", status: "active" }} date="No date" />);
    expect(screen.getByRole("link", { name: "Correct CNR for hearing sync" })).toBeVisible();
  });
  it("requires a year on a non-CNR public number", () => {
    render(<NextHearingCell matter={{ id: "matter", court_name: "Delhi High Court", case_number: "9123", status: "active" }} date="No date" />);
    expect(screen.getByRole("link", { name: "Add a case or filing number with year for hearing sync" })).toBeVisible();
  });
});
