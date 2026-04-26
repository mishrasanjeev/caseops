"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Clock, Loader2 } from "lucide-react";
import { useState } from "react";
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
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import { createMatterTimeEntry } from "@/lib/api/endpoints";

const schema = z.object({
  work_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "YYYY-MM-DD."),
  description: z.string().min(2, "At least 2 characters.").max(500),
  duration_minutes: z
    .number({ error: "Enter a whole number of minutes." })
    .int("Whole minutes only.")
    .min(1, "Must be ≥ 1.")
    .max(1440, "Can't exceed 24h per entry."),
  billable: z.boolean(),
  rate_amount_rupees: z
    .string()
    .regex(/^\d+(\.\d{1,2})?$/, "Rate as a number (e.g. 8000).")
    .optional()
    .or(z.literal("")),
});

type FormValues = z.infer<typeof schema>;

function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
    now.getDate(),
  ).padStart(2, "0")}`;
}

export function NewTimeEntryDialog({ matterId }: { matterId: string }) {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      work_date: todayIso(),
      description: "",
      duration_minutes: 30,
      billable: true,
      rate_amount_rupees: "",
    },
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      createMatterTimeEntry({
        matterId,
        workDate: values.work_date,
        description: values.description.trim(),
        durationMinutes: values.duration_minutes,
        billable: values.billable,
        rateCurrency: "INR",
        rateAmountMinor: values.rate_amount_rupees
          ? Math.round(Number.parseFloat(values.rate_amount_rupees) * 100)
          : null,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "workspace"],
      });
      toast.success("Time entry logged");
      form.reset({
        work_date: todayIso(),
        description: "",
        duration_minutes: 30,
        billable: true,
        rate_amount_rupees: "",
      });
      setOpen(false);
    },
    onError: (err) => {
      toast.error(
        apiErrorMessage(err, "Could not log the time entry."),
      );
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="secondary" data-testid="new-time-entry-trigger">
          <Clock className="h-4 w-4" aria-hidden /> Log time
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Log time on this matter</DialogTitle>
          <DialogDescription>
            Track research, drafting, and hearings. Billable entries flow into
            the next invoice automatically.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-4"
          onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
          noValidate
          aria-label="Log time entry"
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <FormField
              id="work-date"
              label="Work date"
              error={form.formState.errors.work_date?.message}
            >
              <Input id="work-date" type="date" {...form.register("work_date")} />
            </FormField>
            <FormField
              id="duration"
              label="Duration (minutes)"
              error={form.formState.errors.duration_minutes?.message}
            >
              <Input
                id="duration"
                type="number"
                min={1}
                max={1440}
                inputMode="numeric"
                {...form.register("duration_minutes", { valueAsNumber: true })}
              />
            </FormField>
          </div>

          <FormField
            id="time-description"
            label="What did you work on?"
            error={form.formState.errors.description?.message}
          >
            <Textarea
              id="time-description"
              rows={3}
              placeholder="Drafted reply to S.U-B rejoinder; reviewed Ram v. State authorities."
              {...form.register("description")}
            />
          </FormField>

          <label className="flex items-start gap-2 text-sm text-[var(--color-ink-2)]">
            <input type="checkbox" className="mt-0.5" {...form.register("billable")} />
            <span>Billable — include in the next invoice.</span>
          </label>

          <FormField
            id="rate"
            label="Hourly rate in INR (optional)"
            error={form.formState.errors.rate_amount_rupees?.message}
          >
            <Input
              id="rate"
              inputMode="decimal"
              placeholder="8000"
              {...form.register("rate_amount_rupees")}
            />
          </FormField>

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setOpen(false)}
              disabled={mutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={mutation.isPending}
              data-testid="new-time-entry-submit"
            >
              {mutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Logging…
                </>
              ) : (
                "Log entry"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function FormField({
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
  const errorId = error ? `${id}-error` : undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error ? (
        <p id={errorId} className="text-xs text-[var(--color-danger-500,#c53030)]" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
