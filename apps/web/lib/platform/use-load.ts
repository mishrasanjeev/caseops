"use client";

import { useEffect, useState } from "react";

import { consoleErrorMessage } from "./client";

export function usePlatformLoad<T>(load: (signal: AbortSignal) => Promise<T>) {
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<{ pending: boolean; data: T | null; error: string | null }>({ pending: true, data: null, error: null });
  useEffect(() => {
    const controller = new AbortController();
    setState({ pending: true, data: null, error: null });
    void load(controller.signal).then((data) => {
      if (!controller.signal.aborted) setState({ pending: false, data, error: null });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setState({ pending: false, data: null, error: consoleErrorMessage(error) });
    });
    return () => controller.abort();
  }, [load, version]);
  return { ...state, reload: () => setVersion((value) => value + 1) };
}
