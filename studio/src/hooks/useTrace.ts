import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as studio from "../api/studio";
import type { TraceEvent } from "../api/studio";
import { groupRounds, traceStatus } from "./rounds";
import { persistStudioState, restoreStudioState } from "./studioStorage";

type Liveness = "alive" | "dead" | "unknown";
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/**
 * The currently selected RD-Agent experiment: its event snapshot, polling while it runs, the rounds
 * derived from the events, and the pending user-interaction request. Same behaviour as the Vue
 * composable it replaces; `busy` is a UI indicator only and never gates calls.
 */
export function useTrace() {
  const saved = useMemo(() => restoreStudioState(), []);
  const [traceId, setTraceId] = useState<string>(saved.traceId || "");
  const [traceIds, setTraceIds] = useState<string[]>([]);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [acknowledged, setAcknowledged] = useState<string[]>(saved.acknowledged || []);
  const [liveness, setLiveness] = useState<Liveness>("unknown");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // Refs mirror the state the async callbacks need to read after an await.
  const traceIdRef = useRef(traceId);
  traceIdRef.current = traceId;
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const failures = useRef(0);
  const disposed = useRef(false);
  // StrictMode runs mount → unmount → mount on the same instance, so the flag must be reset on (re)mount.
  useEffect(() => { disposed.current = false; return () => { disposed.current = true; clearTimeout(timer.current); }; }, []);

  const rounds = useMemo(() => groupRounds(events), [events]);
  const status = useMemo(() => traceStatus(events, liveness), [events, liveness]);
  const active = status === "运行中" || status === "启动中";
  const activeRef = useRef(active);
  activeRef.current = active;

  const interactionKey = useCallback((e: TraceEvent) => `${traceIdRef.current}:${e.timestamp}:${JSON.stringify(e.content)}`, []);
  const interaction = useMemo(
    // A request answered elsewhere (another tab, or the server's confirm policy / timeout) carries `answered`.
    () => (active ? events.find((e) => e.tag === "user_interaction.request" && !e.answered && !acknowledged.includes(interactionKey(e))) || null : null),
    [active, events, acknowledged, interactionKey],
  );

  const guarded = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try { await fn(); } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }, []);

  const refresh = useCallback(async () => {
    const id = traceIdRef.current;
    if (!id) return;
    const data = await studio.traceSnapshot(id);
    if (id !== traceIdRef.current || disposed.current) return;
    setEvents(data);
    if (!data.length) {
      try {
        const info = await studio.traceStatusInfo(id);
        if (id === traceIdRef.current) setLiveness(!info.loaded ? "unknown" : info.alive ? "alive" : "dead");
      } catch { setLiveness("unknown"); }
    }
  }, []);

  // Background polling never touches `busy`; three consecutive failures stop it with a message.
  const schedule = useCallback(() => {
    clearTimeout(timer.current);
    if (disposed.current || !activeRef.current) return;
    timer.current = setTimeout(async () => {
      try { await refresh(); failures.current = 0; }
      catch (e) {
        if (++failures.current >= 3) { setError(`轮询已停止：${errorText(e)}`); return; }
      }
      schedule();
    }, 3000);
  }, [refresh]);
  // `active` flips from false to true when the first events of a running experiment arrive; keep polling in step.
  useEffect(() => { if (active) schedule(); else clearTimeout(timer.current); }, [active, schedule]);

  const loadTraces = useCallback(() => guarded(async () => { setTraceIds(await studio.traces()); }), [guarded]);
  const select = useCallback(async (id: string, launching = false) => {
    traceIdRef.current = id;
    setTraceId(id);
    setEvents([]);
    setLiveness(launching ? "alive" : "unknown");
    persistStudioState({ traceId: id });
    await guarded(refresh);
    failures.current = 0;
    schedule();
  }, [guarded, refresh, schedule]);
  const clear = useCallback(() => {
    clearTimeout(timer.current);
    traceIdRef.current = "";
    setTraceId("");
    setEvents([]);
    persistStudioState({ traceId: "" });
  }, []);
  const stop = useCallback(() => guarded(async () => { await studio.stopResearch(traceIdRef.current); await refresh(); }), [guarded, refresh]);
  const answer = useCallback(async (payload: unknown) => {
    const current = interaction;
    if (!current) return;
    await guarded(async () => {
      try {
        await studio.submitInteraction(traceIdRef.current, payload);
      } catch (e) {
        // Already answered elsewhere (policy, timeout, another tab): just drop the card.
        if (!(e instanceof studio.ApiError && e.status === 409)) throw e;
      }
      await refresh();
      setAcknowledged((list) => {
        const next = [...list, interactionKey(current)].slice(-50);
        persistStudioState({ acknowledged: next });
        return next;
      });
    });
  }, [guarded, interaction, interactionKey, refresh]);
  const registerLaunched = useCallback((id: string) => setTraceIds((list) => [id, ...list.filter((t) => t !== id)]), []);

  return { traceId, traceIds, events, rounds, status, active, interaction, error, setError, busy, setBusy,
           loadTraces, select, clear, refresh, stop, answer, registerLaunched };
}
export type TraceStore = ReturnType<typeof useTrace>;
