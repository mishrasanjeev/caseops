export class BoundedNetworkEvidence<K> {
  readonly pending = new Map<K, {
    route: string; method: string; startedAt: string;
    response?: { status: number; requestId: string | null };
  }>();
  readonly records: Array<Record<string, unknown>> = [];
  omitted = 0;

  start(key: K, entry: { route: string; method: string; startedAt: string }): void {
    if (entry.method === "GET" && entry.route.startsWith("web/")) { this.omitted++; return; }
    if (this.pending.size >= 128) {
      const read = [...this.pending].find(([, value]) => /^(?:GET|HEAD|OPTIONS)$/.test(value.method));
      if (!read) { this.omitted++; return; }
      this.pending.delete(read[0]);
      this.omitted++;
    }
    this.pending.set(key, entry);
  }

  received(key: K, status: number, requestId: string | null): void {
    const entry = this.pending.get(key);
    if (entry) entry.response = { status, requestId };
  }

  finish(key: K, finishedAt: string): void {
    const entry = this.pending.get(key);
    if (!entry) return;
    this.pending.delete(key);
    const { response, ...safe } = entry;
    this.add(response
      ? { ...safe, ...response, finishedAt, outcome: "response_completed", problemType: null }
      : { ...safe, finishedAt, outcome: "response_unavailable" });
  }

  fail(key: K, finishedAt: string, failureCode: string): void {
    const entry = this.pending.get(key);
    if (!entry) return;
    this.pending.delete(key);
    const { response: _response, ...safe } = entry;
    this.add({ ...safe, finishedAt, outcome: "transport_failed", failureCode });
  }

  retainPending(): void {
    for (const { response: _response, ...safe } of this.pending.values()) {
      this.add({ ...safe, finishedAt: null, outcome: "pending_at_test_end" });
    }
    this.pending.clear();
  }

  add(record: Record<string, unknown>): void {
    if (this.records.length >= 64) {
      const minimum = Math.min(...this.records.map(priority));
      if (priority(record) < minimum) { this.omitted++; return; }
      this.records.splice(this.records.findIndex((value) => priority(value) === minimum), 1);
      this.omitted++;
    }
    this.records.push(record);
  }

  snapshot(): { omitted: number; records: Array<Record<string, unknown>> } {
    return { omitted: this.omitted, records: this.records.map((record) => ({ ...record })) };
  }
}

function priority(record: Record<string, unknown>): number {
  if (record.outcome === "transport_failed" || (typeof record.status === "number" && record.status >= 400)) return 3;
  return /^(?:POST|PUT|PATCH|DELETE)$/.test(String(record.method)) ? 2 : 1;
}
