import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  assignEmployeeCustomRoleMock,
  createCustomRoleMock,
  deleteCustomRoleMock,
  listCapabilityCatalogMock,
  listCustomRolesMock,
  listEmployeesMock,
  toastErrorMock,
  toastSuccessMock,
  updateCustomRoleMock,
  useCapabilityMock,
  useRoleMock,
} = vi.hoisted(() => ({
  assignEmployeeCustomRoleMock: vi.fn(),
  createCustomRoleMock: vi.fn(),
  deleteCustomRoleMock: vi.fn(),
  listCapabilityCatalogMock: vi.fn(),
  listCustomRolesMock: vi.fn(),
  listEmployeesMock: vi.fn(),
  toastErrorMock: vi.fn(),
  toastSuccessMock: vi.fn(),
  updateCustomRoleMock: vi.fn(),
  useCapabilityMock: vi.fn(),
  useRoleMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  assignEmployeeCustomRole: assignEmployeeCustomRoleMock,
  createCustomRole: createCustomRoleMock,
  deleteCustomRole: deleteCustomRoleMock,
  listCapabilityCatalog: listCapabilityCatalogMock,
  listCustomRoles: listCustomRolesMock,
  listEmployees: listEmployeesMock,
  updateCustomRole: updateCustomRoleMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
  useRole: () => useRoleMock(),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccessMock, error: toastErrorMock },
}));

import RolesAdminPage from "@/app/app/admin/roles/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const capabilityRows = [
  {
    capability: "matters:create",
    group: "Matters",
    label: "create",
    owner_only: false,
  },
  {
    capability: "clients:view",
    group: "Clients",
    label: "view",
    owner_only: false,
  },
  {
    capability: "audit:export",
    group: "Audit",
    label: "export",
    owner_only: true,
  },
];

const role = {
  id: "role-1",
  company_id: "company-1",
  name: "Matter creator",
  slug: "matter-creator",
  description: "Can create matters",
  base_role: "viewer" as const,
  permissions: ["matters:create"],
  is_system: false,
  is_active: true,
  assigned_count: 1,
  created_by_membership_id: "owner-membership",
  updated_by_membership_id: "owner-membership",
  created_at: "2026-05-06T00:00:00Z",
  updated_at: "2026-05-06T00:00:00Z",
};

const employee = {
  company_id: "company-1",
  membership_id: "member-1",
  user_id: "user-1",
  email: "member@example.com",
  full_name: "Member One",
  role: "member" as const,
  custom_role_id: null,
  custom_role_name: null,
  membership_active: true,
  user_active: true,
  mobile: null,
  designation: null,
  department: "Litigation",
  employee_code: null,
  manager_membership_id: null,
  manager_name: null,
  joined_on: null,
  employment_status: "active" as const,
  last_login_at: null,
  setup_sent_at: null,
  setup_completed_at: "2026-05-06T00:00:00Z",
  password_reset_sent_at: null,
  force_password_change: false,
  created_at: "2026-05-06T00:00:00Z",
  updated_at: "2026-05-06T00:00:00Z",
};

describe("RolesAdminPage", () => {
  beforeEach(() => {
    assignEmployeeCustomRoleMock.mockReset();
    createCustomRoleMock.mockReset();
    deleteCustomRoleMock.mockReset();
    listCapabilityCatalogMock.mockReset();
    listCustomRolesMock.mockReset();
    listEmployeesMock.mockReset();
    toastErrorMock.mockReset();
    toastSuccessMock.mockReset();
    updateCustomRoleMock.mockReset();
    useCapabilityMock.mockReset();
    useRoleMock.mockReset();
    useCapabilityMock.mockImplementation(
      (capability: string) => capability === "company:manage_users",
    );
    useRoleMock.mockReturnValue("owner");
    listCapabilityCatalogMock.mockResolvedValue({ capabilities: capabilityRows });
    listCustomRolesMock.mockResolvedValue({ roles: [role] });
    listEmployeesMock.mockResolvedValue({
      employees: [
        employee,
        { ...employee, membership_id: "owner-member", email: "owner@example.com", role: "owner" },
      ],
    });
    createCustomRoleMock.mockResolvedValue({ ...role, id: "role-2", slug: "new-role" });
    updateCustomRoleMock.mockResolvedValue(role);
    deleteCustomRoleMock.mockResolvedValue({ ...role, is_active: false });
    assignEmployeeCustomRoleMock.mockResolvedValue({ ...employee, custom_role_id: "role-1" });
  });

  it("hides the page when caller lacks company user management", () => {
    useCapabilityMock.mockReturnValue(false);
    render(withClient(<RolesAdminPage />));
    expect(screen.getByText(/don't have access/i)).toBeInTheDocument();
    expect(listCapabilityCatalogMock).not.toHaveBeenCalled();
  });

  it("creates a custom role from grouped non-owner permissions", async () => {
    const user = userEvent.setup();
    render(withClient(<RolesAdminPage />));

    await screen.findByTestId("custom-role-matter-creator");
    expect(screen.getByTestId("capability-audit:export")).toBeDisabled();
    await user.click(screen.getByTestId("custom-role-new"));
    await user.type(screen.getByTestId("custom-role-name"), "Client reader");
    await user.click(screen.getByTestId("capability-clients:view"));
    await user.click(screen.getByTestId("custom-role-save"));

    await waitFor(() => expect(createCustomRoleMock).toHaveBeenCalled());
    expect(createCustomRoleMock).toHaveBeenCalledWith({
      name: "Client reader",
      description: null,
      baseRole: null,
      permissions: ["clients:view"],
    });
  });

  it("edits and revokes an existing custom role", async () => {
    const user = userEvent.setup();
    render(withClient(<RolesAdminPage />));

    await user.click(await screen.findByTestId("custom-role-matter-creator"));
    await user.clear(screen.getByTestId("custom-role-description"));
    await user.type(screen.getByTestId("custom-role-description"), "Updated");
    await user.click(screen.getByTestId("capability-clients:view"));
    await user.click(screen.getByTestId("custom-role-save"));

    await waitFor(() => expect(updateCustomRoleMock).toHaveBeenCalled());
    expect(updateCustomRoleMock).toHaveBeenCalledWith({
      roleId: "role-1",
      name: "Matter creator",
      description: "Updated",
      baseRole: "viewer",
      permissions: expect.arrayContaining(["matters:create", "clients:view"]),
    });

    await user.click(screen.getByTestId("custom-role-revoke"));
    await waitFor(() => expect(deleteCustomRoleMock).toHaveBeenCalledWith("role-1"));
  });

  it("assigns a custom role to a non-owner employee", async () => {
    const user = userEvent.setup();
    render(withClient(<RolesAdminPage />));

    await screen.findByTestId("custom-role-matter-creator");
    await user.selectOptions(screen.getByTestId("custom-role-employee"), "member-1");
    await user.selectOptions(screen.getByTestId("custom-role-assignment"), "role-1");
    await user.click(screen.getByTestId("custom-role-assign"));

    await waitFor(() => expect(assignEmployeeCustomRoleMock).toHaveBeenCalled());
    expect(assignEmployeeCustomRoleMock).toHaveBeenCalledWith({
      membershipId: "member-1",
      customRoleId: "role-1",
    });
    expect(screen.queryByText(/owner@example.com/)).not.toBeInTheDocument();
  });

  it("hides fixed-role reset for non-owner custom-role managers", async () => {
    useRoleMock.mockReturnValue("member");

    render(withClient(<RolesAdminPage />));

    await screen.findByTestId("custom-role-matter-creator");

    expect(
      screen.queryByRole("option", { name: "Use fixed role capabilities" }),
    ).not.toBeInTheDocument();
  });
});
