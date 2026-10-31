import { useCallback, useEffect, useRef, useState } from "react";
import { readFailure } from "../domain/repository";
import type { ReadFailure } from "../domain/repository";
export type Resource<T> =
  | { state: "loading" }
  | { state: "ready"; data: T }
  | { state: "error"; error: ReadFailure };
export function useResource<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>,
  enabled = true,
) {
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{
    key: string;
    attempt: number;
    value: Resource<T>;
  }>({ key, attempt: -1, value: { state: "loading" } });
  const loader = useRef(load);
  loader.current = load;
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let current = true;
    setResult({ key, attempt, value: { state: "loading" } });
    loader.current(controller.signal).then(
      (data) => {
        if (current)
          setResult({ key, attempt, value: { state: "ready", data } });
      },
      (error) => {
        if (current)
          setResult({
            key,
            attempt,
            value: { state: "error", error: readFailure(error) },
          });
      },
    );
    return () => {
      current = false;
      controller.abort();
    };
  }, [key, attempt, enabled]);
  const reload = useCallback(() => setAttempt((value) => value + 1), []);
  const resource: Resource<T> =
    !enabled || result.key !== key || result.attempt !== attempt
      ? { state: "loading" }
      : result.value;
  return { resource, reload };
}
