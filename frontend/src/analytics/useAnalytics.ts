import { useCallback, useEffect, useRef, useState } from "react";
import { startPolling } from "./polling";
export interface Resource<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  updatedAt: number | null;
}
export function useAnalytics<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>,
  intervalMs = 0,
) {
  const [resource, setResource] = useState<Resource<T>>({
    data: null,
    loading: true,
    error: null,
    updatedAt: null,
  });
  const loader = useRef(load);
  loader.current = load;
  const polling = useRef<ReturnType<typeof startPolling<T>> | null>(null);
  useEffect(() => {
    setResource({ data: null, loading: true, error: null, updatedAt: null });
    const handle = startPolling(
      (signal) => loader.current(signal),
      {
        loading: () =>
          setResource((previous) => ({ ...previous, loading: true })),
        data: (data) =>
          setResource({
            data,
            loading: false,
            error: null,
            updatedAt: Date.now(),
          }),
        error: (error) =>
          setResource((previous) => ({ ...previous, loading: false, error })),
      },
      intervalMs,
    );
    polling.current = handle;
    return () => {
      handle.stop();
      if (polling.current === handle) polling.current = null;
    };
  }, [key, intervalMs]);
  const refresh = useCallback(() => polling.current?.refresh(), []);
  return { ...resource, refresh };
}
