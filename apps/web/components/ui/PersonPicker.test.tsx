import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listCompanyUsersMock } = vi.hoisted(() => ({ listCompanyUsersMock: vi.fn() }));

vi.mock("@/lib/api/endpoints", () => ({ listCompanyUsers: listCompanyUsersMock }));

import { PersonChecklist, PersonName, PersonPicker } from "@/components/ui/PersonPicker";

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

function selectedDescription(select: HTMLElement, value: string, caption: string) {
  expect(select).toHaveAttribute("aria-describedby", `${select.id}-selected-description`);
  const detail = document.getElementById(`${select.id}-selected-description`);
  expect(detail?.tagName).toBe("P");
  expect(detail).toBeVisible();
  expect(detail).toHaveTextContent(caption);
  expect(detail?.textContent).toBe(caption);
  expect(detail).toHaveAttribute("data-selected-option-value", value);
  expect(detail).toHaveClass("min-w-0", "whitespace-normal", "break-all");
  expect(detail?.className).not.toMatch(/truncate|line-clamp|overflow-hidden|sr-only/);
  return detail;
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

  it("shows the complete long selected identity in a linked wrapping description", async () => {
    const name = `Colleague ${"LongName".repeat(20)}`;
    const email = `${"longidentity".repeat(12)}@example.com`;
    listCompanyUsersMock.mockResolvedValue(directory([person("m-long", name, { email })]));
    render(withClient(<PersonPicker id="long-person" value="m-long" onChange={() => {}} />));

    const select = await screen.findByRole("combobox");
    await within(select).findByRole("option", { name: `${name} — ${email}` });
    selectedDescription(select, "m-long", `${name} — ${email}`);
    expect(select).toHaveValue("m-long");
  });

  it("updates the linked identity on change and removes both description and link on clear", async () => {
    function ControlledPicker() {
      const [value, setValue] = useState("m-1");
      return <PersonPicker id="changing-person" value={value} onChange={setValue} />;
    }
    render(withClient(<ControlledPicker />));
    const select = await screen.findByRole("combobox");
    await within(select).findByRole("option", { name: /Priya Raghavan/ });
    selectedDescription(select, "m-1", "Priya Raghavan — m-1@example.com");

    fireEvent.change(select, { target: { value: "m-2" } });
    selectedDescription(select, "m-2", "Anand Rao — m-2@example.com");
    fireEvent.change(select, { target: { value: "" } });
    expect(select).toHaveValue("");
    expect(select).not.toHaveAttribute("aria-describedby");
    expect(document.getElementById("changing-person-selected-description")).toBeNull();
  });

  it("binds identical selected captions to their actual membership rather than their text", async () => {
    listCompanyUsersMock.mockResolvedValue(directory([
      person("m-one", "Same Person", { email: "same@example.com" }),
      person("m-two", "Same Person", { email: "same@example.com" }),
    ]));
    function ControlledPicker() {
      const [value, setValue] = useState("m-one");
      return <PersonPicker id="same-caption" value={value} onChange={setValue} />;
    }
    render(withClient(<ControlledPicker />));
    const select = await screen.findByRole("combobox");
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(3));
    selectedDescription(select, "m-one", "Same Person — same@example.com");
    fireEvent.change(select, { target: { value: "m-two" } });
    selectedDescription(select, "m-two", "Same Person — same@example.com");
    expect(select).toHaveValue("m-two");
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
    selectedDescription(select, "m-historical", historical.textContent ?? "");

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
    selectedDescription(select, "m-missing", historical.textContent ?? "");
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

  it("offers only the server's eligible memberships and names an empty list", async () => {
    const { rerender } = render(
      withClient(
        <PersonPicker id="p" value="" onChange={() => {}} onlyMembershipIds={["m-2"]} emptyText="Nobody else can review." />,
      ),
    );
    const select = await screen.findByRole("combobox");
    await waitFor(() => expect(within(select).getByRole("option", { name: /Anand Rao/ })).toBeInTheDocument());
    expect(within(select).queryByRole("option", { name: /Priya Raghavan/ })).toBeNull();
    expect(screen.queryByText("Nobody else can review.")).toBeNull();

    rerender(
      withClient(
        <PersonPicker id="p" value="" onChange={() => {}} onlyMembershipIds={[]} emptyText="Nobody else can review." />,
      ),
    );
    expect(await screen.findByText("Nobody else can review.")).toBeVisible();
    const empty = await screen.findByRole("combobox");
    expect(within(empty).getAllByRole("option").map((option) => (option as HTMLOptionElement).value)).toEqual([""]);
  });

  it("wires a caller's field error to the select and keeps the identity caption", async () => {
    render(
      withClient(
        <>
          <PersonPicker id="p" value="m-1" onChange={() => {}} errorId="p-error" />
          <p id="p-error">Choose a qualified reviewer.</p>
        </>,
      ),
    );
    const select = await screen.findByRole("combobox");
    await waitFor(() => expect(select).toHaveAttribute("aria-describedby", "p-error p-selected-description"));
    expect(select).toHaveAttribute("aria-invalid", "true");
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
    expect(select).not.toHaveAttribute("aria-describedby");
    expect(document.getElementById("p-selected-description")).toBeNull();
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
    selectedDescription(select, "m-3", "Person 3 — m-3@example.com");
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

  it("explains itself when the staff list cannot be loaded and offers a retry", async () => {
    listCompanyUsersMock.mockRejectedValueOnce(new Error("network"));

    render(withClient(<PersonPicker id="p" value="" onChange={() => {}} />));

    expect(await screen.findByText(/staff list could not be loaded/)).toBeVisible();
    expect(screen.getByRole("combobox")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.queryByText(/staff list could not be loaded/)).toBeNull());
    expect(screen.getByRole("combobox")).toBeEnabled();
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

describe("PersonChecklist", () => {
  beforeEach(() => {
    listCompanyUsersMock.mockReset();
    listCompanyUsersMock.mockResolvedValue(
      directory([
        person("m-2", "Anand Rao"),
        person("m-1", "Priya Raghavan"),
        person("m-3", "Former Clerk", { membership_active: false }),
      ]),
    );
  });

  it("lists active colleagues by name and email and reports membership ids upward", async () => {
    function Harness() {
      const [value, setValue] = useState<string[]>([]);
      return (
        <>
          <PersonChecklist id="attendees" legend="Attending colleagues" value={value} onChange={setValue} />
          <output data-testid="chosen">{value.join(",")}</output>
        </>
      );
    }
    render(withClient(<Harness />));
    const anand = await screen.findByRole("checkbox", { name: "Anand Rao — m-2@example.com" });
    expect(screen.getByRole("checkbox", { name: "Priya Raghavan — m-1@example.com" })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /Former Clerk/ })).toBeNull();
    expect(screen.getByRole("group", { name: "Attending colleagues" })).toBeInTheDocument();
    fireEvent.click(anand);
    expect(screen.getByTestId("chosen")).toHaveTextContent("m-2");
    fireEvent.click(anand);
    expect(screen.getByTestId("chosen")).toHaveTextContent("");
  });

  it("offers a retry when the staff list cannot be loaded", async () => {
    listCompanyUsersMock.mockRejectedValueOnce(new Error("offline"));
    render(withClient(<PersonChecklist id="attendees" legend="Attending colleagues" value={[]} onChange={() => {}} />));
    const retry = await screen.findByRole("button", { name: "Try again" });
    fireEvent.click(retry);
    expect(await screen.findByRole("checkbox", { name: "Anand Rao — m-2@example.com" })).toBeInTheDocument();
  });
});
