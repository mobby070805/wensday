"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { useAssistant } from "./assistant";

/** List + CRUD for a REST collection; refetches when the realtime socket reports a change. */
export function useResource<T extends { id: string }>(path: string, query = "") {
  const { syncTick } = useAssistant();
  const [items, setItems] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    try {
      setItems(await api.get<T[]>(`${path}${query}`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [path, query]);

  useEffect(() => {
    void refetch();
  }, [refetch, syncTick]);

  return {
    items, loading, error, refetch,
    create: async (body: unknown) => { await api.post(path, body); await refetch(); },
    update: async (id: string, body: unknown) => { await api.patch(`${path}/${id}`, body); await refetch(); },
    remove: async (id: string) => { await api.del(`${path}/${id}`); await refetch(); },
  };
}
