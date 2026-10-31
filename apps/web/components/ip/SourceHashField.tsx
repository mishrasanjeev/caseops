"use client";

import { FileDigit } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { sha256HexOfFile } from "@/lib/ip/governance";

/**
 * Evidence that a governed version was built from a specific official source.
 * Nobody can type a SHA-256, and a pasted digest proves nothing about the file
 * the lawyer actually read, so the only path is "Choose source file": the
 * browser hashes the file locally (WebCrypto) and the file is never uploaded.
 */
export function SourceHashField({
  id,
  label = "Official source file",
  value,
  onChange,
  error,
  disabled = false,
}: {
  id: string;
  label?: string;
  value: string;
  onChange: (value: string) => void;
  error?: string | null;
  disabled?: boolean;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [computedFrom, setComputedFrom] = useState<{ name: string; size: number } | null>(null);
  const [computeError, setComputeError] = useState<string | null>(null);
  const [computing, setComputing] = useState(false);
  const labelId = `${id}-label`;
  const resultId = `${id}-result`;
  const errorId = `${id}-error`;
  const message = error ?? computeError;
  const shownFrom = value ? computedFrom : null;

  return (
    <div className="flex min-w-0 flex-col gap-1" role="group" aria-labelledby={labelId}>
      <span id={labelId} className="break-words text-sm font-medium leading-snug text-[var(--color-ink-2)]">{label}</span>
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Button
          id={id}
          type="button"
          size="sm"
          variant="secondary"
          disabled={disabled || computing}
          aria-describedby={message ? `${errorId} ${resultId}` : resultId}
          onClick={() => fileInput.current?.click()}
        >
          <FileDigit className="h-4 w-4" aria-hidden />
          {computing ? "Computing SHA-256…" : value ? "Choose a different file" : "Choose source file"}
        </Button>
        <input
          ref={fileInput}
          type="file"
          hidden
          aria-label={label}
          data-testid={`${id}-file`}
          onChange={async (event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (!file) return;
            setComputing(true);
            setComputeError(null);
            try {
              const digest = await sha256HexOfFile(file);
              setComputedFrom({ name: file.name, size: file.size });
              onChange(digest);
            } catch {
              setComputeError("This browser could not read the file. Try another browser or a local copy of the file.");
            } finally {
              setComputing(false);
            }
          }}
        />
      </div>
      <output id={resultId} aria-live="polite" className="min-w-0 break-all text-xs text-[var(--color-mute)]">
        {value
          ? <>SHA-256 <span className="font-mono">{value}</span>{shownFrom ? ` from ${shownFrom.name} (${shownFrom.size.toLocaleString("en-IN")} bytes), computed in this browser; the file was not uploaded.` : null}</>
          : "Choose the official source you relied on. Its SHA-256 is computed in this browser and the file is not uploaded."}
      </output>
      {message ? (
        <p id={errorId} className="min-w-0 break-words text-xs text-[var(--color-danger)]">{message}</p>
      ) : null}
    </div>
  );
}
