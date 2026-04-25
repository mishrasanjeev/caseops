"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Loader2, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import type { FieldValues, Resolver } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { BenchContextCard } from "@/components/drafting/BenchContextCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  createDraft,
  fetchDraftingSuggestions,
  fetchDraftingTemplate,
  previewDraft,
  type DraftTemplateSchema,
  type DraftTemplateType,
  type DraftingFieldSpec,
  type TemplateSuggestions,
} from "@/lib/api/endpoints";
import { cn } from "@/lib/cn";

const PREVIEW_STEP = "preview";
const PREVIEW_DEBOUNCE_MS = 800;

// ---------------------------------------------------------------
// Runtime Zod schema builder.
//
// Algorithm: for every DraftingFieldSpec we produce a Zod schema
// keyed by `field.name` using `field.kind`. Strings with required=true
// get .min(1); required numbers are coerced (<input type="number"> yields
// a string); booleans default to false; enums use z.enum over the
// declared enum_options; non-required fields are .optional().
// The whole record is assembled into z.object({...}).
// ---------------------------------------------------------------
function buildFormSchema(fields: DraftingFieldSpec[]) {
  const shape: Record<string, z.ZodTypeAny> = {};
  for (const f of fields) {
    let leaf: z.ZodTypeAny;
    switch (f.kind) {
      case "number":
        // <input type="number"> emits a string; coerce via preprocess so
        // this stays compatible with zod 4's stricter pipe typing.
        if (f.required) {
          leaf = z.preprocess(
            (v) => (typeof v === "string" ? Number(v) : v),
            z.number().finite({ message: `${f.label} is required.` }),
          );
        } else {
          leaf = z
            .preprocess(
              (v) => (v === "" || v == null ? undefined : Number(v)),
              z.number().finite().optional(),
            );
        }
        break;
      case "boolean":
        leaf = z.boolean();
        break;
      case "enum":
        if (f.enum_options && f.enum_options.length > 0) {
          const [first, ...rest] = f.enum_options;
          leaf = z.enum([first, ...rest] as [string, ...string[]]);
        } else {
          leaf = z.string();
        }
        break;
      case "date":
      case "text":
      case "string":
      default:
        leaf = z.string();
        break;
    }
    if (f.required && (f.kind === "string" || f.kind === "text" || f.kind === "date")) {
      leaf = (leaf as z.ZodString).min(1, `${f.label} is required.`);
    } else if (!f.required && (f.kind === "string" || f.kind === "text" || f.kind === "date")) {
      // An optional string already accepts "" and undefined.
      leaf = (leaf as z.ZodString).optional();
    }
    shape[f.name] = leaf;
  }
  return z.object(shape);
}

function buildDefaults(fields: DraftingFieldSpec[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    switch (f.kind) {
      case "boolean":
        out[f.name] = false;
        break;
      case "number":
        out[f.name] = "";
        break;
      case "enum":
        out[f.name] = f.enum_options?.[0] ?? "";
        break;
      default:
        out[f.name] = "";
    }
  }
  return out;
}

// Strip empty strings so the preview endpoint sees a clean partial
// facts object; the backend surfaces "[not yet specified]" on the
// missing keys.
function pruneFacts(raw: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(raw)) {
    if (v === "" || v === undefined || v === null) continue;
    out[k] = v;
  }
  return out;
}

type Props = {
  matterId: string;
  templateType: DraftTemplateType;
};

export function DraftingStepper({ matterId, templateType }: Props) {
  const router = useRouter();

  const templateQuery = useQuery({
    queryKey: ["drafting", "templates", templateType],
    queryFn: () => fetchDraftingTemplate(templateType),
  });

  const suggestionsQuery = useQuery({
    queryKey: ["drafting", "templates", templateType, "suggestions"],
    queryFn: () => fetchDraftingSuggestions(templateType),
    // Suggestions are nice-to-have; a failure here must not block the form.
    retry: false,
  });

  if (templateQuery.isPending) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (templateQuery.isError || !templateQuery.data) {
    return (
      <QueryErrorState
        title="Could not load drafting template"
        error={templateQuery.error}
        onRetry={templateQuery.refetch}
      />
    );
  }

  return (
    <StepperInner
      matterId={matterId}
      template={templateQuery.data}
      suggestions={suggestionsQuery.data ?? null}
      onSubmitted={(draftId) =>
        router.push(`/app/matters/${matterId}/drafts/${draftId}`)
      }
    />
  );
}

type InnerProps = {
  matterId: string;
  template: DraftTemplateSchema;
  suggestions: TemplateSuggestions | null;
  onSubmitted: (draftId: string) => void;
};

function StepperInner({ matterId, template, suggestions, onSubmitted }: InnerProps) {
  const schema = useMemo(() => buildFormSchema(template.fields), [template.fields]);
  const defaults = useMemo(() => buildDefaults(template.fields), [template.fields]);
  const steps = useMemo(
    () => [...template.step_groups, PREVIEW_STEP],
    [template.step_groups],
  );

  const form = useForm<FieldValues>({
    resolver: zodResolver(schema) as unknown as Resolver<FieldValues>,
    defaultValues: defaults,
    mode: "onChange",
  });

  const [stepIndex, setStepIndex] = useState(0);
  const currentStep = steps[stepIndex];
  const isPreviewStep = currentStep === PREVIEW_STEP;

  const suggestionLookup = useMemo(() => {
    const map = new Map<string, string[]>();
    if (!suggestions) return map;
    for (const f of suggestions.fields) {
      map.set(f.field_name, f.options);
    }
    return map;
  }, [suggestions]);

  const allValues = form.watch();
  const stepFields = useMemo(
    () =>
      isPreviewStep
        ? []
        : template.fields.filter((f) => f.step_group === currentStep),
    [template.fields, currentStep, isPreviewStep],
  );

  const goNext = async () => {
    if (isPreviewStep) return;
    // Validate only the current step's fields so the user isn't blocked
    // on fields in a later group. RHF's trigger accepts a field list.
    const ok = await form.trigger(stepFields.map((f) => f.name));
    if (!ok) return;
    setStepIndex((i) => Math.min(i + 1, steps.length - 1));
  };
  const goPrev = () => setStepIndex((i) => Math.max(i - 1, 0));

  const createMutation = useMutation({
    mutationFn: async (values: FieldValues) => {
      const title = deriveTitle(template.display_name, values);
      return createDraft({
        matterId,
        title,
        draftType: "brief",
        templateType: template.template_type,
        facts: pruneFacts(values),
      });
    },
    onSuccess: (draft) => {
      toast.success("Draft created — generating first version next.");
      onSubmitted(draft.id);
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not create draft."));
    },
  });

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold text-[var(--color-ink)]">
            {template.display_name}
          </h2>
          {template.statutory_basis.slice(0, 3).map((basis) => (
            <Badge key={basis} tone="neutral">
              {basis}
            </Badge>
          ))}
        </div>
        <p className="text-sm text-[var(--color-mute)]">{template.summary}</p>
      </header>

      {template.template_type === "appeal_memorandum" && matterId ? (
        <BenchContextCard matterId={matterId} />
      ) : null}

      <StepperBreadcrumbs
        steps={steps}
        stepIndex={stepIndex}
        onSelect={(i) => {
          // Only allow jumping to a previous step; forward nav must go
          // through validation.
          if (i <= stepIndex) setStepIndex(i);
        }}
      />

      <form
        className="flex flex-col gap-5"
        onSubmit={form.handleSubmit((values) => createMutation.mutate(values))}
        noValidate
      >
        {isPreviewStep ? (
          <PreviewPane
            templateType={template.template_type}
            facts={pruneFacts(allValues)}
          />
        ) : (
          <Card>
            <CardContent className="flex flex-col gap-4">
              {stepFields.length === 0 ? (
                <p className="text-sm text-[var(--color-mute)]">
                  No fields in this step.
                </p>
              ) : (
                stepFields.map((f) => (
                  <FieldRow
                    key={f.name}
                    field={f}
                    form={form}
                    suggestions={suggestionLookup.get(f.name) ?? null}
                  />
                ))
              )}
            </CardContent>
          </Card>
        )}

        <div className="flex items-center justify-between gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={goPrev}
            disabled={stepIndex === 0}
          >
            <ArrowLeft className="h-4 w-4" aria-hidden /> Previous
          </Button>
          {isPreviewStep ? (
            <Button type="submit" disabled={createMutation.isPending}>
              {createMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Creating draft…
                </>
              ) : (
                "Submit for full draft"
              )}
            </Button>
          ) : (
            <Button type="button" onClick={goNext}>
              Next <ArrowRight className="h-4 w-4" aria-hidden />
            </Button>
          )}
        </div>
      </form>
    </div>
  );
}

function deriveTitle(displayName: string, values: FieldValues): string {
  // Pick the first human-name-ish field for a useful title; fall back
  // to the template display name alone.
  const candidateKeys = [
    "accused_name",
    "applicant_name",
    "petitioner_name",
    "plaintiff_name",
    "complainant_name",
    "deponent_name",
    "drawer_name",
    "sender_name",
  ];
  for (const k of candidateKeys) {
    const v = values[k];
    if (typeof v === "string" && v.trim()) {
      return `${displayName} — ${v.trim()}`;
    }
  }
  return displayName;
}

function StepperBreadcrumbs({
  steps,
  stepIndex,
  onSelect,
}: {
  steps: string[];
  stepIndex: number;
  onSelect: (i: number) => void;
}) {
  return (
    <ol className="flex flex-wrap items-center gap-2" aria-label="Drafting steps">
      {steps.map((s, i) => {
        const state =
          i === stepIndex ? "active" : i < stepIndex ? "done" : "upcoming";
        return (
          <li key={s} className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onSelect(i)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium capitalize transition-colors",
                state === "active" &&
                  "border-[var(--color-brand-500)] bg-[var(--color-brand-50)] text-[var(--color-brand-700)]",
                state === "done" &&
                  "border-[var(--color-line)] bg-white text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]",
                state === "upcoming" &&
                  "cursor-not-allowed border-[var(--color-line)] bg-[var(--color-bg-2)] text-[var(--color-mute)]",
              )}
              disabled={state === "upcoming"}
              aria-current={state === "active" ? "step" : undefined}
              data-testid={`step-${s}`}
            >
              {i + 1}. {s.replace(/_/g, " ")}
            </button>
            {i < steps.length - 1 ? (
              <span className="text-[var(--color-mute-2)]" aria-hidden>
                ›
              </span>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

function FieldRow({
  field,
  form,
  suggestions,
}: {
  field: DraftingFieldSpec;
  form: ReturnType<typeof useForm<FieldValues>>;
  suggestions: string[] | null;
}) {
  const errMessage = form.formState.errors[field.name]?.message as string | undefined;
  const describedBy = errMessage ? `${field.name}-error` : undefined;

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={field.name}>
        {field.label}
        {field.required ? (
          <span className="ml-1 text-[var(--color-mute)]" aria-hidden>
            *
          </span>
        ) : null}
      </Label>
      {field.help_text ? (
        <p className="text-xs text-[var(--color-mute)]">{field.help_text}</p>
      ) : null}

      {field.kind === "text" ? (
        <Textarea
          id={field.name}
          placeholder={field.placeholder ?? undefined}
          aria-invalid={errMessage ? true : undefined}
          aria-describedby={describedBy}
          rows={4}
          {...form.register(field.name)}
        />
      ) : field.kind === "boolean" ? (
        <Controller
          control={form.control}
          name={field.name}
          render={({ field: rf }) => (
            <label className="inline-flex items-center gap-2 text-sm text-[var(--color-ink-2)]">
              <input
                id={field.name}
                type="checkbox"
                checked={Boolean(rf.value)}
                onChange={(e) => rf.onChange(e.target.checked)}
                className="h-4 w-4 rounded border-[var(--color-line)]"
              />
              Yes
            </label>
          )}
        />
      ) : field.kind === "enum" && field.enum_options ? (
        <Controller
          control={form.control}
          name={field.name}
          render={({ field: rf }) => (
            <Select
              value={(rf.value as string) || undefined}
              onValueChange={rf.onChange}
            >
              <SelectTrigger id={field.name}>
                <SelectValue placeholder="Select…" />
              </SelectTrigger>
              <SelectContent>
                {field.enum_options!.map((opt) => (
                  <SelectItem key={opt} value={opt}>
                    {opt}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        />
      ) : field.kind === "date" ? (
        <Input
          id={field.name}
          type="date"
          placeholder={field.placeholder ?? undefined}
          aria-invalid={errMessage ? true : undefined}
          aria-describedby={describedBy}
          {...form.register(field.name)}
        />
      ) : field.kind === "number" ? (
        <Input
          id={field.name}
          type="number"
          placeholder={field.placeholder ?? undefined}
          aria-invalid={errMessage ? true : undefined}
          aria-describedby={describedBy}
          {...form.register(field.name)}
        />
      ) : (
        <Input
          id={field.name}
          type="text"
          placeholder={field.placeholder ?? undefined}
          aria-invalid={errMessage ? true : undefined}
          aria-describedby={describedBy}
          {...form.register(field.name)}
        />
      )}

      {suggestions && suggestions.length > 0 ? (
        <SuggestionsRow
          fieldName={field.name}
          options={suggestions}
          onPick={(v) =>
            form.setValue(field.name, v, {
              shouldValidate: true,
              shouldDirty: true,
            })
          }
        />
      ) : null}

      {errMessage ? (
        <p
          id={describedBy}
          role="alert"
          className="text-xs text-[var(--color-danger-500,#c53030)]"
        >
          {errMessage}
        </p>
      ) : null}
    </div>
  );
}

function SuggestionsRow({
  fieldName,
  options,
  onPick,
}: {
  fieldName: string;
  options: string[];
  onPick: (value: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="inline-flex items-center gap-1 text-xs text-[var(--color-mute)]">
        <Sparkles className="h-3 w-3" aria-hidden /> Suggestions:
      </span>
      {options.slice(0, 8).map((opt) => (
        <button
          key={opt}
          type="button"
          onClick={() => onPick(opt)}
          className="rounded-full border border-[var(--color-line)] bg-white px-2.5 py-0.5 text-xs text-[var(--color-ink-2)] transition-colors hover:border-[var(--color-ink-3)] hover:bg-[var(--color-bg-2)]"
          data-testid={`suggest-${fieldName}-${opt}`}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}

function PreviewPane({
  templateType,
  facts,
}: {
  templateType: DraftTemplateType;
  facts: Record<string, unknown>;
}) {
  // 800ms debounce on the facts blob to avoid flooding Haiku on every
  // keystroke. The stepper pane already shows a spinner while the
  // mutation is in flight.
  const [debouncedFacts, setDebouncedFacts] = useState(facts);
  useEffect(() => {
    const handle = setTimeout(() => setDebouncedFacts(facts), PREVIEW_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [facts]);

  const previewQuery = useQuery({
    queryKey: ["drafting", "preview", templateType, debouncedFacts],
    queryFn: () =>
      previewDraft({ template_type: templateType, facts: debouncedFacts }),
    // Preview is advisory; don't thrash on transient failures.
    retry: 0,
    staleTime: 30_000,
  });

  return (
    <Card>
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[var(--color-ink)]">
            Partial preview
          </h3>
          {previewQuery.isFetching ? (
            <span className="inline-flex items-center gap-1 text-xs text-[var(--color-mute)]">
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
              Refreshing…
            </span>
          ) : null}
        </div>
        <p className="text-xs text-[var(--color-mute)]">
          Fields left blank render as <code>[not yet specified]</code>. This is a
          partial preview, not the final draft.
        </p>
        {previewQuery.isError ? (
          <p className="text-sm text-[var(--color-danger-500,#c53030)]">
            Could not generate a preview right now — you can still submit for
            the full draft.
          </p>
        ) : previewQuery.isPending || !previewQuery.data ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <div
            className="whitespace-pre-wrap rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] p-4 text-sm leading-relaxed text-[var(--color-ink-2)]"
            data-testid="drafting-preview-text"
          >
            {previewQuery.data.preview_text}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
