"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PasswordInput } from "@/components/ui/PasswordInput";
import { bootstrapCompany } from "@/lib/api/auth";
import { apiErrorMessage } from "@/lib/api/config";
import { storeSession } from "@/lib/session";

const schema = z.object({
  companyName: z.string().min(2, "Enter your firm's name.").max(255),
  companySlug: z
    .string()
    .min(2, "Pick a slug (2-80 chars).")
    .max(80)
    .regex(/^[a-z0-9-]+$/, "Lowercase letters, digits, and hyphens only."),
  companyType: z.enum(["law_firm", "corporate_legal", "solo"]),
  ownerFullName: z.string().min(2, "Enter your full name.").max(255),
  ownerEmail: z.string().email("Enter a valid work email."),
  ownerPassword: z
    .string()
    .min(12, "At least 12 characters.")
    .max(128, "Max 128 characters.")
    .regex(/[A-Z]/, "At least one uppercase letter.")
    .regex(/[a-z]/, "At least one lowercase letter.")
    .regex(/[0-9]/, "At least one digit.")
    .regex(/[^A-Za-z0-9]/, "At least one symbol."),
});

type FormValues = z.infer<typeof schema>;

/**
 * In-app company bootstrap (BG-010). On success the API returns an
 * `AuthSession` identical to /login; we store it and push the owner
 * straight into the new workspace.
 */
export function NewWorkspaceForm() {
  const router = useRouter();
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      companyName: "",
      companySlug: "",
      companyType: "law_firm",
      ownerFullName: "",
      ownerEmail: "",
      ownerPassword: "",
    },
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) => bootstrapCompany(values),
    onSuccess: (session) => {
      storeSession(session);
      toast.success(`Workspace created — welcome, ${session.user.full_name.split(" ")[0]}.`);
      router.replace("/app");
    },
    onError: (err) => {
      const message =
        apiErrorMessage(err, "Could not create the workspace. Please try again.");
      toast.error(message);
    },
  });

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
      noValidate
      aria-label="Create workspace"
    >
      <FieldGroup
        id="new-company-name"
        label="Firm / organisation name"
        error={form.formState.errors.companyName?.message}
      >
        {({ invalid, describedBy }) => (
          <Input
            id="new-company-name"
            autoComplete="organization"
            placeholder="Aster Legal LLP"
            aria-invalid={invalid || undefined}
            aria-describedby={describedBy}
            {...form.register("companyName")}
          />
        )}
      </FieldGroup>

      <FieldGroup
        id="new-company-slug"
        label="Workspace slug"
        hint="Lowercase letters, digits, and hyphens. Shown in your workspace URL."
        error={form.formState.errors.companySlug?.message}
      >
        {({ invalid, describedBy }) => (
          <Input
            id="new-company-slug"
            autoComplete="off"
            placeholder="aster-legal"
            aria-invalid={invalid || undefined}
            aria-describedby={describedBy}
            {...form.register("companySlug")}
          />
        )}
      </FieldGroup>

      <FieldGroup
        id="new-company-type"
        label="Organisation type"
        error={form.formState.errors.companyType?.message}
      >
        {({ invalid, describedBy }) => (
          <select
            id="new-company-type"
            className="rounded-md border border-[var(--color-border,#d4d4d8)] bg-white px-3 py-2 text-sm"
            aria-invalid={invalid || undefined}
            aria-describedby={describedBy}
            {...form.register("companyType")}
          >
            <option value="law_firm">Law firm</option>
            <option value="corporate_legal">Corporate legal / GC</option>
            <option value="solo">Solo practitioner</option>
          </select>
        )}
      </FieldGroup>

      <FieldGroup
        id="owner-full-name"
        label="Your full name"
        error={form.formState.errors.ownerFullName?.message}
      >
        {({ invalid, describedBy }) => (
          <Input
            id="owner-full-name"
            autoComplete="name"
            placeholder="Priya Sharma"
            aria-invalid={invalid || undefined}
            aria-describedby={describedBy}
            {...form.register("ownerFullName")}
          />
        )}
      </FieldGroup>

      <FieldGroup
        id="owner-email"
        label="Your work email"
        error={form.formState.errors.ownerEmail?.message}
      >
        {({ invalid, describedBy }) => (
          <Input
            id="owner-email"
            type="email"
            autoComplete="email"
            placeholder="you@firm.in"
            aria-invalid={invalid || undefined}
            aria-describedby={describedBy}
            {...form.register("ownerEmail")}
          />
        )}
      </FieldGroup>

      <FieldGroup
        id="owner-password"
        label="Password"
        hint="12+ chars, with upper, lower, digit, and symbol."
        error={form.formState.errors.ownerPassword?.message}
      >
        {({ invalid, describedBy }) => (
          <PasswordInput
            id="owner-password"
            autoComplete="new-password"
            aria-invalid={invalid || undefined}
            aria-describedby={describedBy}
            {...form.register("ownerPassword")}
          />
        )}
      </FieldGroup>

      <Button
        type="submit"
        size="lg"
        disabled={mutation.isPending}
        className="mt-2 w-full"
        data-testid="new-workspace-submit"
      >
        {mutation.isPending ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" /> Creating workspace…
          </>
        ) : (
          "Create workspace"
        )}
      </Button>
    </form>
  );
}

function FieldGroup({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: (state: { invalid: boolean; describedBy: string | undefined }) => React.ReactNode;
}) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children({ invalid: Boolean(error), describedBy })}
      {hint ? (
        <p id={hintId} className="text-xs text-[var(--color-mute-2)]">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="text-xs text-[var(--color-danger-500,#c53030)]" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
