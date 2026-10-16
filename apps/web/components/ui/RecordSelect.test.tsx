import { createRef } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RecordSelect } from "@/components/ui/RecordSelect";

const caption = `Application number pending · ${"Long registry office ".repeat(20)}`.trim();
const choices = [{ value: "source-a", label: caption }, { value: "source-b", label: caption }];

function current(select: HTMLSelectElement, value: string) {
  expect(select).toHaveValue(value);
  expect(Array.from(select.selectedOptions, option => option.value)).toEqual([value]);
  const detail = document.getElementById(`${select.id}-selected-description`);
  expect(detail).toBeVisible();
  expect(detail).toHaveAttribute("data-selected-option-value", value);
  expect(detail?.textContent).toBe(select.selectedOptions[0].textContent);
  expect(detail).toHaveClass("min-w-0", "whitespace-normal", "break-all");
  expect(detail?.closest("label")).toBeNull();
}

describe("RecordSelect", () => {
  it("shows the verbatim current caption without adding it to the field name, even without overflow", () => {
    render(<RecordSelect id="record" label="Application" value="source-a" options={choices} />);
    const select = screen.getByRole<HTMLSelectElement>("combobox", { name: "Application" });
    expect(select.scrollWidth).toBe(select.clientWidth);
    expect(select).toHaveAccessibleName("Application");
    expect(select).toHaveAccessibleDescription(caption);
    expect(screen.getByLabelText("Application")).toBe(select);
    current(select, "source-a");
  });

  it("changes identity even when two current captions are identical", () => {
    const change = vi.fn();
    const { rerender } = render(<RecordSelect label="Application" value="source-a" options={choices} onChange={change} />);
    const select = screen.getByRole<HTMLSelectElement>("combobox", { name: "Application" });
    current(select, "source-a");
    rerender(<RecordSelect label="Application" value="source-b" options={choices} onChange={change} />);
    current(select, "source-b");
    expect(change).not.toHaveBeenCalled();
  });

  it.each(["", "missing-record"])("really deselects unmatched %s without a first-option fallback or change event", value => {
    const change = vi.fn();
    const { rerender } = render(<RecordSelect id="record" label="Application" value="source-a" options={choices} onChange={change} />);
    const select = screen.getByRole<HTMLSelectElement>("combobox", { name: "Application" });
    rerender(<RecordSelect id="record" label="Application" value={value} options={choices} onChange={change} />);
    expect(select.value).toBe("");
    expect(select.selectedIndex).toBe(-1);
    expect(Array.from(select.selectedOptions)).toEqual([]);
    expect(document.getElementById("record-selected-description")).toBeNull();
    expect(select).not.toHaveAttribute("aria-describedby");
    expect(Array.from(select.options, option => option.value)).toEqual(["source-a", "source-b"]);
    expect(change).not.toHaveBeenCalled();
  });

  it("preserves an explicit empty-link option and removes only its own description token on clear", () => {
    const options = [{ value: "", label: "No link" }, ...choices];
    const { rerender } = render(<><p id="hint">Existing help</p><RecordSelect id="record" label="Application"
      value="source-a" options={options} aria-describedby="hint record-selected-description" /></>);
    const select = screen.getByRole<HTMLSelectElement>("combobox", { name: "Application" });
    expect(select).toHaveAttribute("aria-describedby", "hint record-selected-description");
    rerender(<><p id="hint">Existing help</p><RecordSelect id="record" label="Application"
      value="" options={options} aria-describedby="hint record-selected-description" /></>);
    expect(select.value).toBe("");
    expect(Array.from(select.selectedOptions, option => option.value)).toEqual([""]);
    expect(select).toHaveAttribute("aria-describedby", "hint");
    expect(select).toHaveAccessibleDescription("Existing help");
    expect(document.getElementById("record-selected-description")).toBeNull();
  });

  it("removes a now-ineligible choice instead of describing or selecting another record", () => {
    const change = vi.fn();
    const { rerender } = render(<RecordSelect label="Application" value="source-a" options={choices} onChange={change} />);
    const select = screen.getByRole<HTMLSelectElement>("combobox", { name: "Application" });
    rerender(<RecordSelect label="Application" value="source-a" options={[choices[1]]} onChange={change} />);
    expect(select.value).toBe("");
    expect(select.selectedOptions.length).toBe(0);
    expect(Array.from(select.options, option => option.value)).toEqual(["source-b"]);
    expect(select).not.toHaveAttribute("aria-describedby");
    expect(change).not.toHaveBeenCalled();
  });

  it("keeps an explicitly supplied unavailable row disabled and truthfully described", () => {
    render(<RecordSelect label="Application" value="retained-id" disabled options={[
      { value: "retained-id", label: "Retained application · unavailable", disabled: true }, ...choices,
    ]} />);
    const select = screen.getByRole<HTMLSelectElement>("combobox", { name: "Application" });
    expect(select).toBeDisabled();
    expect(select.options[0]).toBeDisabled();
    current(select, "retained-id");
  });

  it("forwards the final field ID, ref and unchanged native events/props", () => {
    const ref = createRef<HTMLSelectElement>();
    const change = vi.fn();
    const blur = vi.fn();
    render(<RecordSelect id="field-final-id" ref={ref} label="Application" value="source-a" options={choices}
      onChange={change} onBlur={blur} name="application_id" required className="native-style" />);
    const select = screen.getByLabelText<HTMLSelectElement>("Application");
    expect(ref.current).toBe(select);
    expect(select).toHaveAttribute("id", "field-final-id");
    expect(select).toHaveAttribute("name", "application_id");
    expect(select).toBeRequired();
    expect(select).toHaveClass("native-style");
    fireEvent.change(select, { target: { value: "source-b" } });
    fireEvent.blur(select);
    expect(change).toHaveBeenCalledTimes(1);
    expect(blur).toHaveBeenCalledTimes(1);
  });

  it("looks up the full canonical discriminator, never the same-caption application or bare ID", () => {
    const options = [{ value: "application:same-id", label: "Same caption" }, { value: "proceeding:same-id", label: "Same caption" }];
    const { rerender } = render(<RecordSelect label="Legal record" value="proceeding:same-id" options={options} />);
    const select = screen.getByRole<HTMLSelectElement>("combobox", { name: "Legal record" });
    current(select, "proceeding:same-id");
    rerender(<RecordSelect label="Legal record" value="same-id" options={options} />);
    expect(select.value).toBe("");
    expect(select.selectedOptions.length).toBe(0);
    expect(select).not.toHaveAttribute("aria-describedby");
  });
});
