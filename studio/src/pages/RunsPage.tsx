import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert } from "@heroui/react";
import * as studio from "../api/studio";
import type { ExperimentSummary, Job } from "../api/studio";
import { backtestStatusLabel } from "../hooks/backtestStatus";
import { EXPERIMENT_STATUS_LABELS, mergeExperiments, shortTime } from "../hooks/experiments";
import { JOB_KIND_LABELS } from "../hooks/useJobs";
import { fmtDuration } from "../hooks/progress";
import { shortName, useStudio } from "../hooks/studioContext";
import { PageFrame } from "../components/PageFrame";
import { BacktestResultView } from "../components/BacktestResultView";
import { RoundDetail } from "../components/RoundViews";
import { useNow } from "../components/Progress";
import { Block, Btn, Empty, Num, StatusTag, Table, TextTabs } from "../components/minimal";
import type { ReactNode } from "react";
import { Hint } from "../components/widgets";

interface Row {
  key: string; kind: string; id: string; name: string; detail: string; result: ReactNode; status: string; time: string | null;
  live?: boolean; job?: Job;
}

/** Inline progress for a live job: a bar with done/total, or an indeterminate slide with its message. */
function JobProgress({ job }: { job: Job }) {
  const p = job.progress;
  const fraction = p && p.total ? Math.min(1, p.done / p.total) : null;
  return (
    <span className="jobbar" title={job.message || undefined}>
      <span className="jobbar__track">{fraction != null ? <span className="jobbar__fill" style={{ width: `${Math.round(fraction * 100)}%` }} /> : <span className="jobbar__fill jobbar__fill--busy" />}</span>
      <span className="jobbar__text">{fraction != null ? `${p!.done}/${p!.total}` : ""}{job.message ? `${fraction != null ? " · " : ""}${job.message}` : ""}</span>
    </span>
  );
}

const JOB_STATUS: Record<string, string> = { queued: "排队中", running: "运行中", completed: "已完成", failed: "失败" };

/**
 * Every run in one list: research experiments, backtests, and every other background job the server knows
 * (searches, take-apart diagnoses, refreshes, strategy updates, data work), live ones first with progress.
 */
export function RunsPage() {
  const { trace, backtests, layout, workspace } = useStudio();
  const navigate = useNavigate();
  const [filter, setFilter] = useState("all");
  const [selectedKey, setSelectedKey] = useState("");
  const [summaries, setSummaries] = useState<ExperimentSummary[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const loadSummaries = useCallback(() => { studio.experiments().then(setSummaries).catch(() => {}); }, []);
  const loadJobs = useCallback(() => { studio.jobs().then((r) => setJobs(r.items)).catch(() => {}); }, []);
  useEffect(() => { loadSummaries(); }, [loadSummaries, trace.traceIds, trace.status]);
  useEffect(() => { loadJobs(); const t = setInterval(loadJobs, 5000); return () => clearInterval(t); }, [loadJobs]);
  const anyLive = jobs.some((j) => j.status === "running" || j.status === "queued");
  const now = useNow(1000, anyLive);
  // Live backtests/searches move; keep their lists fresh while anything runs.
  useEffect(() => { if (anyLive) { const t = setInterval(() => { backtests.load(); loadSummaries(); }, 10000); return () => clearInterval(t); } }, [anyLive]); // eslint-disable-line react-hooks/exhaustive-deps

  const rows = useMemo<Row[]>(() => {
    const jobById = new Map(jobs.map((j) => [j.id, j]));
    const research: Row[] = mergeExperiments(trace.traceIds, summaries).map((e) => {
      const job = jobById.get(`research:${e.id}`);
      const live = e.status === "running" || e.status === "starting";
      return {
        key: `r:${e.id}`, kind: "research", id: e.id, name: shortName(e.id), detail: e.hypothesis || e.scenario, live, job,
        result: live && job ? <JobProgress job={job} /> : e.rounds == null ? <span className="mm-dim">—</span> : `${e.rounds} 轮 · ${e.accepted} 接受`,
        status: e.id === trace.traceId && trace.events.length ? trace.status : EXPERIMENT_STATUS_LABELS[e.status], time: e.updated,
      };
    });
    const bts: Row[] = backtests.jobs.map((b) => {
      const job = jobById.get(b.id);
      const live = b.status === "queued" || b.status === "running";
      return {
        key: `b:${b.id}`, kind: "backtest", id: b.id, name: b.id.slice(0, 8), live, job,
        detail: `${b.config.factors?.length ?? 0} 信号 · ${b.config.model?.method === "lgbm" ? "LightGBM" : "排名加权"} · ${b.config.start} → ${b.config.end} · ${b.config.market}`,
        result: live && job ? <JobProgress job={job} /> : <Num value={b.total_return} format={(v) => `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`} />,
        status: backtestStatusLabel(b.status), time: b.created || null,
      };
    });
    const seen = new Set([...research.map((r) => `research:${r.id}`), ...bts.map((r) => r.id)]);
    const others: Row[] = jobs.filter((j) => !seen.has(j.id) && j.kind !== "research" && j.kind !== "backtest").map((j) => {
      const live = j.status === "queued" || j.status === "running";
      const elapsed = j.started ? (j.finished ? new Date(j.finished).getTime() : now) - new Date(j.started).getTime() : null;
      return {
        key: `j:${j.id}`, kind: j.kind, id: j.id, name: j.label, live, job: j,
        detail: [j.market, elapsed != null ? `用时 ${fmtDuration(elapsed)}` : "", j.error ? `失败：${j.error}` : ""].filter(Boolean).join(" · "),
        result: live ? <JobProgress job={j} /> : j.result?.total_return != null ? <Num value={j.result.total_return} format={(v) => `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`} />
          : j.result?.end ? <span className="mm-mono mm-dim">→ {j.result.end}</span> : <span className="mm-dim">—</span>,
        status: JOB_STATUS[j.status] || j.status, time: j.finished || j.started,
      };
    });
    const all = [...others, ...bts, ...research];
    const filtered = filter === "all" ? all : filter === "research" ? all.filter((r) => r.kind === "research") : filter === "backtest" ? all.filter((r) => r.kind === "backtest") : all.filter((r) => r.kind !== "research" && r.kind !== "backtest");
    // Live first, then newest.
    return filtered.sort((a, b) => Number(!!b.live) - Number(!!a.live) || (b.time || "").localeCompare(a.time || ""));
  }, [filter, trace.traceIds, trace.traceId, trace.status, trace.events.length, backtests.jobs, summaries, jobs, now]);
  const selected = rows.find((r) => r.key === selectedKey) || null;
  const open = async (row: Row) => {
    setSelectedKey(row.key);
    if (row.kind === "research") { layout.openResults(); await trace.select(row.id); }
    else if (row.kind === "backtest") { layout.openResults(); await backtests.select(row.id); }
  };
  const goTo = (row: Row) => {
    if (row.kind === "research") navigate(workspace.path(`/research?trace=${encodeURIComponent(row.id)}`));
    else if (row.kind === "backtest") navigate(workspace.path(`/backtest?job=${encodeURIComponent(row.id)}`));
    else if (row.job?.link?.page === "search") navigate(workspace.path(`/backtest?tab=search${row.job.link.id ? `&job=${encodeURIComponent(row.job.link.id)}` : ""}`));
    else if (row.job?.link?.page === "strategies") navigate(workspace.path(`/strategies${row.job.link.id ? `?id=${encodeURIComponent(row.job.link.id)}` : ""}`));
    else if (row.job?.link?.page === "factors") navigate(workspace.path("/factors"));
    else if (row.job?.link?.page === "backtest") navigate(workspace.path(`/backtest${row.job.link.id ? `?job=${encodeURIComponent(row.job.link.id)}` : ""}`));
  };
  const liveCount = rows.filter((r) => r.live).length;

  return (
    <PageFrame
      tabs={<TextTabs label="类型" value={filter} onChange={setFilter} items={[{ key: "all", label: "全部" }, { key: "research", label: "研究" }, { key: "backtest", label: "回测" }, { key: "other", label: "其他任务" }]} />}
      actions={<Btn onClick={() => { trace.loadTraces(); backtests.load(); loadSummaries(); loadJobs(); }}>刷新</Btn>}
      resultsTitle={selected ? (selected.kind === "research" ? selected.name : selected.kind === "backtest" ? `回测 ${selected.name}` : selected.name) : "详情"}
      resultsActions={selected && (selected.kind === "research" || selected.kind === "backtest" || selected.job?.link?.page) ? <Btn onClick={() => goTo(selected)}>{selected.kind === "research" ? "在研究页打开 →" : selected.kind === "backtest" ? "在回测页打开 →" : "打开 →"}</Btn> : undefined}
      results={
        selected?.kind === "research" ? (
          <div className="flex flex-col gap-3">
            {trace.status === "未加载" && <Alert status="accent"><Alert.Indicator /><Alert.Content><Alert.Title>这个实验的事件未加载到服务端。</Alert.Title></Alert.Content></Alert>}
            {trace.rounds.map((round) => <RoundDetail key={round.id} round={round} />)}
          </div>
        ) : selected?.kind === "backtest" && backtests.result ? <BacktestResultView result={backtests.result} onDiagnose={backtests.diagnose} />
        : selected?.job ? (
          <div className="flex flex-col gap-2 text-xs">
            <div><span className="mm-dim">类型</span> {JOB_KIND_LABELS[selected.job.kind] || selected.job.kind}</div>
            <div><span className="mm-dim">状态</span> {JOB_STATUS[selected.job.status] || selected.job.status}{selected.job.message ? ` · ${selected.job.message}` : ""}</div>
            {selected.job.started && <div><span className="mm-dim">开始</span> {shortTime(selected.job.started)}{selected.job.finished ? ` → ${shortTime(selected.job.finished)}` : ""}</div>}
            {selected.job.error && <Alert status="danger"><Alert.Indicator /><Alert.Content><Alert.Title>{selected.job.error}</Alert.Title></Alert.Content></Alert>}
            {selected.job.result && <pre className="live__log">{JSON.stringify(selected.job.result, null, 2)}</pre>}
          </div>
        ) : <Hint>点一行查看详情。</Hint>
      }
    >
      <Block title="记录" count={rows.length} note={liveCount ? `${liveCount} 个在跑` : undefined}>
        {rows.length ? (
          <Table label="运行记录" columns={[{ label: "类型", width: 76 }, { label: "名称", width: "26%" }, { label: "说明" }, { label: "结果 / 进度", width: 170, optional: true }, { label: "状态", width: 72 }, { label: "时间", width: 100, optional: true }]}
            rows={rows.map((r) => ({
              key: r.key, selected: r.key === selectedKey, onClick: () => open(r),
              cells: [
                <span key="k" className="mm-dim">{JOB_KIND_LABELS[r.kind] || r.kind}</span>,
                <span key="n" className={`${r.kind === "backtest" ? "mm-mono " : ""}mm-name block truncate`} title={r.name}>{r.name}</span>,
                <span key="d" className="mm-dim block truncate" title={r.detail}>{r.detail}</span>,
                r.result,
                r.live ? <span key="s" className="inline-flex items-center gap-1.5 text-[11px]"><i className="live__dot" aria-hidden />{r.status}</span> : <StatusTag key="s" status={r.status} />,
                <span key="t" className="mm-mono mm-dim">{shortTime(r.time)}</span>,
              ],
            }))} />
        ) : <Empty>还没有记录。</Empty>}
      </Block>
    </PageFrame>
  );
}
