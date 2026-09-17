import { useEffect, useState } from "react";
import * as studio from "../api/studio";
import type { TraceEvent, TraceTail } from "../api/studio";
import { fmtDuration, medianRoundMs, roundProgress } from "../hooks/progress";
import type { RoundProgress, StepState } from "../hooks/progress";
import { Btn } from "./minimal";
import { t } from "../i18n";

/** A clock that ticks every `ms`, for elapsed-time displays. */
export function useNow(ms = 1000, enabled = true) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms, enabled]);
  return now;
}

/** Four segments, one per step: done (filled), current (pulsing), pending (hollow); labels and durations under. */
export function StepStrip({ round, now, compact }: { round: RoundProgress; now: number; compact?: boolean }) {
  const dur = (s: StepState) => (s.state === "pending" || s.startedAt == null ? null : (s.endedAt ?? now) - s.startedAt);
  return (
    <div className={`steps${compact ? " steps--compact" : ""}`} role="list" aria-label={t("轮次进度")}>
      {round.steps.map((s) => (
        <div key={s.key} role="listitem" className="steps__item" data-state={s.state} title={`${s.label}${dur(s) != null ? ` · ${fmtDuration(dur(s))}` : ""}`}>
          <span className="steps__bar" />
          {!compact && (
            <span className="steps__meta">
              <span className="steps__label">{s.label}{s.key === "coding" && s.iterations && s.iterations > 1 ? <small> ×{s.iterations}</small> : null}</span>
              <span className="steps__time">{dur(s) != null ? fmtDuration(dur(s)) : ""}</span>
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

/**
 * The live status card at the top of a running round: step strip with durations, the estimate from earlier
 * rounds, a "may be stuck" note when the process has gone quiet, and a collapsible tail of the process log.
 */
const POLICY_LABELS: Record<string, string> = { hypothesis: t("只确认假设"), all: t("全部确认"), auto: t("全自动") };
/** "只确认假设 · 30 分钟无人则自动继续 · 已自动放行 3 个" for the status card. */
function policyLine(confirm: { mode: string; timeout_min: number } | null | undefined, autoAnswered?: number): string {
  if (!confirm) return "";
  const parts = [POLICY_LABELS[confirm.mode] || confirm.mode];
  if (confirm.mode !== "auto") parts.push(confirm.timeout_min ? t("{0} 分钟无人则自动继续", [confirm.timeout_min]) : t("一直等"));
  if (autoAnswered) parts.push(t("已自动放行 {0} 个确认", [autoAnswered]));
  return parts.join(" · ");
}

export function LiveStatus({ traceId, events, running, waiting, roundId, confirm, autoAnswered }: {
  traceId: string; events: TraceEvent[]; running: boolean; waiting: boolean; roundId: string | null;
  confirm?: { mode: string; timeout_min: number; instruction: string } | null; autoAnswered?: number }) {
  const now = useNow(1000, running);
  const rounds = roundProgress(events, running, now);
  const round = rounds.find((r) => r.id === roundId) ?? rounds[rounds.length - 1];
  const median = medianRoundMs(rounds);
  const [tail, setTail] = useState<TraceTail | null>(null);
  const [showLog, setShowLog] = useState(false);
  useEffect(() => {
    if (!running || !traceId) return;
    let stop = false;
    const load = () => studio.traceTail(traceId, 12).then((t) => { if (!stop) setTail(t); }).catch(() => {});
    load();
    const t = setInterval(load, 5000);
    return () => { stop = true; clearInterval(t); };
  }, [running, traceId]);
  if (!round) {
    if (!running) return null;
    // Before the first round's events: the process is initialising (LLM settings, knowledge base, data).
    const lastOutput = tail?.updated ? new Date(tail.updated).getTime() : null;
    return (
      <div className="live live--on">
        <div className="live__head">
          <span className="live__title"><i className="live__dot" aria-hidden />{waiting ? t("等你确认后开始") : t("正在初始化，等待第一轮假设")}</span>
          <span className="live__meta">{t("首轮通常 8–15 分钟")}</span>
        </div>
        {policyLine(confirm, autoAnswered) && <div className="mm-dim" style={{ fontSize: 11 }}>{t("确认：{0}", [policyLine(confirm, autoAnswered)])}</div>}
        <div className="live__foot">
          <span className="mm-dim">{lastOutput ? t("上次输出 {0}前", [fmtDuration(now - lastOutput)]) : ""}</span>
          <Btn kind="text" onClick={() => setShowLog((v) => !v)}>{showLog ? t("收起日志") : t("实时日志")}</Btn>
        </div>
        {showLog && <pre className="live__log">{tail?.lines?.length ? tail.lines.join("\n") : t("（还没有输出）")}</pre>}
      </div>
    );
  }
  const current = round.steps.find((s) => s.state === "current");
  const isLive = running && round === rounds[rounds.length - 1];
  const lastEventAt = events.length ? Math.max(...events.map((e) => new Date(e.timestamp).getTime())) : null;
  const lastOutputAt = tail?.updated ? new Date(tail.updated).getTime() : null;
  const quietMs = isLive ? now - Math.max(lastEventAt ?? 0, lastOutputAt ?? 0) : 0;
  // Quiet for long relative to what a round takes here (or 10 minutes when nothing is known yet).
  const stuck = isLive && !waiting && quietMs > Math.max(10 * 60_000, (median ?? 0) * 0.75);
  const expected = median ? t("这里每轮约 {0}", [fmtDuration(median)]) : t("首轮通常 8–15 分钟");
  return (
    <div className={`live${isLive ? " live--on" : ""}`}>
      <div className="live__head">
        <span className="live__title">
          {isLive ? <i className="live__dot" aria-hidden /> : null}
          {isLive
            ? waiting ? t("等你确认后继续") : current ? t("{0}中{1}", [current.label, current.key === "coding" && current.iterations ? t(" · 第 {0} 次迭代", [current.iterations]) : ""]) : t("运行中")
            : round.finished ? t("本轮用时 {0}", [fmtDuration(round.elapsed)]) : t("本轮未完成")}
        </span>
        <span className="live__meta">
          {isLive && round.elapsed != null ? t("本轮已 {0} · ", [fmtDuration(round.elapsed)]) : ""}{isLive ? expected : ""}
        </span>
      </div>
      <StepStrip round={round} now={now} />
      {isLive && policyLine(confirm, autoAnswered) && <div className="mm-dim" style={{ fontSize: 11 }}>{t("确认：{0}", [policyLine(confirm, autoAnswered)])}</div>}
      {isLive && (
        <div className="live__foot">
          <span className="mm-dim">
            {lastOutputAt ? t("上次输出 {0}前", [fmtDuration(now - lastOutputAt)]) : lastEventAt ? t("上次事件 {0}前", [fmtDuration(now - lastEventAt)]) : ""}
            {stuck ? <span className="mm-neg"> {t("· 很久没有动静，可能卡住了")}</span> : null}
          </span>
          <Btn kind="text" onClick={() => setShowLog((v) => !v)}>{showLog ? t("收起日志") : t("实时日志")}</Btn>
        </div>
      )}
      {isLive && showLog && (
        <pre className="live__log">{tail?.lines?.length ? tail.lines.join("\n") : t("（还没有输出）")}</pre>
      )}
    </div>
  );
}

/** The card shown once a research run has ended: what it did, how long it took, what to do next. */
export function RunSummary({ events, status, onBacktest, onContinue }: {
  events: TraceEvent[]; status: string; onBacktest?: (factors: string[]) => void; onContinue?: () => void }) {
  const rounds = roundProgress(events, false);
  if (!rounds.length) return null;
  const feedbacks = events.filter((e) => e.tag === "feedback.hypothesis_feedback");
  const accepted = feedbacks.filter((e) => e.content?.decision === true).length;
  const acceptedLoops = new Set(feedbacks.filter((e) => e.content?.decision === true).map((e) => String(e.loop_id)));
  const factorsByLoop = new Map<string, string[]>();
  for (const e of events) {
    if (e.tag !== "feedback.metric") continue;
    factorsByLoop.set(String(e.loop_id), ((e.content?.workspaces?.factors || []) as { name: string }[]).map((f) => f.name));
  }
  const allFactors = [...new Set([...factorsByLoop.values()].flat())];
  const acceptedFactors = [...new Set([...factorsByLoop.entries()].filter(([loop]) => acceptedLoops.has(loop)).flatMap(([, names]) => names))];
  const stamps = events.map((e) => new Date(e.timestamp).getTime()).filter((t) => isFinite(t));
  const total = stamps.length ? Math.max(...stamps) - Math.min(...stamps) : null;
  const tone = status === t("已完成") ? t("研究结束") : status === t("执行失败") ? t("研究失败") : status === t("已停止") ? t("研究已停止") : t("研究已结束");
  return (
    <div className="summary">
      <div className="summary__head">
        <span className="summary__title">{tone}</span>
        <span className="mm-dim" style={{ fontSize: 11 }}>{total != null ? t("共 {0}", [fmtDuration(total)]) : ""}{rounds.length ? t(" · 每轮约 {0}", [fmtDuration(medianRoundMs(rounds))]) : ""}</span>
      </div>
      <div><div className="summary__k">{t("轮次")}</div><div className="summary__v">{rounds.length}</div></div>
      <div><div className="summary__k">{t("接受")}</div><div className="summary__v">{accepted}<span className="mm-dim" style={{ fontSize: 12 }}> / {feedbacks.length}</span></div></div>
      <div><div className="summary__k">{t("产出因子")}</div><div className="summary__v">{allFactors.length}</div></div>
      <div><div className="summary__k">{t("被接受轮次的因子")}</div><div className="summary__v">{acceptedFactors.length}</div></div>
      {(onBacktest || onContinue) && (
        <div className="summary__actions">
          {onBacktest && acceptedFactors.length > 0 && <Btn kind="primary" onClick={() => onBacktest(acceptedFactors)}>{t("用被接受的 {0} 个因子回测 →", [acceptedFactors.length])}</Btn>}
          {onBacktest && allFactors.length > 0 && acceptedFactors.length !== allFactors.length && <Btn onClick={() => onBacktest(allFactors)}>{t("用全部 {0} 个因子回测", [allFactors.length])}</Btn>}
          {onContinue && <Btn kind={acceptedFactors.length ? undefined : "primary"} onClick={onContinue}>{t("继续研究")}</Btn>}
        </div>
      )}
    </div>
  );
}
