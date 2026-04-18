"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, X } from "lucide-react";
import { useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
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
import { ApiError } from "@/lib/api/config";
import { createMatterInvoice } from "@/lib/api/endpoints";

const schema = z.object({
  invoice_number: z
    .string()
    .min(2, "At least 2 characters.")
    .max(80, "Keep it under 80.")
    .regex(/^[A-Za-z0-9\-_/]+$/, "Letters, digits, hyphen, underscore, slash only."),
  issued_on: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "YYYY-MM-DD."),
  due_on: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "YYYY-MM-DD.").optional().or(z.literal("")),
  client_name: z.string().max(255).optional(),
  tax_amount_rupees: z
    .string()
    .regex(/^\d+(\.\d{1,2})?$/, "Tax as a number (e.g. 500 or 500.00).")
    .optional()
    .or(z.literal("")),
  notes: z.string().max(4000).optional(),
  include_uninvoiced_time_entries: z.boolean(),
  manual_items: z
    .array(
      z.object({
        description: z.string().min(2, "Min 2 characters.").max(500),
        amount_rupees: z
          .string()
          .regex(/^\d+(\.\d{1,2})?$/, "Amount as a number (e.g. 10000)."),
      }),
    )
    .max(40, "Too many manual items."),
});

type FormValues = z.infer<typeof schema>;

function rupeesToMinor(rupees: string | undefined | null): number {
  if (!rupees) return 0;
  const value = Number.parseFloat(rupees);
  if (Number.isNaN(value)) return 0;
  return Math.round(value * 100);
}

function todayIso(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function NewInvoiceDialog({ matterId }: { matterId: string }) {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      invoice_number: "",
      issued_on: todayIso(),
      due_on: "",
      client_name: "",
      tax_amount_rupees: "",
      notes: "",
      include_uninvoiced_time_entries: true,
      manual_items: [],
    },
  });
  const manualItems = useFieldArray({ control: form.control, name: "manual_items" });

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      createMatterInvoice({
        matterId,
        invoiceNumber: values.invoice_number.trim(),
        issuedOn: values.issued_on,
        dueOn: values.due_on?.trim() || null,
        clientName: values.client_name?.trim() || null,
        taxAmountMinor: rupeesToMinor(values.tax_amount_rupees),
        notes: values.notes?.trim() || null,
        includeUninvoicedTimeEntries: values.include_uninvoiced_time_entries,
        manualItems: values.manual_items.map((item) => ({
          description: item.description.trim(),
          amount_minor: rupeesToMinor(item.amount_rupees),
        })),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "workspace"],
      });
      toast.success("Invoice issued");
      form.reset({
        invoice_number: "",
        issued_on: todayIso(),
        due_on: "",
        client_name: "",
        tax_amount_rupees: "",
        notes: "",
        include_uninvoiced_time_entries: true,
        manual_items: [],
      });
      setOpen(false);
    },
    onError: (err) => {
      toast.error(
        err instanceof ApiError ? err.detail : "Could not create invoice.",
      );
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" data-testid="new-invoice-trigger">
          <Plus className="h-4 w-4" aria-hidden /> New invoice
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Issue a new invoice</DialogTitle>
          <DialogDescription>
            Uninvoiced billable time on this matter rolls in by default. Add
            manual items for fixed fees or disbursements.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-4"
          onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
          noValidate
          aria-label="New invoice"
        >
          <FormField
            id="invoice-number"
            label="Invoice number"
            error={form.formState.errors.invoice_number?.message}
          >
            <Input
              id="invoice-number"
              placeholder="INV-2026-0001"
              aria-invalid={Boolean(form.formState.errors.invoice_number) || undefined}
              {...form.register("invoice_number")}
            />
          </FormField>

          <div className="grid grid-cols-2 gap-3">
            <FormField
              id="issued-on"
              label="Issued on"
              error={form.formState.errors.issued_on?.message}
            >
              <Input
                id="issued-on"
                type="date"
                {...form.register("issued_on")}
              />
            </FormField>
            <FormField
              id="due-on"
              label="Due on (optional)"
              error={form.formState.errors.due_on?.message}
            >
              <Input id="due-on" type="date" {...form.register("due_on")} />
            </FormField>
          </div>

          <FormField id="client-name" label="Client name (optional)">
            <Input id="client-name" {...form.register("client_name")} />
          </FormField>

          <FormField
            id="tax-amount"
            label="Tax amount in INR (optional)"
            error={form.formState.errors.tax_amount_rupees?.message}
          >
            <Input
              id="tax-amount"
              inputMode="decimal"
              placeholder="0"
              {...form.register("tax_amount_rupees")}
            />
          </FormField>

          <label className="flex items-start gap-2 text-sm text-[var(--color-ink-2)]">
            <input
              type="checkbox"
              className="mt-0.5"
              {...form.register("include_uninvoiced_time_entries")}
            />
            <span>Include uninvoiced billable time on this matter.</span>
          </label>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <Label>Manual line items</Label>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => manualItems.append({ description: "", amount_rupees: "" })}
                data-testid="new-invoice-add-item"
              >
                <Plus className="h-3.5 w-3.5" aria-hidden /> Add item
              </Button>
            </div>
            <div className="flex flex-col gap-2">
              {manualItems.fields.map((field, idx) => (
                <div key={field.id} className="flex items-start gap-2">
                  <Input
                    placeholder="Court fees"
                    aria-label={`Line ${idx + 1} description`}
                    {...form.register(`manual_items.${idx}.description` as const)}
                  />
                  <Input
                    className="w-32"
                    inputMode="decimal"
                    placeholder="Amount"
                    aria-label={`Line ${idx + 1} amount`}
                    {...form.register(`manual_items.${idx}.amount_rupees` as const)}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => manualItems.remove(idx)}
                    aria-label={`Remove line ${idx + 1}`}
                  >
                    <X className="h-4 w-4" aria-hidden />
                  </Button>
                </div>
              ))}
            </div>
          </div>

          <FormField id="invoice-notes" label="Notes (optional)">
            <Textarea id="invoice-notes" rows={3} {...form.register("notes")} />
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
              data-testid="new-invoice-submit"
            >
              {mutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Issuing…
                </>
              ) : (
                "Issue invoice"
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
