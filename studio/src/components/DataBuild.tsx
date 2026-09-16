import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import * as studio from "../api/studio";
import type { BuildStatus } from "../api/studio";
import { errorText } from "../hooks/studioContext";
import { Btn } from "./minimal";

/**
 * The US workspace's data line plus a bottom sheet: the data directory's span and a "重建数据" button that runs
 * scripts/build-us-data.py (Nasdaq membership + Yahoo Finance) in the background with its log streamed here.
 */
export function DataBuild({ onBuilt, compact }: { onBuilt: () => void; compact?: boolean }) {
  const [status, setStatus] = useState<BuildStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const load = useCallback(async () => { try { setStatus(await studio.dataBuildStatus()); } catch (e) { setMessage(errorText(e)); } }, []);
  useEffect(() => { load(); }, [load]);
  const running = !!status?.running;
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => {
      const s = await studio.dataBuildStatus().catch(() => null);
      if (!s) return;
      setStatus(s);
      if (!s.running) onBuilt();
    }, 3000);
    return () => clearInterval(t);
  }, [running, onBuilt]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);
  const start = async () => {
    setMessage("");
    try { const r = await studio.startDataBuild(); if (!r.started) setMessage(r.reason || "未开始"); await load(); } catch (e) { setMessage(errorText(e)); }
  };
  const headline = running ? "构建中" : status?.exit_code === 0 ? "可重建" : status?.exit_code ? "上次失败" : "";
  const sheet = open && createPortal(
    <>
      <div className="sheet-backdrop" onClick={() => setOpen(false)} />
      <div className="sheet" role="dialog" aria-label="重建美股数据">
        <div className="sheet__head">
          <div>
            <div className="sheet__title">重建美股数据</div>
            <div className="text-[11px] text-muted">纳斯达克 100 · Nasdaq 成分快照 + Yahoo Finance 日线</div>
          </div>
          <Btn kind="text" onClick={() => setOpen(false)}>关闭</Btn>
        </div>
        <div className="sheet__body">
          <p className="m-0 text-[12px] leading-relaxed">从 2008 年起按月抓纳指 100 成分，下载所有曾经成分和 ^NDX 的日线，按 Qlib 的方式复权归一后写成二进制数据，并生成股票池和公司名。全程约 5–10 分钟，期间不能跑回测或研究。Yahoo 已下架的退市代码会被跳过。</p>
          {status?.log?.length ? <div className="sheet__log">{status.log.map((l, i) => <div key={i}>{l}</div>)}</div> : null}
          {message && <div className="text-danger">{message}</div>}
          <div className="flex flex-wrap items-center gap-2">
            <Btn kind="primary" disabled={running} onClick={start}>{running ? "构建中…" : status?.started ? "重新构建" : "开始构建"}</Btn>
            <Btn kind="text" onClick={load}>刷新</Btn>
          </div>
        </div>
      </div>
    </>,
    document.body,
  );
  if (compact) {
    return <>
      <Btn kind="primary" onClick={() => setOpen(true)}>{running ? "查看构建进度" : "构建美股数据"}</Btn>
      {sheet}
    </>;
  }
  return (
    <div className="mb-3 text-xs">
      <button type="button" onClick={() => setOpen(true)} aria-haspopup="dialog" aria-expanded={open}
        className="-mx-2.5 flex w-[calc(100%+20px)] items-center gap-2.5 rounded-[10px] px-2.5 py-2 text-left text-foreground transition-colors hover:bg-surface-secondary">
        <span className={`w-[22px] text-center text-[17px] leading-none ${running ? "animate-spin" : ""}`} aria-hidden>⟳</span>
        <span className="min-w-0 flex-1 text-[13px] font-medium">重建数据</span>
        <span className={`flex items-center gap-1.5 text-[11px] ${status?.exit_code ? "text-warning" : "text-muted"}`}>
          {running && <i className="inline-block size-[6px] rounded-full bg-warning" />}
          {headline}
        </span>
      </button>
      {sheet}
    </div>
  );
}
