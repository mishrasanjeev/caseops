"use client";

// Phase B M11 slice 2 — admin email-templates catalogue editor.
// Workspace owners + admins maintain templates; fee-earners pick
// from the list when sending email from the matter Communications
// tab (Compose dialog).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Loader2, Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { apiErrorMessage } from "@/lib/api/config";
import {
  archiveEmailTemplate,
  createEmailTemplate,
  listEmailTemplates,
} from "@/lib/api/endpoints";
import type {
  EmailTemplateRecord,
  EmailTemplateVariable,
} from "@/lib/api/schemas";

// {{var_name}} parser — mirrors the backend regex so the editor can
// auto-detect variables without an extra round-trip.
const PLACEHOLDER_RE = /\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g;

function detectVariables(subject: string, body: string): EmailTemplateVariable[] {
  const seen = new Set<string>();
  const out: EmailTemplateVariable[] = [];
  for (const text of [subject, body]) {
    let m: RegExpExecArray | null;
    while ((m = PLACEHOLDER_RE.exec(text)) !== null) {
      if (!seen.has(m[1])) {
        seen.add(m[1]);
        out.push({ name: m[1], label: null, required: true });
      }
    }
  }
  return out;
}

export default function AdminEmailTemplatesPage() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);

  const query = useQuery({
    queryKey: ["admin", "email-templates"],
    queryFn: () => listEmailTemplates(),
  });

  const createMutation = useMutation({
    mutationFn: createEmailTemplate,
    onSuccess: async () => {
      toast.success("Template saved.");
      setEditing(false);
      await queryClient.invalidateQueries({
        queryKey: ["admin", "email-templates"],
      });
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not save template.")),
  });

  const archiveMutation = useMutation({
    mutationFn: archiveEmailTemplate,
    onSuccess: async () => {
      toast.success("Template archived.");
      await queryClient.invalidateQueries({
        queryKey: ["admin", "email-templates"],
      });
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not archive.")),
  });

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--color-ink)]">
            Email templates
          </h1>
          <p className="mt-1 text-xs text-[var(--color-mute)]">
            Reusable subject + body for the Compose & send action on
            matter Communications. Use <code>{"{{variable_name}}"}</code> for
            placeholders the lawyer fills at send time.
          </p>
        </div>
        <Button
          type="button"
          onClick={() => setEditing((c) => !c)}
          data-testid="email-template-new-toggle"
        >
          <Plus className="h-4 w-4" aria-hidden />
          {editing ? "Cancel" : "New template"}
        </Button>
      </header>

      {editing ? (
        <NewTemplateForm
          submitting={createMutation.isPending}
          onSubmit={(input) => createMutation.mutate(input)}
        />
      ) : null}

      {query.isError ? (
        <QueryErrorState
          title="Could not load templates"
          error={query.error}
          onRetry={query.refetch}
        />
      ) : query.isPending ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : query.data && query.data.templates.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {query.data.templates.map((t) => (
            <TemplateRow
              key={t.id}
              template={t}
              archiving={archiveMutation.isPending}
              onArchive={() => archiveMutation.mutate(t.id)}
            />
          ))}
        </ul>
      ) : (
        <EmptyState
          icon={Plus}
          title="No templates yet"
          description="Click 'New template' above to create one."
        />
      )}
    </div>
  );
}

function TemplateRow({
  template,
  archiving,
  onArchive,
}: {
  template: EmailTemplateRecord;
  archiving: boolean;
  onArchive: () => void;
}) {
  return (
    <li
      className="rounded-md border border-[var(--color-line)] bg-white p-4"
      data-testid={`email-template-${template.id}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="font-semibold text-[var(--color-ink)]">
              {template.name}
            </span>
            <span className="text-[10px] uppercase tracking-wider text-[var(--color-mute)]">
              {template.kind}
            </span>
          </div>
          {template.description ? (
            <p className="mt-1 text-xs text-[var(--color-mute)]">
              {template.description}
            </p>
          ) : null}
          <p className="mt-2 text-sm font-medium text-[var(--color-ink-2)]">
            {template.subject_template}
          </p>
          <p className="mt-1 line-clamp-2 text-xs text-[var(--color-mute)]">
            {template.body_template}
          </p>
          {template.variables.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1">
              {template.variables.map((v) => (
                <span
                  key={v.name}
                  className="rounded bg-[var(--color-line-1)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-mute)]"
                >
                  {`{{${v.name}}}`}
                  {v.required ? "" : "?"}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={archiving}
          onClick={onArchive}
          data-testid={`email-template-archive-${template.id}`}
        >
          <Archive className="h-4 w-4" aria-hidden /> Archive
        </Button>
      </div>
    </li>
  );
}

function NewTemplateForm({
  submitting,
  onSubmit,
}: {
  submitting: boolean;
  onSubmit: (input: {
    name: string;
    kind: string;
    subject_template: string;
    body_template: string;
    description?: string | null;
    variables: EmailTemplateVariable[];
  }) => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState("general");
  const [description, setDescription] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  const detectedVars = detectVariables(subject, body);

  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2" className="text-base">
          New template
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!name.trim() || !subject.trim() || !body.trim()) return;
            onSubmit({
              name: name.trim(),
              kind: kind.trim() || "general",
              description: description.trim() || null,
              subject_template: subject,
              body_template: body,
              variables: detectedVars,
            });
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-xs font-medium text-[var(--color-ink)]">
              Name
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                placeholder="e.g. Status update"
                className="rounded-md border border-[var(--color-line)] px-3 py-2 text-sm"
                data-testid="email-template-name"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-[var(--color-ink)]">
              Kind
              <input
                type="text"
                value={kind}
                onChange={(e) => setKind(e.target.value)}
                placeholder="general / intake / hearing_reminder / …"
                className="rounded-md border border-[var(--color-line)] px-3 py-2 text-sm"
                data-testid="email-template-kind"
              />
            </label>
          </div>
          <label className="flex flex-col gap-1 text-xs font-medium text-[var(--color-ink)]">
            Description (optional)
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="When should this template be used?"
              className="rounded-md border border-[var(--color-line)] px-3 py-2 text-sm"
              data-testid="email-template-description"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-[var(--color-ink)]">
            Subject
            <input
              type="text"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              required
              placeholder='e.g. Status update on your matter {{client_name}}'
              className="rounded-md border border-[var(--color-line)] px-3 py-2 text-sm"
              data-testid="email-template-subject"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-[var(--color-ink)]">
            Body
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              required
              rows={8}
              placeholder='Hi {{client_name}}, the next hearing is on {{hearing_date}}…'
              className="rounded-md border border-[var(--color-line)] px-3 py-2 text-sm font-mono"
              data-testid="email-template-body"
            />
          </label>
          {detectedVars.length > 0 ? (
            <div className="rounded-md border border-[var(--color-line)] bg-[var(--color-line-1)]/40 p-3 text-xs">
              <div className="font-medium text-[var(--color-ink)]">
                Detected variables ({detectedVars.length})
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                {detectedVars.map((v) => (
                  <span
                    key={v.name}
                    className="rounded bg-white px-2 py-0.5 font-mono"
                  >{`{{${v.name}}}`}</span>
                ))}
              </div>
              <p className="mt-1 text-[var(--color-mute)]">
                The Compose dialog will require these at send time.
              </p>
            </div>
          ) : null}
          <div className="flex justify-end">
            <Button
              type="submit"
              disabled={submitting || !name.trim() || !subject.trim() || !body.trim()}
              data-testid="email-template-submit"
            >
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Saving…
                </>
              ) : (
                "Save template"
              )}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
