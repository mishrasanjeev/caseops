"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";

import { consumeResponseWithTimeout } from "@/lib/api/client";

const PdfPages = dynamic(() => import("./DraftPdfPages"), { ssr: false });

type Artifact = { identity: string; url: string; digest: string };
type Owner = { identity: string; controller: AbortController; artifact: Artifact | null; validating: boolean };

async function readPdf(source: string, signal: AbortSignal) {
  return consumeResponseWithTimeout(source, {
    credentials: "include", cache: "no-store", signal, headers: { Accept: "application/pdf" },
  }, 30_000, async (response) => {
    if (!response.ok) {
      const problem = await response.json().catch(() => null);
      throw new Error(typeof problem?.detail === "string" ? problem.detail : "PDF preview is unavailable. Try again.");
    }
    if (response.headers.get("content-type")?.split(";")[0] !== "application/pdf") {
      throw new Error("The server did not return a PDF. Try again.");
    }
    return response.arrayBuffer();
  });
}

async function digest(bytes: ArrayBuffer) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), value => value.toString(16).padStart(2, "0")).join("");
}

function discard(owner: Owner) {
  if (owner.artifact) URL.revokeObjectURL(owner.artifact.url);
  owner.artifact = null;
}

// No query/persistent cache: a preview is private, revision-bound export bytes.
export function useDraftPdfArtifact(source: string | null, reviewIdentity: string) {
  const identity = JSON.stringify([source, reviewIdentity]);
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [failure, setFailure] = useState<{ identity: string; message: string } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [validating, setValidating] = useState(false);
  const active = useRef<Owner | null>(null);
  const currentIdentity = useRef(identity);
  currentIdentity.current = identity;

  useEffect(() => {
    setArtifact(null);
    setFailure(null);
    setValidating(false);
    if (!source) return;
    const owner: Owner = { identity, controller: new AbortController(), artifact: null, validating: false };
    active.current = owner;
    void readPdf(source, owner.controller.signal).then(async (bytes) => {
      const hash = await digest(bytes);
      if (owner.controller.signal.aborted || active.current !== owner || currentIdentity.current !== owner.identity) return;
      owner.artifact = { identity, url: URL.createObjectURL(new Blob([bytes], { type: "application/pdf" })), digest: hash };
      setArtifact(owner.artifact);
    }).catch((error: unknown) => {
      if (!owner.controller.signal.aborted) setFailure({ identity,
        message: error instanceof Error ? error.message : "PDF preview is unavailable. Try again." });
    });
    return () => {
      owner.controller.abort();
      discard(owner);
      if (active.current === owner) active.current = null;
    };
  }, [source, identity, attempt]);

  return {
    url: artifact?.identity === identity ? artifact.url : null,
    error: failure?.identity === identity ? failure.message : null,
    validating,
    revalidate: async () => {
      const owner = active.current;
      if (!source || !owner?.artifact || owner.identity !== identity || owner.validating) return null;
      owner.validating = true;
      setValidating(true);
      try {
        const currentDigest = await digest(await readPdf(source, owner.controller.signal));
        if (active.current !== owner || owner.controller.signal.aborted || currentIdentity.current !== owner.identity) return null;
        if (currentDigest !== owner.artifact?.digest) throw new Error("The PDF or review state changed. Reload the preview before downloading.");
        return owner.artifact.url;
      } catch (error: unknown) {
        if (active.current === owner && !owner.controller.signal.aborted) {
          discard(owner);
          setArtifact(null);
          setFailure({ identity, message: error instanceof Error ? error.message : "PDF download is unavailable. Try again." });
        }
        return null;
      } finally {
        owner.validating = false;
        if (active.current === owner) setValidating(false);
      }
    },
    retry: () => { setArtifact(null); setFailure(null); setAttempt((value) => value + 1); },
  };
}

export function DraftPdfPreview({ url, error, retry }: {
  url: string | null; error: string | null; retry: () => void;
}) {
  if (error) return <div role="alert" className="flex flex-wrap items-center gap-3 text-sm">
    <p>{error}</p><button type="button" className="underline" onClick={retry}>Retry PDF preview</button>
  </div>;
  if (!url) return <p role="status" className="text-sm">Loading PDF preview...</p>;
  return <PdfPages key={url} url={url} />;
}

export function downloadDraftPdf(url: string, title: string, revision: number) {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${title.replace(/[^a-z0-9_-]/gi, "-").slice(0, 60) || "draft"}-r${revision}.pdf`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}
