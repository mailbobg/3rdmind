import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import * as studio from "../api/studio";
import type { SyncStatus } from "../api/studio";
import { errorText } from "../hooks/studioContext";
import { Btn } from "./minimal";

const PHASES: Record<string, string> = { starting: "准备", downloading: "下载", extracting: "校验解包", swapping: "替换目录", done: "完成", failed: "失败" };
const fmtTime = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString("zh-CN", { hour12: false }) : "—");

/**
 * The rail's data line plus a bottom sheet that slides up over the page: local and upstream versions, a
 * manual sync with progress and log, and the daily auto-sync switch. Polls while a sync runs; a finished
 * sync reloads the environment so the rail's date range updates.
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
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

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
  const sync = status?.sync;
  const newer = !!(remote && local && remote.release !== local.release);
  const phase = sync?.phase ? PHASES[sync.phase] || sync.phase : "";
  const headline = running ? `${phase}${sync?.progress != null && sync.phase === "downloading" ? ` ${Math.round(sync.progress * 100)}%` : ""}` : newer ? `有新版 ${remote!.release.slice(5)}` : local?.release ? `版本 ${local.release.slice(5)}` : "";

  return (
    <div className="mb-3 text-xs">
      <button type="button" className="rail-tool" onClick={() => setOpen(true)} aria-haspopup="dialog" aria-expanded={open} title="打开同步面板">
        <i className={`inline-block size-[7px] shrink-0 rounded-full ${running ? "bg-warning" : newer ? "bg-accent" : "bg-success"}`} />
        <span className="rail-tool__label">同步数据</span>
        <span className="rail-tool__hint">{headline}</span>
        <span className="rail-tool__chevron" aria-hidden>›</span>
      </button>
      {open && createPortal(
        <>
          <div className="sheet-backdrop" onClick={() => setOpen(false)} />
          <div className="sheet" role="dialog" aria-label="同步数据">
            <div className="sheet__head">
              <div>
                <div className="sheet__title">同步数据</div>
                <div className="text-[11px] text-muted">Qlib 日线快照 · chenditc/investment_data</div>
              </div>
              <Btn kind="text" onClick={() => setOpen(false)}>关闭</Btn>
            </div>
            <div className="sheet__body">
              <dl className="m-0 flex flex-col gap-1.5">
                <div className="sheet__row"><dt>本地版本</dt><dd>{local?.release || "未知"}{local?.downloaded_at ? <span className="text-muted"> · 下载于 {fmtTime(local.downloaded_at)}</span> : null}</dd></div>
                <div className="sheet__row"><dt>数据区间</dt><dd>{local?.calendar_start || "—"} → {local?.calendar_end || "—"}</dd></div>
                <div className="sheet__row"><dt>最新发布</dt><dd>{status?.remote_error ? <span className="text-danger">无法检查：{status.remote_error}</span> : remote ? <>{remote.release}{remote.published_at ? <span className="text-muted"> · {fmtTime(remote.published_at)}</span> : null}{remote.archive_bytes ? <span className="text-muted"> · {(remote.archive_bytes / 1e6).toFixed(0)} MB</span> : null}</> : "检查中…"}</dd></div>
              </dl>
              {(running || sync?.phase) && (
                <div className="flex flex-col gap-1.5">
                  <div className="sheet__row"><dt>{running ? "进行中" : sync?.phase === "failed" ? "上次同步失败" : "上次同步"}</dt><dd>{phase}{sync?.finished_at && !running ? <span className="text-muted"> · {fmtTime(sync.finished_at)}</span> : null}</dd></div>
                  {running && <div className="sheet__bar"><i style={{ width: `${sync?.phase === "downloading" && sync.progress != null ? Math.round(sync.progress * 100) : sync?.phase === "extracting" ? 85 : sync?.phase === "swapping" ? 95 : 3}%` }} /></div>}
                  {sync?.log?.length ? <div className="sheet__log">{sync.log.map((l, i) => <div key={i}>{l}</div>)}</div> : null}
                </div>
              )}
              {message && <div className="text-danger">{message}</div>}
              <div className="flex flex-wrap items-center gap-2">
                <Btn kind="primary" disabled={busy || running} onClick={() => start(false)}>{running ? "同步中…" : newer ? "同步到最新" : "检查并同步"}</Btn>
                {!newer && !running && <Btn disabled={busy} onClick={() => start(true)}>强制重下</Btn>}
                <Btn kind="text" disabled={busy} onClick={() => load(true, true)}>重新检查</Btn>
              </div>
              <div className="flex flex-col gap-2 border-t border-border pt-3">
                <label className="flex items-center gap-2">
                  <input type="checkbox" className="mm-check" checked={!!status?.settings.auto} onChange={toggleAuto} />
                  <span>每天自动同步，</span>
                  <select className="mm-control" style={{ height: 26, padding: "0 22px 0 8px" }} value={status?.settings.hour ?? 19} onChange={(e) => setHour(Number(e.target.value))} aria-label="自动同步时间">
                    {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}
                  </select>
                  <span>之后检查一次</span>
                </label>
                {status?.settings.last_auto_check && <div className="text-[11px] text-muted">上次自动检查：{status.settings.last_auto_check}</div>}
                <p className="m-0 text-[11px] leading-relaxed text-muted">同步会下载社区快照（约 565 MB），校验 sha256，解包后整体替换数据目录，失败自动回退。有回测或研究在跑时不会开始。同步后"重算到最新"和股票池数据会自动跟到新末日；已有因子的 result.h5 不会自己变。</p>
              </div>
            </div>
          </div>
        </>,
        document.body,
      )}
    </div>
  );
}
