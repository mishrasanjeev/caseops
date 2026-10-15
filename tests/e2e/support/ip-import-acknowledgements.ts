type AcknowledgedImport<T> = { status: number; body: T };

export function ipImportAcknowledgements<T>() {
  const continuations: Array<Promise<AcknowledgedImport<T>>> = [];
  let complete!: (results: AcknowledgedImport<T>[]) => void;
  let fail!: (error: Error) => void;
  const completed = new Promise<AcknowledgedImport<T>[]>((resolve, reject) => {
    complete = resolve;
    fail = reject;
  });

  function response(
    status: number,
    readBody: () => Promise<T>,
    validate: (body: T, index: number) => void | Promise<void>,
  ) {
    const index = continuations.length;
    if (index >= 2) {
      fail(new Error("Unexpected additional IP import acknowledgement."));
      return;
    }
    const acknowledged = Promise.resolve().then(async () => {
      if (status !== [202, 200][index]) {
        throw new Error(`IP import acknowledgement ${index + 1} returned HTTP ${status}.`);
      }
      const body = await readBody();
      await validate(body, index);
      return { status, body };
    });
    continuations.push(acknowledged);
    void acknowledged.then(() => {
      if (continuations.length === 2) void Promise.all(continuations).then(complete, fail);
    }, fail);
  }

  return { continuations, completed, response, fail };
}
