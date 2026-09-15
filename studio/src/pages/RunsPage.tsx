import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Button, Chip } from "@heroui/react";
import { backtestStatusLabel } from "../hooks/backtestStatus";
import { useStudio } from "../hooks/studioContext";
import { PageFrame } from "../components/PageFrame";
import { Panel } from "../components/Panel";
import { BacktestResultView } from "../components/BacktestResultView";
import { RoundDetail } from "../components/RoundViews";
import { TabBar } from "../components/fields";
import { DataTable, Hint, Mono, StatusChip } from "../components/widgets";

interface Row { key: string; kind: "research" | "backtest"; id: string; name: string; detail: string; status: string }

export function RunsPage() {
  const { trace, backtests, layout } = useStudio();
  const navigate = useNavigate();
  const [filter, setFilter] = useState("all");
  const [selectedKey, setSelectedKey] = useState("");

  const rows = useMemo<Row[]>(() => {
    const research: Row[] = filter !== "backtest" ? trace.traceIds.map((id) => ({
      key: `r:${id}`, kind: "research", id, name: id.split("/").slice(1).join("/") || id, detail: id.split("/")[0],
      status: id === trace.traceId ? trace.status : "—",
    })) : [];
    const jobs: Row[] = filter !== "research" ? backtests.jobs.map((job) => ({
      key: `b:${job.id}`, kind: "backtest", id: job.id, name: job.id.slice(0, 8),
      detail: `${job.config.factors?.length ?? 0} 信号 · ${job.config.start} → ${job.config.end} · ${job.config.market}${job.total_return != null ? ` · ${(job.total_return * 100).toFixed(1)}%` : ""}`,
      status: backtestStatusLabel(job.status),
    })) : [];
    return [...jobs, ...research];
  }, [filter, trace.traceIds, trace.traceId, trace.status, backtests.jobs]);
  const selected = rows.find((r) => r.key === selectedKey) || null;
  const open = async (row: Row) => {
    setSelectedKey(row.key);
    layout.openResults();
    if (row.kind === "research") await trace.select(row.id); else await backtests.select(row.id);
  };

  return (
    <PageFrame
      title="运行记录"
      description={`${backtests.jobs.length} 次回测 · ${trace.traceIds.length} 个研究实验`}
      tabs={<TabBar label="类型" value={filter} onChange={setFilter} items={[{ key: "all", label: "全部" }, { key: "research", label: "研究" }, { key: "backtest", label: "回测" }]} />}
      actions={<Button size="sm" variant="secondary" onPress={() => { trace.loadTraces(); backtests.load(); }}>刷新</Button>}
      resultsTitle={selected ? (selected.kind === "research" ? selected.name : `回测 ${selected.name}`) : "详情"}
      resultsActions={selected ? <Button size="sm" variant="secondary" onPress={() => navigate(selected.kind === "research" ? `/research?trace=${encodeURIComponent(selected.id)}` : "/backtest")}>{selected.kind === "research" ? "在研究页打开 →" : "在回测页打开 →"}</Button> : undefined}
      results={
        selected?.kind === "research" ? (
          <div className="flex flex-col gap-3">
            {trace.status === "未加载" && <Alert status="accent"><Alert.Indicator /><Alert.Content><Alert.Title>这个实验的事件未加载到服务端。</Alert.Title></Alert.Content></Alert>}
            {trace.rounds.map((round) => <RoundDetail key={round.id} round={round} />)}
          </div>
        ) : selected?.kind === "backtest" && backtests.result ? <BacktestResultView result={backtests.result} /> : <Hint>点一行查看详情。</Hint>
      }
    >
      <Panel grow flush title={<>记录 <span className="font-normal text-muted">{rows.length} 条</span></>}>
        {rows.length ? (
          <DataTable label="运行记录" head={[["类型"], ["名称"], ["说明"], ["状态"]]}
            rows={rows.map((r) => ({
              key: r.key, selected: r.key === selectedKey, onPress: () => open(r),
              cells: [
                <Chip key="k" size="sm" variant="soft">{r.kind === "research" ? "研究" : "回测"}</Chip>,
                <Mono key="n">{r.name}</Mono>,
                <span key="d" className="text-[11px] text-muted">{r.detail}</span>,
                r.status === "—" ? <span key="s" className="text-muted">—</span> : <StatusChip key="s" status={r.status} />,
              ],
            }))} />
        ) : <div className="p-6 text-center text-xs text-muted">还没有记录。</div>}
      </Panel>
    </PageFrame>
  );
}
