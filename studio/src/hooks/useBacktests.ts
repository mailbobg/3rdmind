import { useCallback, useEffect, useRef, useState } from "react";
import * as studio from "../api/studio";
import type { BacktestRequest, BacktestResult, BacktestSummary } from "../api/studio";
import { validateRequest } from "./validateRequest";

const isActive = (status?: string) => status === "queued" || status === "running";
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** Backtest job list, the selected job's result, and 3s polling while it is queued/running. */
export function useBacktests() {
  const [jobs, setJobs] = useState<BacktestSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;
  const resultRef = useRef(result);
  resultRef.current = result;
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const disposed = useRef(false);
  // StrictMode runs mount → unmount → mount on the same instance, so the flag must be reset on (re)mount.
  useEffect(() => { disposed.current = false; return () => { disposed.current = true; clearTimeout(timer.current); }; }, []);

  const guarded = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try { await fn(); } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }, []);
  const load = useCallback(() => guarded(async () => { setJobs(await studio.backtests()); }), [guarded]);
  const fetchSelected = useCallback(async () => {
    const id = selectedRef.current;
    if (!id) return;
    const data = await studio.backtest(id);
    if (id === selectedRef.current && !disposed.current) { setResult(data); resultRef.current = data; }
  }, []);
  // Polling stops on the first failure (a single job's poll is not worth blind retries) and never touches `busy`.
  const schedule = useCallback(() => {
    clearTimeout(timer.current);
    if (disposed.current || !isActive(resultRef.current?.status)) return;
    timer.current = setTimeout(async () => {
      try { await fetchSelected(); if (!isActive(resultRef.current?.status)) setJobs(await studio.backtests()); }
      catch (e) { setError(errorText(e)); return; }
      schedule();
    }, 3000);
  }, [fetchSelected]);
  const select = useCallback(async (id: string) => {
    selectedRef.current = id;
    setSelectedId(id);
    setResult(null);
    resultRef.current = null;
    await guarded(fetchSelected);
    schedule();
  }, [guarded, fetchSelected, schedule]);
  /** Resolves true when the server accepted the job; false on validation or request failure. */
  const run = useCallback(async (config: BacktestRequest): Promise<boolean> => {
    const message = validateRequest(config);
    if (message) { setError(message); return false; }
    let accepted = false;
    await guarded(async () => {
      const { id } = await studio.runBacktest(config);
      setJobs(await studio.backtests());
      selectedRef.current = id;
      setSelectedId(id);
      const queued: BacktestResult = { id, status: "queued", config };
      setResult(queued);
      resultRef.current = queued;
      accepted = true;
      schedule();
    });
    return accepted;
  }, [guarded, schedule]);

  return { jobs, selectedId, result, error, setError, busy, load, select, run };
}
export type BacktestStore = ReturnType<typeof useBacktests>;
