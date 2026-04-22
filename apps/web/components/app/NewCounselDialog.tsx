"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, UserPlus } from "lucide-react";
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
import { ApiError } from "@/lib/api/config";
import { createOutsideCounselProfile } from "@/lib/api/endpoints";

const schema = z.object({
  name: z.string().min(2, "At least 2 characters.").max(255),
  primary_contact_name: z.string().max(255).optional(),
  primary_contact_email: z
    .string()
    .email("Enter a valid email.")
    .optional()
    .or(z.literal("")),
  primary_contact_phone: z.string().max(40).optional(),
  firm_city: z.string().max(255).optional(),
  jurisdictions: z.string().max(400).optional(),
  practice_areas: z.string().max(400).optional(),
  // Hari-BUG-018/023 (2026-04-22): values MUST match
  // db.models.OutsideCounselPanelStatus. Prior set
  // (active | on_hold | preferred | archived) was the original
  // drift source — submitting on_hold or archived would 422 at
  // the API and confuse the user with no path forward.
  panel_status: z.enum(["active", "preferred", "inactive"]),
  internal_notes: z.string().max(4000).optional(),
});

type FormValues = z.infer<typeof schema>;

function splitCsv(value: string | undefined | null): string[] {
  if (!value) return [];
  return value
    .split(",")
    .map((v) => v.trim())
    .filter((v) => v.length > 0)
    .slice(0, 12);
}

export function NewCounselDialog() {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: "",
      primary_contact_name: "",
      primary_contact_email: "",
      primary_contact_phone: "",
      firm_city: "",
      jurisdictions: "",
      practice_areas: "",
      panel_status: "active",
      internal_notes: "",
    },
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      createOutsideCounselProfile({
        name: values.name.trim(),
        primaryContactName: values.primary_contact_name?.trim() || null,
        primaryContactEmail: values.primary_contact_email?.trim() || null,
        primaryContactPhone: values.primary_contact_phone?.trim() || null,
        firmCity: values.firm_city?.trim() || null,
        jurisdictions: splitCsv(values.jurisdictions),
        practiceAreas: splitCsv(values.practice_areas),
        panelStatus: values.panel_status,
        internalNotes: values.internal_notes?.trim() || null,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["outside-counsel", "workspace"],
      });
      toast.success("Counsel added to panel");
      form.reset();
      setOpen(false);
    },
    onError: (err) => {
      toast.error(
        err instanceof ApiError ? err.detail : "Could not create counsel profile.",
      );
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" data-testid="new-counsel-trigger">
          <UserPlus className="h-4 w-4" aria-hidden /> Add counsel
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Add outside counsel to the panel</DialogTitle>
          <DialogDescription>
            Capture the working contact and panel status. Assignments and spend
            are logged separately from the matter page or the counsel row.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-4"
          onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
          noValidate
          aria-label="Add outside counsel"
        >
          <FormField
            id="counsel-name"
            label="Firm or individual name"
            error={form.formState.errors.name?.message}
          >
            <Input
              id="counsel-name"
              placeholder="Khaitan & Co."
              {...form.register("name")}
            />
          </FormField>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <FormField id="contact-name" label="Primary contact">
              <Input
                id="contact-name"
                placeholder="Neha Bhatia"
                {...form.register("primary_contact_name")}
              />
            </FormField>
            <FormField
              id="contact-email"
              label="Email"
              error={form.formState.errors.primary_contact_email?.message}
            >
              <Input
                id="contact-email"
                type="email"
                placeholder="neha@firm.in"
                {...form.register("primary_contact_email")}
              />
            </FormField>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <FormField id="contact-phone" label="Phone">
              <Input
                id="contact-phone"
                placeholder="+91 98765 43210"
                {...form.register("primary_contact_phone")}
              />
            </FormField>
            <FormField id="firm-city" label="City">
              <Input
                id="firm-city"
                placeholder="Mumbai"
                {...form.register("firm_city")}
              />
            </FormField>
          </div>

          <FormField
            id="jurisdictions"
            label="Jurisdictions (comma-separated)"
          >
            <Input
              id="jurisdictions"
              placeholder="Delhi, Bombay, SC"
              {...form.register("jurisdictions")}
            />
          </FormField>

          <FormField
            id="practice-areas"
            label="Practice areas (comma-separated)"
          >
            <Input
              id="practice-areas"
              placeholder="Arbitration, IP, White-collar"
              {...form.register("practice_areas")}
            />
          </FormField>

          <FormField id="panel-status" label="Panel status">
            <Select
              value={form.watch("panel_status")}
              onValueChange={(value) =>
                form.setValue("panel_status", value as FormValues["panel_status"])
              }
            >
              <SelectTrigger id="panel-status">
                <SelectValue placeholder="Pick panel status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="preferred">Preferred</SelectItem>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="inactive">Inactive</SelectItem>
              </SelectContent>
            </Select>
          </FormField>

          <FormField id="internal-notes" label="Internal notes (optional)">
            <Textarea
              id="internal-notes"
              rows={3}
              {...form.register("internal_notes")}
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
              data-testid="new-counsel-submit"
            >
              {mutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Adding…
                </>
              ) : (
                "Add to panel"
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
