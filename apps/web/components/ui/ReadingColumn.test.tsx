import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReadingColumn } from "./ReadingColumn";

describe("ReadingColumn", () => {
  it("is one centred column whose width is 70ch of the 16px body face", () => {
    render(<ReadingColumn data-testid="column">Body</ReadingColumn>);
    const classes = screen.getByTestId("column").className.split(/\s+/);
    // Centred in <main> with balanced margins, shrinking to the viewport.
    expect(classes).toEqual(expect.arrayContaining(["mx-auto", "w-full", "min-w-0"]));
    // The single cap: `ch` resolves against this element's own font size.
    expect(classes).toEqual(expect.arrayContaining(["max-w-[70ch]", "text-base"]));
    expect(classes.filter((name) => name.startsWith("max-w-"))).toEqual(["max-w-[70ch]"]);
  });

  it("keeps callers' layout classes and attributes", () => {
    render(<ReadingColumn className="flex flex-col gap-8" aria-label="Answer">Body</ReadingColumn>);
    const column = screen.getByLabelText("Answer");
    expect(column).toHaveClass("flex", "flex-col", "gap-8", "max-w-[70ch]");
  });
});
