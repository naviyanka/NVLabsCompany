import { useState, useEffect, useCallback, useRef } from 'react';
import { ApiClientError } from '@/api/client';

export interface UseApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export interface UseApiReturn<T> extends UseApiState<T> {
  refetch: () => void;
}

export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = []
): UseApiReturn<T> {
  const [state, setState] = useState<UseApiState<T>>({
    data: null,
    loading: true,
    error: null,
  });

  // Serialize deps to a stable string to avoid infinite loops when callers
  // pass object/array literals that create new references each render.
  const depsKey = JSON.stringify(deps);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const fetchData = useCallback(async () => {
    setState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const data = await fetcherRef.current();
      setState({ data, loading: false, error: null });
    } catch (err) {
      const message =
        err instanceof ApiClientError
          ? err.detail
          : err instanceof Error
            ? err.message
            : 'An unexpected error occurred';
      setState({ data: null, loading: false, error: message });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [depsKey]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  return { ...state, refetch: fetchData };
}
