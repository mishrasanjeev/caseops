"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  FileDown,
  FileSpreadsheet,
  History,
  KeyRound,
  Loader2,
  Pencil,
  Plus,
  RotateCcw,
  Search,
  ShieldCheck,
  UploadCloud,
  UserX,
  Users,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { PersonPicker } from "@/components/ui/PersonPicker";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { apiErrorMessage } from "@/lib/api/config";
import {
  cancelEmployeeImport,
  commitEmployeeOffboarding,
  commitEmployeeImport,
  createEmployee,
  downloadEmployeeImportTemplate,
  listEmployeeAudit,
  listEmployees,
  listEmployeeMatterAccess,
  previewEmployeeOffboarding,
  previewEmployeeImport,
  resendEmployeeSetup,
  resetEmployeePassword,
  updateEmployee,
  grantMatterAccess,
  revokeMatterAccess,
  setMatterRestrictedAccess,
  type AssignableEmployeeRole,
  type EmployeeAuditEvent,
  type EmployeeEmploymentStatus,
  type EmployeeImportJob,
  type EmployeeImportRowPreview,
  type EmployeeMatterAccessRow,
  type EmployeeOffboardingPreview,
  type EmployeeRecord,
  type EmployeeRole,
  type EmployeeTokenDelivery,
} from "@/lib/api/endpoints";
import { useCapability, useRole } from "@/lib/capabilities";

const ROLE_OPTIONS: Array<{ value: AssignableEmployeeRole; label: string }> = [
  { value: "admin", label: "Admin" },
  { value: "partner", label: "Partner" },
  { value: "member", label: "Member" },
  { value: "paralegal", label: "Paralegal" },
  { value: "viewer", label: "Viewer" },
];

const FILTER_ROLES: Array<{ value: EmployeeRole | ""; label: string }> = [
  { value: "", label: "All roles" },
  { value: "owner", label: "Owner" },
  ...ROLE_OPTIONS,
];

const STATUS_OPTIONS: Array<{ value: EmployeeEmploymentStatus | ""; label: string }> = [
  { value: "", label: "All statuses" },
  { value: "invited", label: "Invited" },
  { value: "active", label: "Active" },
  { value: "inactive", label: "Inactive" },
];

const EDIT_STATUS_OPTIONS: Array<{ value: EmployeeEmploymentStatus; label: string }> = [
  { value: "invited", label: "Invited" },
  { value: "active", label: "Active" },
  { value: "inactive", label: "Inactive" },
];

function clean(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "Not recorded";
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}

function roleLabel(role: string): string {
  return role.replace(/_/g, " ");
}

function deliveryFailureMessage(prefix: string, delivery: EmployeeTokenDelivery): string {
  const detail = delivery.delivery_error?.trim();
  return detail ? `${prefix}: ${detail}` : `${prefix}.`;
}

function notifySetupDelivery(
  delivery: EmployeeTokenDelivery,
  options?: { created?: boolean },
): void {
  const created = options?.created === true;
  if (delivery.delivered) {
    toast.success(created ? "Employee created. Setup link sent." : "Setup link sent.");
    return;
  }
  if (delivery.debug_token) {
    toast.success(
      created
        ? "Employee created. Setup link generated for local/test."
        : "Setup link generated for local/test.",
    );
    return;
  }
  toast.error(
    deliveryFailureMessage(
      created ? "Employee created. Setup link delivery failed" : "Setup link delivery failed",
      delivery,
    ),
  );
}

function notifyResetDelivery(delivery: EmployeeTokenDelivery): void {
  if (delivery.delivered) {
    toast.success("Password reset link sent.");
    return;
  }
  if (delivery.debug_token) {
    toast.success("Password reset link generated for local/test.");
    return;
  }
  toast.error(deliveryFailureMessage("Password reset link delivery failed", delivery));
}

function textCell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not set";
  return String(value);
}

function actionLabel(action: string): string {
  return action.replace(/^employee\./, "").replace(/_/g, " ").replace(/\./g, " ");
}

function triggerTemplateDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export default function EmployeesAdminPage() {
  const canManageUsers = useCapability("company:manage_users");
  const actorRole = useRole();
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [role, setRole] = useState<EmployeeRole | "">("");
  const [status, setStatus] = useState<EmployeeEmploymentStatus | "">("");
  const [department, setDepartment] = useState("");
  const [editing, setEditing] = useState<EmployeeRecord | null>(null);
  const [offboarding, setOffboarding] = useState<EmployeeRecord | null>(null);

  const employeesQuery = useQuery({
    queryKey: ["admin", "employees", { q, role, status, department }],
    queryFn: () =>
      listEmployees({
        q: q.trim(),
        role,
        status,
        department: department.trim(),
      }),
    enabled: canManageUsers,
  });

  const resendMutation = useMutation({
    mutationFn: (membershipId: string) => resendEmployeeSetup(membershipId),
    onSuccess: async (delivery) => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "employees"] });
      notifySetupDelivery(delivery);
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not generate setup link.")),
  });

  const resetMutation = useMutation({
    mutationFn: (membershipId: string) => resetEmployeePassword(membershipId),
    onSuccess: async (delivery) => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "employees"] });
      notifyResetDelivery(delivery);
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not generate reset link.")),
  });

  const employees = employeesQuery.data?.employees ?? [];

  return (
    <div className="flex flex-col gap-6">
      <Link
        href="/app/admin"
        className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-mute)] hover:text-[var(--color-ink)]"
      >
        Back to admin
      </Link>
      <PageHeader
        eyebrow="Admin"
        title="Employee directory"
        description="Manage internal employees, fixed CaseOps roles, directory metadata, and secure setup/reset links."
        actions={
          canManageUsers ? (
            <div className="flex flex-wrap justify-end gap-2">
              <Link
                href="/app/admin/roles"
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-line)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
              >
                <ShieldCheck className="h-4 w-4" aria-hidden /> Role templates
              </Link>
              <BulkEmployeeImportDialog />
              <NewEmployeeDialog />
            </div>
          ) : null
        }
      />

      {!canManageUsers ? (
        <EmptyState
          icon={Users}
          title="You don't have access to manage employees"
          description="Ask a workspace owner or admin for company:manage_users."
        />
      ) : (
        <>
          <Card>
            <CardHeader className="pb-3">
              <CardTitle as="h2" className="text-base">
                Directory filters
              </CardTitle>
              <CardDescription>
                Search and narrow by fixed role, setup status, and department.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 md:grid-cols-[minmax(220px,1fr)_160px_160px_180px]">
                <label className="relative flex flex-col gap-1.5">
                  <span className="text-xs font-medium text-[var(--color-mute)]">
                    Name or email
                  </span>
                  <Search
                    className="pointer-events-none absolute bottom-2.5 left-2.5 h-4 w-4 text-[var(--color-mute)]"
                    aria-hidden
                  />
                  <Input
                    value={q}
                    onChange={(event) => setQ(event.target.value)}
                    placeholder="Search employees"
                    className="pl-8"
                    data-testid="employee-search"
                  />
                </label>
                <label className="flex flex-col gap-1.5">
                  <span className="text-xs font-medium text-[var(--color-mute)]">
                    Role
                  </span>
                  <select
                    value={role}
                    onChange={(event) => setRole(event.target.value as EmployeeRole | "")}
                    className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm"
                    data-testid="employee-role-filter"
                  >
                    {FILTER_ROLES.map((option) => (
                      <option key={option.value || "all"} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1.5">
                  <span className="text-xs font-medium text-[var(--color-mute)]">
                    Status
                  </span>
                  <select
                    value={status}
                    onChange={(event) =>
                      setStatus(event.target.value as EmployeeEmploymentStatus | "")
                    }
                    className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm"
                    data-testid="employee-status-filter"
                  >
                    {STATUS_OPTIONS.map((option) => (
                      <option key={option.value || "all"} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1.5">
                  <span className="text-xs font-medium text-[var(--color-mute)]">
                    Department
                  </span>
                  <Input
                    value={department}
                    onChange={(event) => setDepartment(event.target.value)}
                    placeholder="Litigation"
                    data-testid="employee-department-filter"
                  />
                </label>
              </div>
            </CardContent>
          </Card>

          {employeesQuery.isPending ? (
            <Skeleton className="h-72 w-full" />
          ) : employeesQuery.isError ? (
            <QueryErrorState
              title="Could not load employees"
              error={employeesQuery.error}
              onRetry={employeesQuery.refetch}
            />
          ) : employees.length === 0 ? (
            <EmptyState
              icon={Users}
              title="No employees match these filters"
              description="Clear filters or add a new employee to this workspace."
              action={
                <div className="flex flex-wrap justify-center gap-2">
                  <BulkEmployeeImportDialog />
                  <NewEmployeeDialog />
                </div>
              }
            />
          ) : (
            <Card>
              <CardContent className="p-0">
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-[var(--color-line)] text-sm">
                    <thead className="bg-[var(--color-bg-2)] text-left text-xs font-semibold uppercase text-[var(--color-mute)]">
                      <tr>
                        <th className="px-4 py-3">Employee</th>
                        <th className="px-4 py-3">Role</th>
                        <th className="px-4 py-3">Department</th>
                        <th className="px-4 py-3">Status</th>
                        <th className="px-4 py-3">Last login</th>
                        <th className="px-4 py-3 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--color-line)] bg-white">
                      {employees.map((employee) => (
                        <EmployeeRow
                          key={employee.membership_id}
                          employee={employee}
                          onEdit={() => setEditing(employee)}
                          onResend={() =>
                            resendMutation.mutate(employee.membership_id)
                          }
                          onReset={() =>
                            resetMutation.mutate(employee.membership_id)
                          }
                          onOffboard={() => setOffboarding(employee)}
                          canOffboard={
                            (actorRole === "owner" || actorRole === "admin") &&
                            employee.role !== "owner" &&
                            employee.employment_status !== "inactive"
                          }
                          resending={
                            resendMutation.isPending &&
                            resendMutation.variables === employee.membership_id
                          }
                          resetting={
                            resetMutation.isPending &&
                            resetMutation.variables === employee.membership_id
                          }
                        />
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}

      {editing ? (
        <EditEmployeeDialog
          employee={editing}
          onClose={() => setEditing(null)}
        />
      ) : null}
      {offboarding ? (
        <OffboardEmployeeDialog
          employee={offboarding}
          employees={employees}
          onClose={() => setOffboarding(null)}
        />
      ) : null}
    </div>
  );
}

function EmployeeRow({
  employee,
  onEdit,
  onResend,
  onReset,
  onOffboard,
  canOffboard,
  resending,
  resetting,
}: {
  employee: EmployeeRecord;
  onEdit: () => void;
  onResend: () => void;
  onReset: () => void;
  onOffboard: () => void;
  canOffboard: boolean;
  resending: boolean;
  resetting: boolean;
}) {
  const needsSetup = !employee.setup_completed_at || employee.employment_status === "invited";
  return (
    <tr>
      <td className="px-4 py-3 align-top">
        <div className="font-medium text-[var(--color-ink)]">{employee.full_name}</div>
        <div className="text-xs text-[var(--color-mute)]">{employee.email}</div>
        {employee.employee_code ? (
          <div className="mt-1 font-mono text-xs text-[var(--color-mute)]">
            {employee.employee_code}
          </div>
        ) : null}
      </td>
      <td className="px-4 py-3 align-top">
        <Badge tone={employee.role === "owner" || employee.role === "admin" ? "brand" : "neutral"}>
          {roleLabel(employee.role)}
        </Badge>
        {employee.custom_role_name ? (
          <div className="mt-1 text-xs text-[var(--color-mute)]">
            {employee.custom_role_name}
          </div>
        ) : null}
      </td>
      <td className="px-4 py-3 align-top">
        <div>{employee.department || "Unassigned"}</div>
        {employee.designation ? (
          <div className="text-xs text-[var(--color-mute)]">{employee.designation}</div>
        ) : null}
      </td>
      <td className="px-4 py-3 align-top">
        <StatusBadge status={employee.employment_status} />
      </td>
      <td className="px-4 py-3 align-top text-xs text-[var(--color-mute)]">
        {formatDate(employee.last_login_at)}
      </td>
      <td className="px-4 py-3 align-top">
        <div className="flex justify-end gap-1.5">
          <Button size="sm" variant="ghost" onClick={onEdit} data-testid={`employee-edit-${employee.email}`}>
            <Pencil className="h-4 w-4" aria-hidden />
            Edit
          </Button>
          {needsSetup ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={onResend}
              disabled={resending}
              data-testid={`employee-resend-${employee.email}`}
            >
              {resending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <RotateCcw className="h-4 w-4" aria-hidden />
              )}
              Setup
            </Button>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              onClick={onReset}
              disabled={resetting}
              data-testid={`employee-reset-${employee.email}`}
            >
              {resetting ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <KeyRound className="h-4 w-4" aria-hidden />
              )}
              Reset
            </Button>
          )}
          {canOffboard ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={onOffboard}
              data-testid={`employee-offboard-${employee.email}`}
            >
              <UserX className="h-4 w-4" aria-hidden />
              Offboard
            </Button>
          ) : null}
        </div>
      </td>
    </tr>
  );
}

function objectLabel(value: string): string {
  return value.replace(/_/g, " ");
}

function activeReplacementOptions(
  employees: EmployeeRecord[],
  target: EmployeeRecord,
): EmployeeRecord[] {
  return employees.filter(
    (employee) =>
      employee.membership_id !== target.membership_id &&
      employee.membership_active &&
      employee.user_active &&
      employee.employment_status !== "inactive",
  );
}

function OffboardEmployeeDialog({
  employee,
  employees,
  onClose,
}: {
  employee: EmployeeRecord;
  employees: EmployeeRecord[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const replacements = activeReplacementOptions(employees, employee);
  const [replacementId, setReplacementId] = useState(replacements[0]?.membership_id ?? "");
  const [notes, setNotes] = useState("");
  const [preview, setPreview] = useState<EmployeeOffboardingPreview | null>(null);

  const previewMutation = useMutation({
    mutationFn: () =>
      previewEmployeeOffboarding({
        membershipId: employee.membership_id,
        reassignToMembershipId: replacementId || null,
        notes: clean(notes),
      }),
    onSuccess: (result) => {
      setPreview(result);
      if (result.can_commit) {
        toast.success("Offboarding preview generated.");
      } else {
        toast.error("Offboarding has blockers to resolve.");
      }
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not preview offboarding.")),
  });

  const commitMutation = useMutation({
    mutationFn: () =>
      commitEmployeeOffboarding({
        membershipId: employee.membership_id,
        reassignToMembershipId: replacementId,
        notes: clean(notes),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "employees"] });
      toast.success("Employee offboarded and supported work reassigned.");
      onClose();
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not commit offboarding.")),
  });

  const pending = previewMutation.isPending || commitMutation.isPending;
  const canCommit =
    Boolean(preview?.can_commit) &&
    preview?.reassign_to?.membership_id === replacementId &&
    !pending;

  return (
    <Dialog open onOpenChange={(next) => (!next && !pending ? onClose() : undefined)}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>Offboard employee</DialogTitle>
          <DialogDescription>
            Preview assigned work, choose a replacement, then deactivate access.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
          <div className="flex flex-col gap-3 rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] p-3">
            <div>
              <div className="text-sm font-semibold text-[var(--color-ink)]">
                {employee.full_name}
              </div>
              <div className="text-xs text-[var(--color-mute)]">{employee.email}</div>
            </div>
            <Field label="Replacement employee" id="offboard-replacement">
              <select
                id="offboard-replacement"
                value={replacementId}
                onChange={(event) => {
                  setReplacementId(event.target.value);
                  setPreview(null);
                }}
                className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm"
                data-testid="offboard-replacement"
              >
                {replacements.length === 0 ? (
                  <option value="">No active replacement available</option>
                ) : null}
                {replacements.map((candidate) => (
                  <option key={candidate.membership_id} value={candidate.membership_id}>
                    {candidate.full_name} - {roleLabel(candidate.role)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Notes" id="offboard-notes">
              <Input
                id="offboard-notes"
                value={notes}
                onChange={(event) => {
                  setNotes(event.target.value);
                  setPreview(null);
                }}
                placeholder="Exit notes"
                data-testid="offboard-notes"
              />
            </Field>
            <Button
              type="button"
              onClick={() => previewMutation.mutate()}
              disabled={!replacementId || pending}
              data-testid="offboard-preview"
            >
              {previewMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Previewing
                </>
              ) : (
                <>
                  <History className="h-4 w-4" aria-hidden /> Preview impact
                </>
              )}
            </Button>
            <div className="text-xs leading-5 text-[var(--color-mute)]">
              Commit deactivates the employee and revokes existing sessions. Unsupported
              historical objects remain visible in audit.
            </div>
          </div>

          <div className="min-h-72 rounded-md border border-[var(--color-line)] bg-white">
            {preview ? (
              <div className="flex flex-col">
                <div className="grid gap-2 border-b border-[var(--color-line)] p-3 sm:grid-cols-3">
                  <ImportMetric
                    label="Supported"
                    value={preview.supported_objects.length}
                    tone={preview.can_commit ? "ok" : undefined}
                  />
                  <ImportMetric
                    label="Unsupported"
                    value={preview.unsupported_objects.length}
                  />
                  <ImportMetric
                    label="Blockers"
                    value={preview.blockers.length}
                    tone={preview.blockers.length ? "bad" : "ok"}
                  />
                </div>
                {preview.blockers.length ? (
                  <div className="border-b border-[var(--color-line)] bg-[var(--color-danger-500)]/[0.05] p-3 text-sm text-[var(--color-danger-500)]">
                    {preview.blockers.map((blocker) => (
                      <div key={blocker} className="flex items-start gap-2">
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                        <span>{blocker}</span>
                      </div>
                    ))}
                  </div>
                ) : null}
                <div className="grid gap-4 p-3 lg:grid-cols-2">
                  <OffboardingObjectList
                    title="Supported reassignment"
                    rows={preview.supported_objects}
                  />
                  <OffboardingObjectList
                    title="Unsupported history"
                    rows={preview.unsupported_objects}
                  />
                </div>
              </div>
            ) : (
              <div className="flex h-full min-h-72 items-center justify-center p-6">
                <EmptyState
                  icon={UserX}
                  title="Preview required"
                  description="Choose a replacement employee to enumerate work before offboarding."
                />
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={() => commitMutation.mutate()}
            disabled={!canCommit}
            data-testid="offboard-commit"
          >
            {commitMutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Committing
              </>
            ) : (
              "Commit offboarding"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function OffboardingObjectList({
  title,
  rows,
}: {
  title: string;
  rows: EmployeeOffboardingPreview["supported_objects"];
}) {
  return (
    <div className="rounded-md border border-[var(--color-line)]">
      <div className="border-b border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-2 text-xs font-semibold uppercase text-[var(--color-mute)]">
        {title}
      </div>
      {rows.length === 0 ? (
        <div className="px-3 py-4 text-sm text-[var(--color-mute)]">No objects found.</div>
      ) : (
        <div className="max-h-72 overflow-auto divide-y divide-[var(--color-line)]">
          {rows.slice(0, 80).map((row) => (
            <div key={`${row.object_type}-${row.id}`} className="px-3 py-2">
              <div className="text-sm font-medium text-[var(--color-ink)]">
                {row.label}
              </div>
              <div className="text-xs text-[var(--color-mute)]">
                {objectLabel(row.object_type)} | {row.relation}
              </div>
            </div>
          ))}
          {rows.length > 80 ? (
            <div className="px-3 py-2 text-xs text-[var(--color-mute)]">
              {rows.length - 80} more objects hidden.
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

function BulkEmployeeImportDialog() {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<EmployeeImportJob | null>(null);
  const [commitResult, setCommitResult] = useState<{
    created: number;
    delivered: number;
    localGenerated: number;
    failedDelivery: number;
  } | null>(null);
  const [downloading, setDownloading] = useState<"csv" | "xlsx" | null>(null);
  const queryClient = useQueryClient();

  const resetState = () => {
    setFile(null);
    setJob(null);
    setCommitResult(null);
    setDownloading(null);
  };

  const previewMutation = useMutation({
    mutationFn: (selectedFile: File) => previewEmployeeImport(selectedFile),
    onSuccess: (result) => {
      setJob(result);
      setCommitResult(null);
      toast.success("Employee import preview generated.");
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not preview employee import.")),
  });

  const commitMutation = useMutation({
    mutationFn: () => {
      if (!job) throw new Error("Preview an import before committing.");
      return commitEmployeeImport(job.id);
    },
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "employees"] });
      setJob(result.job);
      const created = result.created_employees.length;
      const delivered = result.created_employees.filter((row) => row.setup.delivered).length;
      const localGenerated = result.created_employees.filter(
        (row) => !row.setup.delivered && Boolean(row.setup.debug_token),
      ).length;
      const failedDelivery = result.created_employees.filter(
        (row) => !row.setup.delivered && !row.setup.debug_token,
      ).length;
      setCommitResult({ created, delivered, localGenerated, failedDelivery });
      toast.success(`Employee import committed. ${created} employees created.`);
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not commit employee import.")),
  });

  const cancelMutation = useMutation({
    mutationFn: () => {
      if (!job) throw new Error("No import to cancel.");
      return cancelEmployeeImport(job.id);
    },
    onSuccess: () => {
      toast.success("Employee import cancelled.");
      resetState();
      setOpen(false);
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not cancel employee import.")),
  });

  const pending =
    previewMutation.isPending || commitMutation.isPending || cancelMutation.isPending;
  const rowsToShow = job
    ? [
        ...job.rows.filter((row) => row.errors.length > 0),
        ...job.rows.filter((row) => row.errors.length === 0).slice(0, 50),
      ]
    : [];
  const hiddenRows = job ? Math.max(job.rows.length - rowsToShow.length, 0) : 0;

  async function downloadTemplate(format: "csv" | "xlsx") {
    try {
      setDownloading(format);
      const blob = await downloadEmployeeImportTemplate(format);
      triggerTemplateDownload(
        blob,
        `caseops-employee-import-template.${format}`,
      );
    } catch (err) {
      toast.error(apiErrorMessage(err, "Could not download employee template."));
    } finally {
      setDownloading(null);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && pending) return;
        setOpen(next);
        if (!next) resetState();
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="secondary" data-testid="employee-import-trigger">
          <UploadCloud className="h-4 w-4" aria-hidden /> Bulk upload
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>Bulk employee upload</DialogTitle>
          <DialogDescription>
            Preview CSV/XLSX rows, resolve validation errors, then commit setup-link onboarding.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
          <div className="flex flex-col gap-3 rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] p-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-[var(--color-ink)]">
              <FileSpreadsheet className="h-4 w-4" aria-hidden />
              Template
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => void downloadTemplate("csv")}
                disabled={downloading !== null}
                data-testid="employee-import-template-csv"
              >
                {downloading === "csv" ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <FileDown className="h-4 w-4" aria-hidden />
                )}
                CSV
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => void downloadTemplate("xlsx")}
                disabled={downloading !== null}
                data-testid="employee-import-template-xlsx"
              >
                {downloading === "xlsx" ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <FileDown className="h-4 w-4" aria-hidden />
                )}
                XLSX
              </Button>
            </div>
            <Field label="Upload file" id="employee-import-file">
              <Input
                id="employee-import-file"
                type="file"
                accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                onChange={(event) => {
                  const selected = event.target.files?.[0] ?? null;
                  setFile(selected);
                  setJob(null);
                  setCommitResult(null);
                }}
                data-testid="employee-import-file"
              />
            </Field>
            <Button
              type="button"
              onClick={() => file && previewMutation.mutate(file)}
              disabled={!file || pending}
              data-testid="employee-import-preview"
            >
              {previewMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Previewing
                </>
              ) : (
                <>
                  <UploadCloud className="h-4 w-4" aria-hidden /> Preview
                </>
              )}
            </Button>
            {file ? (
              <div className="text-xs text-[var(--color-mute)]">
                Selected {file.name} | {Math.ceil(file.size / 1024)} KB
              </div>
            ) : null}
          </div>

          <div className="min-h-72 rounded-md border border-[var(--color-line)] bg-white">
            {job ? (
              <div className="flex flex-col">
                <div className="grid gap-2 border-b border-[var(--color-line)] p-3 sm:grid-cols-4">
                  <ImportMetric label="Rows" value={job.total_rows} />
                  <ImportMetric label="Valid" value={job.valid_rows} tone="ok" />
                  <ImportMetric label="Errors" value={job.invalid_rows} tone="bad" />
                  <ImportMetric label="Status" value={job.status} />
                </div>
                {commitResult ? (
                  <div className="border-b border-[var(--color-line)] bg-[var(--color-bg-2)] p-3">
                    <div className="flex flex-wrap items-center gap-3 text-sm">
                      <span className="inline-flex items-center gap-1.5 font-semibold text-[var(--color-ink)]">
                        <CheckCircle2 className="h-4 w-4 text-[var(--color-success-500)]" aria-hidden />
                        {commitResult.created} employees created
                      </span>
                      <span className="text-[var(--color-mute)]">
                        {commitResult.delivered} delivered | {commitResult.localGenerated} local/test generated | {commitResult.failedDelivery} delivery failed
                      </span>
                    </div>
                  </div>
                ) : null}
                <div className="max-h-[44vh] overflow-auto">
                  <table className="min-w-full divide-y divide-[var(--color-line)] text-sm">
                    <thead className="sticky top-0 bg-[var(--color-bg-2)] text-left text-xs font-semibold uppercase text-[var(--color-mute)]">
                      <tr>
                        <th className="px-3 py-2">Row</th>
                        <th className="px-3 py-2">Name</th>
                        <th className="px-3 py-2">Email</th>
                        <th className="px-3 py-2">Role</th>
                        <th className="px-3 py-2">Department</th>
                        <th className="px-3 py-2">Errors</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--color-line)]">
                      {rowsToShow.map((row) => (
                        <ImportRow key={row.id} row={row} />
                      ))}
                    </tbody>
                  </table>
                </div>
                {hiddenRows > 0 ? (
                  <div className="border-t border-[var(--color-line)] px-3 py-2 text-xs text-[var(--color-mute)]">
                    {hiddenRows} valid rows are hidden from this preview table.
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="flex h-full min-h-72 items-center justify-center p-6">
                <EmptyState
                  icon={FileSpreadsheet}
                  title="No import preview yet"
                  description="Choose a CSV or XLSX file to validate employee rows before commit."
                />
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              if (job && job.status === "previewed" && !commitResult) {
                cancelMutation.mutate();
              } else {
                resetState();
                setOpen(false);
              }
            }}
            disabled={pending}
            data-testid="employee-import-cancel"
          >
            {cancelMutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Cancelling
              </>
            ) : job && job.status === "previewed" && !commitResult ? (
              "Cancel import"
            ) : (
              "Close"
            )}
          </Button>
          <Button
            type="button"
            onClick={() => commitMutation.mutate()}
            disabled={
              !job ||
              job.status !== "previewed" ||
              job.invalid_rows > 0 ||
              pending ||
              Boolean(commitResult)
            }
            data-testid="employee-import-commit"
          >
            {commitMutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Committing
              </>
            ) : (
              "Commit valid import"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ImportMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: "ok" | "bad";
}) {
  const toneClass =
    tone === "ok"
      ? "text-[var(--color-success-500)]"
      : tone === "bad"
        ? "text-[var(--color-danger-500)]"
        : "text-[var(--color-ink)]";
  return (
    <div>
      <div className="text-xs font-medium uppercase text-[var(--color-mute)]">
        {label}
      </div>
      <div className={`font-mono text-base font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}

function ImportRow({ row }: { row: EmployeeImportRowPreview }) {
  const hasErrors = row.errors.length > 0;
  return (
    <tr className={hasErrors ? "bg-[var(--color-danger-500)]/[0.04]" : undefined}>
      <td className="px-3 py-2 align-top font-mono text-xs">{row.row_number}</td>
      <td className="px-3 py-2 align-top">{textCell(row.normalized.full_name)}</td>
      <td className="px-3 py-2 align-top">{textCell(row.normalized.email)}</td>
      <td className="px-3 py-2 align-top">
        <Badge tone={hasErrors ? "neutral" : "brand"}>
          {textCell(row.normalized.role)}
        </Badge>
      </td>
      <td className="px-3 py-2 align-top">{textCell(row.normalized.department)}</td>
      <td className="px-3 py-2 align-top">
        {hasErrors ? (
          <div className="flex flex-col gap-1 text-xs text-[var(--color-danger-500)]">
            {row.errors.map((error) => (
              <span key={error} className="inline-flex items-start gap-1.5">
                <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                {error}
              </span>
            ))}
          </div>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-xs text-[var(--color-success-500)]">
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
            Valid
          </span>
        )}
      </td>
    </tr>
  );
}

function NewEmployeeDialog() {
  const [open, setOpen] = useState(false);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<AssignableEmployeeRole>("member");
  const [mobile, setMobile] = useState("");
  const [designation, setDesignation] = useState("");
  const [department, setDepartment] = useState("");
  const [employeeCode, setEmployeeCode] = useState("");
  const [managerMembershipId, setManagerMembershipId] = useState("");
  const [joinedOn, setJoinedOn] = useState("");
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () =>
      createEmployee({
        fullName: fullName.trim(),
        email: email.trim().toLowerCase(),
        role,
        mobile: clean(mobile),
        designation: clean(designation),
        department: clean(department),
        employeeCode: clean(employeeCode),
        managerMembershipId: clean(managerMembershipId),
        joinedOn: clean(joinedOn),
      }),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "employees"] });
      notifySetupDelivery(result.setup, { created: true });
      setFullName("");
      setEmail("");
      setRole("member");
      setMobile("");
      setDesignation("");
      setDepartment("");
      setEmployeeCode("");
      setManagerMembershipId("");
      setJoinedOn("");
      setOpen(false);
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not create employee.")),
  });

  const ready =
    fullName.trim().length >= 2 &&
    email.includes("@") &&
    !mutation.isPending;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" data-testid="new-employee-trigger">
          <Plus className="h-4 w-4" aria-hidden /> Add employee
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Add employee</DialogTitle>
          <DialogDescription>
            Create an internal account and generate a single-use setup link.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4 md:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!ready) {
              toast.error("Name and a valid email are required.");
              return;
            }
            mutation.mutate();
          }}
        >
          <Field label="Full name" id="employee-name">
            <Input id="employee-name" value={fullName} onChange={(event) => setFullName(event.target.value)} data-testid="employee-name" />
          </Field>
          <Field label="Email" id="employee-email">
            <Input id="employee-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} data-testid="employee-email" />
          </Field>
          <Field label="Role" id="employee-role">
            <select id="employee-role" value={role} onChange={(event) => setRole(event.target.value as AssignableEmployeeRole)} className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm" data-testid="employee-role">
              {ROLE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </Field>
          <Field label="Department" id="employee-department">
            <Input id="employee-department" value={department} onChange={(event) => setDepartment(event.target.value)} data-testid="employee-department" />
          </Field>
          <Field label="Designation" id="employee-designation">
            <Input id="employee-designation" value={designation} onChange={(event) => setDesignation(event.target.value)} />
          </Field>
          <Field label="Mobile" id="employee-mobile">
            <Input id="employee-mobile" value={mobile} onChange={(event) => setMobile(event.target.value)} />
          </Field>
          <Field label="Employee code" id="employee-code">
            <Input id="employee-code" value={employeeCode} onChange={(event) => setEmployeeCode(event.target.value)} />
          </Field>
          <Field label="Joined on" id="employee-joined">
            <Input id="employee-joined" type="date" value={joinedOn} onChange={(event) => setJoinedOn(event.target.value)} />
          </Field>
          <Field label="Manager" id="employee-manager">
            <PersonPicker id="employee-manager" value={managerMembershipId} onChange={setManagerMembershipId} placeholder="No manager" />
          </Field>
          <DialogFooter className="md:col-span-2">
            <Button type="button" variant="ghost" onClick={() => setOpen(false)} disabled={mutation.isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={!ready} data-testid="new-employee-submit">
              {mutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Creating
                </>
              ) : (
                "Create employee"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function EditEmployeeDialog({
  employee,
  onClose,
}: {
  employee: EmployeeRecord;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [fullName, setFullName] = useState(employee.full_name);
  const [role, setRole] = useState<AssignableEmployeeRole>(
    employee.role === "owner" ? "member" : (employee.role as AssignableEmployeeRole),
  );
  const [status, setStatus] = useState<EmployeeEmploymentStatus>(
    employee.employment_status === "offboarding" ? "inactive" : employee.employment_status,
  );
  const [mobile, setMobile] = useState(employee.mobile ?? "");
  const [designation, setDesignation] = useState(employee.designation ?? "");
  const [department, setDepartment] = useState(employee.department ?? "");
  const [employeeCode, setEmployeeCode] = useState(employee.employee_code ?? "");
  const [managerMembershipId, setManagerMembershipId] = useState(
    employee.manager_membership_id ?? "",
  );
  const [joinedOn, setJoinedOn] = useState(employee.joined_on ?? "");

  const auditQuery = useQuery({
    queryKey: ["admin", "employees", employee.membership_id, "audit"],
    queryFn: () => listEmployeeAudit(employee.membership_id),
  });

  const mutation = useMutation({
    mutationFn: () =>
      updateEmployee({
        membershipId: employee.membership_id,
        fullName: fullName.trim(),
        role: employee.role === "owner" ? undefined : role,
        employmentStatus: employee.role === "owner" ? undefined : status,
        mobile: clean(mobile),
        designation: clean(designation),
        department: clean(department),
        employeeCode: clean(employeeCode),
        managerMembershipId: clean(managerMembershipId),
        joinedOn: clean(joinedOn),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "employees"] });
      toast.success("Employee updated.");
      onClose();
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not update employee.")),
  });

  return (
    <Dialog open onOpenChange={(next) => (!next ? onClose() : undefined)}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit employee</DialogTitle>
          <DialogDescription>
            Update directory metadata and fixed CaseOps role/status.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4 md:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <Field label="Full name" id="edit-employee-name">
            <Input id="edit-employee-name" value={fullName} onChange={(event) => setFullName(event.target.value)} data-testid="edit-employee-name" />
          </Field>
          <Field label="Email" id="edit-employee-email">
            <Input id="edit-employee-email" value={employee.email} disabled />
          </Field>
          <Field label="Role" id="edit-employee-role">
            {employee.role === "owner" ? (
              <Input id="edit-employee-role" value="Owner" disabled />
            ) : (
              <select id="edit-employee-role" value={role} onChange={(event) => setRole(event.target.value as AssignableEmployeeRole)} className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm" data-testid="edit-employee-role">
                {ROLE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Status" id="edit-employee-status">
            <select id="edit-employee-status" value={status} disabled={employee.role === "owner"} onChange={(event) => setStatus(event.target.value as EmployeeEmploymentStatus)} className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm" data-testid="edit-employee-status">
              {EDIT_STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </Field>
          <Field label="Department" id="edit-employee-department">
            <Input id="edit-employee-department" value={department} onChange={(event) => setDepartment(event.target.value)} data-testid="edit-employee-department" />
          </Field>
          <Field label="Designation" id="edit-employee-designation">
            <Input id="edit-employee-designation" value={designation} onChange={(event) => setDesignation(event.target.value)} />
          </Field>
          <Field label="Mobile" id="edit-employee-mobile">
            <Input id="edit-employee-mobile" value={mobile} onChange={(event) => setMobile(event.target.value)} />
          </Field>
          <Field label="Employee code" id="edit-employee-code">
            <Input id="edit-employee-code" value={employeeCode} onChange={(event) => setEmployeeCode(event.target.value)} />
          </Field>
          <Field label="Joined on" id="edit-employee-joined">
            <Input id="edit-employee-joined" type="date" value={joinedOn} onChange={(event) => setJoinedOn(event.target.value)} />
          </Field>
          <Field label="Manager" id="edit-employee-manager">
            <PersonPicker id="edit-employee-manager" value={managerMembershipId} onChange={setManagerMembershipId} placeholder="No manager" />
          </Field>
          <div className="md:col-span-2 rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-2 text-xs text-[var(--color-mute)]">
            Setup sent {formatDate(employee.setup_sent_at)}. Password reset sent{" "}
            {formatDate(employee.password_reset_sent_at)}.
          </div>
          {/* BUG-048 (Hari 2026-05-11): admin matter-access section.
              Surfaces every matter in the company with this employee's
              effective access state and a one-click grant/revoke.
              Only meaningful for non-owner roles — owners always
              have full access by definition. */}
          {employee.role !== "owner" ? (
            <EmployeeMatterAccessPanel
              membershipId={employee.membership_id}
              displayName={employee.full_name}
            />
          ) : null}
          <EmployeeHistoryPanel
            events={auditQuery.data?.events ?? []}
            isPending={auditQuery.isPending}
            isError={auditQuery.isError}
          />
          <DialogFooter className="md:col-span-2">
            <Button type="button" variant="ghost" onClick={onClose} disabled={mutation.isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending} data-testid="edit-employee-submit">
              {mutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Saving
                </>
              ) : (
                "Save changes"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// BUG-048 (Hari 2026-05-11): admin matter-access panel inside the
// EditEmployeeDialog. Per row:
//   - "Restricted" tag when the matter has restricted_access on
//   - "Walled off" tag when an ethical wall excludes this employee
//     (overrides any grant — display only, no toggle here)
//   - "Assignee" tag when the employee is the matter's primary owner
//   - Grant/Revoke button when the matter is restricted
//   - "Open access" hint + "Restrict matter" button when the matter
//     is unrestricted (admin can flip restricted_access from here so
//     they don't have to navigate to the cockpit just to lock down a
//     single matter for one employee)
function EmployeeMatterAccessPanel({
  membershipId,
  displayName,
}: {
  membershipId: string;
  displayName: string;
}) {
  const queryClient = useQueryClient();
  const accessQuery = useQuery({
    queryKey: ["admin", "employees", membershipId, "matter-access"],
    queryFn: () => listEmployeeMatterAccess(membershipId),
  });
  const [pendingMatterId, setPendingMatterId] = useState<string | null>(null);

  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: ["admin", "employees", membershipId, "matter-access"],
    });

  const grantMutation = useMutation({
    mutationFn: (matterId: string) =>
      grantMatterAccess({
        matterId,
        membershipId,
        reason: `Granted from Admin > Employees > ${displayName}`,
      }),
    onMutate: (matterId) => setPendingMatterId(matterId),
    onSuccess: async () => {
      await invalidate();
      toast.success("Matter access granted.");
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not grant access.")),
    onSettled: () => setPendingMatterId(null),
  });

  const revokeMutation = useMutation({
    mutationFn: ({ matterId, grantId }: { matterId: string; grantId: string }) =>
      revokeMatterAccess({ matterId, grantId }),
    onMutate: ({ matterId }) => setPendingMatterId(matterId),
    onSuccess: async () => {
      await invalidate();
      toast.success("Matter access revoked.");
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not revoke access.")),
    onSettled: () => setPendingMatterId(null),
  });

  const restrictMutation = useMutation({
    mutationFn: (matterId: string) =>
      setMatterRestrictedAccess({ matterId, restricted: true }),
    onMutate: (matterId) => setPendingMatterId(matterId),
    onSuccess: async () => {
      await invalidate();
      toast.success("Matter is now restricted to explicit grants.");
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not turn on restricted access.")),
    onSettled: () => setPendingMatterId(null),
  });

  const matters = accessQuery.data?.matters ?? [];
  const restrictedCount = matters.filter((m) => m.restricted_access).length;
  const grantCount = matters.filter((m) => m.has_grant).length;
  const wallCount = matters.filter((m) => m.is_walled).length;

  return (
    <div className="md:col-span-2 rounded-md border border-[var(--color-line)]">
      <div className="flex items-center justify-between border-b border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-2">
        <div className="inline-flex items-center gap-2 text-sm font-semibold text-[var(--color-ink)]">
          Matter access
        </div>
        <span className="text-xs text-[var(--color-mute)]">
          {grantCount} explicit grant{grantCount === 1 ? "" : "s"} | {restrictedCount}{" "}
          restricted matter{restrictedCount === 1 ? "" : "s"}
          {wallCount > 0 ? ` | ${wallCount} walled` : ""}
        </span>
      </div>
      {accessQuery.isPending ? (
        <div className="p-3">
          <Skeleton className="h-20 w-full" />
        </div>
      ) : accessQuery.isError ? (
        <div className="px-3 py-4 text-sm text-[var(--color-danger-500)]">
          Could not load matter access.
        </div>
      ) : matters.length === 0 ? (
        <div className="px-3 py-4 text-sm text-[var(--color-mute)]">
          No matters in this company yet.
        </div>
      ) : (
        <div
          className="max-h-72 overflow-auto divide-y divide-[var(--color-line)]"
          data-testid="employee-matter-access-list"
        >
          {matters.map((row) => (
            <EmployeeMatterAccessRow
              key={row.matter_id}
              row={row}
              isPending={pendingMatterId === row.matter_id}
              onGrant={() => grantMutation.mutate(row.matter_id)}
              onRevoke={() =>
                row.grant_id &&
                revokeMutation.mutate({
                  matterId: row.matter_id,
                  grantId: row.grant_id,
                })
              }
              onRestrict={() => restrictMutation.mutate(row.matter_id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function EmployeeMatterAccessRow({
  row,
  isPending,
  onGrant,
  onRevoke,
  onRestrict,
}: {
  row: EmployeeMatterAccessRow;
  isPending: boolean;
  onGrant: () => void;
  onRevoke: () => void;
  onRestrict: () => void;
}) {
  return (
    <div
      className="grid gap-2 px-3 py-2 sm:grid-cols-[1fr_auto] sm:items-center"
      data-testid={`employee-matter-access-row-${row.matter_id}`}
    >
      <div className="min-w-0">
        <div className="text-sm font-medium text-[var(--color-ink)] truncate">
          {row.matter_code}
          <span className="ml-2 text-[var(--color-mute)]">{row.matter_title}</span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-[var(--color-mute)]">
          {row.is_walled ? (
            <span className="rounded-full bg-[var(--color-warn-50,#fff6e0)] px-2 py-0.5 text-[var(--color-warn-700,#9a4a00)]">
              Walled off (ethical wall)
            </span>
          ) : null}
          {row.is_assignee ? (
            <span className="rounded-full bg-[var(--color-bg-2)] px-2 py-0.5">
              Assignee
            </span>
          ) : null}
          {row.restricted_access ? (
            <span className="rounded-full bg-[var(--color-bg-2)] px-2 py-0.5">
              Restricted
            </span>
          ) : (
            <span>Open access — every member can see this matter.</span>
          )}
          {row.has_grant && !row.is_walled ? (
            <span
              className="rounded-full bg-[var(--color-brand-50,#eef2ff)] px-2 py-0.5 text-[var(--color-brand-700)]"
              data-testid={`employee-matter-access-granted-${row.matter_id}`}
            >
              Grant active
            </span>
          ) : null}
        </div>
      </div>
      <div className="flex justify-end gap-2">
        {row.is_walled ? (
          <span className="text-xs text-[var(--color-mute)]">
            Remove the wall in the matter cockpit to enable.
          </span>
        ) : row.restricted_access ? (
          row.has_grant ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={isPending}
              onClick={onRevoke}
              data-testid={`employee-matter-access-revoke-${row.matter_id}`}
            >
              {isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              ) : null}
              Revoke
            </Button>
          ) : (
            <Button
              type="button"
              size="sm"
              disabled={isPending}
              onClick={onGrant}
              data-testid={`employee-matter-access-grant-${row.matter_id}`}
            >
              {isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              ) : null}
              Grant access
            </Button>
          )
        ) : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={isPending}
            onClick={onRestrict}
            data-testid={`employee-matter-access-restrict-${row.matter_id}`}
          >
            {isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : null}
            Restrict matter
          </Button>
        )}
      </div>
    </div>
  );
}

function EmployeeHistoryPanel({
  events,
  isPending,
  isError,
}: {
  events: EmployeeAuditEvent[];
  isPending: boolean;
  isError: boolean;
}) {
  return (
    <div className="md:col-span-2 rounded-md border border-[var(--color-line)]">
      <div className="flex items-center justify-between border-b border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-2">
        <div className="inline-flex items-center gap-2 text-sm font-semibold text-[var(--color-ink)]">
          <History className="h-4 w-4" aria-hidden />
          Employee history
        </div>
        <span className="text-xs text-[var(--color-mute)]">{events.length} events</span>
      </div>
      {isPending ? (
        <div className="p-3">
          <Skeleton className="h-16 w-full" />
        </div>
      ) : isError ? (
        <div className="px-3 py-4 text-sm text-[var(--color-danger-500)]">
          Could not load employee history.
        </div>
      ) : events.length === 0 ? (
        <div className="px-3 py-4 text-sm text-[var(--color-mute)]">
          No employee history recorded yet.
        </div>
      ) : (
        <div className="max-h-56 overflow-auto divide-y divide-[var(--color-line)]">
          {events.slice(0, 40).map((event) => (
            <div key={event.id} className="grid gap-1 px-3 py-2 sm:grid-cols-[1fr_150px]">
              <div>
                <div className="text-sm font-medium text-[var(--color-ink)]">
                  {actionLabel(event.action)}
                </div>
                <div className="text-xs text-[var(--color-mute)]">
                  {event.actor_label || "System"} | {event.result}
                </div>
              </div>
              <div className="font-mono text-xs text-[var(--color-mute)] sm:text-right">
                {formatDate(event.created_at)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  id,
  children,
}: {
  label: string;
  id: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
    </div>
  );
}
