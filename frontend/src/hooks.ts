import { useEffect, useState } from "react";
import { api } from "./api";

export function useFetch<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!!path);
  useEffect(() => {
    if (!path) return;
    let alive = true;
    setLoading(true); setError(null);
    api<T>(path).then(d => alive && setData(d)).catch(e => alive && setError(e.message)).finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [path]);
  return { data, error, loading };
}
