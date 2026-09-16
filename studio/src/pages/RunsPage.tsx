import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert } from "@heroui/react";
import * as studio from "../api/studio";
import type { ExperimentSummary } from "../api/studio";
import { backtestStatusLabel } from "../hooks/backtestStatus";
import { EXPERIMENT_STATUS_LABELS, mergeExperiments, shortTime } from "../hooks/experiments";
import { shortName, useStudio } from "../hooks/studioContext";
import { PageFrame } from "../components/PageFrame";
import { BacktestResultView } from "../components/BacktestResultView";
import { RoundDetail } from "../components/RoundViews";
import { Block, Btn, Empty, Num, StatusTag, Table, TextTabs } from "../components/minimal";
import type { ReactNode } from "react";
import { Hint } from "../components/widgets";

interface Row { key: string; kind: "research" | "backtest"; id: string; name: string; detail: string; result: ReactNode; status: string; time: string | null }

export function RunsPage() {
  const { trace, backtests, layout, workspace } = useStudio();
  const navigate = useNavigate();
  const [filter, setFilter] = useState("all");
  const [selectedKey, setSelectedKey] = useState("");
  const [summaries, setSummaries] = useState<ExperimentSummary[]>([]);
  const loadSummaries = useCallback(() => { studio.experiments().then(setSummaries).catch(() => {}); }, []);
  useEffect(() => { loadSummaries(); }, [loadSummaries, trace.traceIds, trace.status]);

  const rows = useMemo<Row[]>(() => {
    const research: Row[] = filter !== "backtest" ? mergeExperiments(workspace.region === "cn" ? trace.traceIds : summaries.map((s) => s.id), summaries).map((e) => ({
      key: `r:${e.id}`, kind: "research", id: e.id, name: shortName(e.id), detail: e.hypothesis || e.scenario,
      result: e.rounds == null ? <span className="mm-dim">—</span> : `${e.rounds} 轮 · ${e.accepted} 接受`,
      status: e.id === trace.traceId && trace.events.length ? trace.status : EXPERIMENT_STATUS_LABELS[e.status], time: e.updated,
    })) : [];
    const jobs: Row[] = filter !== "research" ? backtests.jobs.map((job) => ({
      key: `b:${job.id}`, kind: "backtest", id: job.id, name: job.id.slice(0, 8),
      detail: `${job.config.factors?.length ?? 0} 信号 · ${job.config.model?.method === "lgbm" ? "LightGBM" : "排名加权"} · ${job.config.start} → ${job.config.end} · ${job.config.market}`,
      result: <Num value={job.total_return} format={(v) => `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`} />,
      status: backtestStatusLabel(job.status), time: job.created || null,
    })) : [];
    return [...jobs, ...research];
  }, [filter, trace.traceIds, trace.traceId, trace.status, trace.events.length, backtests.jobs, summaries]);
  const selected = rows.find((r) => r.key === selectedKey) || null;
  const open = async (row: Row) => {
    setSelectedKey(row.key);
    layout.openResults();
    if (row.kind === "research") await trace.select(row.id); else await backtests.select(row.id);
  };

  return (
    <PageFrame
      tabs={<TextTabs label="类型" value={filter} onChange={setFilter} items={[{ key: "all", label: "全部" }, { key: "research", label: "研究" }, { key: "backtest", label: "回测" }]} />}
      actions={<Btn onClick={() => { trace.loadTraces(); backtests.load(); loadSummaries(); }}>刷新</Btn>}
      resultsTitle={selected ? (selected.kind === "research" ? selected.name : `回测 ${selected.name}`) : "详情"}
      resultsActions={selected ? <Btn onClick={() => navigate(selected.kind === "research" ? `/research?trace=${encodeURIComponent(selected.id)}` : "/backtest")}>{selected.kind === "research" ? "在研究页打开 →" : "在回测页打开 →"}</Btn> : undefined}
      results={
        selected?.kind === "research" ? (
          <div className="flex flex-col gap-3">
            {trace.status === "未加载" && <Alert status="accent"><Alert.Indicator /><Alert.Content><Alert.Title>这个实验的事件未加载到服务端。</Alert.Title></Alert.Content></Alert>}
            {trace.rounds.map((round) => <RoundDetail key={round.id} round={round} />)}
          </div>
        ) : selected?.kind === "backtest" && backtests.result ? <BacktestResultView result={backtests.result} onDiagnose={backtests.diagnose} /> : <Hint>点一行查看详情。</Hint>
      }
    >
      <Block title="记录" count={rows.length}>
        {rows.length ? (
          <Table label="运行记录" columns={[{ label: "类型", width: 52 }, { label: "名称", width: 190 }, { label: "说明" }, { label: "结果", num: true, width: 110, optional: true }, { label: "状态", width: 72 }, { label: "时间", width: 100, optional: true }]}
            rows={rows.map((r) => ({
              key: r.key, selected: r.key === selectedKey, onClick: () => open(r),
              cells: [
                <span key="k" className="mm-dim">{r.kind === "research" ? "研究" : "回测"}</span>,
                <span key="n" className="mm-mono mm-name block truncate">{r.name}</span>,
                <span key="d" className="mm-dim block truncate" title={r.detail}>{r.detail}</span>,
                r.result,
                <StatusTag key="s" status={r.status} />,
                <span key="t" className="mm-mono mm-dim">{shortTime(r.time)}</span>,
              ],
            }))} />
        ) : <Empty>还没有记录。</Empty>}
      </Block>
    </PageFrame>
  );
}
