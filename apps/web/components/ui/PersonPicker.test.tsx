import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listCompanyUsersMock } = vi.hoisted(() => ({ listCompanyUsersMock: vi.fn() }));

vi.mock("@/lib/api/endpoints", () => ({ listCompanyUsers: listCompanyUsersMock }));

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
    role: "member",
    membership_active: true,
    user_id: `user-${id}`,
    user_active: true,
    created_at: "2026-08-16T00:00:00Z",
    ...extra,
  };
}

function directory(users: ReturnType<typeof person>[]) {
  return { company_id: "company-1", company_slug: "firm", users };
}

describe("PersonPicker", () => {
  beforeEach(() => {
    listCompanyUsersMock.mockReset();
    listCompanyUsersMock.mockResolvedValue(
      directory([person("m-2", "Anand Rao"), person("m-1", "Priya Raghavan")]),
    );
  });

  it("uses the ordinary tenant directory and identifies every option by email", async () => {
    listCompanyUsersMock.mockResolvedValue(
      directory([
        person("m-2", "Priya Raghavan", { email: "priya.two@example.com" }),
        person("m-1", "Priya Raghavan", { email: "priya.one@example.com" }),
        person("m-3", "Anand Rao", { email: "anand@example.com" }),
      ]),
    );

    render(withClient(<PersonPicker id="p" value="" onChange={() => {}} />));

    const select = await screen.findByRole("combobox");
    await waitFor(() => expect(listCompanyUsersMock).toHaveBeenCalledOnce());
    expect(
      within(select).getByRole("option", {
        name: "Priya Raghavan — priya.one@example.com",
      }),
    ).toBeInTheDocument();
    expect(
      within(select).getByRole("option", {
        name: "Priya Raghavan — priya.two@example.com",
      }),
    ).toBeInTheDocument();
    const names = within(select)
      .getAllByRole("option")
      .map((option) => option.textContent)
      .slice(1);
    expect(names).toEqual([
      "Anand Rao — anand@example.com",
      "Priya Raghavan — priya.one@example.com",
      "Priya Raghavan — priya.two@example.com",
    ]);
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

  it("offers only memberships whose membership and user are both active", async () => {
    listCompanyUsersMock.mockResolvedValue(
      directory([
        person("m-active", "Active Person"),
        person("m-membership-off", "Inactive Membership", { membership_active: false }),
        person("m-user-off", "Inactive User", { user_active: false }),
      ]),
    );

    render(withClient(<PersonPicker id="p" value="" onChange={() => {}} />));

    const select = await screen.findByRole("combobox");
    await waitFor(() =>
      expect(within(select).getByRole("option", { name: /Active Person/ })).toBeInTheDocument(),
    );
    expect(within(select).queryByRole("option", { name: /Inactive Membership/ })).toBeNull();
    expect(within(select).queryByRole("option", { name: /Inactive User/ })).toBeNull();
  });

  it("preserves an inactive historical manager until the user explicitly replaces it", async () => {
    const onChange = vi.fn();
    listCompanyUsersMock.mockResolvedValue(
      directory([
        person("m-active", "Active Manager"),
        person("m-historical", "Former Manager", {
          email: "former.manager@example.com",
          membership_active: false,
          user_active: false,
        }),
      ]),
    );

    render(withClient(<PersonPicker id="edit-employee-manager" value="m-historical" onChange={onChange} />));

    const select = await screen.findByRole("combobox");
    const historical = await within(select).findByRole("option", {
      name: /Former Manager — former\.manager@example\.com — current; unavailable for new assignments/,
    });
    expect(historical).toBeDisabled();
    expect(select).toHaveValue("m-historical");
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.change(select, { target: { value: "m-active" } });
    expect(onChange).toHaveBeenCalledWith("m-active");
  });

  it("preserves a stale directory miss without silently clearing it", async () => {
    const onChange = vi.fn();
    listCompanyUsersMock.mockResolvedValue(directory([person("m-active", "Active Manager")]));

    render(withClient(<PersonPicker id="edit-employee-manager" value="m-missing" onChange={onChange} />));

    const select = await screen.findByRole("combobox");
    const historical = await within(select).findByRole("option", {
      name: /Current selection m-missing — unavailable for new assignments/,
    });
    expect(historical).toBeDisabled();
    expect(select).toHaveValue("m-missing");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("omits a person who cannot be a valid answer", async () => {
    render(
      withClient(<PersonPicker id="p" value="" onChange={() => {}} excludeMembershipIds={["m-1"]} />),
    );

    const select = await screen.findByRole("combobox");
    await waitFor(() =>
      expect(within(select).getByRole("option", { name: /Anand Rao/ })).toBeInTheDocument(),
    );
    expect(within(select).queryByRole("option", { name: /Priya Raghavan/ })).toBeNull();
  });

  it("clears an explicitly excluded selection without reinserting it", async () => {
    const onChange = vi.fn();
    render(
      withClient(
        <PersonPicker
          id="p"
          value="m-1"
          onChange={onChange}
          excludeMembershipIds={["m-1"]}
        />,
      ),
    );

    const select = await screen.findByRole("combobox");
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(""));
    expect(select).toHaveValue("");
    expect(within(select).queryByRole("option", { name: /Priya Raghavan/ })).toBeNull();
  });

  it("keeps a valid chosen person visible when only the text filter hides them", async () => {
    listCompanyUsersMock.mockResolvedValue(
      directory(Array.from({ length: 12 }, (_, index) => person(`m-${index}`, `Person ${index}`))),
    );

    render(withClient(<PersonPicker id="p" value="m-3" onChange={() => {}} />));

    const filter = await screen.findByLabelText("Filter colleagues by name");
    fireEvent.change(filter, { target: { value: "Person 9" } });

    const select = screen.getByRole("combobox");
    await waitFor(() =>
      expect(within(select).getByRole("option", { name: /Person 3/ })).toBeInTheDocument(),
    );
    expect(within(select).getByRole("option", { name: /Person 9/ })).toBeInTheDocument();
  });

  it("says plainly when a filter matches nobody", async () => {
    listCompanyUsersMock.mockResolvedValue(
      directory(Array.from({ length: 12 }, (_, index) => person(`m-${index}`, `Person ${index}`))),
    );

    render(withClient(<PersonPicker id="p" value="" onChange={() => {}} />));

    fireEvent.change(await screen.findByLabelText("Filter colleagues by name"), {
      target: { value: "Nobody" },
    });

    expect(await screen.findByText("No colleague matches that filter.")).toBeVisible();
  });

  it("explains itself when the staff list cannot be loaded", async () => {
    listCompanyUsersMock.mockRejectedValue(new Error("network"));

    render(withClient(<PersonPicker id="p" value="" onChange={() => {}} />));

    expect(await screen.findByText(/staff list could not be loaded/)).toBeVisible();
  });
});

describe("PersonName", () => {
  beforeEach(() => {
    listCompanyUsersMock.mockReset();
    listCompanyUsersMock.mockResolvedValue(
      directory([person("m-1", "Priya Raghavan", { membership_active: false, user_active: false })]),
    );
  });

  it("resolves an inactive historical tenant membership by name", async () => {
    render(withClient(<PersonName membershipId="m-1" />));

    expect(await screen.findByText("Priya Raghavan — m-1@example.com")).toBeVisible();
  });

  it("uses email to disambiguate duplicate names on read paths", async () => {
    listCompanyUsersMock.mockResolvedValue(
      directory([
        person("m-1", "Priya Raghavan", { email: "priya.one@example.com" }),
        person("m-2", "Priya Raghavan", { email: "priya.two@example.com" }),
      ]),
    );

    render(withClient(<PersonName membershipId="m-2" />));

    expect(await screen.findByText("Priya Raghavan — priya.two@example.com")).toBeVisible();
    expect(screen.queryByText("Priya Raghavan — priya.one@example.com")).toBeNull();
  });

  it("falls back to the identifier rather than showing nothing", async () => {
    render(withClient(<PersonName membershipId="m-unknown" />));

    expect(await screen.findByText("m-unknown")).toBeVisible();
  });

  it("says unassigned when there is no person at all", async () => {
    render(withClient(<PersonName membershipId={null} />));

    expect(await screen.findByText("Unassigned")).toBeVisible();
  });
});
