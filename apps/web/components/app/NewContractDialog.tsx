"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import { createContract } from "@/lib/api/endpoints";

const schema = z.object({
  title: z.string().min(3, "At least 3 characters."),
  contract_code: z
    .string()
    .min(2, "At least 2 characters.")
    .max(40, "Keep it short and unique.")
    .regex(/^[A-Za-z0-9\-_/]+$/, "Letters, digits, hyphen, underscore, slash only."),
  contract_type: z.string().min(2, "Contract type helps classify."),
  counterparty_name: z.string().min(2).max(255).optional().or(z.literal("")),
  status: z.enum(["draft", "in_review", "executed", "expired", "terminated", "renewed"]),
  effective_on: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().or(z.literal("")),
  expires_on: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().or(z.literal("")),
  governing_law: z.string().max(120).optional().or(z.literal("")),
  summary: z.string().max(2000).optional().or(z.literal("")),
});

type FormValues = z.infer<typeof schema>;

export function NewContractDialog() {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const queryClient = useQueryClient();
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: "",
      contract_code: "",
      contract_type: "msa",
      counterparty_name: "",
      status: "draft",
      effective_on: "",
      expires_on: "",
      governing_law: "India",
      summary: "",
    },
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      createContract({
        title: values.title.trim(),
        contractCode: values.contract_code.trim().toUpperCase(),
        contractType: values.contract_type.trim(),
        counterpartyName: values.counterparty_name?.trim() || null,
        status: values.status,
        effectiveOn: values.effective_on || null,
        expiresOn: values.expires_on || null,
        governingLaw: values.governing_law?.trim() || null,
        summary: values.summary?.trim() || null,
      }),
    onSuccess: async (contract) => {
      await queryClient.invalidateQueries({ queryKey: ["contracts", "list"] });
      toast.success("Contract created");
      form.reset();
      setOpen(false);
      const id = (contract as { id?: string })?.id;
      if (id) router.push(`/app/contracts/${id}`);
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not create contract."));
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" data-testid="new-contract-trigger">
          <Plus className="h-4 w-4" aria-hidden /> New contract
        </Button>
      </DialogTrigger>
      {/* Ram-BUG-004 (2026-04-22): on narrow viewports the dialog
          rendered with the form taller than the screen and the
          submit/cancel buttons fell below the fold with no scroll
          affordance. Cap the height at 90vh + scroll the body so
          the footer is always reachable. The grid-cols-2 fields
          below also stack vertically on mobile via the
          grid-cols-1 sm: prefix added at the same time. */}
      <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Create a new contract</DialogTitle>
          <DialogDescription>
            Set up the contract record. You can upload the actual document
            after and let CaseOps extract clauses, obligations, and run the
            playbook comparison.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-4"
          onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
          noValidate
          aria-label="New contract"
        >
          <Field
            id="contract-title"
            label="Title"
            error={form.formState.errors.title?.message}
          >
            <Input
              id="contract-title"
              placeholder="MSA with Acme India"
              {...form.register("title")}
            />
          </Field>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field
              id="contract-code"
              label="Code"
              error={form.formState.errors.contract_code?.message}
            >
              <Input
                id="contract-code"
                placeholder="C-ACME-001"
                {...form.register("contract_code")}
              />
            </Field>
            <Field id="contract-type" label="Type">
              <Input
                id="contract-type"
                placeholder="msa / nda / sow"
                {...form.register("contract_type")}
              />
            </Field>
          </div>

          <Field id="counterparty" label="Counterparty (optional)">
            <Input
              id="counterparty"
              placeholder="Acme India Pvt Ltd"
              {...form.register("counterparty_name")}
            />
          </Field>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field id="effective-on" label="Effective on">
              <Input
                id="effective-on"
                type="date"
                {...form.register("effective_on")}
              />
            </Field>
            <Field id="expires-on" label="Expires on">
              <Input
                id="expires-on"
                type="date"
                {...form.register("expires_on")}
              />
            </Field>
          </div>

          <Field id="contract-status" label="Status">
            <Select
              value={form.watch("status")}
              onValueChange={(value) =>
                form.setValue("status", value as FormValues["status"])
              }
            >
              <SelectTrigger id="contract-status">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="draft">Draft</SelectItem>
                <SelectItem value="in_review">In review</SelectItem>
                <SelectItem value="executed">Executed</SelectItem>
                <SelectItem value="expired">Expired</SelectItem>
                <SelectItem value="terminated">Terminated</SelectItem>
                <SelectItem value="renewed">Renewed</SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <Field id="governing-law" label="Governing law">
            <Input id="governing-law" {...form.register("governing_law")} />
          </Field>

          <Field id="contract-summary" label="Summary (optional)">
            <Textarea id="contract-summary" rows={3} {...form.register("summary")} />
          </Field>

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
              data-testid="new-contract-submit"
            >
              {mutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Creating…
                </>
              ) : (
                "Create contract"
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
