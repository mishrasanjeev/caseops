import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listEmployeesMock } = vi.hoisted(() => ({ listEmployeesMock: vi.fn() }));

vi.mock("@/lib/api/endpoints", () => ({ listEmployees: listEmployeesMock }));

import { PersonName, PersonPicker } from "@/components/ui/PersonPicker";

function withClient(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function person(id: string, name: string, extra: Record<string, unknown> = {}) {
  return {
    membership_id: id,
    full_name: name,
    email: `${id}@example.com`,
    designation: "Associate",
    department: "IP",
    membership_active: true,
    user_active: true,
    employment_status: "active",
    ...extra,
  };
}

describe("PersonPicker", () => {
  beforeEach(() => {
    listEmployeesMock.mockReset();
    listEmployeesMock.mockResolvedValue({
      employees: [person("m-2", "Anand Rao"), person("m-1", "Priya Raghavan")],
      total: 2,
    });
  });

  it("offers colleagues by name, not by identifier", async () => {
    render(withClient(<PersonPicker id="p" value="" onChange={() => {}} />));

    const select = await screen.findByRole("combobox");
    await waitFor(() =>
      expect(within(select).getByRole("option", { name: /Priya Raghavan/ })).toBeInTheDocument(),
    );
    // The qualifier disambiguates two people with the same name.
    expect(within(select).getByRole("option", { name: "Priya Raghavan — Associate" })).toBeInTheDocument();
    // Sorted by name so the list is scannable rather than in API order.
    const names = within(select)
      .getAllByRole("option")
      .map((option) => option.textContent)
      .slice(1);
    expect(names).toEqual(["Anand Rao — Associate", "Priya Raghavan — Associate"]);
  });

  it("reports the membership id upward, so callers are unchanged", async () => {
    const onChange = vi.fn();
    render(withClient(<PersonPicker id="p" value="" onChange={onChange} />));

    const select = await screen.findByRole("combobox");
    await waitFor(() =>
      expect(within(select).getByRole("option", { name: /Anand Rao/ })).toBeInTheDocument(),
    );
    fireEvent.change(select, { target: { value: "m-2" } });

    expect(onChange).toHaveBeenCalledWith("m-2");
  });

  it("omits a person who cannot be a valid answer", async () => {
    render(
      withClient(<PersonPicker id="p" value="" onChange={() => {}} excludeMembershipIds={["m-1"]} />),
    );

    const select = await screen.findByRole("combobox");
    await waitFor(() =>
      expect(within(select).getByRole("option", { name: /Anand Rao/ })).toBeInTheDocument(),
    );
    // Offering to transfer work to its current holder is a dead end.
    expect(within(select).queryByRole("option", { name: /Priya Raghavan/ })).toBeNull();
  });

  it("keeps a chosen person visible even when the filter would hide them", async () => {
    listEmployeesMock.mockResolvedValue({
      employees: Array.from({ length: 12 }, (_, index) => person(`m-${index}`, `Person ${index}`)),
      total: 12,
    });

    render(withClient(<PersonPicker id="p" value="m-3" onChange={() => {}} />));

    const filter = await screen.findByLabelText("Filter colleagues by name");
    fireEvent.change(filter, { target: { value: "Person 9" } });

    const select = screen.getByRole("combobox");
    // Without this the control would look like it had lost the selection.
    await waitFor(() =>
      expect(within(select).getByRole("option", { name: /Person 3/ })).toBeInTheDocument(),
    );
    expect(within(select).getByRole("option", { name: /Person 9/ })).toBeInTheDocument();
  });

  it("says plainly when a filter matches nobody", async () => {
    listEmployeesMock.mockResolvedValue({
      employees: Array.from({ length: 12 }, (_, index) => person(`m-${index}`, `Person ${index}`)),
      total: 12,
    });

    render(withClient(<PersonPicker id="p" value="" onChange={() => {}} />));

    fireEvent.change(await screen.findByLabelText("Filter colleagues by name"), {
      target: { value: "Nobody" },
    });

    expect(await screen.findByText("No colleague matches that filter.")).toBeVisible();
  });

  it("explains itself when the staff list cannot be loaded", async () => {
    listEmployeesMock.mockRejectedValue(new Error("network"));

    render(withClient(<PersonPicker id="p" value="" onChange={() => {}} />));

    // Failing to a silent empty dropdown would read as "nobody works here".
    expect(
      await screen.findByText(/staff list could not be loaded/),
    ).toBeVisible();
  });
});

describe("PersonName", () => {
  beforeEach(() => {
    listEmployeesMock.mockReset();
    listEmployeesMock.mockResolvedValue({ employees: [person("m-1", "Priya Raghavan")], total: 1 });
  });

  it("renders a membership id as the person's name", async () => {
    render(withClient(<PersonName membershipId="m-1" />));

    expect(await screen.findByText("Priya Raghavan")).toBeVisible();
  });

  it("falls back to the identifier rather than showing nothing", async () => {
    render(withClient(<PersonName membershipId="m-unknown" />));

    // An unresolved reference is more honest than a blank where a name belongs.
    expect(await screen.findByText("m-unknown")).toBeVisible();
  });

  it("says unassigned when there is no person at all", async () => {
    render(withClient(<PersonName membershipId={null} />));

    expect(await screen.findByText("Unassigned")).toBeVisible();
  });
});
