"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus } from "lucide-react";
import { useId, useState } from "react";
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
import { apiErrorMessage } from "@/lib/api/config";
import { createMatter } from "@/lib/api/endpoints";

const schema = z.object({
  title: z.string().min(3, "At least 3 characters."),
  matter_code: z
    .string()
    .min(2, "At least 2 characters.")
    .max(40, "Keep it short and unique."),
  practice_area: z.string().min(2, "Practice area helps classify the work."),
  client_name: z.string().optional(),
  opposing_party: z.string().optional(),
  forum_level: z.enum(["lower_court", "high_court", "supreme_court", "tribunal"]),
  status: z.enum(["intake", "active", "on_hold", "closed"]),
  description: z.string().max(2000).optional(),
});

type FormValues = z.infer<typeof schema>;

const FORUMS: { value: FormValues["forum_level"]; label: string }[] = [
  { value: "lower_court", label: "Lower court" },
  { value: "high_court", label: "High Court" },
  { value: "supreme_court", label: "Supreme Court" },
  { value: "tribunal", label: "Tribunal" },
];
const STATUSES: { value: FormValues["status"]; label: string }[] = [
  { value: "intake", label: "Intake" },
  { value: "active", label: "Active" },
  { value: "on_hold", label: "On hold" },
  { value: "closed", label: "Closed" },
];

export function NewMatterDialog() {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: "",
      matter_code: "",
      client_name: "",
      opposing_party: "",
      practice_area: "",
      forum_level: "high_court",
      status: "active",
      description: "",
    },
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      createMatter({
        title: values.title.trim(),
        matter_code: values.matter_code.trim().toUpperCase(),
        client_name: values.client_name?.trim() || undefined,
        opposing_party: values.opposing_party?.trim() || undefined,
        practice_area: values.practice_area?.trim() || undefined,
        description: values.description?.trim() || undefined,
        forum_level: values.forum_level,
        status: values.status,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["matters"] });
      toast.success("Matter created");
      form.reset();
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
          <Field label="Forum">
            {({ fieldId }) => (
              <Select
                value={form.watch("forum_level")}
                onValueChange={(v) => form.setValue("forum_level", v as FormValues["forum_level"])}
              >
                <SelectTrigger id={fieldId}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {FORUMS.map((f) => (
                    <SelectItem key={f.value} value={f.value}>
                      {f.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>
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
            <Button type="submit" disabled={mutation.isPending}>
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
