import { describe, expect, it, vi } from "vitest";

import { ipImportAcknowledgements } from "../../../../tests/e2e/support/ip-import-acknowledgements";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(accept => { resolve = accept; });
  return { promise, resolve };
}

describe("dated IP import acknowledgement sequencing", () => {
  it("does not release the visible-completion assertion until both response bodies validate", async () => {
    const acknowledgements = ipImportAcknowledgements<number>();
    const second = deferred<number>();
    const visibleCompletion = vi.fn();
    const finished = acknowledgements.completed.then(visibleCompletion);
    acknowledgements.response(202, async () => 100, value => { expect(value).toBe(100); });
    await acknowledgements.continuations[0];
    expect(visibleCompletion).not.toHaveBeenCalled();
    acknowledgements.response(200, () => second.promise, value => { expect(value).toBe(101); });
    await Promise.resolve();
    expect(visibleCompletion).not.toHaveBeenCalled();
    second.resolve(101);
    await finished;
    expect(visibleCompletion).toHaveBeenCalledExactlyOnceWith([
      { status: 202, body: 100 }, { status: 200, body: 101 },
    ]);
  });

  it.each([400, 401, 409, 500])("fails HTTP %s before parsing instead of waiting for the remaining response", async status => {
    const acknowledgements = ipImportAcknowledgements<number>();
    const readBody = vi.fn();
    const rejected = expect(acknowledgements.completed).rejects.toThrow(`HTTP ${status}`);
    acknowledgements.response(status, readBody, () => undefined);
    await rejected;
    expect(readBody).not.toHaveBeenCalled();
    expect(acknowledgements.continuations).toHaveLength(1);
  });

  it("retains a malformed response error instead of releasing the assertion", async () => {
    const acknowledgements = ipImportAcknowledgements<number>();
    const error = new SyntaxError("invalid acknowledgement JSON");
    const rejected = expect(acknowledgements.completed).rejects.toBe(error);
    acknowledgements.response(202, async () => { throw error; }, () => undefined);
    await rejected;
    expect(acknowledgements.continuations).toHaveLength(1);
  });

  it("fails immediately on transport failure without fabricating the remaining acknowledgement", async () => {
    const acknowledgements = ipImportAcknowledgements<number>();
    acknowledgements.response(202, async () => 100, () => undefined);
    await acknowledgements.continuations[0];
    const error = new Error("net::ERR_ABORTED");
    const rejected = expect(acknowledgements.completed).rejects.toBe(error);
    acknowledgements.fail(error);
    await rejected;
    expect(acknowledgements.continuations).toHaveLength(1);
  });

  it("does not acknowledge a no-progress or identity validator failure", async () => {
    const acknowledgements = ipImportAcknowledgements<number>();
    const error = new Error("IP import made no progress");
    const rejected = expect(acknowledgements.completed).rejects.toBe(error);
    acknowledgements.response(202, async () => 50, () => { throw error; });
    await rejected;
    expect(acknowledgements.continuations).toHaveLength(1);
  });

  it("requires the final response body to parse even after the successful first acknowledgement", async () => {
    const acknowledgements = ipImportAcknowledgements<number>();
    acknowledgements.response(202, async () => 100, () => undefined);
    await acknowledgements.continuations[0];
    const error = new SyntaxError("invalid final acknowledgement JSON");
    const rejected = expect(acknowledgements.completed).rejects.toBe(error);
    acknowledgements.response(200, async () => { throw error; }, () => undefined);
    await rejected;
    expect(acknowledgements.continuations).toHaveLength(2);
  });
});
