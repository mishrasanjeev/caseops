import type { IpControlReview } from "@/lib/api/endpoints";

/**
 * The printable control-review manifest (CAL-OPS-09).
 *
 * The API *records* whether an export succeeded; it does not produce one. So
 * the artifact is built here, and `generated` is only reported back once this
 * has actually produced a document — reporting a successful export that never
 * happened would be the same falsehood as recording an acceptance nobody gave.
 *
 * CAL-OPS-09 requires the generation time, the filters and the freshness to be
 * visible on the manifest, and CAL-OPS-13 requires every mandatory exception to
 * appear. The `manifest_sha256` is printed so a filed copy can be checked back
 * against the server's record.
 *
 * Record names remain omitted. Decision notes and evidence references are
 * included because they are required review evidence, so the finished file is
 * explicitly treated as confidential firm material.
 */

const EXCEPTION_KIND: Record<string, string> = {
  uncovered: "Deadline has no coverage",
  inactive_owner: "Coverage owner is inactive",
  unprojected_calendar: "Not projected to a calendar",
  open_incident: "Open incident",
};

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function describeFilters(filters: Record<string, unknown>): string {
  const entries = Object.entries(filters).filter(
    ([, value]) => value !== null && value !== undefined && value !== "",
  );
  if (!entries.length) return "None applied";
  return entries.map(([key, value]) => `${key}=${String(value)}`).join(", ");
}

function describeFreshness(review: IpControlReview): string {
  const stale = review.freshness?.stale_sources;
  const failed = review.freshness?.failed_queries;
  const parts: string[] = [];
  if (Array.isArray(stale) && stale.length) {
    parts.push(`Stale sources: ${stale.map(String).join(", ")}`);
  }
  if (Array.isArray(failed) && failed.length) {
    parts.push(`Failed queries: ${failed.map(String).join(", ")}`);
  }
  return parts.length ? parts.join(" · ") : "All sources current at generation";
}

export function buildControlReviewManifest(review: IpControlReview): string {
  const rows: [string, string][] = [
    ["Generated", review.generated_at],
    ["Query version", review.query_version],
    ["Snapshot schema", String(review.snapshot.schema_version)],
    ["Timezone", review.snapshot.timezone],
    ["Filters", describeFilters(review.filters)],
    ["Freshness", describeFreshness(review)],
    ["Completeness", review.completeness_status],
    ["Records reviewed", String(review.report.docket_count)],
    ["Ready", String(review.report.ready_count)],
    ["Uncovered deadlines", String(review.report.uncovered_deadline_count)],
    ["Open incidents", String(review.report.open_incident_count)],
    [
      "Not projected to calendar",
      String(review.report.unprojected_calendar_count),
    ],
    ["Inactive coverage", String(review.report.inactive_coverage_count)],
    ["Review policy", review.review_policy.policy_version],
    [
      "Required signatures",
      String(review.review_policy.required_signature_count),
    ],
    [
      "Required reviewer sample",
      String(review.review_policy.required_sample_size),
    ],
    ["Manifest SHA-256", review.manifest_sha256],
  ];

  if (review.signed_off_at) {
    rows.push(["Signed off", review.signed_off_at]);
    rows.push(["Signed by", review.signer_label_snapshot ?? "Unrecorded"]);
  }

  const incompleteness = review.incompleteness_reasons.length
    ? `<section><h2>Incomplete</h2><ul>${review.incompleteness_reasons
        .map((reason) => `<li>${escapeHtml(reason)}</li>`)
        .join("")}</ul></section>`
    : "";

  const exceptions = review.mandatory_exceptions.length
    ? `<section><h2>Exceptions (${review.mandatory_exceptions.length})</h2><ul>${review.mandatory_exceptions
        .map(
          (exception) =>
            `<li>${escapeHtml(EXCEPTION_KIND[exception.kind] ?? exception.kind)} — record ${escapeHtml(
              exception.docket_id,
            )}${exception.critical ? " (critical)" : ""}</li>`,
        )
        .join("")}</ul></section>`
    : "<section><h2>Exceptions</h2><p>None recorded at generation.</p></section>";

  const includedRecords = review.snapshot.included_records.length
    ? `<section><h2>Included records (${review.snapshot.included_records.length})</h2><ul>${review.snapshot.included_records
        .map(
          (record) =>
            `<li>record ${escapeHtml(record.docket_id)} · version ${record.current_version} · SHA-256 ${escapeHtml(record.sha256)}</li>`,
        )
        .join("")}</ul></section>`
    : "<section><h2>Included records</h2><p>None visible at generation.</p></section>";

  const decisions = review.exception_decisions.length
    ? `<section><h2>Exception decisions (${review.exception_decisions.length})</h2><ul>${review.exception_decisions
        .map(
          (decision) =>
            `<li>record ${escapeHtml(decision.docket_id)} · ${escapeHtml(
              EXCEPTION_KIND[decision.exception_kind] ??
                decision.exception_kind,
            )} · ${escapeHtml(decision.disposition)} · ${escapeHtml(
              decision.annotation,
            )} · evidence ${escapeHtml(decision.evidence_reference)} · ${escapeHtml(
              decision.decided_at,
            )}</li>`,
        )
        .join("")}</ul></section>`
    : "<section><h2>Exception decisions</h2><p>None recorded.</p></section>";

  const samples = review.reviewer_samples.length
    ? `<section><h2>Independent reviewer samples (${review.reviewer_samples.length})</h2><ul>${review.reviewer_samples
        .map(
          (sample) =>
            `<li>record ${escapeHtml(sample.docket_id)} · source ${escapeHtml(
              sample.source_evidence_reference,
            )} · calculation ${escapeHtml(
              sample.calculation_evidence_reference,
            )} · coverage ${escapeHtml(sample.coverage_evidence_reference)} · ${escapeHtml(
              sample.sampled_at,
            )}</li>`,
        )
        .join("")}</ul></section>`
    : "<section><h2>Independent reviewer samples</h2><p>None recorded.</p></section>";

  const signatures = review.signatures.length
    ? `<section><h2>Signatures (${review.signatures.length}/${review.review_policy.required_signature_count})</h2><ol>${review.signatures
        .map(
          (signature) =>
            `<li>${escapeHtml(signature.signer_label_snapshot)} · ${escapeHtml(
              signature.signer_role,
            )} · ${escapeHtml(signature.signed_at)} · attestation ${escapeHtml(
              signature.attestation,
            )}</li>`,
        )
        .join("")}</ol></section>`
    : `<section><h2>Signatures (0/${review.review_policy.required_signature_count})</h2><p>None recorded.</p></section>`;

  const delta = review.predecessor_review_id
    ? `<section><h2>Changes since preceding signed review</h2><p>Predecessor ${escapeHtml(
        review.predecessor_review_id,
      )}; ${review.delta.added_docket_ids.length} added, ${
        review.delta.removed_docket_ids.length
      } removed, ${review.delta.changed_docket_ids.length} changed; ${
        review.delta.added_exception_keys.length
      } exceptions added and ${review.delta.removed_exception_keys.length} removed.</p></section>`
    : "<section><h2>Changes since preceding signed review</h2><p>No comparable signed predecessor.</p></section>";

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>IP control review ${escapeHtml(review.id)}</title>
<style>
  body { font-family: Georgia, "Times New Roman", serif; color: #1b1b21; margin: 2rem; max-width: 70ch; }
  h1 { font-size: 1.35rem; margin-bottom: 0.25rem; }
  p.sub { color: #55555f; margin-top: 0; }
  table { border-collapse: collapse; width: 100%; margin: 1.25rem 0; }
  th, td { border-bottom: 1px solid #d8d8de; padding: 0.4rem 0.5rem; text-align: left; vertical-align: top; }
  th { width: 16rem; font-weight: 600; }
  td { font-variant-numeric: tabular-nums; word-break: break-all; }
  h2 { font-size: 1rem; margin-bottom: 0.35rem; }
  ul { margin-top: 0; padding-left: 1.1rem; }
  footer { margin-top: 2rem; color: #55555f; font-size: 0.85rem; }
  @media print { body { margin: 0; } }
</style>
</head>
<body>
<h1>IP daily docket — control review</h1>
<p class="sub">Review ${escapeHtml(review.id)}</p>
<table>
${rows
  .map(
    ([label, value]) =>
      `<tr><th>${escapeHtml(label)}</th><td>${escapeHtml(value)}</td></tr>`,
  )
  .join("\n")}
</table>
${incompleteness}
${exceptions}
${includedRecords}
${decisions}
${samples}
${signatures}
${delta}
<footer>
Confidential firm material. Record titles are omitted, but review notes and
evidence references may be sensitive. Check the SHA-256 above against the stored
review to confirm this copy is tied to the frozen report.
</footer>
</body>
</html>`;
}

/** Hands the built manifest to the browser. Throws if it cannot be delivered. */
export function downloadControlReviewManifest(review: IpControlReview): void {
  const blob = new Blob([buildControlReviewManifest(review)], {
    type: "text/html;charset=utf-8",
  });
  const href = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = `ip-control-review-${review.id}.html`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    URL.revokeObjectURL(href);
  }
}
