"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Label } from "@/components/ui/Label";

/** A read-only value the user must paste elsewhere exactly, with a Copy button. */
export function CopyField({
  id,
  label,
  value,
  description,
}: {
  id: string;
  label: string;
  value: string;
  description?: string;
}) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      toast.success(`${label} copied`);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      const input = document.getElementById(id) as HTMLInputElement | null;
      input?.select();
      toast.error("Copy is blocked in this browser. The address is selected; press Ctrl+C.");
    }
  }
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex min-w-0 items-stretch gap-2">
        <input
          id={id}
          readOnly
          value={value}
          aria-describedby={description ? `${id}-description` : undefined}
          onFocus={(event) => event.currentTarget.select()}
          className="min-w-0 flex-1 rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2 font-mono text-xs text-[var(--color-ink)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-500)]"
          data-testid={`${id}-value`}
        />
        <button
          type="button"
          onClick={() => void copy()}
          aria-label={`Copy ${label}`}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-[var(--color-line)] bg-white px-3 text-xs font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-500)]"
          data-testid={`${id}-copy`}
        >
          {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      {description ? (
        <p id={`${id}-description`} className="text-xs text-[var(--color-mute)]">
          {description}
        </p>
      ) : null}
    </div>
  );
}
