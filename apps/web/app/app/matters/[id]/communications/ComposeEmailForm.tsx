"use client";

import { Eye, Loader2, Send } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { apiErrorMessage } from "@/lib/api/config";
import { previewMatterEmail, type MatterEmailMessage, type MatterEmailPreview } from "@/lib/api/communications-email";
import type { EmailTemplateRecord } from "@/lib/api/schemas";
import { useCapability } from "@/lib/capabilities";

export type EmailSubmission = MatterEmailMessage & {
  recipient_email: string; recipient_name: string | null;
};

const known = new Set(["client_name", "hearing_date", "matter_title", "matter_code"]);
const field = "min-w-0 w-full rounded-md border border-[var(--color-line)] px-3 py-2 text-sm";

export function ComposeEmailForm({ matterId, templates, loading, templateError, submitting, onSubmit }: {
  matterId: string; templates: EmailTemplateRecord[]; loading: boolean;
  templateError: string | null; submitting: boolean; onSubmit: (input: EmailSubmission) => void;
}) {
  const canManage = useCapability("email_templates:manage");
  const [templateId, setTemplateId] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [variables, setVariables] = useState<Record<string, string>>({});
  const [recipient, setRecipient] = useState("");
  const [name, setName] = useState("");
  const [preview, setPreview] = useState<{ key: string; data: MatterEmailPreview } | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const message: MatterEmailMessage = { template_id: templateId || null, subject, body, variables };
  const key = JSON.stringify(message);
  const current = preview?.key === key ? preview.data : null;
  const selected = templates.find((t) => t.id === templateId);
  const customVariables = [...new Set([
    ...(selected?.variables.map((v) => v.name) ?? []),
    ...Array.from(`${subject}\n${body}`.matchAll(/\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g), (m) => m[1]),
  ])].filter((v) => !known.has(v)).slice(0, 40);
  const validMessage = subject.trim().length >= 2 && body.trim().length >= 2;
  const ready = !!current && !current.missing_variables.length && !current.invalid_placeholders.length;

  async function showPreview() {
    if (!validMessage || previewing) return;
    setPreview(null);
    setError(null);
    setPreviewing(true);
    try {
      setPreview({ key, data: await previewMatterEmail(matterId, message) });
    } catch (err) {
      setError(apiErrorMessage(err, "Could not preview email. Try again."));
    } finally {
      setPreviewing(false);
    }
  }

  return <section className="min-w-0 border-y border-[var(--color-line)] py-4" aria-label="Compose email">
    <h2 className="mb-3 text-base font-semibold">Compose &amp; send</h2>
    <form onSubmit={(e) => {
      e.preventDefault();
      if (ready && !submitting && !previewing && recipient.trim()) {
        onSubmit({ ...message, recipient_email: recipient.trim(), recipient_name: name.trim() || null });
      }
    }}>
      <fieldset disabled={submitting} className="flex min-w-0 flex-col gap-3">
        {loading ? <p role="status">Loading templates...</p> : null}
        {templateError ? <p role="alert" className="text-sm">{templateError}</p> : null}
        <div className="flex min-w-0 flex-wrap items-end gap-3">
          <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs font-medium">Template
            <select className={field} value={templateId} data-testid="comm-send-template" onChange={(e) => {
              const t = templates.find((item) => item.id === e.target.value);
              setTemplateId(e.target.value); setSubject(t?.subject_template ?? "");
              setBody(t?.body_template ?? ""); setVariables({}); setPreview(null); setError(null);
            }}>
              <option value="">Manual message</option>
              {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </label>
          {canManage ? <a className="shrink-0 py-2 text-sm underline" href="/app/admin/email-templates">Manage templates</a> : null}
        </div>
        <div className="grid min-w-0 gap-3 sm:grid-cols-2">
          <label className="flex min-w-0 flex-col gap-1 text-xs font-medium">Recipient email
            <input className={field} type="email" required value={recipient} onChange={(e) => setRecipient(e.target.value)} data-testid="comm-send-recipient-email" />
          </label>
          <label className="flex min-w-0 flex-col gap-1 text-xs font-medium">Recipient name (optional)
            <input className={field} maxLength={255} value={name} onChange={(e) => setName(e.target.value)} data-testid="comm-send-recipient-name" />
          </label>
        </div>
        <label className="flex min-w-0 flex-col gap-1 text-xs font-medium">Subject
          <input className={field} required maxLength={400} value={subject} onChange={(e) => setSubject(e.target.value)} data-testid="comm-send-subject" />
        </label>
        <label className="flex min-w-0 flex-col gap-1 text-xs font-medium">Message
          <textarea className={field} rows={7} required maxLength={20000} value={body} onChange={(e) => setBody(e.target.value)} data-testid="comm-send-body" />
        </label>
        {customVariables.map((v) => <label key={v} className="flex min-w-0 flex-col gap-1 text-xs font-medium">{selected?.variables.find((item) => item.name === v)?.label || v}
          <input className={field} maxLength={2000} value={variables[v] ?? ""} onChange={(e) => setVariables((old) => ({ ...old, [v]: e.target.value }))} data-testid={`comm-send-var-${v}`} />
        </label>)}
        {error ? <p role="alert" className="text-sm">{error}</p> : null}
        {current ? <div className="min-w-0 space-y-2 border-t border-[var(--color-line)] pt-3" data-testid="comm-send-preview-result">
          <h3 className="text-sm font-semibold">Preview</h3>
          {current.missing_variables.length || current.invalid_placeholders.length ? <p role="alert" className="break-words text-sm">
            Not ready to send. Missing values or unsupported placeholders: {[...current.missing_variables, ...current.invalid_placeholders].join(", ")}.
            {" "}Update the matter or replace these placeholders in the message, then preview again.
          </p> : null}
          <p className="break-words text-sm font-semibold">{current.subject}</p>
          <p className="whitespace-pre-wrap break-words text-sm">{current.body}</p>
        </div> : null}
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="outline" disabled={!validMessage || previewing} onClick={showPreview} data-testid="comm-send-preview">
            {previewing ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />} Preview
          </Button>
          <Button type="submit" disabled={!ready || previewing || submitting || !recipient.trim()} data-testid="comm-send-submit">
            <Send className="h-4 w-4" aria-hidden />{submitting ? "Sending..." : "Send"}
          </Button>
        </div>
      </fieldset>
    </form>
  </section>;
}
