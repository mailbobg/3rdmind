import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import * as studio from "../api/studio";
import type { BacktestResult, SignalExport, Strategy, StrategyRun } from "../api/studio";
import { shortTime } from "../hooks/experiments";
import { download, errorText, shortName, useStudio } from "../hooks/studioContext";
import { persistStudioState } from "../hooks/studioStorage";
import { PageFrame } from "../components/PageFrame";
import { Section } from "../components/Section";
import { DateInput } from "../components/DateInput";
import { BacktestResultView } from "../components/BacktestResultView";
import { Block, Btn, Empty, Field, Note, Num, NumberInput, P, StatusTag, Table, TextInput, TextTabs } from "../components/minimal";
import { CurveOverlay, DataTable, Hint, Instrument, MetricGrid, Mono, Signed, money, percent } from "../components/widgets";
import { t } from "../i18n";

const RUN_STATUS: Record<string, string> = { queued: t("排队中"), running: t("运行中"), completed: t("已完成"), failed: t("失败"), missing: t("记录丢失") };

/**
 * Strategies: named factor portfolios with the evidence they were saved on and every tracking run since.
 * The work column lists them; the results column shows one strategy's members, evidence and run history,
 * with the latest run's full backtest report underneath.
 */
export function StrategiesPage() {
  const { basket, layout, env, backtests, trace, workspace } = useStudio();
  const navigate = useNavigate();
  const [items, setItems] = useState<Strategy[]>([]);
  const [search, setSearch] = useSearchParams();
  const [selectedId, setSelectedId] = useState(search.get("id") || "");
  // ?id= (from the runs page, a toast or the failure banner) opens that strategy on arrival.
  useEffect(() => { if (search.get("id")) { layout.openResults(); setSearch({}, { replace: true }); } }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const [detail, setDetail] = useState<Strategy | null>(null);
  const [latestRun, setLatestRun] = useState<BacktestResult | null>(null);
  const [signal, setSignal] = useState<SignalExport | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [filter, setFilter] = useState("all");
  const [editing, setEditing] = useState(false);
  // 回流研究: a new factor-research run with this strategy's members as base features.
  const [researching, setResearching] = useState(false);
  const [researchLoops, setResearchLoops] = useState(3);
  const [researchHours, setResearchHours] = useState(2);
  const research = async (s: Strategy) => {
    setResearching(true);
    try {
      const r = await studio.researchFromStrategy(s.id, researchLoops, researchHours);
      // The first confirmation asks for the research direction; pre-fill it with the strategy context.
      persistStudioState({ objective: r.instruction });
      trace.registerLaunched(r.id);
      navigate(workspace.path(`/research?trace=${encodeURIComponent(r.id)}`));
    } catch (e) { setError(errorText(e)); } finally { setResearching(false); }
  };
  const [draft, setDraft] = useState({ name: "", note: "" });

  const load = useCallback(async () => {
    try { setItems(await studio.strategies()); setError(""); } catch (e) { setError(errorText(e)); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const open = useCallback(async (id: string) => {
    setSelectedId(id); setEditing(false); layout.openResults();
    try { const s = await studio.strategy(id); setDetail(s); setDraft({ name: s.name, note: s.note || "" }); } catch (e) { setError(errorText(e)); }
  }, [layout]);
  // The newest run's full report; polled while it is still running.
  const lastRunId = detail?.run_details?.length ? detail.run_details[detail.run_details.length - 1].id : "";
  useEffect(() => {
    setLatestRun(null); setSignal(null);
    if (!lastRunId) return;
    let stop = false;
    const tick = async () => {
      try {
        const r = await studio.backtest(lastRunId);
        if (stop) return;
        setLatestRun(r);
        if (r.status === "completed" && selectedId) studio.strategySignal(selectedId).then((sig) => { if (!stop) setSignal(sig); }).catch(() => { if (!stop) setSignal(null); });
        if (r.status === "queued" || r.status === "running") setTimeout(tick, 3000);
        else if (detail && selectedId) { studio.strategy(selectedId).then((s) => { if (!stop) setDetail(s); }).catch(() => {}); load(); }
      } catch (e) { if (!stop) setError(errorText(e)); }
    };
    tick();
    return () => { stop = true; };
  }, [lastRunId]); // eslint-disable-line react-hooks/exhaustive-deps

  // 更新到最新 takes an optional window: start defaults to the evidence start, end to the data's last day.
  const [updating, setUpdating] = useState(false);
  const [span, setSpan] = useState({ start: "", end: "" });
  const openUpdate = (s: Strategy) => { setSpan({ start: s.evidence?.start || "", end: env?.end || "" }); setUpdating((v) => !v); };
  const update = async (s: Strategy) => {
    if (span.start && span.end && span.start >= span.end) { setError(t("更新区间的开始必须早于结束。")); return; }
    setBusy(s.id); setUpdating(false);
    try {
      const r = await studio.updateStrategy(s.id, { start: span.start || undefined, end: span.end || undefined });
      if (r.failures.length) setError(t("部分因子没能重算：{0}。回测已用现有数据启动。", [r.failures.join("；")]));
      await load();
      await open(s.id);
    } catch (e) { setError(errorText(e)); } finally { setBusy(""); }
  };
  const remove = async (s: Strategy) => {
    if (!window.confirm(t("删除策略「{0}」？它的回测记录会保留。", [s.name]))) return;
    try { await studio.deleteStrategy(s.id); if (selectedId === s.id) { setSelectedId(""); setDetail(null); } await load(); } catch (e) { setError(errorText(e)); }
  };
  const saveEdit = async () => {
    if (!detail) return;
    try { const s = await studio.renameStrategy(detail.id, draft); setDetail(s); setEditing(false); await load(); } catch (e) { setError(errorText(e)); }
  };
  const exportCsv = async (s: Strategy) => {
    try {
      const text = await fetch(studio.strategySignalCsvUrl(s.id)).then(async (r) => { if (!r.ok) throw new Error((await r.json()).error || `HTTP ${r.status}`); return r.text(); });
      download(`signal-${signal?.as_of || "latest"}-${s.name}.csv`, text, "text/csv");
    } catch (e) { setError(errorText(e)); }
  };
  const toBasket = (s: Strategy) => { basket.replace(s.factors.map((f) => ({ ...f, kind: f.kind || "factor" }))); navigate(workspace.path("/backtest")); };

  const rows = useMemo(() => items.filter((s) => filter === "all" || (filter === "tracked" ? (s.run_count ?? 0) > 1 : (s.run_count ?? 0) <= 1)), [items, filter]);
  const runCurves = useMemo(() => {
    if (!latestRun?.rows) return [];
    return [{ name: t("最新一次"), points: latestRun.rows.map((r) => [r.date, r.equity] as [string, number]), bold: true },
            { name: t("基准"), points: latestRun.rows.map((r) => [r.date, r.benchmark] as [string, number]), dashed: true }];
  }, [latestRun]);
  const runsTable = (runs: StrategyRun[]) => (
    <Table label={t("跟踪记录")} columns={[{ label: t("时间"), width: 100 }, { label: t("类型"), width: 56 }, { label: t("区间") }, { label: t("收益"), num: true, width: 80 }, { label: t("超额"), num: true, width: 80, optional: true }, { label: t("夏普"), num: true, width: 60, optional: true }, { label: t("回撤"), num: true, width: 72, optional: true }, { label: t("状态"), width: 64 }]}
      rows={runs.map((r) => ({
        key: r.id, onClick: () => { backtests.select(r.id); navigate(workspace.path("/backtest")); },
        cells: [
          <span key="t" className="mm-mono mm-dim">{shortTime(r.created || null)}</span>,
          <span key="k" className="mm-dim">{r.kind === "evidence" ? t("证据") : t("更新")}</span>,
          <span key="w" className="mm-mono mm-dim">{r.start} → {r.end}</span>,
          <Num key="r" value={r.total_return} format={(v) => `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`} />,
          <Num key="x" value={typeof r.total_return === "number" && typeof r.benchmark_return === "number" ? r.total_return - r.benchmark_return : null} format={(v) => `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`} />,
          <span key="s" className="mm-mono">{typeof r.sharpe === "number" ? r.sharpe.toFixed(2) : "—"}</span>,
          <span key="d" className="mm-mono">{typeof r.max_drawdown === "number" ? percent(r.max_drawdown, 1) : "—"}</span>,
          <StatusTag key="st" status={RUN_STATUS[r.status || ""] || r.status || "—"} />,
        ],
      }))} />
  );

  return (
    <PageFrame
      tabs={<TextTabs label={t("筛选")} value={filter} onChange={setFilter} items={[{ key: "all", label: t("全部策略") }, { key: "tracked", label: t("已跟踪") }, { key: "fresh", label: t("只有证据") }]} />}
      actions={<Btn onClick={load}>{t("刷新")}</Btn>}
      resultsTitle={detail ? detail.name : t("策略详情")}
      resultsActions={detail ? (
        <>
          <Btn kind="text" onClick={() => setEditing((v) => !v)}>{editing ? t("取消") : t("重命名")}</Btn>
          <Btn onClick={() => toBasket(detail)}>{t("放进信号篮 →")}</Btn>
          <Btn kind="primary" disabled={busy === detail.id || !env?.data_ready} onClick={() => openUpdate(detail)}>{busy === detail.id ? t("重算并回测中…") : t("更新到最新")}</Btn>
        </>
      ) : undefined}
      results={detail ? (
        <div className="flex flex-col gap-3">
          {updating && (
            <Section title={t("更新到最新")} note={t("重算成员因子，再在这个区间上回测，结果追加到跟踪记录")}>
              <div className="flex flex-wrap items-end gap-3">
                <Field label={t("开始")} hint={t("默认证据起点")}><DateInput ariaLabel={t("开始")} value={span.start} onChange={(v) => setSpan((w) => ({ ...w, start: v }))} max={span.end || env?.end} presets={detail.evidence?.start ? [{ label: t("证据起点"), value: detail.evidence.start }] : []} /></Field>
                <Field label={t("结束")} hint={t("默认行情最后一天")}><DateInput ariaLabel={t("结束")} value={span.end} onChange={(v) => setSpan((w) => ({ ...w, end: v }))} min={span.start} max={env?.end} presets={env?.end ? [{ label: t("数据末日"), value: env.end }] : []} /></Field>
                <Btn kind="primary" disabled={busy === detail.id} onClick={() => update(detail)}>{t("开始更新")}</Btn>
                <Btn kind="text" onClick={() => setUpdating(false)}>{t("取消")}</Btn>
              </div>
              <Hint>{t("成员、权重和参数不在这里改：点“放进信号篮 →”到组合回测里调整并跑一次，保存时选“覆盖这个策略”。")}</Hint>
            </Section>
          )}
          {editing && (
            <Section title={t("重命名")}>
              <div className="flex flex-col gap-2">
                <TextInput value={draft.name} onChange={(v) => setDraft((d) => ({ ...d, name: v }))} placeholder={t("策略名称")} />
                <textarea className="mm-control" rows={3} value={draft.note} onChange={(e) => setDraft((d) => ({ ...d, note: e.target.value }))} placeholder={t("备注：为什么保存它、验证结论、注意事项")} />
                <div><Btn kind="primary" onClick={saveEdit}>{t("保存")}</Btn></div>
              </div>
            </Section>
          )}
          <Section title={t("成员")} note={t("{0} 个信号 · {1} · {2} · topk {3} / n_drop {4}", [detail.factors.length, detail.model.method === "lgbm" ? "LightGBM" : t("排名加权"), detail.params.market, detail.params.topk, detail.params.n_drop])}>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {detail.factors.map((f) => <span key={`${f.trace}#${f.loop_id}#${f.name}`} className="flex items-center gap-1 text-xs"><Mono>{f.name}</Mono><span className="text-muted">{t("×{0} · {1} 第 {2} 轮", [f.weight, shortName(f.trace), f.loop_id + 1])}</span></span>)}
            </div>
            {detail.note && <p className="m-0 text-xs">{detail.note}</p>}
            <Hint>保存于 {shortTime(detail.created)}{detail.evidence?.start ? t(" · 证据区间 {0} → {1}", [detail.evidence.start, detail.evidence.end]) : ""}{detail.evidence?.search_id ? t(" · 来自组合搜索 {0}", [detail.evidence.search_id.slice(0, 8)]) : ""}</Hint>
          </Section>
          <Section title={t("围着这个策略继续研究")} note={t("策略成员作为基础特征")}>
            <p className="m-0 text-xs">{t("启动一次新的因子研发：每一轮训练都带上这 {0} 个成员因子，Agent 被要求只找与它们低相关、有增量的新因子，不重做已有的。产出进因子库，可以直接拿来和策略成员一起回测、诊断。", [detail.factors.filter((f) => (f.kind || "factor") === "factor").length])}</p>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-muted">{t("轮数")}</span><NumberInput value={researchLoops} onChange={setResearchLoops} min={1} max={30} className="mm-weight" />
              <span className="text-muted">{t("时限（小时）")}</span><NumberInput value={researchHours} onChange={setResearchHours} min={0.1} max={24} step={0.5} className="mm-weight" />
              <Btn kind="primary" disabled={researching || !env?.chat_model} onClick={() => research(detail)}>{researching ? t("启动中…") : t("开始研究")}</Btn>
            </div>
            <Hint>{t("开始后会跳到 AI 研究页；Agent 第一次停下来确认方向时，研究方向已按这个策略预填好，可以改。")}</Hint>
          </Section>
          <Section title={t("跟踪记录")} note={t("{0} 次回测", [detail.run_details?.length ?? 0])}>
            {detail.run_details?.length ? runsTable(detail.run_details) : <Hint>{t("还没有回测记录。点“更新到最新”跑第一次。")}</Hint>}
            <Hint>{t("“证据”是保存时依据的那次回测；“更新”是之后每次把成员因子重算到最新、从证据区间起点跑到行情末日的结果。区间越往后延，超额收益还在不在，就是这个策略是否仍然有效的答案。")}</Hint>
          </Section>
          {signal && (
            <Section title={t("最新信号")} note={<span className="flex items-center gap-2">{t("截至 {0}", [signal.as_of])}<Btn onClick={() => detail && exportCsv(detail)}>{t("导出 CSV")}</Btn><Btn kind="text" onClick={() => download(`signal-${signal.as_of}-${detail.name}.json`, JSON.stringify(signal, null, 2), "application/json")}>JSON</Btn></span>}>
              <Hint>{t("目标持仓是策略在最新一次回测结束时的持仓，即进入下一个交易日的仓位；评分是最后一个信号日的排名，下一次调仓按它买前 {0} 名、每天最多换出 {1} 只。交易系统直接读 CSV：type 列为 holding 的是持仓（权重、数量、价格），为 score 的是排名。", [signal.topk, signal.n_drop])}</Hint>
              <MetricGrid columns={3} items={[
                { label: t("持仓数"), value: String(signal.rows.filter((r) => r.type === "holding").length) },
                { label: t("持仓市值"), value: money(signal.rows.filter((r) => r.type === "holding").reduce((a, r) => a + (r.value || 0), 0), workspace.region) },
                { label: t("现金"), value: money(signal.cash, workspace.region) },
              ]} />
              <DataTable label={t("目标持仓")} head={[[t("标的")], [t("权重"), "end"], [t("数量"), "end"], [t("价格"), "end"], [t("市值"), "end"], [t("最新排名"), "end"]]}
                rows={signal.rows.filter((r) => r.type === "holding").map((r) => {
                  const rank = signal.rows.find((x) => x.type === "score" && x.instrument === r.instrument)?.rank;
                  return { key: r.instrument, cells: [
                    <Instrument key="i" code={r.instrument} />,
                    <span key="w" className="tabular-nums">{typeof r.weight === "number" ? percent(r.weight, 1) : "—"}</span>,
                    <span key="a" className="tabular-nums">{typeof r.amount === "number" ? Math.round(r.amount).toLocaleString() : "—"}</span>,
                    <span key="p" className="tabular-nums">{typeof r.price === "number" ? r.price.toFixed(2) : "—"}</span>,
                    <span key="v" className="tabular-nums">{money(r.value, workspace.region)}</span>,
                    <span key="r" className={`tabular-nums ${rank == null ? "text-muted" : rank <= signal.topk ? "" : "text-danger"}`}>{rank ?? `> ${signal.rows.filter((x) => x.type === "score").length}`}</span>,
                  ] };
                })} />
              <DataTable label={t("最新评分")} head={[[t("排名"), "end"], [t("标的")], [t("评分"), "end"], [t("当前")]]}
                rows={signal.rows.filter((r) => r.type === "score").slice(0, signal.topk * 2).map((r) => ({ key: `s-${r.instrument}`, cells: [
                  <span key="r" className="tabular-nums">{r.rank}</span>,
                  <Instrument key="i" code={r.instrument} />,
                  <span key="s" className="tabular-nums">{typeof r.score === "number" ? r.score.toFixed(4) : "—"}</span>,
                  <span key="h" className={`text-[11px] ${r.held ? "text-success" : "text-muted"}`}>{r.held ? t("持有中") : (r.rank ?? 0) <= signal.topk ? t("待买入") : ""}</span>,
                ] }))} />
              <Hint>{t("排名跌出前 {0} 的持仓标红：按 TopkDropout 规则它们是下一次调仓最先被换出的候选。", [signal.topk])}</Hint>
            </Section>
          )}
          {latestRun?.metrics && (
            <Section title={t("最新一次")} note={`${latestRun.config.start} → ${latestRun.config.end}`}>
              <MetricGrid columns={3} items={[
                { label: t("总收益"), value: <Signed value={latestRun.metrics.total_return} format={(v) => percent(v)} /> },
                { label: t("超额"), value: <Signed value={latestRun.metrics.total_return - latestRun.metrics.benchmark_return} format={(v) => percent(v)} /> },
                { label: t("夏普"), value: typeof latestRun.metrics.sharpe === "number" ? latestRun.metrics.sharpe.toFixed(2) : "—" },
              ]} />
              {runCurves.length > 0 && <CurveOverlay series={runCurves} height={240} />}
            </Section>
          )}
          {latestRun && (latestRun.status === "queued" || latestRun.status === "running") && <Note tone="info">{t("最新一次回测正在运行，跑完这里会自动刷新。")}</Note>}
          {latestRun?.metrics && <BacktestResultView result={latestRun} onDiagnose={undefined} />}
        </div>
      ) : <Hint>{t("点一个策略查看成员、证据和跟踪记录。")}</Hint>}
    >
      {error && <Note tone="bad" actions={<Btn kind="text" onClick={() => setError("")}>{t("关闭")}</Btn>}>{error}</Note>}
      <Block title={t("策略")} count={rows.length} note={items.length ? t("点一行查看；“更新到最新”会重算成员因子并重跑回测") : undefined}>
        {rows.length ? (
          <Table label={t("策略")} columns={[{ label: t("名称") }, { label: t("信号"), num: true, width: 50 }, { label: t("最新收益"), num: true, width: 90 }, { label: t("最新区间"), width: 190, optional: true }, { label: t("跟踪"), num: true, width: 50, optional: true }, { label: t("状态"), width: 64 }, { label: "", width: 120 }]}
            rows={rows.map((s) => ({
              key: s.id, selected: s.id === selectedId, onClick: () => open(s.id),
              cells: [
                <span key="n" className="block truncate"><span className="mm-name">{s.name}</span>{s.note ? <span className="mm-dim"> · {s.note}</span> : null}</span>,
                String(s.factors.length),
                <Num key="r" value={s.latest?.total_return} format={(v) => `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`} />,
                <span key="w" className="mm-mono mm-dim">{s.latest ? `${s.latest.start} → ${s.latest.end}` : "—"}</span>,
                String(s.run_count ?? 0),
                <StatusTag key="st" status={s.latest ? (RUN_STATUS[s.latest.status || ""] || "—") : "—"} />,
                <span key="a" className="flex gap-2" onClick={(e) => e.stopPropagation()}>
                  <button type="button" className="mm-link" disabled={busy === s.id} onClick={() => update(s)}>{busy === s.id ? t("更新中…") : t("更新")}</button>
                  <button type="button" className="mm-link" onClick={() => remove(s)}>{t("删除")}</button>
                </span>,
              ],
            }))} />
        ) : <Empty>{t("还没有保存的策略。回测跑出满意的组合后，在结果标题行点“保存为策略”。")}</Empty>}
      </Block>
      <P>{t("策略记录的是成员因子、权重、合成方式和回测参数，以及保存时依据的那次回测；之后每次“更新到最新”都会追加一条跟踪记录。")}</P>
    </PageFrame>
  );
}
