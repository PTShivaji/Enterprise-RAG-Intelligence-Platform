import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage } from "../services/api";

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => Promise<void>;
}

/** Runs an async loader on mount (and when deps change) with loading / error state. */
export function useApi<T>(loader: () => Promise<T>, deps: unknown[] = []): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const generation = useRef(0);

  const reload = useCallback(async () => {
    const id = ++generation.current;
    setLoading(true);
    try {
      const result = await loaderRef.current();
      if (id === generation.current) {
        setData(result);
        setError(null);
      }
    } catch (err) {
      if (id === generation.current) setError(errorMessage(err));
    } finally {
      if (id === generation.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, reload };
}
