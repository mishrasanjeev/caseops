"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/Button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import {
  EMPTY_FORUM_SELECTION,
  ForumSelector,
  forumSelectionFromEntry,
  isConsumerDistrictFallbackForumSelection,
  isDistrictFallbackForumSelection,
  isLegacyForumSelection,
  type ForumSelection,
} from "@/components/matters/ForumSelector";
import { apiErrorMessage } from "@/lib/api/config";
import { createMatter, fetchForumCatalog } from "@/lib/api/endpoints";
import {
  MATTER_CODE_MESSAGE,
  normalizeMatterCodeInput,
} from "@/lib/matter-code";

const schema = z.object({
  title: z.string().min(3, "At least 3 characters."),
  matter_code: z
    .string()
    .transform((value) => normalizeMatterCodeInput(value))
    .pipe(
      z
        .string()
        .min(2, "At least 2 characters.")
        .max(40, "Keep it short and unique.")
        .regex(/^[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])$/, MATTER_CODE_MESSAGE),
    ),
  practice_area: z.string().min(2, "Practice area helps classify the work."),
  client_name: z.string().optional(),
  opposing_party: z.string().optional(),
  status: z.enum(["intake", "active", "on_hold", "disposed"]),
  description: z.string().max(2000).optional(),
});

type FormValues = z.infer<typeof schema>;

const STATUSES: { value: FormValues["status"]; label: string }[] = [
  { value: "intake", label: "Intake" },
  { value: "active", label: "Active" },
  { value: "on_hold", label: "On hold" },
  { value: "disposed", label: "Dispose" },
];

export function NewMatterDialog() {
  const [open, setOpen] = useState(false);
  const [forumSelection, setForumSelection] =
    useState<ForumSelection>(EMPTY_FORUM_SELECTION);
  const queryClient = useQueryClient();
  const forumCatalogQuery = useQuery({
    queryKey: ["courts", "forum-catalog"],
    queryFn: fetchForumCatalog,
    enabled: open,
  });
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: "",
      matter_code: "",
      client_name: "",
      opposing_party: "",
      practice_area: "",
      status: "intake",
      description: "",
    },
  });
  const forumCatalogEntries = forumCatalogQuery.data?.entries ?? [];
  const forumCatalogEmpty =
    forumCatalogQuery.isSuccess && forumCatalogEntries.length === 0;
  const forumCatalogFailed = forumCatalogQuery.isError;
  const forumCatalogUnavailable = forumCatalogFailed || forumCatalogEmpty;
  const legacyFallbackSelected = isLegacyForumSelection(forumSelection);
  const legacyFallbackIncomplete =
    forumCatalogUnavailable &&
    legacyFallbackSelected &&
    !forumSelection.court_name?.trim();
  const districtFallbackIncomplete =
    isDistrictFallbackForumSelection(forumSelection) &&
    (!forumSelection.forum_district?.trim() || !forumSelection.court_name?.trim());
  const consumerDistrictFallbackIncomplete =
    isConsumerDistrictFallbackForumSelection(forumSelection) &&
    (!forumSelection.forum_district?.trim() || !forumSelection.court_name?.trim());
  const forumSubmissionBlocked =
    forumCatalogQuery.isPending ||
    (forumCatalogUnavailable && !legacyFallbackSelected) ||
    legacyFallbackIncomplete ||
    districtFallbackIncomplete ||
    consumerDistrictFallbackIncomplete;
  const forumCatalogStatusMessage = forumCatalogQuery.isPending
    ? "Loading forum catalog before matter creation."
    : forumCatalogFailed
      ? "Forum catalog could not be loaded. Select Other / uncatalogued and enter a court or forum name to use the legacy fallback."
      : forumCatalogEmpty
        ? "Forum catalog is empty. Select Other / uncatalogued and enter a court or forum name to use the legacy fallback."
        : null;
  const forumCatalogStatusTone = forumCatalogFailed
    ? "error"
    : forumCatalogEmpty
      ? "warning"
      : "info";
  const shouldApplyDefaultForumSelection =
    forumSelection.forum_category === "high_court" &&
    forumSelection.forum_level === "high_court" &&
    !forumSelection.forum_catalog_entry_id &&
    !forumSelection.court_id &&
    !forumSelection.court_name &&
    !forumSelection.forum_state &&
    !forumSelection.forum_district &&
    !forumSelection.forum_city &&
    !forumSelection.forum_consumer_level;

  useEffect(() => {
    if (!open || !shouldApplyDefaultForumSelection) return;
    const entries = forumCatalogQuery.data?.entries ?? [];
    const defaultEntry =
      entries.find((entry) => entry.id === "hc:delhi") ??
      entries.find((entry) => entry.forum_type === "high_court") ??
      entries[0];
    if (defaultEntry) setForumSelection(forumSelectionFromEntry(defaultEntry));
  }, [forumCatalogQuery.data?.entries, open, shouldApplyDefaultForumSelection]);

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      createMatter({
        title: values.title.trim(),
        matter_code: normalizeMatterCodeInput(values.matter_code),
        client_name: values.client_name?.trim() || undefined,
        opposing_party: values.opposing_party?.trim() || undefined,
        practice_area: values.practice_area?.trim() || undefined,
        description: values.description?.trim() || undefined,
        forum_level: forumSelection.forum_level,
        court_id: forumSelection.court_id,
        court_name: forumSelection.court_name || undefined,
        forum_catalog_entry_id: forumSelection.forum_catalog_entry_id,
        forum_state: forumSelection.forum_state,
        forum_district: forumSelection.forum_district,
        forum_city: forumSelection.forum_city,
        forum_consumer_level: forumSelection.forum_consumer_level,
        status: values.status,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["matters"] });
      toast.success("Matter created");
      form.reset();
      setForumSelection(EMPTY_FORUM_SELECTION);
      setOpen(false);
    },
    onError: (err) => {
      const message = apiErrorMessage(err, "Could not create matter.");
      toast.error(message);
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="md" data-testid="new-matter-trigger">
          <Plus className="h-4 w-4" /> New matter
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>New matter</DialogTitle>
          <DialogDescription>
            Create the matter shell now — details like parties, hearings, and documents can be
            added from the cockpit.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4 md:grid-cols-2"
          onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
          noValidate
        >
          <Field label="Title" error={form.formState.errors.title?.message} className="md:col-span-2">
            {({ fieldId, errorId, invalid }) => (
              <Input
                id={fieldId}
                aria-invalid={invalid || undefined}
                aria-describedby={errorId}
                placeholder="State v. Rao — Bail Appeal"
                autoFocus
                {...form.register("title")}
              />
            )}
          </Field>
          <Field label="Matter code" error={form.formState.errors.matter_code?.message}>
            {({ fieldId, errorId, invalid }) => (
              <Input
                id={fieldId}
                aria-invalid={invalid || undefined}
                aria-describedby={errorId}
                placeholder="BLR-2026-001"
                {...form.register("matter_code")}
              />
            )}
          </Field>
          <Field label="Practice area" error={form.formState.errors.practice_area?.message}>
            {({ fieldId, errorId, invalid }) => (
              <Input
                id={fieldId}
                aria-invalid={invalid || undefined}
                aria-describedby={errorId}
                placeholder="Criminal / Commercial"
                {...form.register("practice_area")}
              />
            )}
          </Field>
          <Field label="Client name" error={form.formState.errors.client_name?.message}>
            {({ fieldId, errorId, invalid }) => (
              <Input
                id={fieldId}
                aria-invalid={invalid || undefined}
                aria-describedby={errorId}
                placeholder="Rao Family Office"
                {...form.register("client_name")}
              />
            )}
          </Field>
          <Field label="Opposing party" error={form.formState.errors.opposing_party?.message}>
            {({ fieldId, errorId, invalid }) => (
              <Input
                id={fieldId}
                aria-invalid={invalid || undefined}
                aria-describedby={errorId}
                placeholder="State of Karnataka"
                {...form.register("opposing_party")}
              />
            )}
          </Field>
          <div className="md:col-span-2">
            <ForumSelector
              entries={forumCatalogEntries}
              value={forumSelection}
              onChange={setForumSelection}
              disabled={forumCatalogQuery.isPending}
              idPrefix="new-matter-forum"
              statusMessage={forumCatalogStatusMessage}
              statusTone={forumCatalogStatusTone}
            />
          </div>
          <Field label="Status">
            {({ fieldId }) => (
              <Select
                value={form.watch("status")}
                onValueChange={(v) => form.setValue("status", v as FormValues["status"])}
              >
                <SelectTrigger id={fieldId}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STATUSES.map((s) => (
                    <SelectItem key={s.value} value={s.value}>
                      {s.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>
          <Field
            label="Description"
            error={form.formState.errors.description?.message}
            className="md:col-span-2"
          >
            {({ fieldId, errorId, invalid }) => (
              <Textarea
                id={fieldId}
                aria-invalid={invalid || undefined}
                aria-describedby={errorId}
                rows={3}
                placeholder="One-paragraph summary that an associate could brief a partner from."
                {...form.register("description")}
              />
            )}
          </Field>
          <DialogFooter className="md:col-span-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                form.reset();
                setOpen(false);
              }}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending || forumSubmissionBlocked}>
              {mutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Creating…
                </>
              ) : (
                "Create matter"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  label,
  error,
  children,
  className,
}: {
  label: string;
  error?: string;
  children: (state: {
    fieldId: string;
    errorId: string | undefined;
    invalid: boolean;
  }) => React.ReactNode;
  className?: string;
}) {
  const generated = useId();
  const fieldId = `field-${generated}`;
  const errorId = error ? `${fieldId}-error` : undefined;
  return (
    <div className={`flex flex-col gap-1.5 ${className ?? ""}`}>
      <Label htmlFor={fieldId}>{label}</Label>
      {children({ fieldId, errorId, invalid: Boolean(error) })}
      {error ? (
        <p
          id={errorId}
          className="text-xs text-[var(--color-danger-500,#c53030)]"
          role="alert"
        >
          {error}
        </p>
      ) : null}
    </div>
  );
}
