import { useCallback, useEffect, useMemo, useState } from "react";
import * as studio from "../api/studio";
import type { BacktestSummary, CorrelationMatrix as Corr, Coverage, FactorRef, FactorWeight, LibraryFactor } from "../api/studio";
import { basketKey as key } from "../hooks/useFactorBasket";
import { backtestStatusLabel } from "../hooks/backtestStatus";
import { persistStudioState, restoreStudioState } from "../hooks/studioStorage";
import { download, errorText, shortName, useStudio } from "../hooks/studioContext";
import { PageFrame } from "../components/PageFrame";
import { BacktestResultView } from "../components/BacktestResultView";
import { Block, Btn, Empty, Field, FieldGrid, Link, Note, Num, NumberInput, P, SelectInput, Table, TextInput, TextTabs } from "../components/minimal";
import { Hint } from "../components/widgets";

type Market = "csi300" | "csi500" | "all";
interface Params { start: string; end: string; market: Market; benchmark: string; topk: number; n_drop: number; account: number; open_cost: number; close_cost: number }
interface Lgbm { train: [string, string]; valid: [string, string]; params: Record<string, number> }

const shiftYears = (date: string, years: number) => { const d = new Date(date); d.setFullYear(d.getFullYear() + years); return d.toISOString().slice(0, 10); };
const dayBefore = (date: string) => { const d = new Date(date); d.setDate(d.getDate() - 1); return d.toISOString().slice(0, 10); };
const LGBM_DEFAULTS = { learning_rate: 0.05, num_leaves: 63, max_depth: 8, n_estimators: 1000, early_stopping_rounds: 50, colsample_bytree: 0.8, subsample: 0.8, lambda_l2: 1 };

export function BacktestPage() {
  const { env, backtests, basket, layout } = useStudio();
  const saved = useMemo(() => restoreStudioState(), []);
  const [params, setParams] = useState<Params>({
    start: "", end: "", market: "csi300", benchmark: "SH000300", topk: 10, n_drop: 2, account: 1000000, open_cost: 0.0005, close_cost: 0.0015, ...(saved.params || {}),
  });
  const set = <K extends keyof Params>(k: K, v: Params[K]) => setParams((p) => ({ ...p, [k]: v }));
  const [method, setMethod] = useState<"rank" | "lgbm">(saved.model?.method === "lgbm" ? "lgbm" : "rank");
  const [lgbm, setLgbm] = useState<Lgbm>({
    train: ["", ""], valid: ["", ""], params: { ...LGBM_DEFAULTS },
    ...(saved.model?.method === "lgbm" ? { train: saved.model.train, valid: saved.model.valid, params: { ...LGBM_DEFAULTS, ...saved.model.params } } : {}),
  });
  const [tab, setTab] = useState("params");
  const [source, setSource] = useState("");
  const [pageError, setPageError] = useState("");
  const [library, setLibrary] = useState<Record<string, LibraryFactor>>({});
  const info = (f: FactorWeight) => library[key(f)];
  // Every signal's date span: the library's cached analysis when a factor has one, otherwise read from its
  // result.h5 (or a prediction's pred.pkl) through the coverage endpoints, so the date warnings always apply.
  const [fetched, setFetched] = useState<Record<string, Coverage | null>>({});
  const coverageOf = (f: FactorWeight): Coverage | undefined =>
    (f.kind === "prediction" ? undefined : info(f)?.coverage || info(f)?.analysis?.coverage) || fetched[key(f)] || undefined;
  useEffect(() => {
    for (const f of basket.items) {
      if (coverageOf(f) || key(f) in fetched) continue;
      setFetched((m) => ({ ...m, [key(f)]: null }));
      const request = f.kind === "prediction" ? studio.predictionCoverage(f.trace, f.loop_id) : studio.factorCoverage(f);
      request.then((c) => setFetched((m) => ({ ...m, [key(f)]: { start: c.start, end: c.end } }))).catch(() => {});
    }
  }, [basket.items, library]); // eslint-disable-line react-hooks/exhaustive-deps

  // Default windows once the environment is known: the last year of data, and 1 + 1 years before it for a model.
  useEffect(() => {
    const end = env?.end;
    if (!end) return;
    setParams((p) => (p.start && p.end ? p : { ...p, end, start: shiftYears(end, -1) }));
  }, [env]);
  useEffect(() => {
    if (lgbm.train[0] || !params.start) return;
    const valid: [string, string] = [shiftYears(params.start, -1), dayBefore(params.start)];
    setLgbm((l) => ({ ...l, valid, train: [shiftYears(params.start, -2), dayBefore(valid[0])] }));
  }, [params.start, lgbm.train]);
  const loadLibrary = useCallback(() => studio.factorLibrary().then((list) => setLibrary(Object.fromEntries(list.map((f) => [key(f), f])))).catch(() => {}), []);
  useEffect(() => { loadLibrary(); }, [loadLibrary]);
  // "重算到最新" for every factor signal whose coverage ends before the requested end: sequential Qlib subprocesses.
  const [refreshing, setRefreshing] = useState(false);
  const staleFactors = useMemo(() => basket.items.filter((f) => (f.kind || "factor") === "factor" && coverageOf(f) && params.end && coverageOf(f)!.end < params.end), [basket.items, library, fetched, params.end]); // eslint-disable-line react-hooks/exhaustive-deps
  // Factors whose signal stops before the market data does: candidates for 重算到最新.
  const behindMarket = useMemo(() => basket.items.filter((f) => (f.kind || "factor") === "factor" && coverageOf(f) && env?.end && coverageOf(f)!.end < env.end), [basket.items, library, fetched, env?.end]); // eslint-disable-line react-hooks/exhaustive-deps
  const refreshStale = async (targets: FactorWeight[] = staleFactors) => {
    setRefreshing(true);
    try {
      for (const f of targets) {
        await studio.refreshFactor(f);
        setFetched((m) => { const next = { ...m }; delete next[key(f)]; return next; });
      }
      await loadLibrary();
      // With longer signals the untouched window may grow back to the market's end; the clamp trims any excess.
      if (!datesTouched && env?.end) { setParams((p) => ({ ...p, end: env.end! })); setAutoNote(""); }
    } catch (e) { setPageError(`重算失败：${errorText(e)}`); } finally { setRefreshing(false); }
  };
  useEffect(() => { if (backtests.jobs.length && !backtests.selectedId) backtests.select(backtests.jobs[0].id); }, [backtests.jobs]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (tab === "source" && !source) studio.strategySource().then((r) => setSource(r.code)).catch((e) => setPageError(errorText(e))); }, [tab, source]);

  // Pairwise correlation of the factor signals in the basket (predictions excluded), debounced.
  const factorRefs = useMemo<FactorRef[]>(() => basket.items.filter((f) => (f.kind || "factor") === "factor").map((f) => ({ trace: f.trace, loop_id: f.loop_id, name: f.name })), [basket.items]);
  const [correlation, setCorrelation] = useState<Corr | null>(null);
  const [correlationError, setCorrelationError] = useState("");
  useEffect(() => {
    setCorrelation(null); setCorrelationError("");
    if (factorRefs.length < 2) return;
    const t = setTimeout(() => studio.factorCorrelation(factorRefs).then(setCorrelation).catch((e) => setCorrelationError(errorText(e))), 400);
    return () => clearTimeout(t);
  }, [factorRefs]);
  const maxCorr = useMemo(() => {
    if (!correlation) return 0;
    let m = 0;
    correlation.matrix.forEach((row, i) => row.forEach((v, j) => { if (i !== j) m = Math.max(m, Math.abs(v)); }));
    return m;
  }, [correlation]);
  const coverage = useMemo(() => {
    const spans = basket.items.map(coverageOf).filter((c): c is Coverage => !!c);
    if (!spans.length) return null;
    return { start: spans.reduce((a, c) => (c.start > a ? c.start : a), spans[0].start), end: spans.reduce((a, c) => (c.end < a ? c.end : a), spans[0].end) };
  }, [basket.items, library, fetched]); // eslint-disable-line react-hooks/exhaustive-deps
  const coverageUnknown = basket.items.filter((f) => !coverageOf(f)).length;
  const dateWarning = useMemo(() => {
    if (!coverage || !params.start || !params.end) return "";
    if (params.start <= coverage.start) return `回测开始日 ${params.start} 不晚于信号首日 ${coverage.start}：策略要用前一天的评分，请把开始日往后挪。`;
    if (params.end > coverage.end) return `回测结束日 ${params.end} 超出信号覆盖末日 ${coverage.end}，会直接报错。`;
    return "";
  }, [coverage, params.start, params.end]);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const addDays = (date: string, n: number) => { const d = new Date(date); d.setDate(d.getDate() + n); return iso(d); };
  // Until the user touches the dates, the window follows the signals: the default (last year of market data)
  // always runs past research factors, which stop at the experiment's own data end, so clamp instead of blocking.
  const [datesTouched, setDatesTouched] = useState(false);
  const [autoNote, setAutoNote] = useState("");
  const setDate = (k: "start" | "end", v: string) => { setDatesTouched(true); setAutoNote(""); set(k, v); };
  useEffect(() => {
    if (datesTouched || !coverage || !params.start || !params.end) return;
    const minStart = addDays(coverage.start, 1);
    let start = params.start, end = params.end;
    if (end > coverage.end) { end = coverage.end; start = shiftYears(end, -1); }  // keep the default one-year length
    if (start < minStart) start = minStart;
    if (start >= end) { start = minStart; end = coverage.end; }
    if (start !== params.start || end !== params.end) {
      setParams((p) => ({ ...p, start, end }));
      setAutoNote(`回测区间已按信号覆盖自动调整为 ${start} → ${end}（信号数据到 ${coverage.end}）；需要更长就先把因子重算到最新。`);
    }
  }, [coverage, params.start, params.end, datesTouched]); // eslint-disable-line react-hooks/exhaustive-deps
  // Rank mode gets the whole coverage; LightGBM needs history first, so the backtest takes the last third and
  // training / validation split the first two thirds 2:1 (the worker insists on train < valid < backtest).
  const fitToCoverage = () => {
    if (!coverage) return;
    if (method !== "lgbm") { setParams((p) => ({ ...p, start: addDays(coverage.start, 1), end: coverage.end })); return; }
    const days = Math.round((new Date(coverage.end).getTime() - new Date(coverage.start).getTime()) / 86400000);
    if (days < 90) { setPageError(`信号覆盖只有 ${days} 天，放不下训练、验证和回测三段；换成排名加权或移出覆盖短的信号。`); return; }
    const backtestStart = addDays(coverage.start, Math.floor(days * 2 / 3));
    const trainEnd = addDays(coverage.start, Math.floor(days * 4 / 9));
    setLgbm((l) => ({ ...l, train: [coverage.start, trainEnd], valid: [addDays(trainEnd, 1), addDays(backtestStart, -1)] }));
    setParams((p) => ({ ...p, start: backtestStart, end: coverage.end }));
  };
  // The worker rejects overlapping windows outright; say so before the run.
  const orderWarning = useMemo(() => {
    if (method !== "lgbm" || !params.start) return "";
    if (lgbm.train[1] && lgbm.valid[0] && lgbm.train[1] >= lgbm.valid[0]) return `验证窗口 ${lgbm.valid[0]} 开始时训练窗口（到 ${lgbm.train[1]}）还没结束，两段必须前后相接。`;
    if (lgbm.valid[1] && lgbm.valid[1] >= params.start) return `回测开始日 ${params.start} 不晚于验证窗口结束日 ${lgbm.valid[1]}：模型会在回测期上训练，后端会拒绝。`;
    return "";
  }, [method, lgbm.train, lgbm.valid, params.start]);
  // LightGBM needs every signal observed inside the training and validation windows (the worker refuses
  // an empty column rather than dropping it); name the signals that would fail before the run starts.
  const windowGaps = useMemo(() => {
    if (method !== "lgbm") return [];
    const check = (name: string, [a, b]: [string, string]) => {
      if (!a || !b) return null;
      const missing = basket.items.filter((f) => { const c = coverageOf(f); return c && (c.end < a || c.start > b); });
      return missing.length ? { name, window: [a, b] as [string, string], missing } : null;
    };
    return [check("训练", lgbm.train), check("验证", lgbm.valid)].filter((g): g is NonNullable<typeof g> => !!g);
  }, [method, lgbm.train, lgbm.valid, basket.items, library, fetched]); // eslint-disable-line react-hooks/exhaustive-deps
  // These would all be rejected by the worker, so the run button waits until they are fixed.
  const blocked = !!dateWarning || !!orderWarning || windowGaps.length > 0;
  const removeGapSignals = () => { for (const f of windowGaps.flatMap((g) => g.missing)) if (basket.has(f)) basket.toggle(f); };
  // Fit both windows between the shared coverage start and the day before the backtest: two thirds training, one third validation.
  const fitWindowsToCoverage = () => {
    if (!coverage || !params.start) return;
    const from = new Date(coverage.start), to = new Date(dayBefore(params.start));
    const days = Math.round((to.getTime() - from.getTime()) / 86400000);
    if (days < 60) { setPageError(`信号覆盖起点 ${coverage.start} 到回测开始前一天只有 ${days} 天，放不下训练和验证窗口；请把回测开始日往后挪。`); return; }
    const split = new Date(from); split.setDate(split.getDate() + Math.floor(days * 2 / 3));
    setLgbm((l) => ({ ...l, train: [iso(from), iso(split)], valid: [iso(new Date(split.getTime() + 86400000)), iso(to)] }));
  };

  const submit = useCallback(async () => {
    const model = method === "lgbm" ? { method: "lgbm" as const, train: [...lgbm.train] as [string, string], valid: [...lgbm.valid] as [string, string], params: { ...lgbm.params } } : { method: "rank" as const };
    const accepted = await backtests.run({ factors: basket.items.map((f) => ({ ...f, weight: Number(f.weight) })), model, ...params });
    if (accepted) { persistStudioState({ params, model }); layout.openResults(); }
  }, [method, lgbm, basket.items, params, backtests, layout]);
  const result = backtests.result;
  const jobLabel = (job: BacktestSummary) =>
    `${backtestStatusLabel(job.status)}${job.total_return != null ? ` ${(job.total_return * 100).toFixed(1)}%` : ""} · ${job.config.factors?.length ?? 0} 信号 · ${job.config.model?.method === "lgbm" ? "LGBM" : "排名"} · ${job.config.start} → ${job.config.end}`;

  const statusLine = [
    coverage ? `覆盖 ${coverage.start} → ${coverage.end}` : "",
    factorRefs.length >= 2 ? (correlation ? `最高相关 ${maxCorr.toFixed(2)}${maxCorr >= 0.7 ? "（有信号重复）" : ""}` : correlationError ? "相关性计算失败" : "计算相关性…") : "",
  ].filter(Boolean).join(" · ");
  const lgbmKeys = ["learning_rate", "num_leaves", "max_depth", "n_estimators", "early_stopping_rounds"] as const;

  return (
    <PageFrame
      tabs={<TextTabs label="工作区视图" value={tab} onChange={setTab} items={[{ key: "params", label: "参数设置" }, { key: "source", label: "策略源码" }]} />}
      actions={<Btn kind="primary" disabled={backtests.busy || !env?.data_ready || !basket.items.length || blocked} title={blocked ? "先处理下面标红的日期问题" : undefined} onClick={submit}>{backtests.busy ? "运行中…" : blocked ? "日期有问题，无法运行" : "运行回测"}</Btn>}
      resultsTitle={result ? `回测 ${result.id.slice(0, 8)}` : "回测结果"}
      resultsActions={
        <>
          <SelectInput ariaLabel="回测历史" placeholder="回测历史" className="w-80 max-w-full" value={backtests.selectedId || ""} onChange={(id) => { backtests.select(id); layout.openResults(); }}
            options={backtests.jobs.map((j) => ({ value: j.id, label: jobLabel(j) }))} />
          {result?.metrics && <Btn kind="text" onClick={() => download(`backtest-${result.id.slice(0, 8)}.json`, JSON.stringify(result, null, 2), "application/json")}>导出 JSON</Btn>}
        </>
      }
      results={result ? <BacktestResultView result={result} onDiagnose={backtests.diagnose} /> : <Hint>运行回测后在这里看指标、净值曲线、持仓与成交。</Hint>}
    >
      {(backtests.error || pageError) && <Note tone="bad" actions={<Btn kind="text" onClick={() => { backtests.setError(""); setPageError(""); }}>关闭</Btn>}>{backtests.error || pageError}</Note>}
      {!env && <Note>后端未连接，无法回测。运行 scripts/start-backend.sh 后刷新。</Note>}
      {env && !env.data_ready && <Note>Qlib 数据未就绪（{env.provider_uri}），无法回测。</Note>}

      {tab === "params" ? (
        <>
          <Block title="回测参数" note={`${params.start || "?"} → ${params.end || "?"} · ${params.market}`}>
            <FieldGrid min={140}>
              <Field label="开始"><TextInput type="date" value={params.start} onChange={(v) => setDate("start", v)} /></Field>
              <Field label="结束"><TextInput type="date" value={params.end} onChange={(v) => setDate("end", v)} /></Field>
              <Field label="股票池"><SelectInput value={params.market} onChange={(v) => set("market", v)} options={[{ value: "csi300", label: "沪深300" }, { value: "csi500", label: "中证500" }, { value: "all", label: "全市场" }]} /></Field>
              <Field label="基准"><TextInput value={params.benchmark} onChange={(v) => set("benchmark", v)} /></Field>
              <Field label="持股数" hint="每天按评分持有前 topk 只"><NumberInput value={params.topk} onChange={(v) => set("topk", v)} min={1} max={500} /></Field>
              <Field label="每日换出" hint="每天最多换出 n_drop 只"><NumberInput value={params.n_drop} onChange={(v) => set("n_drop", v)} min={0} max={500} /></Field>
              <Field label="初始资金"><NumberInput value={params.account} onChange={(v) => set("account", v)} min={1000} step={100000} /></Field>
              <Field label="买入费率" hint="0.0005 = 万分之五"><NumberInput value={params.open_cost} onChange={(v) => set("open_cost", v)} min={0} max={0.1} step={0.0001} /></Field>
              <Field label="卖出费率" hint="0.0015 含印花税"><NumberInput value={params.close_cost} onChange={(v) => set("close_cost", v)} min={0} max={0.1} step={0.0001} /></Field>
              <Field label="信号合成" hint="排名加权：截面百分位排名按权重求和；LightGBM：学信号与次日收益的关系，验证集早停">
                <SelectInput value={method} onChange={setMethod} options={[{ value: "rank", label: "排名加权" }, { value: "lgbm", label: "训练 LightGBM" }]} />
              </Field>
            </FieldGrid>
            {autoNote && !dateWarning && (
              <div style={{ marginTop: 12 }}>
                <Note tone="info" actions={behindMarket.length > 0 ? <Btn disabled={refreshing} onClick={() => refreshStale(behindMarket)}>{refreshing ? "重算中…" : `把 ${behindMarket.length} 个因子重算到最新`}</Btn> : undefined}>{autoNote}</Note>
              </div>
            )}
            {dateWarning && (
              <div style={{ marginTop: 12 }}>
                <Note tone="bad" actions={coverage && <>
                  {staleFactors.length > 0 && <Btn disabled={refreshing} onClick={() => refreshStale()}>{refreshing ? "重算中…" : `把 ${staleFactors.length} 个因子重算到最新`}</Btn>}
                  <Btn onClick={fitToCoverage}>{method === "lgbm" ? "按覆盖区间重排三段" : "按覆盖区间填日期"}</Btn>
                </>}>{dateWarning}</Note>
              </div>
            )}
            {orderWarning && <div style={{ marginTop: 12 }}><Note tone="bad" actions={coverage && <Btn onClick={fitToCoverage}>按覆盖区间重排三段</Btn>}>{orderWarning}</Note></div>}
            {windowGaps.map((g) => (
              <div key={g.name} style={{ marginTop: 12 }}>
                <Note tone="bad" actions={<><Btn onClick={removeGapSignals}>移出这些信号</Btn><Btn onClick={fitWindowsToCoverage}>把窗口挪进覆盖区间</Btn></>}>
                  {g.name}窗口 {g.window[0]} → {g.window[1]} 里没有 {g.missing.map((f) => `${f.name}（${coverageOf(f)!.start} → ${coverageOf(f)!.end}）`).join("、")} 的数据，LightGBM 会直接报错。
                </Note>
              </div>
            ))}
          </Block>
          {method === "lgbm" && (
            <Block title="LightGBM" note="训练集学关系，验证集早停">
              <FieldGrid min={140}>
                <Field label="训练开始"><TextInput type="date" value={lgbm.train[0]} onChange={(v) => setLgbm((l) => ({ ...l, train: [v, l.train[1]] }))} /></Field>
                <Field label="训练结束"><TextInput type="date" value={lgbm.train[1]} onChange={(v) => setLgbm((l) => ({ ...l, train: [l.train[0], v] }))} /></Field>
                <Field label="验证开始"><TextInput type="date" value={lgbm.valid[0]} onChange={(v) => setLgbm((l) => ({ ...l, valid: [v, l.valid[1]] }))} /></Field>
                <Field label="验证结束"><TextInput type="date" value={lgbm.valid[1]} onChange={(v) => setLgbm((l) => ({ ...l, valid: [l.valid[0], v] }))} /></Field>
                {lgbmKeys.map((k) => <Field key={k} label={k}><NumberInput value={lgbm.params[k]} onChange={(v) => setLgbm((l) => ({ ...l, params: { ...l.params, [k]: v } }))} /></Field>)}
              </FieldGrid>
            </Block>
          )}
          <Block title="信号篮" count={basket.items.length} note={statusLine} noteTone={maxCorr >= 0.7 ? "bad" : "ok"}>
            {basket.items.length ? (
              <>
                <Table label="信号篮" columns={[{ label: "信号" }, { label: "来源", width: 200, optional: true }, { label: "IC", num: true, width: 82 }, { label: "Rank IC", num: true, width: 82 }, { label: "覆盖", width: 156, optional: true }, { label: "权重", num: true, width: 84 }, { label: "", width: 52 }]}
                  rows={basket.items.map((f) => ({
                    key: key(f),
                    cells: [
                      <span key="n" className="mm-mono mm-name">{f.name}</span>,
                      <span key="s" className="mm-dim block truncate">{shortName(f.trace)} · 第 {f.loop_id + 1} 轮</span>,
                      <Num key="ic" value={info(f)?.analysis?.ic.mean} />,
                      <Num key="ric" value={info(f)?.analysis?.rank_ic.mean} />,
                      <span key="cov" className="mm-mono mm-dim">{coverageOf(f) ? `${coverageOf(f)!.start.slice(0, 7)} → ${coverageOf(f)!.end.slice(0, 7)}` : key(f) in fetched ? "读取中…" : "未知"}</span>,
                      <NumberInput key="w" className="mm-weight" ariaLabel="权重" step={0.5} value={f.weight} disabled={method === "lgbm"} onChange={(v) => basket.setWeight(f, v)} />,
                      <Link key="x" onClick={() => basket.toggle(f)}>移除</Link>,
                    ],
                  }))} />
                <P>
                  TopkDropoutStrategy · 前一日评分 · 当日收盘成交 · 权重为负 = 反向使用{method === "lgbm" ? "（LightGBM 模式下权重不生效）" : ""}
                  {coverageUnknown ? ` · ${coverageUnknown} 个信号的覆盖区间未知，未计入` : ""} · <Link href="#/factors">去因子库增减</Link>
                </P>
              </>
            ) : (
              <Empty>还没有选信号。去 <Link href="#/factors">因子库</Link> 勾选，或在研究轮次里点“用 N 个因子回测”。</Empty>
            )}
          </Block>
        </>
      ) : (
        <Block title="studio_worker.py" note="只读 · 服务端执行"><pre className="mm-pre">{source || "加载中…"}</pre></Block>
      )}
    </PageFrame>
  );
}
