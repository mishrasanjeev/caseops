import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  cancelEmployeeImportMock,
  commitEmployeeOffboardingMock,
  commitEmployeeImportMock,
  createEmployeeMock,
  downloadEmployeeImportTemplateMock,
  listEmployeeAuditMock,
  listCompanyUsersMock,
  listEmployeesMock,
  previewEmployeeOffboardingMock,
  previewEmployeeImportMock,
  resendEmployeeSetupMock,
  resetEmployeePasswordMock,
  toastErrorMock,
  toastSuccessMock,
  updateEmployeeMock,
  useCapabilityMock,
  useRoleMock,
} = vi.hoisted(() => ({
  cancelEmployeeImportMock: vi.fn(),
  commitEmployeeOffboardingMock: vi.fn(),
  commitEmployeeImportMock: vi.fn(),
  createEmployeeMock: vi.fn(),
  downloadEmployeeImportTemplateMock: vi.fn(),
  listEmployeeAuditMock: vi.fn(),
  listCompanyUsersMock: vi.fn(),
  listEmployeesMock: vi.fn(),
  previewEmployeeOffboardingMock: vi.fn(),
  previewEmployeeImportMock: vi.fn(),
  resendEmployeeSetupMock: vi.fn(),
  resetEmployeePasswordMock: vi.fn(),
  toastErrorMock: vi.fn(),
  toastSuccessMock: vi.fn(),
  updateEmployeeMock: vi.fn(),
  useCapabilityMock: vi.fn(),
  useRoleMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  cancelEmployeeImport: cancelEmployeeImportMock,
  commitEmployeeOffboarding: commitEmployeeOffboardingMock,
  commitEmployeeImport: commitEmployeeImportMock,
  createEmployee: createEmployeeMock,
  downloadEmployeeImportTemplate: downloadEmployeeImportTemplateMock,
  listEmployeeAudit: listEmployeeAuditMock,
  listCompanyUsers: listCompanyUsersMock,
  listEmployees: listEmployeesMock,
  previewEmployeeOffboarding: previewEmployeeOffboardingMock,
  previewEmployeeImport: previewEmployeeImportMock,
  resendEmployeeSetup: resendEmployeeSetupMock,
  resetEmployeePassword: resetEmployeePasswordMock,
  updateEmployee: updateEmployeeMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
  useRole: () => useRoleMock(),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccessMock, error: toastErrorMock },
}));

import EmployeesAdminPage from "@/app/app/admin/employees/page";
import type {
  EmployeeImportJob,
  EmployeeOffboardingPreview,
  EmployeeRecord,
} from "@/lib/api/endpoints";

function employee(overrides: Partial<EmployeeRecord> = {}): EmployeeRecord {
  return {
    company_id: "c1",
    membership_id: "m1",
    user_id: "u1",
    email: "asha@example.com",
    full_name: "Asha Rao",
    role: "member",
    custom_role_id: null,
    custom_role_name: null,
    membership_active: true,
    user_active: true,
    mobile: "+91-9876543210",
    designation: "Associate",
    department: "Litigation",
    employee_code: "EMP-1",
    manager_membership_id: null,
    manager_name: null,
    joined_on: "2026-05-06",
    employment_status: "invited",
    last_login_at: null,
    setup_sent_at: "2026-05-06T00:00:00Z",
    setup_completed_at: null,
    password_reset_sent_at: null,
    force_password_change: true,
    created_at: "2026-05-06T00:00:00Z",
    updated_at: "2026-05-06T00:00:00Z",
    ...overrides,
  };
}

function importJob(overrides: Partial<EmployeeImportJob> = {}): EmployeeImportJob {
  return {
    id: "job-1",
    company_id: "c1",
    filename: "employees.csv",
    content_type: "text/csv",
    status: "previewed",
    total_rows: 2,
    valid_rows: 1,
    invalid_rows: 1,
    created_count: 0,
    failed_count: 0,
    error_message: null,
    created_at: "2026-05-06T00:00:00Z",
    updated_at: "2026-05-06T00:00:00Z",
    expires_at: "2026-05-07T00:00:00Z",
    committed_at: null,
    cancelled_at: null,
    rows: [
      {
        id: "row-1",
        row_number: 2,
        raw: { Name: "", Email: "bad@example.com", Role: "member" },
        normalized: {
          full_name: null,
          email: "bad@example.com",
          role: "member",
          department: null,
        },
        errors: ["Name is required."],
        status: "invalid",
        created_membership_id: null,
      },
      {
        id: "row-2",
        row_number: 3,
        raw: { Name: "Valid User", Email: "valid@example.com", Role: "member" },
        normalized: {
          full_name: "Valid User",
          email: "valid@example.com",
          role: "member",
          department: "Litigation",
        },
        errors: [],
        status: "valid",
        created_membership_id: null,
      },
    ],
    ...overrides,
  };
}

function offboardingPreview(
  overrides: Partial<EmployeeOffboardingPreview> = {},
): EmployeeOffboardingPreview {
  return {
    employee: employee(),
    reassign_to: employee({
      membership_id: "m2",
      user_id: "u2",
      email: "dev@example.com",
      full_name: "Dev Mehta",
      role: "admin",
      employment_status: "active",
      setup_completed_at: "2026-05-06T01:00:00Z",
      force_password_change: false,
    }),
    supported_objects: [
      {
        object_type: "matters",
        id: "matter-1",
        label: "LW8-001 - Offboarding Matter",
        relation: "assignee",
        supported: true,
        matter_id: "matter-1",
      },
      {
        object_type: "team_memberships",
        id: "team-member-1",
        label: "Disputes Team",
        relation: "team member",
        supported: true,
        matter_id: null,
      },
    ],
    unsupported_objects: [
      {
        object_type: "drafts",
        id: "draft-1",
        label: "LW8-001 - Draft submissions",
        relation: "creator",
        supported: false,
        matter_id: "matter-1",
      },
    ],
    supported_counts: {
      matters: 1,
      team_memberships: 1,
    },
    unsupported_counts: {
      drafts: 1,
    },
    blockers: [],
    can_commit: true,
    ...overrides,
  };
}

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("EmployeesAdminPage", () => {
  beforeEach(() => {
    cancelEmployeeImportMock.mockReset();
    commitEmployeeOffboardingMock.mockReset();
    commitEmployeeImportMock.mockReset();
    createEmployeeMock.mockReset();
    downloadEmployeeImportTemplateMock.mockReset();
    listEmployeeAuditMock.mockReset();
    listCompanyUsersMock.mockReset().mockResolvedValue({
      company_id: "c1",
      company_slug: "firm",
      users: [
        {
          membership_id: "m1",
          user_id: "u1",
          email: "asha@example.com",
          full_name: "Asha Rao",
          role: "member",
          membership_active: true,
          user_active: true,
          created_at: "2026-05-06T00:00:00Z",
        },
      ],
    });
    listEmployeesMock.mockReset();
    previewEmployeeOffboardingMock.mockReset();
    previewEmployeeImportMock.mockReset();
    resendEmployeeSetupMock.mockReset();
    resetEmployeePasswordMock.mockReset();
    toastErrorMock.mockReset();
    toastSuccessMock.mockReset();
    updateEmployeeMock.mockReset();
    useCapabilityMock.mockReset();
    useRoleMock.mockReset();
    useCapabilityMock.mockImplementation(
      (capability: string) => capability === "company:manage_users",
    );
    useRoleMock.mockReturnValue("owner");
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:caseops-template"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
    listEmployeesMock.mockResolvedValue({
      employees: [
        employee(),
        employee({
          membership_id: "m2",
          user_id: "u2",
          email: "dev@example.com",
          full_name: "Dev Mehta",
          role: "admin",
          department: "Finance",
          employment_status: "active",
          setup_completed_at: "2026-05-06T01:00:00Z",
          force_password_change: false,
        }),
      ],
    });
    createEmployeeMock.mockResolvedValue({
      employee: employee({ email: "new@example.com", full_name: "New User" }),
      setup: {
        delivered: false,
        delivery_error: "non-prod",
        expires_at: "2026-05-07T00:00:00Z",
        debug_token: "debug-token",
      },
    });
    downloadEmployeeImportTemplateMock.mockResolvedValue(
      new Blob(["Name,Email,Role\n"], { type: "text/csv" }),
    );
    previewEmployeeImportMock.mockResolvedValue(importJob());
    previewEmployeeOffboardingMock.mockResolvedValue(offboardingPreview());
    commitEmployeeOffboardingMock.mockResolvedValue({
      employee: employee({
        employment_status: "inactive",
        membership_active: false,
        user_active: false,
      }),
      reassigned_to: employee({
        membership_id: "m2",
        user_id: "u2",
        email: "dev@example.com",
        full_name: "Dev Mehta",
        role: "admin",
        employment_status: "active",
        setup_completed_at: "2026-05-06T01:00:00Z",
        force_password_change: false,
      }),
      preview: offboardingPreview(),
      deactivated: true,
      sessions_revoked: true,
    });
    listEmployeeAuditMock.mockResolvedValue({
      employee: employee(),
      events: [
        {
          id: "audit-1",
          action: "employee.created",
          actor_membership_id: "m-owner",
          actor_label: "Owner S8",
          target_type: "employee",
          target_id: "m1",
          result: "success",
          metadata: {},
          created_at: "2026-05-06T00:00:00Z",
        },
        {
          id: "audit-2",
          action: "employee.offboarding.committed",
          actor_membership_id: "m-owner",
          actor_label: "Owner S8",
          target_type: "employee",
          target_id: "m1",
          result: "success",
          metadata: {},
          created_at: "2026-05-06T01:00:00Z",
        },
      ],
    });
    cancelEmployeeImportMock.mockResolvedValue(
      importJob({ status: "cancelled", cancelled_at: "2026-05-06T00:05:00Z" }),
    );
    commitEmployeeImportMock.mockResolvedValue({
      job: importJob({
        status: "committed",
        valid_rows: 2,
        invalid_rows: 0,
        created_count: 2,
        committed_at: "2026-05-06T00:05:00Z",
        rows: [
          {
            id: "row-1",
            row_number: 2,
            raw: { Name: "Valid User", Email: "valid@example.com", Role: "member" },
            normalized: {
              full_name: "Valid User",
              email: "valid@example.com",
              role: "member",
              department: "Litigation",
            },
            errors: [],
            status: "created",
            created_membership_id: "m-valid",
          },
          {
            id: "row-2",
            row_number: 3,
            raw: { Name: "Second User", Email: "second@example.com", Role: "viewer" },
            normalized: {
              full_name: "Second User",
              email: "second@example.com",
              role: "viewer",
              department: "Finance",
            },
            errors: [],
            status: "created",
            created_membership_id: "m-second",
          },
        ],
      }),
      created_employees: [
        {
          employee: employee({
            membership_id: "m-valid",
            email: "valid@example.com",
            full_name: "Valid User",
          }),
          setup: {
            delivered: true,
            delivery_error: null,
            expires_at: "2026-05-07T00:00:00Z",
            debug_token: null,
          },
        },
        {
          employee: employee({
            membership_id: "m-second",
            email: "second@example.com",
            full_name: "Second User",
          }),
          setup: {
            delivered: false,
            delivery_error: "non-prod",
            expires_at: "2026-05-07T00:00:00Z",
            debug_token: "bulk-debug-token",
          },
        },
      ],
    });
    resendEmployeeSetupMock.mockResolvedValue({
      delivered: false,
      delivery_error: "non-prod",
      expires_at: "2026-05-07T00:00:00Z",
      debug_token: "setup-token",
    });
    resetEmployeePasswordMock.mockResolvedValue({
      delivered: true,
      delivery_error: null,
      expires_at: "2026-05-06T01:00:00Z",
      debug_token: null,
    });
    updateEmployeeMock.mockImplementation(async (input) =>
      employee({
        membership_id: input.membershipId,
        full_name: input.fullName,
        department: input.department,
      }),
    );
  });

  it("gates the directory on company:manage_users", () => {
    useCapabilityMock.mockReturnValue(false);
    render(withClient(<EmployeesAdminPage />));
    expect(
      screen.getByText(/You don't have access to manage employees/i),
    ).toBeInTheDocument();
    expect(listEmployeesMock).not.toHaveBeenCalled();
  });

  it("renders employees and passes filters to the API", async () => {
    const user = userEvent.setup();
    render(withClient(<EmployeesAdminPage />));
    expect(await screen.findByText("Asha Rao")).toBeInTheDocument();
    await user.type(screen.getByTestId("employee-search"), "asha");
    await user.selectOptions(screen.getByTestId("employee-role-filter"), "member");
    await user.selectOptions(screen.getByTestId("employee-status-filter"), "invited");
    await user.type(screen.getByTestId("employee-department-filter"), "Litigation");
    await waitFor(() =>
      expect(listEmployeesMock).toHaveBeenLastCalledWith(
        expect.objectContaining({
          q: "asha",
          role: "member",
          status: "invited",
          department: "Litigation",
        }),
      ),
    );
  });

  it("creates an employee without asking for a raw password", async () => {
    const user = userEvent.setup();
    render(withClient(<EmployeesAdminPage />));
    await screen.findByText("Asha Rao");
    await user.click(screen.getByTestId("new-employee-trigger"));
    await user.type(screen.getByTestId("employee-name"), "New User");
    await user.type(screen.getByTestId("employee-email"), "new@example.com");
    await user.selectOptions(screen.getByTestId("employee-role"), "paralegal");
    await user.type(screen.getByTestId("employee-department"), "Contracts");
    await user.click(screen.getByTestId("new-employee-submit"));
    await waitFor(() => expect(createEmployeeMock).toHaveBeenCalledTimes(1));
    expect(createEmployeeMock).toHaveBeenCalledWith(
      expect.objectContaining({
        fullName: "New User",
        email: "new@example.com",
        role: "paralegal",
        department: "Contracts",
      }),
    );
    expect(toastSuccessMock).toHaveBeenCalledWith(
      "Employee created. Setup link generated for local/test.",
    );
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
  });

  it("supports setup resend, password reset, and metadata edit actions", async () => {
    const user = userEvent.setup();
    render(withClient(<EmployeesAdminPage />));
    await screen.findByText("Asha Rao");

    await user.click(screen.getByTestId("employee-resend-asha@example.com"));
    await waitFor(() => expect(resendEmployeeSetupMock).toHaveBeenCalledWith("m1"));
    expect(toastSuccessMock).toHaveBeenCalledWith(
      "Setup link generated for local/test.",
    );

    await user.click(screen.getByTestId("employee-reset-dev@example.com"));
    await waitFor(() => expect(resetEmployeePasswordMock).toHaveBeenCalledWith("m2"));
    expect(toastSuccessMock).toHaveBeenCalledWith("Password reset link sent.");

    await user.click(screen.getByTestId("employee-edit-asha@example.com"));
    expect(await screen.findByText("Employee history")).toBeInTheDocument();
    expect(await screen.findByText("offboarding committed")).toBeInTheDocument();
    expect(listEmployeeAuditMock).toHaveBeenCalledWith("m1");
    const department = screen.getByTestId("edit-employee-department");
    await user.clear(department);
    await user.type(department, "Strategy");
    await user.click(screen.getByTestId("edit-employee-submit"));
    await waitFor(() =>
      expect(updateEmployeeMock).toHaveBeenCalledWith(
        expect.objectContaining({
          membershipId: "m1",
          fullName: "Asha Rao",
          department: "Strategy",
        }),
      ),
    );
  });

  it("preserves an inactive historical manager during an unrelated employee edit", async () => {
    const user = userEvent.setup();
    listEmployeesMock.mockResolvedValue({
      employees: [
        employee({
          manager_membership_id: "m-historical-manager",
          manager_name: "Former Manager",
        }),
      ],
    });
    listCompanyUsersMock.mockResolvedValue({
      company_id: "c1",
      company_slug: "firm",
      users: [
        {
          membership_id: "m-historical-manager",
          user_id: "u-historical-manager",
          email: "former.manager@example.com",
          full_name: "Former Manager",
          role: "member",
          membership_active: false,
          user_active: false,
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    });

    render(withClient(<EmployeesAdminPage />));
    await screen.findByText("Asha Rao");
    await user.click(screen.getByTestId("employee-edit-asha@example.com"));

    const manager = await screen.findByLabelText("Manager");
    expect(manager).toHaveValue("m-historical-manager");
    expect(
      within(manager).getByRole("option", {
        name: /Former Manager.*current; unavailable for new assignments/,
      }),
    ).toBeDisabled();

    const department = screen.getByTestId("edit-employee-department");
    await user.clear(department);
    await user.type(department, "Strategy");
    await user.click(screen.getByTestId("edit-employee-submit"));

    await waitFor(() =>
      expect(updateEmployeeMock).toHaveBeenCalledWith(
        expect.objectContaining({
          membershipId: "m1",
          department: "Strategy",
          managerMembershipId: "m-historical-manager",
        }),
      ),
    );
  });

  it("previews and commits employee offboarding through the directory", async () => {
    const user = userEvent.setup();
    render(withClient(<EmployeesAdminPage />));
    await screen.findByText("Asha Rao");

    await user.click(screen.getByTestId("employee-offboard-asha@example.com"));
    expect(screen.getByText("Offboard employee")).toBeInTheDocument();
    expect(screen.getByTestId("offboard-replacement")).toHaveValue("m2");
    await user.click(screen.getByTestId("offboard-preview"));

    await waitFor(() =>
      expect(previewEmployeeOffboardingMock).toHaveBeenCalledWith({
        membershipId: "m1",
        reassignToMembershipId: "m2",
        notes: null,
      }),
    );
    expect(await screen.findByText("LW8-001 - Offboarding Matter")).toBeInTheDocument();
    expect(screen.getByText("LW8-001 - Draft submissions")).toBeInTheDocument();

    await user.click(screen.getByTestId("offboard-commit"));
    await waitFor(() =>
      expect(commitEmployeeOffboardingMock).toHaveBeenCalledWith({
        membershipId: "m1",
        reassignToMembershipId: "m2",
        notes: null,
      }),
    );
    expect(toastSuccessMock).toHaveBeenCalledWith(
      "Employee offboarded and supported work reassigned.",
    );
  });

  it("reports setup and reset delivery failures without exposing token values", async () => {
    const user = userEvent.setup();
    resendEmployeeSetupMock.mockResolvedValueOnce({
      delivered: false,
      delivery_error: "sendgrid not configured",
      expires_at: "2026-05-07T00:00:00Z",
      debug_token: null,
    });
    resetEmployeePasswordMock.mockResolvedValueOnce({
      delivered: false,
      delivery_error: "sendgrid unavailable",
      expires_at: "2026-05-06T01:00:00Z",
      debug_token: null,
    });

    render(withClient(<EmployeesAdminPage />));
    await screen.findByText("Asha Rao");

    await user.click(screen.getByTestId("employee-resend-asha@example.com"));
    await waitFor(() =>
      expect(toastErrorMock).toHaveBeenCalledWith(
        "Setup link delivery failed: sendgrid not configured",
      ),
    );

    await user.click(screen.getByTestId("employee-reset-dev@example.com"));
    await waitFor(() =>
      expect(toastErrorMock).toHaveBeenCalledWith(
        "Password reset link delivery failed: sendgrid unavailable",
      ),
    );

    expect(screen.queryByText("setup-token")).not.toBeInTheDocument();
    expect(screen.queryByText("reset-token")).not.toBeInTheDocument();
  });

  it("downloads bulk import templates", async () => {
    const user = userEvent.setup();
    render(withClient(<EmployeesAdminPage />));
    await screen.findByText("Asha Rao");

    await user.click(screen.getByTestId("employee-import-trigger"));
    await user.click(screen.getByTestId("employee-import-template-csv"));

    await waitFor(() =>
      expect(downloadEmployeeImportTemplateMock).toHaveBeenCalledWith("csv"),
    );
    expect(URL.createObjectURL).toHaveBeenCalled();
  });

  it("previews bulk import row errors and blocks commit", async () => {
    const user = userEvent.setup();
    render(withClient(<EmployeesAdminPage />));
    await screen.findByText("Asha Rao");

    await user.click(screen.getByTestId("employee-import-trigger"));
    const file = new File(["Name,Email,Role\n,bad@example.com,member\n"], "employees.csv", {
      type: "text/csv",
    });
    await user.upload(screen.getByTestId("employee-import-file"), file);
    await user.click(screen.getByTestId("employee-import-preview"));

    await waitFor(() => expect(previewEmployeeImportMock).toHaveBeenCalledWith(file));
    expect(await screen.findByText("Name is required.")).toBeInTheDocument();
    expect(screen.getByTestId("employee-import-commit")).toBeDisabled();
  });

  it("commits valid bulk import and summarizes setup delivery safely", async () => {
    const user = userEvent.setup();
    previewEmployeeImportMock.mockResolvedValueOnce(
      importJob({
        id: "job-valid",
        total_rows: 2,
        valid_rows: 2,
        invalid_rows: 0,
        rows: [
          {
            id: "row-valid-1",
            row_number: 2,
            raw: { Name: "Valid User", Email: "valid@example.com", Role: "member" },
            normalized: {
              full_name: "Valid User",
              email: "valid@example.com",
              role: "member",
              department: "Litigation",
            },
            errors: [],
            status: "valid",
            created_membership_id: null,
          },
          {
            id: "row-valid-2",
            row_number: 3,
            raw: { Name: "Second User", Email: "second@example.com", Role: "viewer" },
            normalized: {
              full_name: "Second User",
              email: "second@example.com",
              role: "viewer",
              department: "Finance",
            },
            errors: [],
            status: "valid",
            created_membership_id: null,
          },
        ],
      }),
    );
    render(withClient(<EmployeesAdminPage />));
    await screen.findByText("Asha Rao");

    await user.click(screen.getByTestId("employee-import-trigger"));
    const file = new File(
      ["Name,Email,Role\nValid User,valid@example.com,member\n"],
      "employees.csv",
      { type: "text/csv" },
    );
    await user.upload(screen.getByTestId("employee-import-file"), file);
    await user.click(screen.getByTestId("employee-import-preview"));
    await screen.findByText("Valid User");

    await user.click(screen.getByTestId("employee-import-commit"));
    await waitFor(() => expect(commitEmployeeImportMock).toHaveBeenCalledWith("job-valid"));
    expect(await screen.findByText("2 employees created")).toBeInTheDocument();
    expect(screen.getByText(/1 delivered \| 1 local\/test generated \| 0 delivery failed/i)).toBeInTheDocument();
    expect(screen.queryByText("bulk-debug-token")).not.toBeInTheDocument();
  });

  it("cancels a previewed bulk import job", async () => {
    const user = userEvent.setup();
    render(withClient(<EmployeesAdminPage />));
    await screen.findByText("Asha Rao");

    await user.click(screen.getByTestId("employee-import-trigger"));
    const file = new File(["Name,Email,Role\nValid,valid@example.com,member\n"], "employees.csv", {
      type: "text/csv",
    });
    await user.upload(screen.getByTestId("employee-import-file"), file);
    await user.click(screen.getByTestId("employee-import-preview"));
    await screen.findByText("Name is required.");

    await user.click(screen.getByTestId("employee-import-cancel"));
    await waitFor(() => expect(cancelEmployeeImportMock).toHaveBeenCalledWith("job-1"));
    expect(toastSuccessMock).toHaveBeenCalledWith("Employee import cancelled.");
  });
});
