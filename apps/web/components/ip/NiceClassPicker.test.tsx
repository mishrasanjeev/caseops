import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchIpNiceClassesMock } = vi.hoisted(() => ({ fetchIpNiceClassesMock: vi.fn() }));

vi.mock("@/lib/api/endpoints", () => ({ fetchIpNiceClasses: fetchIpNiceClassesMock }));

import { NiceClassPicker, searchNiceClasses } from "@/components/ip/NiceClassPicker";
import { ApiError } from "@/lib/api/config";
import { ipNiceClassCatalogue, type IpNiceClassCatalogue } from "@/lib/api/schemas";

// Official NCL 13-2026 text for the classes the assertions name; the rest only
// need to exist so the list has the full 45 the API contract guarantees.
const OFFICIAL: Record<number, { heading: string; note: string }> = {
  9: {
    heading:
      "Scientific, research, navigation, surveying, photographic, cinematographic, audiovisual, optical, weighing, measuring, signalling, detecting, testing, inspecting, life-saving and teaching apparatus and instruments; apparatus and instruments for recording, transmitting, reproducing or processing sound, images or data; recorded and downloadable multimedia files, computer software.",
    note: "Class 9 includes mainly apparatus and instruments for scientific or research purposes, audiovisual and information technology equipment, as well as safety and life-saving equipment.",
  },
  35: {
    heading: "Advertising; business management, organization and administration; office functions.",
    note: "Class 35 includes mainly services involving business management, operation, organization and administration of a commercial or industrial enterprise, as well as advertising, marketing and promotional services.",
  },
  41: {
    heading: "Education; providing of training; entertainment; sporting and cultural activities.",
    note: "Class 41 includes mainly services consisting of all forms of education or training.",
  },
  45: {
    heading:
      "Legal services; security services for the physical protection of tangible property and individuals; dating services, online social networking services; funerary services; babysitting.",
    note: "Class 45 includes mainly legal and security services, as well as certain personal and social services rendered by others to meet the needs of individuals.",
  },
};

function catalogue(): IpNiceClassCatalogue {
  return {
    edition: "NCL 13-2026",
    in_force_from: "2026-01-01",
    source_url: "https://nclpub.wipo.int/enfr/?version=20260101",
    source_data_url: "https://www.wipo.int/classifications/data/nice/20260101.zip",
    retrieved_on: "2026-10-31",
    headings_sha256: "a".repeat(64),
    attribution:
      "Nice Classification, 13th edition, version 2026 (NCL 13-2026). Copyright World Intellectual Property Organization (WIPO).",
    classes: Array.from({ length: 45 }, (_, index) => {
      const number = index + 1;
      return {
        number,
        kind: number <= 34 ? ("goods" as const) : ("services" as const),
        heading: OFFICIAL[number]?.heading ?? `Fixture heading for class ${number}.`,
        note: OFFICIAL[number]?.note ?? `Class ${number} includes mainly fixture items.`,
      };
    }),
  };
}

function withClient(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function Single({ initial = null, onChange }: { initial?: number | null; onChange?: (value: number) => void }) {
  const [value, setValue] = useState<number | null>(initial);
  return (
    <NiceClassPicker
      id="tm-class"
      label="Nice class"
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange?.(next);
      }}
    />
  );
}

function Multiple({ onChange, unavailable }: { onChange?: (value: number[]) => void; unavailable?: number[] }) {
  const [value, setValue] = useState<number[]>([]);
  return (
    <NiceClassPicker
      id="madrid-classes"
      label="Nice classes"
      mode="multiple"
      value={value}
      unavailable={unavailable}
      onChange={(next) => {
        setValue(next);
        onChange?.(next);
      }}
    />
  );
}

async function ready(name = "Nice class") {
  const input = screen.getByRole("combobox", { name });
  await waitFor(() => expect(input).toBeEnabled());
  return input;
}

function options() {
  return within(screen.getByRole("listbox")).getAllByRole("option");
}

describe("NiceClassPicker", () => {
  beforeEach(() => {
    fetchIpNiceClassesMock.mockReset();
    fetchIpNiceClassesMock.mockResolvedValue(catalogue());
  });

  it("offers all 45 catalogue classes, each named by number, kind and heading", async () => {
    render(withClient(<Single />));
    const input = await ready();

    fireEvent.click(screen.getByRole("button", { name: "Show Nice classes" }));

    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(input).toHaveAttribute("aria-controls", "tm-class-listbox");
    expect(screen.getByRole("listbox", { name: "Nice class" })).toBeVisible();
    const rows = options();
    expect(rows).toHaveLength(45);
    expect(rows[0]).toHaveAccessibleName("Class 1, goods: Fixture heading for class 1.");
    expect(rows[34]).toHaveAccessibleName(
      "Class 35, services: Advertising; business management, organization and administration; office functions.",
    );
    expect(rows[34]).toHaveTextContent(/^Class 35Services/);
    expect(screen.getByText(/Copyright World Intellectual Property Organization/)).toBeVisible();
    expect(screen.getByRole("link", { name: "WIPO source" })).toHaveAttribute(
      "href",
      "https://nclpub.wipo.int/enfr/?version=20260101",
    );
    expect(fetchIpNiceClassesMock).toHaveBeenCalledTimes(1);
  });

  it("finds class 35 by typing 'advertising' and class 45 by its number", async () => {
    const user = userEvent.setup();
    render(withClient(<Single />));
    const input = await ready();

    await user.type(input, "advertising");
    let rows = options();
    expect(rows[0]).toHaveAttribute("id", "tm-class-option-35");
    expect(rows.map((row) => row.id)).not.toContain("tm-class-option-9");

    await user.clear(input);
    await user.type(input, "Class 45");
    rows = options();
    expect(rows.map((row) => row.id)).toEqual(["tm-class-option-45"]);
  });

  it("matches words from the explanatory note and shows the note that matched", async () => {
    const user = userEvent.setup();
    render(withClient(<Single />));
    const input = await ready();

    await user.type(input, "information technology");

    const rows = options();
    expect(rows.map((row) => row.id)).toEqual(["tm-class-option-9"]);
    expect(within(rows[0]).getByText(/audiovisual and information technology equipment/)).toBeVisible();
  });

  it("selects with the keyboard and keeps the chosen class visible with its heading", async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    render(withClient(<Single onChange={changed} />));
    const input = await ready();

    await user.type(input, "3");
    expect(input).toHaveAttribute("aria-activedescendant", "tm-class-option-3");
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(input).toHaveAttribute("aria-activedescendant", "tm-class-option-31");
    await user.keyboard("{ArrowUp}");
    expect(input).toHaveAttribute("aria-activedescendant", "tm-class-option-30");
    await user.clear(input);
    await user.type(input, "35");
    await user.keyboard("{Enter}");

    expect(changed).toHaveBeenCalledWith(35);
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(input).toHaveValue("");
    const caption =
      "Class 35 — Advertising; business management, organization and administration; office functions.";
    expect(input).toHaveAccessibleDescription(caption);
    expect(document.getElementById("tm-class-selected-description")).toHaveTextContent(caption);
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("shows a stored selection with its heading before the list is opened", async () => {
    render(withClient(<Single initial={45} />));
    const input = await ready();

    expect(input).toHaveAccessibleDescription(
      "Class 45 — Legal services; security services for the physical protection of tangible property and individuals; dating services, online social networking services; funerary services; babysitting.",
    );
  });

  it("never lets Enter in the search box submit the surrounding form", async () => {
    const user = userEvent.setup();
    const submit = vi.fn((event: { preventDefault: () => void }) => event.preventDefault());
    render(
      withClient(
        <form onSubmit={submit}>
          <Single />
        </form>,
      ),
    );
    const input = await ready();

    await user.type(input, "zzzz{Enter}");

    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByText(/Search by class number \(1 to 45\)/)).toBeVisible();
    expect(screen.getByText(/No Nice class matches/, { selector: "p.sr-only" })).toBeInTheDocument();
    expect(screen.queryAllByRole("option")).toHaveLength(0);
  });

  it("closes on Escape without changing the selection", async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    render(withClient(<Single onChange={changed} />));
    const input = await ready();

    await user.type(input, "35");
    await user.keyboard("{Escape}");

    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(changed).not.toHaveBeenCalled();
  });

  it("chooses several classes in multiple mode and removes one", async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    render(withClient(<Multiple onChange={changed} />));
    const input = await ready("Nice classes");

    await user.type(input, "35");
    await user.keyboard("{Enter}");
    await user.clear(input);
    await user.type(input, "9");
    await user.click(screen.getByRole("option", { name: /^Class 9, goods:/ }));

    expect(changed).toHaveBeenLastCalledWith([35, 9]);
    expect(screen.getByRole("listbox")).toHaveAttribute("aria-multiselectable", "true");
    const chosen = screen.getByRole("list", { name: "Nice classes: selected" });
    expect(within(chosen).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Class 35 — Advertising; business management, organization and administration; office functions.",
      expect.stringMatching(/^Class 9 — Scientific, research/),
    ]);

    await user.click(screen.getByRole("button", { name: "Remove class 35" }));
    expect(changed).toHaveBeenLastCalledWith([9]);
  });

  it("does not let a class listed elsewhere be chosen again", async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    render(withClient(<Multiple onChange={changed} unavailable={[9]} />));
    const input = await ready("Nice classes");

    await user.type(input, "9");
    const blocked = screen.getByRole("option", { name: /^Class 9, goods: .*Already listed in another row\.$/ });
    expect(blocked).toHaveAttribute("aria-disabled", "true");
    expect(input).not.toHaveAttribute("aria-activedescendant");
    await user.click(blocked);
    await user.keyboard("{Enter}");

    expect(changed).not.toHaveBeenCalled();
  });

  it("is disabled while the catalogue loads", async () => {
    fetchIpNiceClassesMock.mockReturnValue(new Promise(() => undefined));
    render(withClient(<Single />));

    const input = screen.getByRole("combobox", { name: "Nice class" });
    expect(input).toBeDisabled();
    expect(input).toHaveAttribute("placeholder", "Loading Nice classes…");
    expect(screen.getByText("Loading the WIPO Nice class list…")).toBeVisible();
    expect(screen.getByRole("button", { name: "Show Nice classes" })).toBeDisabled();
  });

  it("explains a failed catalogue load, stays disabled and recovers on retry", async () => {
    fetchIpNiceClassesMock
      .mockRejectedValueOnce(new ApiError(503, "Database capacity is temporarily unavailable.", null))
      .mockResolvedValueOnce(catalogue());
    render(withClient(<Single />));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "The Nice class list could not be loaded, so a class cannot be chosen yet. Database capacity is temporarily unavailable.",
    );
    const input = screen.getByRole("combobox", { name: "Nice class" });
    expect(input).toBeDisabled();
    expect(input).toHaveAttribute("placeholder", "Nice classes unavailable");

    fireEvent.click(within(alert).getByRole("button", { name: "Try again" }));

    await waitFor(() => expect(input).toBeEnabled());
    expect(screen.queryByRole("alert")).toBeNull();
    expect(fetchIpNiceClassesMock).toHaveBeenCalledTimes(2);
  });

  it("anchors a caller's validation message to the field", async () => {
    render(
      withClient(
        <>
          <NiceClassPicker id="row-1" label="Nice class" value={null} onChange={() => undefined} invalid errorId="row-1-error" />
          <p id="row-1-error">Class row 1: choose a Nice class between 1 and 45.</p>
        </>,
      ),
    );
    const input = await ready();

    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Class row 1: choose a Nice class between 1 and 45.");
  });
});

describe("Nice class catalogue contract", () => {
  it("refuses a partial or out-of-order catalogue", () => {
    const full = catalogue();
    expect(ipNiceClassCatalogue.safeParse(full).success).toBe(true);
    expect(ipNiceClassCatalogue.safeParse({ ...full, classes: full.classes.slice(1) }).success).toBe(false);
    const swapped = [...full.classes];
    [swapped[0], swapped[1]] = [swapped[1], swapped[0]];
    expect(ipNiceClassCatalogue.safeParse({ ...full, classes: swapped }).success).toBe(false);
  });

  it("searches numbers by prefix and text by every word", () => {
    const rows = catalogue().classes;
    expect(searchNiceClasses(rows, "4").map((row) => row.number)).toEqual([4, 40, 41, 42, 43, 44, 45]);
    expect(searchNiceClasses(rows, "cl. 09").map((row) => row.number)).toEqual([9]);
    expect(searchNiceClasses(rows, "legal security").map((row) => row.number)).toEqual([45]);
    expect(searchNiceClasses(rows, "")).toHaveLength(45);
    expect(searchNiceClasses(rows, "0")).toEqual([]);
  });
});
