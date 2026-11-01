import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  Select,
  SelectContent,
  SelectEmpty,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";

// jsdom has no layout engine, so these tests pin the class and library
// contract that bounds the list. Real geometry (inside the viewport,
// scrollable, last option reachable) needs a Playwright journey.

const LONG_CODE = `CALDIAG-100DC57D-D4DA-48C3-9398-568E8A67F784-3-${"X".repeat(60)}`;
const OPTIONS = Array.from({ length: 120 }, (_, index) => ({
  value: `matter-${index}`,
  label:
    index === 87
      ? `${LONG_CODE} - Isolated Calendar diagnostic`
      : `Matter ${index} - Shivani Khullar & Anr. Vs Samir Bajpai & Ors`,
}));

function Picker({ onValueChange = () => {}, defaultValue }: {
  onValueChange?: (value: string) => void;
  defaultValue?: string;
}) {
  return (
    <Select defaultValue={defaultValue} onValueChange={onValueChange}>
      <SelectTrigger id="matter" aria-label="Matter">
        <SelectValue placeholder="Select Matter" />
      </SelectTrigger>
      <SelectContent>
        {OPTIONS.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function open() {
  const trigger = screen.getByRole("combobox", { name: "Matter" });
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false, pointerType: "mouse" });
  return screen.getByRole("listbox");
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Select", () => {
  it("binds the open list to the room Radix measured beside the trigger", () => {
    render(<Picker />);
    const listbox = open();

    // The variables we bind are the ones this Radix version publishes.
    expect(listbox.style.getPropertyValue("--radix-select-content-available-height")).toBe(
      "var(--radix-popper-available-height)",
    );
    expect(listbox.style.getPropertyValue("--radix-select-content-available-width")).toBe(
      "var(--radix-popper-available-width)",
    );
    expect(listbox.style.getPropertyValue("--radix-select-trigger-width")).toBe(
      "var(--radix-popper-anchor-width)",
    );

    expect(listbox).toHaveClass(
      "min-w-[var(--radix-select-trigger-width)]",
      "max-h-[min(var(--radix-select-content-available-height),22rem)]",
      "max-w-[min(var(--radix-select-content-available-width),32rem)]",
      "overflow-hidden",
    );
    // No escape hatches that paint over the page instead of scrolling.
    expect(listbox.className).not.toMatch(/overflow-visible|z-\[|max-h-none|max-w-none/);
    // The viewport is the scroller: Radix gives it flex:1 and overflow-y auto.
    const viewport = listbox.querySelector<HTMLElement>("[data-radix-select-viewport]");
    expect(viewport).not.toBeNull();
    expect(viewport!.style.overflow).toBe("hidden auto");
    expect(within(listbox).getAllByRole("option")).toHaveLength(OPTIONS.length);
  });

  it("wraps long and space-less option captions instead of widening the list", () => {
    render(<Picker />);
    const listbox = open();
    const longest = within(listbox).getByRole("option", { name: `${LONG_CODE} - Isolated Calendar diagnostic` });
    expect(longest).toHaveClass("whitespace-normal", "[overflow-wrap:anywhere]", "items-start", "min-w-0");
    expect(longest.className).not.toMatch(/truncate|whitespace-nowrap/);
    // The full caption stays readable in the list.
    expect(longest).toHaveTextContent(`${LONG_CODE} - Isolated Calendar diagnostic`);
  });

  it("keeps a long selected caption inside the trigger box", () => {
    const change = vi.fn();
    render(<Picker onValueChange={change} />);
    const listbox = open();
    fireEvent.click(within(listbox).getByRole("option", { name: `${LONG_CODE} - Isolated Calendar diagnostic` }));
    expect(change).toHaveBeenCalledWith("matter-87");

    const trigger = screen.getByRole("combobox", { name: "Matter" });
    expect(trigger).toHaveClass("h-10", "min-w-0", "[&>span]:min-w-0", "[&>span]:flex-1", "[&>span]:truncate");
    const value = trigger.querySelector(":scope > span");
    expect(value).toHaveTextContent(`${LONG_CODE} - Isolated Calendar diagnostic`);
    const chevron = trigger.querySelector(":scope > svg");
    expect(chevron).toHaveClass("shrink-0");
    expect(chevron).toHaveAttribute("aria-hidden", "true");
  });

  it("renders a scroll cue when the list overflows its bound", async () => {
    // Radix hides the native scrollbar; the scroll buttons are the only cue.
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(4000);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(352);
    render(<Picker />);
    const listbox = open();
    const viewport = listbox.querySelector("[data-radix-select-viewport]")!;
    await waitFor(() => {
      const next = viewport.nextElementSibling;
      expect(next).not.toBeNull();
      expect(next).toHaveAttribute("aria-hidden", "true");
      expect(next?.querySelector("svg")).not.toBeNull();
    });
  });

  it("offers an unavailable status row that cannot be chosen", () => {
    const change = vi.fn();
    render(
      <Select onValueChange={change}>
        <SelectTrigger aria-label="Matter">
          <SelectValue placeholder="Select Matter" />
        </SelectTrigger>
        <SelectContent>
          <SelectEmpty>No accessible Matter matches this search.</SelectEmpty>
        </SelectContent>
      </Select>,
    );
    const listbox = open();
    const row = within(listbox).getByRole("option", { name: "No accessible Matter matches this search." });
    expect(row).toHaveAttribute("aria-disabled", "true");
    expect(row).toHaveAttribute("aria-selected", "false");
    expect(row).not.toHaveAttribute("data-value");
    fireEvent.click(row);
    fireEvent.keyDown(listbox, { key: "Enter" });
    expect(change).not.toHaveBeenCalled();
  });
});
