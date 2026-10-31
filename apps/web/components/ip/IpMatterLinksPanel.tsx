"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowUpRight, Link2, Plus, Unlink, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { MatterPicker } from "@/components/app/MatterPicker";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { Label } from "@/components/ui/Label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { API_FORM_ERROR_KEY, apiErrorMessage, apiFieldErrors } from "@/lib/api/config";
import {
  createIpDocketMatterLink,
  fetchIpDocketMatterLinks,
  fetchIpDocket,
  fetchMatterIpLinks,
  retireIpDocketMatterLink,
  type IpDocket,
  type IpMatterLink,
  type IpMatterRelationRole,
} from "@/lib/api/endpoints";
import type { Matter } from "@/lib/api/schemas";
import { useSequencedQuerySettled } from "@/lib/use-sequenced-query-settled";

const ROLES: Array<{ value: IpMatterRelationRole; label: string }> = [
  { value: "operational", label: "Operational" },
  { value: "litigation", label: "Litigation" },
  { value: "advisory", label: "Advisory" },
  { value: "appeal", label: "Appeal" },
  { value: "enforcement", label: "Enforcement" },
  { value: "billing", label: "Billing" },
  { value: "other", label: "Other" },
];

// services/matter_operational_guard.py matter_is_operational: only these
// lifecycle states may become the operational Matter.
const OPERATIONAL_MATTER_STATUSES = new Set(["intake", "active", "on_hold"]);

const LINK_FIELD_IDS = {
  matter_id: "ip-link-matter",
  relation_role: "ip-link-role",
  reason: "ip-link-reason",
} as const;

function titleCase(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function IpMatterLinksPanel({
  docket,
  canWrite,
  onChanged,
}: {
  docket: IpDocket;
  canWrite: boolean;
  onChanged: () => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [matterId, setMatterId] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [relationRole, setRelationRole] =
    useState<IpMatterRelationRole>("litigation");
  const [reason, setReason] = useState("");
  const [retiringId, setRetiringId] = useState<string | null>(null);
  const [retirementReason, setRetirementReason] = useState("");
  const links = useQuery({
    queryKey: ["ip", "dockets", docket.id, "matter-links"],
    queryFn: () => fetchIpDocketMatterLinks(docket.id),
  });
  const activeOperational = links.data?.links.some(
    (link) => link.relation_role === "operational" && link.retired_at === null,
  );
  // Mirrors services/ip_matter_links.py create_matter_link: the picker lists
  // what the write would refuse as disabled, with the reason.
  const matterDisabledReason = (matter: Matter): string | null => {
    if (
      links.data?.links.some(
        (link) =>
          link.matter_id === matter.id &&
          link.relation_role === relationRole &&
          link.retired_at === null,
      )
    ) {
      return `already linked as ${titleCase(relationRole)}`;
    }
    if (relationRole !== "operational") return null;
    if (!OPERATIONAL_MATTER_STATUSES.has(matter.status)) {
      return `${titleCase(matter.status)} Matters cannot be operational`;
    }
    if (docket.matter_id && docket.matter_id !== matter.id) {
      return "another Matter is this record's operational Matter";
    }
    return null;
  };
  const fieldError = (key: keyof typeof LINK_FIELD_IDS) => fieldErrors[LINK_FIELD_IDS[key]] ?? null;
  const fieldIds: string[] = Object.values(LINK_FIELD_IDS);
  const formError = Object.entries(fieldErrors)
    .filter(([key]) => !fieldIds.includes(key))
    .map(([key, message]) => (key === API_FORM_ERROR_KEY ? message : `${titleCase(key)}: ${message}`))
    .join(" ");
  const clearFieldError = (key: keyof typeof LINK_FIELD_IDS) =>
    setFieldErrors((current) => {
      const next = { ...current };
      delete next[LINK_FIELD_IDS[key]];
      return next;
    });
  const reasonTooShort = reason.trim().length < 8;

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["ip", "dockets", docket.id, "matter-links"],
      }),
      queryClient.invalidateQueries({ queryKey: ["ip", "dockets", docket.id] }),
      queryClient.invalidateQueries({ queryKey: ["ip", "dockets"] }),
    ]);
    await onChanged();
  }

  const createLink = useMutation({
    mutationFn: async () => {
      const current = await fetchIpDocket(docket.id);
      return createIpDocketMatterLink({
        docketId: docket.id,
        matterId,
        relationRole,
        reason: reason.trim(),
        expectedDocketUpdatedAt: current.updated_at,
      });
    },
    onSuccess: async () => {
      toast.success("Matter relationship added.");
      setShowCreate(false);
      setMatterId("");
      setReason("");
      setFieldErrors({});
      await refresh();
    },
    onError: (error) => {
      const message = apiErrorMessage(error, "Could not add the Matter relationship.");
      const fields = apiFieldErrors(error, LINK_FIELD_IDS);
      setFieldErrors(Object.keys(fields).length ? fields : { [API_FORM_ERROR_KEY]: message });
      toast.error(message);
    },
  });
  const retireLink = useMutation({
    mutationFn: async (link: IpMatterLink) => {
      const current = await fetchIpDocket(docket.id);
      return retireIpDocketMatterLink({
        docketId: docket.id,
        linkId: link.id,
        reason: retirementReason.trim(),
        expectedLinkUpdatedAt: link.updated_at,
        expectedDocketUpdatedAt: current.updated_at,
      });
    },
    onSuccess: async () => {
      toast.success("Matter relationship retired.");
      setRetiringId(null);
      setRetirementReason("");
      await refresh();
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not retire the Matter relationship.")),
  });

  return (
    <Card className="min-w-0" data-testid="ip-matter-links-panel">
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle as="h3">Matter relationships</CardTitle>
          <CardDescription>Effective-dated roles with independent lifecycle states.</CardDescription>
        </div>
        {canWrite ? (
          <Button
            size="sm"
            variant={showCreate ? "ghost" : "outline"}
            onClick={() => setShowCreate((value) => !value)}
          >
            {showCreate ? <X className="h-4 w-4" aria-hidden /> : <Plus className="h-4 w-4" aria-hidden />}
            {showCreate ? "Close" : "Link Matter"}
          </Button>
        ) : null}
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-4">
        {showCreate ? (
          <form
            className="grid min-w-0 gap-4 border-b border-[var(--color-line)] pb-4"
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              setFieldErrors({});
              createLink.mutate();
            }}
          >
            <MatterPicker
              id="ip-link-matter"
              label="Matter"
              searchLabel="Search Matters"
              value={matterId}
              onChange={(next) => {
                setMatterId(next);
                clearFieldError("matter_id");
              }}
              disabledReason={matterDisabledReason}
              error={fieldError("matter_id")}
              required
            />
            <div className="min-w-0 sm:max-w-xs">
              <Label htmlFor="ip-link-role">Role</Label>
              <Select
                value={relationRole}
                onValueChange={(value) => {
                  setRelationRole(value as IpMatterRelationRole);
                  setMatterId("");
                  clearFieldError("relation_role");
                }}
              >
                <SelectTrigger
                  id="ip-link-role"
                  className="mt-1 w-full"
                  aria-invalid={fieldError("relation_role") ? true : undefined}
                  aria-describedby={fieldError("relation_role") ? "ip-link-role-error" : undefined}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ROLES.map((role) => (
                    <SelectItem
                      key={role.value}
                      value={role.value}
                      disabled={role.value === "operational" && activeOperational}
                    >
                      {role.value === "operational" && activeOperational
                        ? `${role.label} (retire the current operational link first)`
                        : role.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {fieldError("relation_role") ? (
                <p id="ip-link-role-error" className="mt-1 text-sm text-[var(--color-danger-500)]">
                  {fieldError("relation_role")}
                </p>
              ) : null}
            </div>
            <div className="min-w-0">
              <Label htmlFor="ip-link-reason">Reason</Label>
              <Textarea
                id="ip-link-reason"
                className="mt-1"
                value={reason}
                maxLength={2000}
                required
                aria-invalid={fieldError("reason") ? true : undefined}
                aria-describedby={["ip-link-reason-hint", fieldError("reason") ? "ip-link-reason-error" : null]
                  .filter(Boolean)
                  .join(" ")}
                onChange={(event) => {
                  setReason(event.target.value);
                  clearFieldError("reason");
                }}
              />
              <p id="ip-link-reason-hint" className="mt-1 text-xs text-[var(--color-mute)]">
                At least 8 characters. Recorded in the audit trail.
              </p>
              {fieldError("reason") ? (
                <p id="ip-link-reason-error" className="mt-1 text-sm text-[var(--color-danger-500)]">
                  {fieldError("reason")}
                </p>
              ) : null}
            </div>
            {formError ? (
              <p role="alert" className="min-w-0 break-words text-sm text-[var(--color-danger-500)]">
                {formError}
              </p>
            ) : null}
            <div className="flex min-w-0 flex-wrap items-center gap-3">
              <Button
                type="submit"
                size="sm"
                className="whitespace-nowrap"
                disabled={!matterId || reasonTooShort || createLink.isPending}
              >
                <Link2 className="h-4 w-4" aria-hidden />
                {createLink.isPending ? "Adding relationship…" : "Add relationship"}
              </Button>
              {!matterId || reasonTooShort ? (
                <span className="text-xs text-[var(--color-mute)]">
                  {!matterId ? "Choose a Matter" : "Give a reason of at least 8 characters"} to add the relationship.
                </span>
              ) : null}
            </div>
          </form>
        ) : null}

        {links.isPending ? (
          <p className="text-sm text-[var(--color-mute)]" role="status">Loading relationships…</p>
        ) : links.isError ? (
          <Button variant="secondary" onClick={() => links.refetch()}>Retry relationships</Button>
        ) : links.data.links.length === 0 ? (
          <p className="text-sm text-[var(--color-mute)]">No Matter relationships.</p>
        ) : (
          <ul className="flex min-w-0 flex-col gap-3">
            {links.data.links.map((link) => (
              <li
                key={link.id}
                className={`min-w-0 border-b border-[var(--color-line)] pb-3 last:border-0 last:pb-0 ${link.retired_at ? "opacity-70" : ""}`}
              >
                <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <Link
                        href={`/app/matters/${link.matter_id}`}
                        className="break-words text-sm font-semibold text-[var(--color-brand-700)] hover:underline"
                      >
                        {link.lifecycle.matter_code} - {link.lifecycle.matter_title}
                      </Link>
                      <Badge tone="neutral">{titleCase(link.relation_role)}</Badge>
                      {link.retired_at ? <Badge tone="neutral">Retired</Badge> : null}
                    </div>
                    <p className="mt-1 break-words text-xs text-[var(--color-mute)]">{link.reason}</p>
                    {link.retirement_reason ? (
                      <p className="mt-1 break-words text-xs text-[var(--color-mute)]">
                        Retirement: {link.retirement_reason}
                      </p>
                    ) : null}
                  </div>
                  {!link.retired_at && canWrite ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setRetiringId(link.id)}
                    >
                      <Unlink className="h-4 w-4" aria-hidden /> Retire
                    </Button>
                  ) : null}
                </div>
                <div className="mt-3 grid min-w-0 gap-2 sm:grid-cols-2">
                  <div className="min-w-0 rounded-md border border-[var(--color-line)] px-3 py-2">
                    <div className="text-xs font-medium text-[var(--color-mute)]">Matter lifecycle</div>
                    <div className="mt-1 break-words text-sm font-semibold">{titleCase(link.lifecycle.matter_status)}</div>
                  </div>
                  <div className="min-w-0 rounded-md border border-[var(--color-line)] px-3 py-2">
                    <div className="text-xs font-medium text-[var(--color-mute)]">IP lifecycle</div>
                    <div className="mt-1 break-words text-sm font-semibold">{titleCase(link.lifecycle.docket_status)}</div>
                  </div>
                </div>
                {link.access_mismatch_warning ? (
                  <div className="mt-2 flex items-start gap-2 text-xs text-amber-800" role="status">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                    Matter and IP access policies differ.
                  </div>
                ) : null}
                {retiringId === link.id ? (
                  <div className="mt-3 flex min-w-0 flex-col gap-2 sm:flex-row sm:items-end">
                    <div className="min-w-0 flex-1">
                      <Label htmlFor={`retire-${link.id}`}>Retirement reason</Label>
                      <Textarea
                        id={`retire-${link.id}`}
                        className="mt-1"
                        value={retirementReason}
                        onChange={(event) => setRetirementReason(event.target.value)}
                      />
                    </div>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={retirementReason.trim().length < 8 || retireLink.isPending}
                        onClick={() => retireLink.mutate(link)}
                      >
                        <Unlink className="h-4 w-4" aria-hidden /> Retire
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setRetiringId(null)}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export function MatterIpLinksPanel({
  matterId,
  loadEnabled = true,
  onLoadSettled,
}: {
  matterId: string;
  loadEnabled?: boolean;
  onLoadSettled?: () => void;
}) {
  const links = useQuery({
    queryKey: ["matters", matterId, "ip-links"],
    queryFn: ({ signal }) => fetchMatterIpLinks(matterId, { signal }),
    enabled: loadEnabled,
  });
  useSequencedQuerySettled({
    enabled: loadEnabled,
    identity: matterId,
    settled: links.isFetched,
    onSettled: onLoadSettled,
  });
  if (!links.isPending && !links.isError && links.data.links.length === 0) return null;
  return (
    <Card className="min-w-0 lg:col-span-3" data-testid="matter-ip-links-panel">
      <CardHeader>
        <CardTitle>Linked IP records</CardTitle>
        <CardDescription>Independent Matter and IP lifecycle states.</CardDescription>
      </CardHeader>
      <CardContent>
        {links.isPending ? (
          <p className="text-sm text-[var(--color-mute)]" role="status">Loading linked IP records…</p>
        ) : links.isError ? (
          <Button variant="secondary" onClick={() => links.refetch()}>Retry linked IP records</Button>
        ) : (
          <ul className="grid min-w-0 gap-3 md:grid-cols-2">
            {links.data.links.map((link) => (
              <li key={link.id} className="min-w-0 rounded-md border border-[var(--color-line)] p-3">
                <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="break-words text-sm font-semibold">{link.lifecycle.docket_title}</div>
                    <div className="mt-1 flex flex-wrap gap-2">
                      <Badge tone="neutral">{titleCase(link.relation_role)}</Badge>
                      {link.retired_at ? <Badge tone="neutral">Retired</Badge> : null}
                    </div>
                  </div>
                  <Button href={`/app/ip?docket=${link.docket_id}`} size="sm" variant="ghost">
                    <ArrowUpRight className="h-4 w-4" aria-hidden /> Open IP
                  </Button>
                </div>
                <div className="mt-3 grid min-w-0 grid-cols-2 gap-2 text-xs">
                  <div className="min-w-0"><span className="text-[var(--color-mute)]">Matter</span><strong className="mt-1 block break-words">{titleCase(link.lifecycle.matter_status)}</strong></div>
                  <div className="min-w-0"><span className="text-[var(--color-mute)]">IP</span><strong className="mt-1 block break-words">{titleCase(link.lifecycle.docket_status)}</strong></div>
                </div>
                {link.access_mismatch_warning ? (
                  <div className="mt-2 flex items-center gap-2 text-xs text-amber-800">
                    <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden /> Access policies differ
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
