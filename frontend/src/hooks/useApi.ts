import { useState, useEffect, useCallback } from 'react';

interface UseApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

// Kept for future shared data loading; current pages mostly use explicit Promise.all flows.
export function useApi<T>(fetcher: () => Promise<T>): UseApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetcher()
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [fetcher]);

  useEffect(() => { load(); }, [load]);

  return { data, loading, error, refetch: load };
}
