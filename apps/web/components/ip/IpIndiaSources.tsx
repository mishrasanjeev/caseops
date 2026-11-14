"use client";

import { ExternalLink } from "lucide-react";
import { useId, useState } from "react";

import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { IPINDIA_REVIEWED_ON, IPINDIA_SOURCES, searchIpIndiaSources, type IpIndiaSourceKind } from "@/lib/ip/ipindia-sources";

const kindLabel = { register: "External register", form: "Form reference", rule: "Rule reference" };

export function IpIndiaSources() {
  const id = useId();
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<"all" | IpIndiaSourceKind>("all");
  const rows = searchIpIndiaSources(query, kind);
  return <details className="min-w-0 border-y border-line py-4" data-testid="ipindia-sources">
    <summary className="cursor-pointer font-semibold">IP India official sources and form references</summary>
    <section aria-label="IP India reference search" className="mt-4 min-w-0 space-y-4">
      <p className="text-sm text-mute">India only. Reviewed {IPINDIA_REVIEWED_ON}. This search covers {IPINDIA_SOURCES.length} curated references, not live patent, trademark or design records. Registry automation remains separate and is not enabled here.</p>
      <div className="flex min-w-0 flex-wrap gap-3">
        <div className="min-w-0 flex-1 basis-56"><Label htmlFor={`${id}-query`}>Search official references</Label>
          <Input id={`${id}-query`} type="search" maxLength={200} value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
        <div className="min-w-0 basis-44"><Label htmlFor={`${id}-kind`}>Source type</Label>
          <select id={`${id}-kind`} className="h-10 w-full min-w-0 rounded-sm border border-line bg-white px-3 text-sm" value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}>
            <option value="all">All references</option><option value="register">External registers</option><option value="form">Forms</option><option value="rule">Rules</option>
          </select>
        </div>
      </div>
      <p role="status" className="text-sm">{rows.length} of {IPINDIA_SOURCES.length} references</p>
      {rows.length === 0 ? <p>No curated reference matches. This does not mean a right or official record does not exist.</p> : <ul className="divide-y divide-line">
        {rows.map((row) => <li key={row.id} className="min-w-0 space-y-2 py-4 text-sm">
          <p className="text-xs text-mute">{kindLabel[row.kind]} · {row.domain}</p>
          <a className="inline-flex min-w-0 items-start gap-2 break-words font-semibold text-brand-700 underline" href={row.url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">
            <span className="min-w-0 break-words">{row.title}</span><ExternalLink className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          </a>
          <p>{row.summary}</p>
          {row.fields.length > 0 && <ol className="list-inside list-decimal">{row.fields.map((field) => <li key={field}>{field}</li>)}</ol>}
          <p className="text-mute">{row.access}</p>
          {row.sha256 && <details><summary className="cursor-pointer text-xs">Reviewed artifact SHA-256</summary><code className="block break-all text-xs">{row.sha256}</code></details>}
          <a className="text-xs underline" href={row.discoveredFrom} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Official source index</a>
        </li>)}
      </ul>}
    </section>
  </details>;
}
