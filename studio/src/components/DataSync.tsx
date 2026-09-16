import { useCallback, useEffect, useState } from "react";
import * as studio from "../api/studio";
import type { SyncStatus } from "../api/studio";
import { errorText } from "../hooks/studioContext";

const PHASES: Record<string, string> = { starting: "准备", downloading: "下载", extracting: "校验解包", swapping: "替换目录", done: "完成", failed: "失败" };

/**
 * The rail's data block: what the Qlib snapshot covers, whether the upstream release is newer, a manual
 * sync button with progress, and the daily auto-sync switch. Polls while a sync runs; a finished sync
 * reloads the environment so the date range in the rail updates.
 */
export function DataSync({ onSynced }: { onSynced: () => void }) {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [message, setMessage] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async (check = false, fresh = false) => {
    try { setStatus(await studio.dataSyncStatus(check, fresh)); } catch (e) { setMessage(errorText(e)); }
  }, []);
  useEffect(() => { load(true); }, [load]);
  const running = !!status?.sync.running;
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => {
      const s = await studio.dataSyncStatus().catch(() => null);
      if (!s) return;
      setStatus(s);
      if (!s.sync.running) { onSynced(); load(true, true); }
    }, 2000);
    return () => clearInterval(t);
  }, [running, load, onSynced]);

  const start = async (force = false) => {
    setBusy(true); setMessage("");
    try {
      const r = await studio.startDataSync(force);
      if (!r.started) setMessage(r.reason || "未开始");
      await load();
    } catch (e) { setMessage(errorText(e)); } finally { setBusy(false); }
  };
  const toggleAuto = async () => {
    if (!status) return;
    try { const s = await studio.saveDataSyncSettings({ auto: !status.settings.auto }); setStatus({ ...status, settings: s }); } catch (e) { setMessage(errorText(e)); }
  };
  const setHour = async (hour: number) => {
    if (!status) return;
    try { const s = await studio.saveDataSyncSettings({ hour }); setStatus({ ...status, settings: s }); } catch (e) { setMessage(errorText(e)); }
  };

  const local = status?.local;
  const remote = status?.remote;
  const newer = !!(remote && local && remote.release !== local.release);
  const sync = status?.sync;
  return (
    <div className="mb-3 text-xs">
      <button type="button" className="flex w-full items-center gap-2 text-left" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <i className={`inline-block size-[7px] rounded-full ${running ? "bg-warning" : newer ? "bg-accent" : "bg-success"}`} />
        <span className="flex-1">同步数据</span>
        <span className="text-[11px] text-muted">{running ? `${PHASES[sync?.phase || ""] || "进行中"}${sync?.progress != null && sync.phase === "downloading" ? ` ${Math.round(sync.progress * 100)}%` : ""}` : newer ? `有新版 ${remote!.release.slice(5)}` : local?.release ? `版本 ${local.release.slice(5)}` : ""}</span>
        <span className="text-[10px] text-muted">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div className="mt-2 flex flex-col gap-2 rounded-lg border border-border p-2.5 text-[11px] text-muted">
          <div>本地 {local?.release || "未知版本"} · 数据到 {local?.calendar_end || "—"}</div>
          <div>{status?.remote_error ? `无法检查更新：${status.remote_error}` : remote ? `最新发布 ${remote.release}${remote.archive_bytes ? ` · ${(remote.archive_bytes / 1e6).toFixed(0)} MB` : ""}` : "检查更新中…"}</div>
          {sync?.log?.length ? <div className="max-h-24 overflow-auto font-mono text-[10px] leading-relaxed">{sync.log.slice(-4).map((l, i) => <div key={i}>{l}</div>)}</div> : null}
          {message && <div className="text-danger">{message}</div>}
          <div className="flex flex-wrap items-center gap-1.5">
            <button type="button" className="mm-btn" disabled={busy || running} onClick={() => start(false)}>{running ? "同步中…" : newer ? "同步到最新" : "检查并同步"}</button>
            {!newer && !running && <button type="button" className="mm-btn mm-btn--text" disabled={busy} onClick={() => start(true)}>强制重下</button>}
          </div>
          <label className="flex items-center gap-2">
            <input type="checkbox" className="mm-check" checked={!!status?.settings.auto} onChange={toggleAuto} />
            <span>每天自动同步，</span>
            <select className="mm-control" style={{ height: 24, padding: "0 20px 0 6px", fontSize: 11 }} value={status?.settings.hour ?? 19} onChange={(e) => setHour(Number(e.target.value))} aria-label="自动同步时间">
              {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}
            </select>
            <span>后</span>
          </label>
          <div>同步会下载社区快照（约 565 MB）并整体替换数据目录；有回测或研究在跑时不会开始。更新后需要重算因子、重建股票池数据的地方会自动处理。</div>
        </div>
      )}
    </div>
  );
}
