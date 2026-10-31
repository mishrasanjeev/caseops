"use client";

import { FileDigit } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { sha256HexOfFile } from "@/lib/ip/governance";

/**
 * SHA-256 of an official source. Nobody can type a digest from memory, so the
 * usual path is "Compute from file": the browser hashes the chosen file
 * locally (WebCrypto) and the file itself is never uploaded. A pasted digest
 * is still accepted and validated by the caller.
 */
export function SourceHashField({
  id,
  label = "Source SHA-256",
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
  const [computedFrom, setComputedFrom] = useState<string | null>(null);
  const [computeError, setComputeError] = useState<string | null>(null);
  const [computing, setComputing] = useState(false);
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const message = error ?? computeError;

  return (
    <div className="flex min-w-0 flex-col gap-1">
      <Label htmlFor={id} className="break-words leading-snug">{label}</Label>
      <Input
        id={id}
        value={value}
        disabled={disabled}
        spellCheck={false}
        autoComplete="off"
        className="font-mono text-xs"
        aria-invalid={message ? true : undefined}
        aria-describedby={message ? `${errorId} ${hintId}` : hintId}
        onChange={(event) => {
          setComputedFrom(null);
          onChange(event.target.value.trim());
        }}
        placeholder="64 hexadecimal characters"
      />
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={disabled || computing}
          onClick={() => fileInput.current?.click()}
        >
          <FileDigit className="h-4 w-4" aria-hidden /> {computing ? "Computing…" : "Compute from file"}
        </Button>
        <input
          ref={fileInput}
          type="file"
          className="sr-only"
          tabIndex={-1}
          aria-label={`${label}: source file to hash`}
          data-testid={`${id}-file`}
          onChange={async (event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (!file) return;
            setComputing(true);
            setComputeError(null);
            try {
              onChange(await sha256HexOfFile(file));
              setComputedFrom(file.name);
            } catch {
              setComputeError("This browser could not hash the file. Paste the SHA-256 instead.");
            } finally {
              setComputing(false);
            }
          }}
        />
      </div>
      <p id={hintId} className="min-w-0 break-words text-xs text-[var(--color-mute)]">
        {computedFrom
          ? `Computed from ${computedFrom} in this browser; the file was not uploaded.`
          : "Choose the official source file to compute its SHA-256 here, or paste the published digest."}
      </p>
      {message ? (
        <p id={errorId} className="min-w-0 break-words text-xs text-[var(--color-danger)]">{message}</p>
      ) : null}
    </div>
  );
}
