import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import * as studio from "../api/studio";
import type { ExtraSource, ExtraStatus, SyncStatus } from "../api/studio";
import { universeLabel } from "../api/studio";
import { errorText } from "../hooks/studioContext";
import { Btn, SelectInput, TextInput } from "./minimal";
import { locale, t } from "../i18n";

const QUANTDB_PHASES: Record<string, string> = { starting: t("准备"), downloading: t("更新价格表"), extracting: t("导出 Qlib 目录"), done: t("完成"), failed: t("失败") };
const PHASES: Record<string, string> = { starting: t("准备"), downloading: t("下载"), extracting: t("校验解包"), swapping: t("替换目录"), done: t("完成"), failed: t("失败") };
const fmtTime = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString(locale(), { hour12: false }) : "—");
const carriedBy = (exports: Record<string, boolean>) => Object.entries(exports).filter(([, ok]) => ok).map(([m]) => universeLabel(m)).join("、");
const tushareKeys = (s: ExtraStatus) => Math.max(0, ...Object.entries(s.tables).filter(([name]) => name !== "cn.baostock").map(([, t]) => t.keys));

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
  // Extra A-share fields (baostock): status while the sheet is open, and a poll while their job runs.
  const [extra, setExtra] = useState<ExtraStatus | null>(null);
  const [extraJob, setExtraJob] = useState<string | null>(null);
  const extraRunning = !!extraJob;
  useEffect(() => { if (open) studio.extraDataStatus().then(setExtra).catch(() => setExtra(null)); }, [open]);
  useEffect(() => {
    if (!extraJob) return;
    const timer = setInterval(async () => {
      const job = await studio.job(extraJob).catch(() => null);
      if (job && job.status !== "running" && job.status !== "queued") {
        setExtraJob(null);
        if (job.status !== "completed") setMessage(t("扩展字段没取完：{0}", [job.error || job.status]));
        studio.extraDataStatus().then(setExtra).catch(() => null);
        onSynced();
      }
    }, 5000);
    return () => clearInterval(timer);
  }, [extraJob, onSynced]);
  const [home, setHome] = useState("");
  useEffect(() => { if (extra) setHome(extra.home_setting); }, [extra?.home_setting]);  // eslint-disable-line react-hooks/exhaustive-deps
  const saveHome = async () => {
    setBusy(true); setMessage("");
    try { setExtra(await studio.saveExtraHome(home)); } catch (e) { setMessage(errorText(e)); } finally { setBusy(false); }
  };
  const startExtra = async (source: ExtraSource) => {
    setBusy(true); setMessage("");
    try { setExtraJob((await studio.startExtraData(source)).job); } catch (e) { setMessage(errorText(e)); } finally { setBusy(false); }
  };
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
      if (!r.started) setMessage(r.reason || t("未开始"));
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
  const fromQuantdb = (status?.settings.source ?? "quantdb") === "quantdb";
  const label = (release: string) => (release.startsWith("quantdb ") ? release.slice(8) : release.slice(5));  // "quantdb 2026-09-22" → the day; "v2026-09-21" → the date
  const newer = !!(remote && local && remote.release !== local.release);
  const phase = sync?.phase ? (fromQuantdb ? QUANTDB_PHASES[sync.phase] || PHASES[sync.phase] : PHASES[sync.phase]) || sync.phase : "";
  const headline = running ? `${phase}${sync?.progress != null && sync.phase === "downloading" ? ` ${Math.round(sync.progress * 100)}%` : ""}` : newer ? (fromQuantdb ? t("可更新到 {0}", [label(remote!.release)]) : t("有新版 {0}", [label(remote!.release)])) : local?.release ? (fromQuantdb ? t("数据到 {0}", [label(local.release)]) : t("版本 {0}", [label(local.release)])) : "";
  const setSource = async (source: "quantdb" | "snapshot") => {
    if (!status) return;
    try { const s = await studio.saveDataSyncSettings({ source }); setStatus({ ...status, settings: s }); load(true, true); } catch (e) { setMessage(errorText(e)); }
  };

  return (
    <div className="text-xs">
      <button type="button" onClick={() => setOpen(true)} aria-haspopup="dialog" aria-expanded={open}
        className="-mx-2.5 flex w-[calc(100%+20px)] items-center gap-2.5 rounded-[10px] px-2.5 py-2 text-left text-foreground transition-colors hover:bg-surface-secondary">
        <span className={`w-[22px] text-center text-[17px] leading-none ${running ? "animate-spin" : ""}`} aria-hidden>⟳</span>
        <span className="min-w-0 flex-1 text-[13px] font-medium">{t("同步数据")}</span>
        <span className={`flex items-center gap-1.5 text-[11px] ${newer ? "text-accent" : "text-muted"}`}>
          {(running || newer) && <i className={`inline-block size-[6px] rounded-full ${running ? "bg-warning" : "bg-accent"}`} />}
          {headline}
        </span>
      </button>
      {open && createPortal(
        <>
          <div className="sheet-backdrop" onClick={() => setOpen(false)} />
          <div className="sheet" role="dialog" aria-label={t("同步数据")}>
            <div className="sheet__head">
              <div>
                <div className="sheet__title">{t("同步数据")}</div>
                <div className="text-[11px] text-muted">{t("Qlib 日线快照 · chenditc/investment_data")}</div>
              </div>
              <Btn kind="text" onClick={() => setOpen(false)}>{t("关闭")}</Btn>
            </div>
            <div className="sheet__body">
              <dl className="m-0 flex flex-col gap-1.5">
                <div className="sheet__row"><dt>{t("价格来源")}</dt><dd><SelectInput className="!h-[26px] w-[200px]" value={status?.settings.source ?? "quantdb"} onChange={(v) => setSource(v as "quantdb" | "snapshot")} ariaLabel={t("价格来源")} searchable={false}
                  options={[{ value: "quantdb", label: t("quantdb（Tushare 日线，按交易日增量）") }, { value: "snapshot", label: t("社区快照（GitHub 整包下载）") }]} /></dd></div>
                <div className="sheet__row"><dt>{t("本地版本")}</dt><dd>{local?.release || t("未知")}{local?.downloaded_at ? <span className="text-muted"> {t("· 下载于 {0}", [fmtTime(local.downloaded_at)])}</span> : null}</dd></div>
                <div className="sheet__row"><dt>{t("数据区间")}</dt><dd>{local?.calendar_start || "—"} → {local?.calendar_end || "—"}</dd></div>
                <div className="sheet__row"><dt>{t("最新发布")}</dt><dd>{status?.remote_error ? <span className="text-danger">{t("无法检查：{0}", [status.remote_error])}</span> : remote ? <>{remote.release}{remote.published_at ? <span className="text-muted"> · {fmtTime(remote.published_at)}</span> : null}{remote.archive_bytes ? <span className="text-muted"> · {(remote.archive_bytes / 1e6).toFixed(0)} MB</span> : null}</> : t("检查中…")}</dd></div>
              </dl>
              {(running || sync?.phase) && (
                <div className="flex flex-col gap-1.5">
                  <div className="sheet__row"><dt>{running ? t("进行中") : sync?.phase === "failed" ? t("上次同步失败") : t("上次同步")}</dt><dd>{phase}{sync?.finished_at && !running ? <span className="text-muted"> · {fmtTime(sync.finished_at)}</span> : null}</dd></div>
                  {running && <div className="sheet__bar"><i style={{ width: `${sync?.phase === "downloading" && sync.progress != null ? Math.round(sync.progress * 100) : sync?.phase === "extracting" ? 85 : sync?.phase === "swapping" ? 95 : 3}%` }} /></div>}
                  {sync?.log?.length ? <div className="sheet__log">{sync.log.map((l, i) => <div key={i}>{l}</div>)}</div> : null}
                </div>
              )}
              {message && <div className="text-danger">{message}</div>}
              <div className="flex flex-wrap items-center gap-2">
                <Btn kind="primary" disabled={busy || running} onClick={() => start(false)}>{running ? t("同步中…") : newer ? t("同步到最新") : t("检查并同步")}</Btn>
                {!newer && !running && <Btn disabled={busy} onClick={() => start(true)}>{fromQuantdb ? t("重新导出") : t("强制重下")}</Btn>}
                <Btn kind="text" disabled={busy} onClick={() => load(true, true)}>{t("重新检查")}</Btn>
              </div>
              <div className="flex flex-col gap-2 border-t border-border pt-3">
                <div className="text-[12px] font-medium">{t("扩展字段（quantdb）")}</div>
                <div className="text-[11px] text-muted">
                  {extra ? (extra.installed ? t("共享数据库 {0}", [extra.home || "—"]) : t("没有安装 quantdb：pip install -e <quantdb 仓库>，字段功能不可用。")) : t("检查中…")}
                </div>
                <p className="m-0 text-[11px] leading-relaxed text-muted">{t("A 股扩展字段从独立的 quantdb 数据库读取，其他程序共用同一份数据。位置由 QUANTDB_HOME 决定（默认 ~/.quantdb），密钥放在它的 .env 里。")}</p>
                {extra?.installed && (
                  <>
                    <div className="flex items-center gap-2">
                      <TextInput className="flex-1" value={home} onChange={setHome} placeholder={t("留空用默认 ~/.quantdb")} ariaLabel="QUANTDB_HOME" />
                      <Btn disabled={busy || extraRunning || home === extra.home_setting} onClick={saveHome}>{t("保存位置")}</Btn>
                    </div>
                    <div className="text-[11px] text-muted">
                      {t("{0}/.env 里的密钥：", [extra.home || "~/.quantdb"])}
                      {Object.entries(extra.settings).map(([key, ok]) => <span key={key} className={ok ? "ml-2" : "ml-2 opacity-50"}>{ok ? "✓" : "✗"} {key}</span>)}
                    </div>
                  </>
                )}
              </div>
              {extra?.installed && (
                <>
                  <div className="flex flex-col gap-2 border-t border-border pt-3">
                    <div className="text-[12px] font-medium">{t("baostock 字段")}</div>
                    <div className="text-[11px] text-muted">
                      {extra.tables["cn.baostock"] ? t("{0} 只股票，数据到 {1}；股票池数据带这些字段：{2}", [extra.tables["cn.baostock"].symbols, extra.tables["cn.baostock"].end || "—", carriedBy(extra.baostock_exports) || t("暂无")]) : t("还没有取过。")}
                    </div>
                    <p className="m-0 text-[11px] leading-relaxed text-muted">{t("换手率、PE / PB / PS / PCF、流通市值、ST 标记，按日拼进各 A 股股票池的因子数据（$turnover、$pe_ttm、$pb、$float_cap…），研究和重算都能用。逐只取，全 A 首次约一个半小时，之后增量。")}</p>
                    <div><Btn disabled={busy || extraRunning} onClick={() => startExtra("baostock")}>{extraRunning ? t("取字段中…") : extra.tables["cn.baostock"] ? t("增量更新 baostock 字段") : t("取 baostock 字段")}</Btn></div>
                  </div>
                  <div className="flex flex-col gap-2 border-t border-border pt-3">
                    <div className="text-[12px] font-medium">{t("Tushare 字段")}</div>
                    <div className="text-[11px] text-muted">
                      {!extra.configured ? t("quantdb 没有配置 Tushare 服务器。") : tushareKeys(extra) ? t("{0} 个交易日，数据到 {1}；股票池数据带这些字段：{2}", [tushareKeys(extra), extra.last || "—", carriedBy(extra.tushare_exports) || t("暂无")]) : t("还没有取过。")}
                    </div>
                    <p className="m-0 text-[11px] leading-relaxed text-muted">{t("按交易日取全市场的大小单资金流、融资融券、筹码分布、自由流通换手和市值、龙虎榜、大宗交易，以及按公告日对齐的财务指标、业绩预告快报、股东户数、限售解禁（$mf_net_xl、$rz_bal、$winner_rate、$roe、$unlock_30d…）。两台服务器并行、有限速，首次约三小时，之后增量。")}</p>
                    {extra.configured && <div><Btn disabled={busy || extraRunning} onClick={() => startExtra("tushare")}>{extraRunning ? t("取字段中…") : tushareKeys(extra) ? t("增量更新 Tushare 字段") : t("取 Tushare 字段")}</Btn></div>}
                  </div>
                </>
              )}
              <div className="flex flex-col gap-2 border-t border-border pt-3">
                <label className="flex items-center gap-2">
                  <input type="checkbox" className="mm-check" checked={!!status?.settings.auto} onChange={toggleAuto} />
                  <span>{t("每天自动同步，")}</span>
                  <SelectInput className="!h-[26px] w-[84px]" value={String(status?.settings.hour ?? 19)} onChange={(v) => setHour(Number(v))} ariaLabel={t("自动同步时间")} searchable={false}
                    options={Array.from({ length: 24 }, (_, h) => ({ value: String(h), label: `${String(h).padStart(2, "0")}:00` }))} />
                  <span>{t("之后检查一次")}</span>
                </label>
                {status?.settings.last_auto_check && <div className="text-[11px] text-muted">{t("上次自动检查：{0}", [status.settings.last_auto_check])}{status.settings.last_fields_check ? t("；扩展字段上次自动更新：{0}", [status.settings.last_fields_check]) : ""}</div>}
                <p className="m-0 text-[11px] leading-relaxed text-muted">{t("自动同步之后接着更新 quantdb 里的扩展字段（Tushare、董监高、baostock 增量）并重建有字段的股票池数据，规则策略的信号跟到同一天。有任务在跑就等下一个整点再试。")}</p>
                <p className="m-0 text-[11px] leading-relaxed text-muted">{fromQuantdb
                  ? t("同步先把 quantdb 里的价格表（Tushare 日线、复权因子、股票主表、指数成分）补到最新交易日，再从 quantdb 整体导出 Qlib 数据目录并替换，Qlib 和回测引擎读的格式不变。收盘后 17:30 起当天数据可用。有回测或研究在跑时不会开始。")
                  : t("同步会下载社区快照（约 565 MB），校验 sha256，解包后整体替换数据目录，失败自动回退。有回测或研究在跑时不会开始。同步后“重算到最新”和股票池数据会自动跟到新末日；已有因子的 result.h5 不会自己变。")}</p>
              </div>
            </div>
          </div>
        </>,
        document.body,
      )}
    </div>
  );
}
