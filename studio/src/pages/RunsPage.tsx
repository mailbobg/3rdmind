import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert } from "@heroui/react";
import { backtestStatusLabel } from "../hooks/backtestStatus";
import { useStudio } from "../hooks/studioContext";
import { PageFrame } from "../components/PageFrame";
import { BacktestResultView } from "../components/BacktestResultView";
import { RoundDetail } from "../components/RoundViews";
import { Block, Btn, Empty, StatusTag, Table, TextTabs } from "../components/minimal";
import { Hint } from "../components/widgets";

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
      tabs={<TextTabs label="类型" value={filter} onChange={setFilter} items={[{ key: "all", label: "全部" }, { key: "research", label: "研究" }, { key: "backtest", label: "回测" }]} />}
      actions={<Btn onClick={() => { trace.loadTraces(); backtests.load(); }}>刷新</Btn>}
      resultsTitle={selected ? (selected.kind === "research" ? selected.name : `回测 ${selected.name}`) : "详情"}
      resultsActions={selected ? <Btn onClick={() => navigate(selected.kind === "research" ? `/research?trace=${encodeURIComponent(selected.id)}` : "/backtest")}>{selected.kind === "research" ? "在研究页打开 →" : "在回测页打开 →"}</Btn> : undefined}
      results={
        selected?.kind === "research" ? (
          <div className="flex flex-col gap-3">
            {trace.status === "未加载" && <Alert status="accent"><Alert.Indicator /><Alert.Content><Alert.Title>这个实验的事件未加载到服务端。</Alert.Title></Alert.Content></Alert>}
            {trace.rounds.map((round) => <RoundDetail key={round.id} round={round} />)}
          </div>
        ) : selected?.kind === "backtest" && backtests.result ? <BacktestResultView result={backtests.result} /> : <Hint>点一行查看详情。</Hint>
      }
    >
      <Block title="记录" count={rows.length}>
        {rows.length ? (
          <Table label="运行记录" columns={[{ label: "类型", width: 60 }, { label: "名称", width: 210 }, { label: "说明" }, { label: "状态", width: 72 }]}
            rows={rows.map((r) => ({
              key: r.key, selected: r.key === selectedKey, onClick: () => open(r),
              cells: [
                <span key="k" className="mm-dim">{r.kind === "research" ? "研究" : "回测"}</span>,
                <span key="n" className="mm-mono mm-name">{r.name}</span>,
                <span key="d" className="mm-dim block truncate">{r.detail}</span>,
                r.status === "—" ? <span key="s" className="mm-dim">—</span> : <StatusTag key="s" status={r.status} />,
              ],
            }))} />
        ) : <Empty>还没有记录。</Empty>}
      </Block>
    </PageFrame>
  );
}
