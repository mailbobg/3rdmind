import { useCallback, useEffect, useRef, useState } from "react";
import * as studio from "../api/studio";
import type { SearchRequest, SearchResult, SearchSummary } from "../api/studio";

const live = (status?: string) => status === "queued" || status === "running";
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** Portfolio-search jobs: the list, the selected job's result, and 3s polling while it runs. */
export function useSearches() {
  const [jobs, setJobs] = useState<SearchSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;
  const resultRef = useRef(result);
  resultRef.current = result;
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const disposed = useRef(false);
  useEffect(() => { disposed.current = false; return () => { disposed.current = true; clearTimeout(timer.current); }; }, []);

  const guarded = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await fn(); } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }, []);
  const load = useCallback(() => guarded(async () => { setJobs(await studio.searches()); }), [guarded]);
  const fetchSelected = useCallback(async () => {
    const id = selectedRef.current;
    if (!id) return;
    const data = await studio.search(id);
    if (id === selectedRef.current && !disposed.current) { setResult(data); resultRef.current = data; }
  }, []);
  const schedule = useCallback(() => {
    clearTimeout(timer.current);
    if (disposed.current || !live(resultRef.current?.status)) return;
    timer.current = setTimeout(async () => {
      try { await fetchSelected(); if (!live(resultRef.current?.status)) setJobs(await studio.searches()); }
      catch (e) { setError(errorText(e)); return; }
      schedule();
    }, 3000);
  }, [fetchSelected]);
  const select = useCallback(async (id: string) => {
    selectedRef.current = id; setSelectedId(id); setResult(null); resultRef.current = null;
    await guarded(fetchSelected);
    schedule();
  }, [guarded, fetchSelected, schedule]);
  const run = useCallback(async (config: SearchRequest): Promise<boolean> => {
    let accepted = false;
    await guarded(async () => {
      const { id } = await studio.runSearch(config);
      setJobs(await studio.searches());
      selectedRef.current = id; setSelectedId(id);
      const queued: SearchResult = { id, status: "queued", created: new Date().toISOString(), config };
      setResult(queued); resultRef.current = queued;
      accepted = true;
      schedule();
    });
    return accepted;
  }, [guarded, schedule]);

  return { jobs, selectedId, result, error, setError, busy, load, select, run };
}
