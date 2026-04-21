"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Inbox,
  Loader2,
  Plus,
  XCircle,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

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
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Textarea } from "@/components/ui/Textarea";
import { ApiError } from "@/lib/api/config";
import {
  createIntakeRequest,
  type IntakePriority,
  type IntakeRequest,
  type IntakeStatus,
  listIntakeRequests,
  promoteIntakeRequest,
  updateIntakeRequest,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

const STATUS_ORDER: IntakeStatus[] = [
  "new",
  "triaging",
  "in_progress",
  "completed",
  "rejected",
];

const STATUS_LABEL: Record<IntakeStatus, string> = {
  new: "New",
  triaging: "Triaging",
  in_progress: "In progress",
  completed: "Completed",
  rejected: "Rejected",
};

export default function IntakePage() {
  const canSubmit = useCapability("intake:submit");
  const canTriage = useCapability("intake:triage");
  const canPromote = useCapability("intake:promote");

  const [filter, setFilter] = useState<IntakeStatus | "all">("all");

  const queryKey = ["intake", "requests", filter];
  const listQuery = useQuery({
    queryKey,
    queryFn: () =>
      listIntakeRequests({
        status: filter === "all" ? null : filter,
      }),
    enabled: canSubmit,
  });

  const requests = listQuery.data?.requests ?? [];
  const counts = STATUS_ORDER.reduce<Record<IntakeStatus, number>>(
    (acc, key) => {
      acc[key] = requests.filter((r) => r.status === key).length;
      return acc;
    },
    { new: 0, triaging: 0, in_progress: 0, completed: 0, rejected: 0 },
  );

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Intake"
        title="Legal intake queue"
        description="Inbound requests from business units. Triage, assign, and promote to a matter when scope is clear."
        actions={canSubmit ? <NewIntakeDialog /> : null}
      />

      {!canSubmit ? (
        <EmptyState
          icon={Inbox}
          title="You don't have access to intake"
          description="Ask a workspace admin to grant the intake:submit capability."
        />
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-5">
            <StatusTile
              label="All"
              value={requests.length}
              active={filter === "all"}
              onClick={() => setFilter("all")}
            />
            {STATUS_ORDER.map((key) => (
              <StatusTile
                key={key}
                label={STATUS_LABEL[key]}
                value={counts[key]}
                active={filter === key}
                onClick={() => setFilter(key)}
              />
            ))}
          </section>

          {listQuery.isPending ? (
            <Skeleton className="h-64 w-full" />
          ) : listQuery.isError ? (
            <QueryErrorState
              title="Could not load intake queue"
              error={listQuery.error}
              onRetry={listQuery.refetch}
            />
          ) : requests.length === 0 ? (
            <EmptyState
              icon={Inbox}
              title={filter === "all" ? "No intake requests" : `Nothing in ${STATUS_LABEL[filter as IntakeStatus]}`}
              description={
                filter === "all"
                  ? "Business units file requests here; the legal team triages and promotes them to matters."
                  : "Adjust the filter above to see other statuses."
              }
              action={canSubmit ? <NewIntakeDialog /> : undefined}
            />
          ) : (
            <ul className="flex flex-col gap-2" data-testid="intake-request-list">
              {requests.map((request) => (
                <IntakeRow
                  key={request.id}
                  request={request}
                  canTriage={canTriage}
                  canPromote={canPromote}
                />
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function StatusTile({
  label,
  value,
  active,
  onClick,
}: {
  label: string;
  value: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-left transition-colors ${
        active
          ? "border-[var(--color-brand-500)] bg-[var(--color-brand-50)]"
          : "border-[var(--color-line)] bg-white hover:bg-[var(--color-bg-2)]"
      }`}
    >
      <span className="text-xs font-medium uppercase tracking-[0.06em] text-[var(--color-mute)]">
        {label}
      </span>
      <span className="tabular text-lg font-semibold text-[var(--color-ink)]">
        {value}
      </span>
    </button>
  );
}

function IntakeRow({
  request,
  canTriage,
  canPromote,
}: {
  request: IntakeRequest;
  canTriage: boolean;
  canPromote: boolean;
}) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [triageNotes, setTriageNotes] = useState(request.triage_notes ?? "");

  const updateMutation = useMutation({
    mutationFn: (partial: {
      status?: IntakeStatus;
      priority?: IntakePriority;
      triageNotes?: string;
    }) =>
      updateIntakeRequest({
        requestId: request.id,
        status: partial.status,
        priority: partial.priority,
        triageNotes: partial.triageNotes,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["intake", "requests"] });
      toast.success("Intake request updated.");
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Could not update request."),
  });

  const promoteMutation = useMutation({
    mutationFn: (matterCode: string) =>
      promoteIntakeRequest({ requestId: request.id, matterCode }),
    onSuccess: async (updated) => {
      await queryClient.invalidateQueries({ queryKey: ["intake", "requests"] });
      toast.success(`Promoted to matter ${updated.linked_matter_code}.`);
      setOpen(false);
      if (updated.linked_matter_id) {
        router.push(`/app/matters/${updated.linked_matter_id}`);
      }
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Could not promote request."),
  });

  const priorityColor: Record<IntakePriority, string> = {
    low: "bg-slate-100 text-slate-700 border-slate-200",
    medium: "bg-sky-50 text-sky-700 border-sky-200",
    high: "bg-amber-50 text-amber-800 border-amber-200",
    urgent: "bg-rose-50 text-rose-700 border-rose-200",
  };

  return (
    <li className="rounded-lg border border-[var(--color-line)] bg-white p-3">
      <button
        type="button"
        className="flex w-full items-start justify-between gap-3 text-left"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <StatusBadge status={request.status} />
            <span
              className={`inline-flex items-center rounded-full border px-2 py-0.5 font-medium capitalize ${priorityColor[request.priority]}`}
            >
              {request.priority}
            </span>
            <span className="text-[var(--color-mute)] capitalize">
              {request.category.replace(/_/g, " ")}
            </span>
            {request.linked_matter_code ? (
              <span className="font-mono text-[var(--color-brand-700)]">
                → {request.linked_matter_code}
              </span>
            ) : null}
          </div>
          <div className="mt-1 text-sm font-semibold text-[var(--color-ink)]">
            {request.title}
          </div>
          <div className="text-xs text-[var(--color-mute)]">
            {request.requester_name}
            {request.business_unit ? ` · ${request.business_unit}` : ""}
            {request.desired_by ? ` · wants it by ${request.desired_by}` : ""}
          </div>
        </div>
        <ArrowUpRight
          className={`h-4 w-4 shrink-0 text-[var(--color-mute)] transition-transform ${open ? "rotate-45" : ""}`}
          aria-hidden
        />
      </button>

      {open ? (
        <div className="mt-3 flex flex-col gap-3 border-t border-[var(--color-line-2)] pt-3">
          <p className="whitespace-pre-wrap text-sm text-[var(--color-ink-2)]">
            {request.description}
          </p>

          {canTriage ? (
            <div className="flex flex-wrap items-center gap-2">
              <Select
                value={request.status}
                onValueChange={(value) =>
                  updateMutation.mutate({ status: value as IntakeStatus })
                }
              >
                <SelectTrigger className="w-40" aria-label="Update status">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STATUS_ORDER.map((status) => (
                    <SelectItem key={status} value={status}>
                      {STATUS_LABEL[status]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={request.priority}
                onValueChange={(value) =>
                  updateMutation.mutate({ priority: value as IntakePriority })
                }
              >
                <SelectTrigger className="w-36" aria-label="Update priority">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="low">Low</SelectItem>
                  <SelectItem value="medium">Medium</SelectItem>
                  <SelectItem value="high">High</SelectItem>
                  <SelectItem value="urgent">Urgent</SelectItem>
                </SelectContent>
              </Select>
              {canPromote && !request.linked_matter_id ? (
                <PromoteButton
                  busy={promoteMutation.isPending}
                  onConfirm={(code) => promoteMutation.mutate(code)}
                  errorDetail={
                    promoteMutation.isError
                      ? (promoteMutation.error instanceof ApiError
                          ? promoteMutation.error.detail
                          : "Could not promote request.")
                      : null
                  }
                />
              ) : null}
            </div>
          ) : null}

          {canTriage ? (
            <div className="flex flex-col gap-1">
              <Label htmlFor={`triage-${request.id}`} className="text-xs">
                Triage notes
              </Label>
              <Textarea
                id={`triage-${request.id}`}
                rows={2}
                value={triageNotes}
                onChange={(event) => setTriageNotes(event.target.value)}
                onBlur={() => {
                  if (triageNotes !== (request.triage_notes ?? "")) {
                    updateMutation.mutate({ triageNotes });
                  }
                }}
                data-testid={`intake-triage-notes-${request.id}`}
              />
            </div>
          ) : request.triage_notes ? (
            <div className="text-xs text-[var(--color-mute)]">
              Triage notes: {request.triage_notes}
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function PromoteButton({
  busy,
  onConfirm,
  errorDetail,
}: {
  busy: boolean;
  onConfirm: (matterCode: string) => void;
  errorDetail: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");

  // Detect the "matter code already in use" backend error and auto-bump
  // the trailing index so one click suggests a free code. BUG-017 Hari
  // 2026-04-21: previously this error only fired as a toast and the
  // user had to manually retry.
  const codeInUse =
    errorDetail !== null && /already in use/i.test(errorDetail);
  const suggestion = codeInUse ? suggestNextMatterCode(code.trim()) : null;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" disabled={busy}>
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <CheckCircle2 className="h-4 w-4" aria-hidden />
          )}
          Promote to matter
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Promote intake to matter</DialogTitle>
          <DialogDescription>
            Pick a matter code. You can edit matter details (practice area, forum) on the matter page afterwards.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Label htmlFor="promote-matter-code">Matter code</Label>
          <Input
            id="promote-matter-code"
            value={code}
            onChange={(event) => setCode(event.target.value.toUpperCase())}
            placeholder="INT-2026-0001"
            aria-invalid={codeInUse ? true : undefined}
            data-testid="intake-promote-code"
          />
          {codeInUse ? (
            <div
              className="flex flex-col gap-2 rounded-md border border-[var(--color-warn-600)]/30 bg-[var(--color-warn-50)] p-2 text-xs text-[var(--color-warn-700)]"
              role="alert"
            >
              <span>
                Matter code <span className="font-mono">{code.trim()}</span> is already in use.
              </span>
              {suggestion ? (
                <button
                  type="button"
                  className="self-start rounded-md border border-[var(--color-warn-600)]/40 bg-white px-2 py-0.5 font-mono text-[var(--color-warn-700)] hover:bg-[var(--color-warn-50)]"
                  onClick={() => setCode(suggestion)}
                  data-testid="intake-promote-suggest"
                >
                  Try {suggestion}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            disabled={busy || code.trim().length < 2}
            onClick={() => onConfirm(code.trim())}
            data-testid="intake-promote-confirm"
          >
            Create matter
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}


/**
 * Given a matter code like `"CORP-ARB-99"`, suggest the next available
 * one by bumping the trailing numeric segment: `"CORP-ARB-100"`. If the
 * code has no trailing digits, append `-2`. Pure function — exported
 * for unit testing.
 */
export function suggestNextMatterCode(current: string): string | null {
  const trimmed = current.trim();
  if (trimmed.length < 2) return null;
  const match = /^(.*?)(\d+)$/.exec(trimmed);
  if (match) {
    const [, prefix, digits] = match;
    const next = String(Number(digits) + 1).padStart(digits.length, "0");
    return `${prefix}${next}`;
  }
  return `${trimmed}-2`;
}

const newIntakeSchema = z.object({
  title: z.string().min(3).max(255),
  category: z.enum([
    "contract_review",
    "policy_question",
    "litigation_support",
    "compliance",
    "employment",
    "ip_trademark",
    "m_and_a",
    "regulatory",
    "other",
  ]),
  priority: z.enum(["low", "medium", "high", "urgent"]),
  requester_name: z.string().min(2).max(255),
  requester_email: z.string().email().optional().or(z.literal("")),
  business_unit: z.string().max(120).optional().or(z.literal("")),
  description: z.string().min(10).max(8000),
  desired_by: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().or(z.literal("")),
});
type NewIntakeValues = z.infer<typeof newIntakeSchema>;

function NewIntakeDialog() {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const form = useForm<NewIntakeValues>({
    resolver: zodResolver(newIntakeSchema),
    defaultValues: {
      title: "",
      category: "contract_review",
      priority: "medium",
      requester_name: "",
      requester_email: "",
      business_unit: "",
      description: "",
      desired_by: "",
    },
  });

  const mutation = useMutation({
    mutationFn: (values: NewIntakeValues) =>
      createIntakeRequest({
        title: values.title.trim(),
        category: values.category,
        priority: values.priority,
        requesterName: values.requester_name.trim(),
        requesterEmail: values.requester_email?.trim() || null,
        businessUnit: values.business_unit?.trim() || null,
        description: values.description.trim(),
        desiredBy: values.desired_by || null,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["intake", "requests"] });
      toast.success("Intake request filed.");
      form.reset();
      setOpen(false);
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Could not file request."),
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" data-testid="new-intake-trigger">
          <Plus className="h-4 w-4" aria-hidden /> New request
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>File a new intake request</DialogTitle>
          <DialogDescription>
            The legal team will triage and decide whether to promote this to a
            matter.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-4"
          onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
          noValidate
          aria-label="New intake request"
        >
          <Field id="intake-title" label="Title" error={form.formState.errors.title?.message}>
            <Input id="intake-title" placeholder="Review vendor MSA" {...form.register("title")} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field id="intake-category" label="Category">
              <Select
                value={form.watch("category")}
                onValueChange={(value) =>
                  form.setValue("category", value as NewIntakeValues["category"])
                }
              >
                <SelectTrigger id="intake-category">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="contract_review">Contract review</SelectItem>
                  <SelectItem value="policy_question">Policy question</SelectItem>
                  <SelectItem value="litigation_support">Litigation support</SelectItem>
                  <SelectItem value="compliance">Compliance</SelectItem>
                  <SelectItem value="employment">Employment</SelectItem>
                  <SelectItem value="ip_trademark">IP / Trademark</SelectItem>
                  <SelectItem value="m_and_a">M&A</SelectItem>
                  <SelectItem value="regulatory">Regulatory</SelectItem>
                  <SelectItem value="other">Other</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field id="intake-priority" label="Priority">
              <Select
                value={form.watch("priority")}
                onValueChange={(value) =>
                  form.setValue("priority", value as NewIntakeValues["priority"])
                }
              >
                <SelectTrigger id="intake-priority">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="low">Low</SelectItem>
                  <SelectItem value="medium">Medium</SelectItem>
                  <SelectItem value="high">High</SelectItem>
                  <SelectItem value="urgent">Urgent</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field
              id="intake-requester-name"
              label="Your name"
              error={form.formState.errors.requester_name?.message}
            >
              <Input id="intake-requester-name" {...form.register("requester_name")} />
            </Field>
            <Field id="intake-business-unit" label="Business unit (optional)">
              <Input id="intake-business-unit" {...form.register("business_unit")} />
            </Field>
          </div>
          <Field
            id="intake-email"
            label="Email (optional)"
            error={form.formState.errors.requester_email?.message}
          >
            <Input
              id="intake-email"
              type="email"
              {...form.register("requester_email")}
            />
          </Field>
          <Field id="intake-desired-by" label="Desired by (optional)">
            <Input id="intake-desired-by" type="date" {...form.register("desired_by")} />
          </Field>
          <Field
            id="intake-description"
            label="Describe the request"
            error={form.formState.errors.description?.message}
          >
            <Textarea
              id="intake-description"
              rows={4}
              placeholder="Attach as much context as possible — vendor name, business goal, risk concerns…"
              {...form.register("description")}
            />
          </Field>

          <DialogFooter>
            <Button
              variant="ghost"
              type="button"
              onClick={() => setOpen(false)}
              disabled={mutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={mutation.isPending}
              data-testid="new-intake-submit"
            >
              {mutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Filing…
                </>
              ) : (
                "File request"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  id,
  label,
  error,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error ? (
        <p className="text-xs text-[var(--color-danger-500,#c53030)]" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

// Icon placeholders retained so `lucide-react` tree-shakes identically
// when the server-side rendering pass picks them up; they are referenced
// above in PromoteButton via CheckCircle2 and the warn/reject toasts
// surface the remaining semantics.
void AlertTriangle;
void XCircle;
