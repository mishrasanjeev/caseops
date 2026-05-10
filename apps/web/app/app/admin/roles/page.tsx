"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Save, ShieldCheck, Trash2, UserCog } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
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
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  assignEmployeeCustomRole,
  createCustomRole,
  deleteCustomRole,
  listCapabilityCatalog,
  listCustomRoles,
  listEmployees,
  updateCustomRole,
  type AssignableEmployeeRole,
  type CapabilityRecord,
  type CustomRoleRecord,
} from "@/lib/api/endpoints";
import { useCapability, useRole } from "@/lib/capabilities";

const BASE_ROLE_OPTIONS: Array<{ value: AssignableEmployeeRole | ""; label: string }> = [
  { value: "", label: "No base role" },
  { value: "admin", label: "Admin" },
  { value: "partner", label: "Partner" },
  { value: "member", label: "Member" },
  { value: "paralegal", label: "Paralegal" },
  { value: "viewer", label: "Viewer" },
];

function capabilityKey(capability: CapabilityRecord): string {
  return `${capability.group}:${capability.capability}`;
}

// Treats a missing `custom_role_delegable` as delegable (true) for
// backward compat with older API responses. A capability is protected
// when the API says it is non-delegable OR when it is owner-only.
function isCapabilityProtected(capability: CapabilityRecord): boolean {
  if (capability.owner_only) return true;
  if (capability.custom_role_delegable === false) return true;
  return false;
}

function capabilityLabelSuffix(capability: CapabilityRecord): string {
  if (capability.owner_only) return " (owner only)";
  if (capability.custom_role_delegable === false) return " (protected)";
  return "";
}

function roleSummary(role: CustomRoleRecord): string {
  if (!role.permissions.length) return "No permissions";
  const preview = role.permissions.slice(0, 3).join(", ");
  return role.permissions.length > 3
    ? `${preview} +${role.permissions.length - 3}`
    : preview;
}

export default function RolesAdminPage() {
  const canManageUsers = useCapability("company:manage_users");
  const actorRole = useRole();
  const queryClient = useQueryClient();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [baseRole, setBaseRole] = useState<AssignableEmployeeRole | "">("");
  const [permissions, setPermissions] = useState<Set<string>>(new Set());
  const [membershipId, setMembershipId] = useState("");
  const [assignmentRoleId, setAssignmentRoleId] = useState("");

  const capabilitiesQuery = useQuery({
    queryKey: ["admin", "capabilities"],
    queryFn: listCapabilityCatalog,
    enabled: canManageUsers,
  });
  const rolesQuery = useQuery({
    queryKey: ["admin", "custom-roles"],
    queryFn: () => listCustomRoles(),
    enabled: canManageUsers,
  });
  const employeesQuery = useQuery({
    queryKey: ["admin", "employees", "roles"],
    queryFn: () => listEmployees({}),
    enabled: canManageUsers,
  });

  const groupedCapabilities = useMemo(() => {
    const groups = new Map<string, CapabilityRecord[]>();
    for (const cap of capabilitiesQuery.data?.capabilities ?? []) {
      const rows = groups.get(cap.group) ?? [];
      rows.push(cap);
      groups.set(cap.group, rows);
    }
    return Array.from(groups.entries()).map(([group, rows]) => [
      group,
      rows.sort((a, b) => capabilityKey(a).localeCompare(capabilityKey(b))),
    ] as const);
  }, [capabilitiesQuery.data?.capabilities]);

  // Defence-in-depth: even if the disabled state is bypassed (browser
  // devtools, stale cache, future component refactor), strip protected
  // capabilities from the submit payload so the backend never has to
  // emit a 403 on a path the user could have completed via the UI.
  // The backend's `validate_custom_role_permissions` is still the
  // authoritative gate; this is belt-and-braces.
  const delegableCapabilitySet = useMemo(() => {
    const set = new Set<string>();
    for (const cap of capabilitiesQuery.data?.capabilities ?? []) {
      if (!isCapabilityProtected(cap)) set.add(cap.capability);
    }
    return set;
  }, [capabilitiesQuery.data?.capabilities]);

  const sanitizedPermissions = useMemo(
    () => Array.from(permissions).filter((permission) => delegableCapabilitySet.has(permission)),
    [permissions, delegableCapabilitySet],
  );

  const roles = rolesQuery.data?.roles ?? [];
  const assignableRoles = roles.filter((role) => role.is_active);
  const employees = employeesQuery.data?.employees ?? [];
  const editingRole = editingId ? roles.find((role) => role.id === editingId) ?? null : null;

  const resetEditor = () => {
    setEditingId(null);
    setName("");
    setDescription("");
    setBaseRole("");
    setPermissions(new Set());
  };

  const loadRole = (role: CustomRoleRecord) => {
    setEditingId(role.id);
    setName(role.name);
    setDescription(role.description ?? "");
    setBaseRole(role.base_role ?? "");
    setPermissions(new Set(role.permissions));
  };

  const createMutation = useMutation({
    mutationFn: () =>
      createCustomRole({
        name: name.trim(),
        description: description.trim() || null,
        baseRole: baseRole || null,
        permissions: sanitizedPermissions,
      }),
    onSuccess: async () => {
      toast.success("Custom role created.");
      resetEditor();
      await queryClient.invalidateQueries({ queryKey: ["admin", "custom-roles"] });
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not create role.")),
  });

  const updateMutation = useMutation({
    mutationFn: () => {
      if (!editingId) throw new Error("Select a role first.");
      return updateCustomRole({
        roleId: editingId,
        name: name.trim(),
        description: description.trim() || null,
        baseRole: baseRole || null,
        permissions: sanitizedPermissions,
      });
    },
    onSuccess: async () => {
      toast.success("Custom role updated. Assigned users must refresh their session.");
      await queryClient.invalidateQueries({ queryKey: ["admin", "custom-roles"] });
      await queryClient.invalidateQueries({ queryKey: ["admin", "employees"] });
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not update role.")),
  });

  const deleteMutation = useMutation({
    mutationFn: (roleId: string) => deleteCustomRole(roleId),
    onSuccess: async () => {
      toast.success("Custom role revoked.");
      resetEditor();
      await queryClient.invalidateQueries({ queryKey: ["admin", "custom-roles"] });
      await queryClient.invalidateQueries({ queryKey: ["admin", "employees"] });
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not revoke role.")),
  });

  const assignMutation = useMutation({
    mutationFn: () =>
      assignEmployeeCustomRole({
        membershipId,
        customRoleId: assignmentRoleId || null,
      }),
    onSuccess: async () => {
      toast.success("Employee custom role updated.");
      setMembershipId("");
      setAssignmentRoleId("");
      await queryClient.invalidateQueries({ queryKey: ["admin", "employees"] });
      await queryClient.invalidateQueries({ queryKey: ["admin", "custom-roles"] });
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not assign custom role.")),
  });

  const pending =
    createMutation.isPending ||
    updateMutation.isPending ||
    deleteMutation.isPending ||
    assignMutation.isPending;
  const canSubmitRole =
    name.trim().length >= 2 && sanitizedPermissions.length > 0 && !pending;
  const canClearCustomRole = actorRole === "owner";
  const canSubmitAssignment =
    Boolean(membershipId) && (canClearCustomRole || Boolean(assignmentRoleId)) && !pending;

  if (!canManageUsers) {
    return (
      <EmptyState
        icon={ShieldCheck}
        title="You don't have access to manage role templates"
        description="Ask a workspace owner or admin for company:manage_users."
      />
    );
  }

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
        title="Custom role templates"
        description="Create tenant-scoped templates over approved server capabilities. Owner-only powers remain fixed to owners."
        actions={
          <Link
            href="/app/admin/employees"
            className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-line)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
          >
            <UserCog className="h-4 w-4" aria-hidden /> Employees
          </Link>
        }
      />

      {capabilitiesQuery.isPending || rolesQuery.isPending || employeesQuery.isPending ? (
        <Skeleton className="h-96 w-full" />
      ) : capabilitiesQuery.isError || rolesQuery.isError || employeesQuery.isError ? (
        <QueryErrorState
          title="Could not load custom role controls"
          error={capabilitiesQuery.error ?? rolesQuery.error ?? employeesQuery.error}
          onRetry={() => {
            void capabilitiesQuery.refetch();
            void rolesQuery.refetch();
            void employeesQuery.refetch();
          }}
        />
      ) : (
        <div className="grid gap-6 xl:grid-cols-[minmax(260px,360px)_minmax(0,1fr)]">
          <Card>
            <CardHeader>
              <CardTitle as="h2">Templates</CardTitle>
              <CardDescription>
                One active custom role can replace a non-owner employee's fixed role capabilities.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {roles.length === 0 ? (
                <p className="text-sm text-[var(--color-mute)]">
                  No custom roles yet. Create the first template from the matrix.
                </p>
              ) : (
                roles.map((role) => (
                  <button
                    key={role.id}
                    type="button"
                    className={`rounded-md border px-3 py-2 text-left text-sm ${
                      editingId === role.id
                        ? "border-[var(--color-brand-700)] bg-[var(--color-bg-2)]"
                        : "border-[var(--color-line)] bg-white hover:bg-[var(--color-bg-2)]"
                    }`}
                    onClick={() => loadRole(role)}
                    data-testid={`custom-role-${role.slug}`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-medium text-[var(--color-ink)]">{role.name}</span>
                      <Badge tone={role.assigned_count > 0 ? "brand" : "neutral"}>
                        {role.assigned_count} assigned
                      </Badge>
                    </div>
                    <div className="mt-1 text-xs text-[var(--color-mute)]">
                      {roleSummary(role)}
                    </div>
                  </button>
                ))
              )}
              <Button type="button" variant="ghost" onClick={resetEditor} data-testid="custom-role-new">
                <Plus className="h-4 w-4" aria-hidden /> New role
              </Button>
            </CardContent>
          </Card>

          <div className="flex flex-col gap-6">
            <Card>
              <CardHeader>
                <CardTitle as="h2">{editingRole ? "Edit role" : "Create role"}</CardTitle>
                <CardDescription>
                  Unknown, inactive, revoked, and owner-only permissions fail closed on the server.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <form
                  className="flex flex-col gap-4"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (editingRole) updateMutation.mutate();
                    else createMutation.mutate();
                  }}
                >
                  <div className="grid gap-3 md:grid-cols-[minmax(220px,1fr)_180px]">
                    <label className="flex flex-col gap-1.5">
                      <Label htmlFor="custom-role-name">Role name</Label>
                      <Input
                        id="custom-role-name"
                        value={name}
                        onChange={(event) => setName(event.target.value)}
                        placeholder="Litigation reviewer"
                        data-testid="custom-role-name"
                      />
                    </label>
                    <label className="flex flex-col gap-1.5">
                      <Label htmlFor="custom-role-base">Base role label</Label>
                      <select
                        id="custom-role-base"
                        value={baseRole}
                        onChange={(event) =>
                          setBaseRole(event.target.value as AssignableEmployeeRole | "")
                        }
                        className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm"
                        data-testid="custom-role-base"
                      >
                        {BASE_ROLE_OPTIONS.map((option) => (
                          <option key={option.value || "none"} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <label className="flex flex-col gap-1.5">
                    <Label htmlFor="custom-role-description">Description</Label>
                    <Textarea
                      id="custom-role-description"
                      value={description}
                      onChange={(event) => setDescription(event.target.value)}
                      placeholder="Who should receive this template and why"
                      data-testid="custom-role-description"
                    />
                  </label>

                  <div className="grid gap-3 lg:grid-cols-2">
                    {groupedCapabilities.map(([group, rows]) => (
                      <fieldset
                        key={group}
                        className="rounded-md border border-[var(--color-line)] p-3"
                      >
                        <legend className="px-1 text-sm font-semibold text-[var(--color-ink)]">
                          {group}
                        </legend>
                        <div className="mt-2 grid gap-2">
                          {rows.map((capability) => {
                            const checked = permissions.has(capability.capability);
                            const protectedCapability = isCapabilityProtected(capability);
                            const labelSuffix = capabilityLabelSuffix(capability);
                            const reason = capability.protected_reason;
                            return (
                              <label
                                key={capability.capability}
                                className={`flex items-start gap-2 text-sm ${
                                  protectedCapability
                                    ? "text-[var(--color-mute)]"
                                    : "text-[var(--color-ink)]"
                                }`}
                                title={reason ?? undefined}
                              >
                                <input
                                  type="checkbox"
                                  className="mt-1"
                                  checked={checked && !protectedCapability}
                                  disabled={protectedCapability}
                                  aria-describedby={
                                    protectedCapability
                                      ? `capability-${capability.capability}-reason`
                                      : undefined
                                  }
                                  onChange={(event) => {
                                    if (protectedCapability) return;
                                    const next = new Set(permissions);
                                    if (event.target.checked) next.add(capability.capability);
                                    else next.delete(capability.capability);
                                    setPermissions(next);
                                  }}
                                  data-testid={`capability-${capability.capability}`}
                                />
                                <span>
                                  <span className="block font-medium">
                                    {capability.label}
                                    {labelSuffix}
                                  </span>
                                  <span className="block font-mono text-xs text-[var(--color-mute)]">
                                    {capability.capability}
                                  </span>
                                  {protectedCapability && reason ? (
                                    <span
                                      id={`capability-${capability.capability}-reason`}
                                      className="block text-xs text-[var(--color-mute)]"
                                      data-testid={`capability-${capability.capability}-reason`}
                                    >
                                      {reason}
                                    </span>
                                  ) : null}
                                </span>
                              </label>
                            );
                          })}
                        </div>
                      </fieldset>
                    ))}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button type="submit" disabled={!canSubmitRole} data-testid="custom-role-save">
                      {pending ? (
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                      ) : editingRole ? (
                        <Save className="h-4 w-4" aria-hidden />
                      ) : (
                        <Plus className="h-4 w-4" aria-hidden />
                      )}
                      {editingRole ? "Save role" : "Create role"}
                    </Button>
                    {editingRole ? (
                      <Button
                        type="button"
                        variant="ghost"
                        disabled={pending}
                        onClick={() => deleteMutation.mutate(editingRole.id)}
                        data-testid="custom-role-revoke"
                      >
                        <Trash2 className="h-4 w-4" aria-hidden /> Revoke
                      </Button>
                    ) : null}
                  </div>
                </form>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle as="h2">Assign to employee</CardTitle>
                <CardDescription>
                  Assignment revokes stale sessions so the next request uses server-resolved capabilities.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <form
                  className="grid gap-3 md:grid-cols-[minmax(220px,1fr)_minmax(220px,1fr)_auto]"
                  onSubmit={(event) => {
                    event.preventDefault();
                    assignMutation.mutate();
                  }}
                >
                  <label className="flex flex-col gap-1.5">
                    <span className="text-xs font-medium text-[var(--color-mute)]">
                      Employee
                    </span>
                    <select
                      value={membershipId}
                      onChange={(event) => setMembershipId(event.target.value)}
                      className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm"
                      data-testid="custom-role-employee"
                    >
                      <option value="">Select employee</option>
                      {employees
                        .filter((employee) => employee.role !== "owner")
                        .map((employee) => (
                          <option key={employee.membership_id} value={employee.membership_id}>
                            {employee.full_name} - {employee.email}
                            {employee.custom_role_name ? ` (${employee.custom_role_name})` : ""}
                          </option>
                        ))}
                    </select>
                  </label>
                  <label className="flex flex-col gap-1.5">
                    <span className="text-xs font-medium text-[var(--color-mute)]">
                      Custom role
                    </span>
                    <select
                      value={assignmentRoleId}
                      onChange={(event) => setAssignmentRoleId(event.target.value)}
                      className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm"
                      data-testid="custom-role-assignment"
                    >
                      {canClearCustomRole ? (
                        <option value="">Use fixed role capabilities</option>
                      ) : null}
                      {assignableRoles.map((role) => (
                        <option key={role.id} value={role.id}>
                          {role.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="flex items-end">
                    <Button
                      type="submit"
                      disabled={!canSubmitAssignment}
                      data-testid="custom-role-assign"
                    >
                      {assignMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                      ) : (
                        <UserCog className="h-4 w-4" aria-hidden />
                      )}
                      Apply
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
